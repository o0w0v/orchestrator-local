"""Protocol and lifecycle tests use a local fake backend; no paid/cloud inference."""
import asyncio
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from orchestrator_local.core import Store,UserError,artifact_schema,input_document,packed,patch_artifact,read_settings
from orchestrator_local.worker import reap_interrupted

ROOT=Path(__file__).resolve().parents[1]
BASE={"data":{"total":10,"details":[{"id":"a","value":10}]},"report_md":"合計は10です。"}
EXPORTS=[{"name":"details.csv","pointer":"/data/details","columns":["id","value"]}]


class Backend(BaseHTTPRequestHandler):
    calls=0
    disconnected=threading.Event()
    lock=threading.Lock()
    version_delay=0

    def log_message(self,*args):
        pass

    def reply(self,value):
        b=packed(value).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)

    def do_GET(self):
        if self.path=='/api/version':
            delay=type(self).version_delay;type(self).version_delay=0
            if delay:time.sleep(delay)
            self.reply({'version':'fake'})
        elif self.path=='/api/tags':self.reply({'models':[{'name':'gemma4:26b','digest':'test-digest'}]})
        else:self.send_error(404)

    def do_POST(self):
        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path=='/api/show':
            self.reply({'thinking':{'values':[True,False]}});return
        if self.path!='/api/chat':self.send_error(404);return
        with self.lock:type(self).calls+=1
        payload=json.loads(request['messages'][1]['content'])
        scenario=payload['inputs'].get('scenario','normal')
        if scenario=='http_error':self.send_error(503);return
        self.send_response(200);self.send_header('Content-Type','application/x-ndjson');self.end_headers()
        try:
            for _ in range(200 if scenario=='slow' else 2):
                self.wfile.write(b'{"message":{"thinking":"PRIVATE_FAKE_THOUGHT_DO_NOT_SAVE"},"done":false}\n');self.wfile.flush();time.sleep(.02)
            value={'data':{'files':[{'path':'src/add.js','content':'export const add = (a, b) => a + b;\n'}]},'report_md':'加算関数のコード案です。'} if scenario=='code' else BASE
            text='not JSON' if scenario=='invalid' else packed(value)
            for part in [text[:10],text[10:]]:
                self.wfile.write((packed({'message':{'content':part},'done':False})+'\n').encode());self.wfile.flush()
            self.wfile.write((packed({'message':{'content':''},'done':True,'done_reason':'stop','prompt_eval_count':50,'eval_count':40,'total_duration':100000000,'load_duration':0,'prompt_eval_duration':100,'eval_duration':200})+'\n').encode());self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
            type(self).disconnected.set()


@asynccontextmanager
async def client(config):
    params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'serve.py'),'--config',str(config)],cwd=str(ROOT))
    async with stdio_client(params) as (r,w):
        async with ClientSession(r,w) as session:
            await session.initialize()
            yield session


async def call(session,name,**kwargs):
    result=await session.call_tool(name,arguments=kwargs)
    if result.isError:
        raise AssertionError(str(result.content))
    return result.structuredContent or json.loads(result.content[0].text)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend=ThreadingHTTPServer(('127.0.0.1',0),Backend)
        cls.thread=threading.Thread(target=cls.backend.serve_forever,daemon=True);cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.backend.shutdown();cls.backend.server_close();cls.thread.join()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        self.config=root/'settings.json'
        value={'data_dir':str(root/'data'),'input_roots':[str(root/'data/inbox')],
               'ollama_url':f'http://127.0.0.1:{self.backend.server_port}','model':'gemma4:26b','model_digest':'test-digest','think':True,
               'options':{'num_ctx':65536,'num_predict':32768},'job_timeout_seconds':10,'auto_start_ollama':False}
        self.config.write_text(packed(value),encoding='utf8')
        self.settings=read_settings(self.config);self.store=Store(self.settings)
        self.store.set_dispatch_enabled(True)
        self.service=subprocess.Popen([sys.executable,'-m','orchestrator_local.service','--config',str(self.config)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        from orchestrator_local.service import status
        for _ in range(50):
            if status(self.settings)['ready']:break
            time.sleep(.1)
        else:self.fail('service failed to start')

    def tearDown(self):
        (Path(self.settings['data_dir'])/'runtime/service.stop').write_text('stop')
        try:self.service.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.service.terminate();self.service.wait(timeout=5)
        self.temp.cleanup()

    async def ready(self,s,job_id):
        for _ in range(15):
            r=await call(s,'get_job',job_id=job_id,wait_seconds=1)
            if r['state'] not in {'QUEUED','RUNNING'}:return r
        self.fail('worker timed out')

    async def test_stdio_generation_reconnect_patch_and_amend(self):
        before=Backend.calls
        async with client(self.config) as s:
            tools=await s.list_tools();self.assertEqual(len(tools.tools),9)
            a=await call(s,'start_job',request_key='one',request='資料を集計する',inputs={'scenario':'normal'},csv_exports=EXPORTS)
            duplicate=await call(s,'start_job',request_key='one',request='資料を集計する',inputs={'scenario':'normal'},csv_exports=EXPORTS)
            self.assertEqual(a['id'],duplicate['id']);self.assertTrue(duplicate['reused'])
        # A separate stdio connection can recover the running/candidate job.
        async with client(self.config) as s:
            r=await self.ready(s,a['id']);self.assertEqual(r['state'],'CANDIDATE_READY');self.assertEqual(r['candidate'],BASE)
            changes=[{'path':'/data/total','before':10,'after':12},{'path':'/report_md','before':BASE['report_md'],'after':'合計は12です。'}]
            result=await call(s,'finalize_job',job_id=a['id'],candidate_hash=r['candidate_hash'],decision='PATCH',changes=changes,impact='合計の誤りを直す')
            again=await call(s,'finalize_job',job_id=a['id'],candidate_hash=r['candidate_hash'],decision='PATCH',changes=changes,impact='合計の誤りを直す')
            self.assertEqual(result['saved_path'],again['saved_path'])
            first=Path(result['saved_path']);self.assertEqual(json.loads((first/'data.json').read_text(encoding='utf8'))['total'],12)
            second=await call(s,'amend_result',job_id=a['id'],result_hash=result['result_hash'],changes=[{'path':'/report_md','before':'合計は12です。','after':'合計12。'}],impact='ユーザー指定の短縮')
            self.assertEqual(second['revision'],2);self.assertTrue(first.is_dir());self.assertEqual((first/'report.md').read_text(encoding='utf8'),'合計は12です。\n')
            third=await call(s,'amend_result',job_id=a['id'],result_hash=second['result_hash'],
                changes=[{'path':'/data/details','before':BASE['data']['details'],'after':[{'id':'a','value':10,'quantity':2}]}],
                impact='依頼された数量列を追加',requested_change='CSVに数量列も付けて',
                csv_exports=[{'name':'details.csv','pointer':'/data/details','columns':['id','value','quantity']}])
            self.assertEqual(third['revision'],3)
            self.assertTrue((Path(third['saved_path'])/'details.csv').read_text(encoding='utf-8-sig').startswith('id,value,quantity\n'))
            self.assertTrue((first/'details.csv').read_text(encoding='utf-8-sig').startswith('id,value\n'))
        self.assertEqual(Backend.calls-before,1)
        for p in (Path(self.settings['data_dir'])/'jobs').rglob('*'):
            if p.is_file():self.assertNotIn(b'PRIVATE_FAKE_THOUGHT_DO_NOT_SAVE',p.read_bytes())

    async def test_accept_preserves_candidate_and_direct_does_not_generate(self):
        before=Backend.calls
        async with client(self.config) as s:
            d=await call(s,'save_direct_result',request_key='direct',request='合計を書く',artifact=BASE,csv_exports=EXPORTS)
            self.assertEqual(Backend.calls,before)
            a=await call(s,'start_job',request_key='local',request='集計する')
            r=await self.ready(s,a['id'])
            out=await call(s,'finalize_job',job_id=a['id'],candidate_hash=r['candidate_hash'])
            self.assertEqual(json.loads((Path(out['saved_path'])/'artifact.json').read_text(encoding='utf8')),r['candidate'])
            self.assertEqual(out['result_hash'],r['candidate_hash'])

    async def test_cancel_and_queue_do_not_run_twice(self):
        Backend.disconnected.clear();before=Backend.calls
        async with client(self.config) as s:
            a=await call(s,'start_job',request_key='slow',request='集計する',inputs={'scenario':'slow'})
            for _ in range(40):
                if Backend.calls>before:break
                await asyncio.sleep(.1)
            b=await call(s,'start_job',request_key='queued',request='別の集計')
            await call(s,'cancel_job',job_id=b['id'])
            await call(s,'cancel_job',job_id=a['id'])
            r=await self.ready(s,a['id']);self.assertEqual(r['state'],'CANCELLED')
            self.assertEqual((await call(s,'get_job',job_id=b['id']))['state'],'CANCELLED')
            for _ in range(30):
                if Backend.disconnected.is_set():break
                await asyncio.sleep(.1)
            self.assertTrue(Backend.disconnected.is_set())
        self.assertEqual(Backend.calls-before,1)

    async def test_failure_is_not_retried_or_adoptable(self):
        before=Backend.calls
        async with client(self.config) as s:
            for scenario in ['invalid','http_error']:
                a=await call(s,'start_job',request_key=scenario,request='集計する',inputs={'scenario':scenario})
                r=await self.ready(s,a['id']);self.assertEqual(r['state'],'FAILED')
                bad=await s.call_tool('finalize_job',arguments={'job_id':a['id'],'candidate_hash':'x'})
                self.assertTrue(bad.isError)
        self.assertEqual(Backend.calls-before,2)

    async def test_cold_readiness_can_take_more_than_four_seconds(self):
        Backend.version_delay=4.3
        async with client(self.config) as s:
            a=await call(s,'start_job',request_key='cold',request='集計する')
            r=await self.ready(s,a['id'])
            self.assertEqual(r['state'],'CANDIDATE_READY')

    async def test_service_crash_is_recorded_without_regeneration(self):
        before=Backend.calls
        async with client(self.config) as s:
            a=await call(s,'start_job',request_key='crash',request='集計する',inputs={'scenario':'slow'})
            for _ in range(40):
                if Backend.calls>before:break
                await asyncio.sleep(.1)
            self.service.terminate();self.service.wait(timeout=5)
            # Simulate a reused PID that is alive, so liveness alone is insufficient.
            self.store.update(a['id'],worker_pid=os.getpid())
            self.service=subprocess.Popen([sys.executable,'-m','orchestrator_local.service','--config',str(self.config)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
            from orchestrator_local.service import status
            for _ in range(50):
                if status(self.settings)['ready']:break
                await asyncio.sleep(.1)
            r=await call(s,'get_job',job_id=a['id'])
            self.assertEqual(r['state'],'INTERRUPTED')
            await asyncio.sleep(.3)
            self.assertEqual(Backend.calls-before,1)

    def test_atomic_patch_stale_hash_schema_and_path_limits(self):
        original=copy.deepcopy(BASE)
        with self.assertRaises(UserError):
            patch_artifact(BASE,[{'path':'/data/total','before':10,'after':20},{'path':'/report_md','before':'wrong','after':'new'}],artifact_schema())
        self.assertEqual(BASE,original)
        with self.assertRaises(UserError):
            patch_artifact(BASE,[{'path':'/data','before':BASE['data'],'after':BASE['data']},{'path':'/data/total','before':10,'after':20}],artifact_schema())
        with self.assertRaises(UserError):
            patch_artifact(BASE,[{'path':'/data/total','before':True,'after':20}],artifact_schema())
        outside=Path(self.temp.name)/'outside.json';outside.write_text('{}')
        with self.assertRaises(UserError):input_document(self.settings,str(outside))
        with self.assertRaises(UserError):artifact_schema({'type':'object','$ref':'https://example.com/schema'})
        row,_=self.store.create('hash','job',executor='conversation')
        self.store.update(row['id'],state='CANDIDATE_READY',candidate=packed(BASE),candidate_hash='real')
        with self.assertRaises(UserError):self.store.save(row['id'],'stale')
        self.assertEqual(self.store.get(row['id'])['state'],'CANDIDATE_READY')

    def test_duplicate_key_csv_formula_escape_and_orphan(self):
        with self.assertRaises(UserError):
            from orchestrator_local.core import parse
            parse('{"a":1,"a":2}')
        r,_=self.store.create('one','same',executor='conversation')
        with self.assertRaises(UserError):self.store.create('one','different')
        with self.store.transaction() as db:db.execute('UPDATE jobs SET updated=?,worker_pid=? WHERE id=?',(time.time()-40,2147483600,r['id']))
        reap_interrupted(self.store);self.assertEqual(self.store.get(r['id'])['state'],'INTERRUPTED')
        dest=Path(self.temp.name)/'csv';dest.mkdir()
        value=copy.deepcopy(BASE);value['data']['details'][0]['id']='=1+1'
        Store._export(dest,value,EXPORTS)
        self.assertIn("'=1+1",(dest/'details.csv').read_text(encoding='utf-8-sig'))
        self.assertEqual(json.loads((dest/'data.json').read_text(encoding='utf8'))['details'][0]['id'],'=1+1')


if __name__=='__main__':unittest.main()
