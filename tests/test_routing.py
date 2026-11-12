"""Routing tests use fake calls and temporary state; no Cloud, real Gemma, or user registration."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from orchestrator_local.core import Store, UserError, packed, sha
from orchestrator_local.routing import MODEL, Router, native_usage, completed_result, DISABLED_HOST_NOTICE

DECISION={'route':'GEMMA_DIRECT','reason':'明確な集計','delegation_scope':'集計だけ','verification':'元資料と照合',
          'state':'COMPLETE','source':'LUNA','model_called':True,'usage':{'input_tokens':20,'output_tokens':5},'usage_capture_complete':True}


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.store=Store({'data_dir':str(self.root),'input_roots':[str(self.root/'inbox')],
            'options':{'num_ctx':65536,'num_predict':32768}})
        self.router=Router(self.store)

    def test_off_and_per_request_optout_never_invoke_router(self):
        with patch('orchestrator_local.routing.run_luna') as run:
            self.assertEqual(self.router.route('off','依頼')['route'],'SOL_DIRECT')
            self.store.set_dispatch_enabled(True)
            self.assertEqual(self.router.route('no-local','依頼',local_allowed=False)['route'],'SOL_DIRECT')
            run.assert_not_called()
        self.assertFalse((self.root/'routing').exists())

    def test_retry_returns_same_result_and_changed_source_is_rejected(self):
        self.store.set_dispatch_enabled(True)
        with patch('orchestrator_local.routing.run_luna',return_value=DECISION) as run:
            first=self.router.route('same','集計',{'rows':[1,2,3]})
            second=self.router.route('same','集計',{'rows':[1,2,3]})
            self.assertEqual(first['routing_id'],second['routing_id']);self.assertTrue(second['reused'])
            self.assertEqual(run.call_count,1)
            with self.assertRaises(UserError):self.router.route('same','集計',{'rows':[1,2,4]})
            self.assertEqual(run.call_count,1)

    def test_concurrent_duplicate_does_not_make_a_second_paid_call(self):
        self.store.set_dispatch_enabled(True);started=threading.Event();release=threading.Event()
        def fake(*args):
            started.set();self.assertTrue(release.wait(5));return DECISION
        with patch('orchestrator_local.routing.run_luna',side_effect=fake) as run,ThreadPoolExecutor(2) as pool:
            first=pool.submit(self.router.route,'concurrent','集計')
            self.assertTrue(started.wait(5))
            second=self.router.route('concurrent','集計')
            self.assertEqual(second['state'],'RUNNING');self.assertEqual(run.call_count,1)
            release.set();self.assertEqual(first.result()['route'],'GEMMA_DIRECT')

    def test_failed_paid_call_is_preserved_and_never_automatically_retried(self):
        self.store.set_dispatch_enabled(True)
        def fail(settings,folder,task):
            (folder/'STARTED.json').write_text('{}');raise UserError('capacity failure')
        with patch('orchestrator_local.routing.run_luna',side_effect=fail) as run:
            first=self.router.route('failure','集計');second=self.router.route('failure','集計')
            self.assertEqual(first['route'],'SOL_DIRECT');self.assertTrue(first['reported_consumption_unknown'])
            self.assertTrue(second['reused']);self.assertEqual(run.call_count,1)
            self.assertTrue((Path(first['audit_path'])/'STARTED.json').exists())

    def test_oversized_source_is_not_truncated_or_sent(self):
        self.store.set_dispatch_enabled(True)
        with patch('orchestrator_local.routing.run_luna') as run:
            result=self.router.route('large','集計',{'source':'あ'*24000})
            self.assertEqual(result['route'],'SOL_DIRECT');run.assert_not_called()

    def test_same_contract_reaches_worker_and_conversation_review(self):
        self.store.set_dispatch_enabled(True)
        contract={'evidence_ids':'request.id, catalog.id, teams.idの順。起点を含める。'}
        inputs={'work_contract':contract,'rows':[{'id':'r1','ref':'c1'}]}
        schema={'type':'object','properties':{'evidence_ids':{'type':'array','items':{'type':'string'},'description':contract['evidence_ids']}},'required':['evidence_ids']}
        with patch('orchestrator_local.routing.run_luna',return_value=DECISION):
            result=self.router.route('contract','証跡を返す',inputs,data_schema=schema)
        job,_=self.store.create('contract','証跡を返す',inputs,data_schema=schema)
        candidate={'data':{'evidence_ids':['r1','c1','t1']},'report_md':'宛先を特定しました。'}
        self.store.update(job['id'],state='CANDIDATE_READY',candidate=packed(candidate),candidate_hash=sha(candidate))
        view=self.store.view(job['id'],True)
        self.assertEqual(result['work_contract'],view['review_inputs']['inputs']['work_contract'])
        self.assertEqual(view['review_data_schema'],schema);self.assertEqual(view['candidate'],candidate)

    def test_native_metadata_counts_once_and_does_not_export_private_thought(self):
        root=self.root/'codex';sessions=root/'sessions';sessions.mkdir(parents=True)
        usage={'input_tokens':100,'cached_input_tokens':80,'cache_write_input_tokens':0,
               'output_tokens':5,'reasoning_output_tokens':1,'total_tokens':105}
        values=[{'type':'turn_context','payload':{'model':MODEL,'effort':'low','service_tier':None}},
                {'type':'private_reasoning','payload':{'text':'PRIVATE_TEST_DO_NOT_EXPORT'}},
                {'type':'token_usage_record','payload':{'response_id':'response-one','usage':usage,'thread_token_usage':usage}}]
        path=sessions/'rollout-session-one.jsonl';path.write_text('\n'.join(packed(x) for x in values),encoding='utf8')
        with patch.dict(os.environ,{'CODEX_HOME':str(root)}):
            result=native_usage('session-one');self.assertEqual(result['usage'],usage)
            self.assertNotIn('PRIVATE_TEST_DO_NOT_EXPORT',packed(result))
            path.write_text(path.read_text()+'\n'+packed(values[-1]),encoding='utf8')
            with self.assertRaises(UserError):native_usage('session-one')

    def test_disabled_host_startup_notice_is_not_a_model_tool_call(self):
        folder=self.root/'recorded';folder.mkdir()
        answer={key:DECISION[key] for key in ['route','reason','delegation_scope','verification']}
        beginning=[{'type':'thread.started','thread_id':'fixture'},
                   {'type':'item.completed','item':{'type':'error','message':DISABLED_HOST_NOTICE}}]
        turn={'type':'turn.started'}
        ending=[{'type':'item.completed','item':{'type':'agent_message','text':packed(answer)}},
                {'type':'turn.completed'}]
        (folder/'answer.json').write_text(packed(answer),encoding='utf8')
        (folder/'stderr.log').write_text('',encoding='utf8')
        def write(events):
            (folder/'events.jsonl').write_text('\n'.join(packed(x) for x in events),encoding='utf8')
        with patch('orchestrator_local.routing.native_usage',return_value={'usage':{'input_tokens':10}}):
            write(beginning+[turn]+ending)
            value=completed_result(folder,0)
            self.assertEqual(value['route'],'GEMMA_DIRECT');self.assertTrue(value['usage_capture_complete'])
            self.assertEqual(value['startup_notices'],[DISABLED_HOST_NOTICE])
            for event in [{'type':'error','message':'Unknown runtime error'},
                          {'type':'command_execution','command':'must not run'}]:
                write(beginning+[turn,{'type':'item.completed','item':event}]+ending)
                with self.assertRaises(UserError):completed_result(folder,0)
            write([beginning[0],turn,beginning[1]]+ending)
            with self.assertRaises(UserError):completed_result(folder,0)


if __name__=='__main__':unittest.main()
