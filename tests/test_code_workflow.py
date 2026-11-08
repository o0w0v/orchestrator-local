"""Code drafts use the existing queue/review path; neither tools nor worker execute them."""
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_runtime as fixtures
from test_runtime import Backend,ROOT,call,client
from orchestrator_local.code_artifact import source_paths,validate
from orchestrator_local.core import UserError
from orchestrator_local.installation import register


class PathTests(unittest.TestCase):
    def test_code_paths_do_not_escape_or_collide_on_windows(self):
        self.assertEqual(source_paths(['index.html','src/main.js']),['index.html','src/main.js'])
        for paths in [[],['../outside.py'],['/absolute.py'],['C:/outside.py'],['dir\\x.py'],['CON.txt'],['a.js','A.js'],['src','src/main.js'],['x.'],['a:stream']]:
            with self.subTest(paths=paths),self.assertRaises(UserError):source_paths(paths)
        with self.assertRaises(UserError):validate({'data':{'files':[{'path':'a.py'},{'path':'a.py'}]}},['a.py','b.py'])


class CodeWorkflowTests(unittest.IsolatedAsyncioTestCase):
    setUpClass=classmethod(fixtures.RuntimeTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.RuntimeTests.tearDownClass.__func__)
    setUp=fixtures.RuntimeTests.setUp
    tearDown=fixtures.RuntimeTests.tearDown
    ready=fixtures.RuntimeTests.ready

    async def cli(self,name,args=None,helper=False):
        path=Path(self.temp.name)/('args-'+name+'.json')
        path.write_text(json.dumps(args or {},ensure_ascii=False),encoding='utf8')
        if helper:
            command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'skills/orchestrator-local/scripts/call_tool.ps1'),'-Tool',name,'-ArgumentsFile',str(path),'-Config',str(self.config)]
        else:command=[sys.executable,str(ROOT/'runtime_entry.py'),'call','--config',str(self.config),'--tool',name,'--arguments-file',str(path)]
        result=await asyncio.to_thread(subprocess.run,command,cwd=ROOT,capture_output=True,text=True,encoding='utf8',timeout=30)
        return result.returncode,json.loads(result.stdout)

    async def test_code_draft_dedup_review_nested_exports_and_revision(self):
        before=Backend.calls
        args={'request_key':'code-one','request':'src/add.jsに加算関数を作る','file_paths':['src/add.js'],'inputs':{'scenario':'code'}}
        untouched=Path(self.temp.name)/'source-project';untouched.mkdir()
        (untouched/'keep.txt').write_bytes(b'unchanged')
        async with client(self.config) as session:
            job=await call(session,'start_code_job',**args)
            duplicate=await call(session,'start_code_job',**args)
            self.assertEqual(job['id'],duplicate['id']);self.assertTrue(duplicate['reused'])
            candidate=await self.ready(session,job['id'])
            self.assertEqual(candidate['work_type'],'code')
            self.assertFalse(list(untouched.glob('*.js')))
            self.store.set_dispatch_enabled(False)
            saved=await call(session,'finalize_job',job_id=job['id'],candidate_hash=candidate['candidate_hash'])
            first=Path(saved['saved_path'])
            content=candidate['candidate']['data']['files'][0]['content']
            self.assertEqual((first/'source/src/add.js').read_text(),content)
            manifest=json.loads((first/'manifest.json').read_text())
            self.assertEqual(manifest['files']['source/src/add.js'],hashlib.sha256((first/'source/src/add.js').read_bytes()).hexdigest())
            revised=await call(session,'amend_result',job_id=job['id'],result_hash=saved['result_hash'],changes=[{'path':'/data/files/0/content','before':content,'after':content+'// requested note\n'}],impact='利用者が求めたコメントの追記')
            self.assertEqual((first/'source/src/add.js').read_text(),content)
            self.assertEqual((Path(revised['saved_path'])/'source/src/add.js').read_text(),content+'// requested note\n')
            self.assertEqual(Backend.calls,before+1)
            status,view=await self.cli('get_job',{'job_id':job['id']})
            self.assertEqual(status,0,view);self.assertEqual(view['source_files'],[str(Path(revised['saved_path'])/'source/src/add.js')])
            self.assertEqual((untouched/'keep.txt').read_bytes(),b'unchanged')

    async def test_off_and_bad_paths_do_not_create_or_generate_code(self):
        before=Backend.calls
        async with client(self.config) as session:
            bad=await session.call_tool('start_code_job',arguments={'request_key':'bad-path','request':'コード案','file_paths':['../escape.js']})
            self.assertTrue(bad.isError)
            self.store.set_dispatch_enabled(False)
            code,error=await self.cli('start_code_job',{'request_key':'off-code','request':'コード案','file_paths':['index.html']})
            self.assertEqual(code,1);self.assertIn('OFF',error['error'])
            self.assertEqual(Backend.calls,before)
            self.assertFalse(list((Path(self.settings['data_dir'])/'jobs').iterdir()))

    @unittest.skipUnless(sys.platform=='win32','Windows host bridge')
    async def test_skill_helper_shares_status_and_off_guard(self):
        root=Path(self.temp.name)
        register(self.settings,root/'codex/config.toml',root/'codex/skills')
        self.store.set_dispatch_enabled(False)
        code,status=await self.cli('local_status',helper=True)
        self.assertEqual(code,0,status);self.assertFalse(status['local_dispatch']['enabled'])
        before=Backend.calls
        code,result=await self.cli('start_code_job',{'request_key':'bridge-off','request':'コード案','file_paths':['index.html']},helper=True)
        self.assertEqual(code,1);self.assertIn('OFF',result['error']);self.assertEqual(Backend.calls,before)
