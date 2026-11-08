"""The OFF preference is enforced at admission and claim, including live MCP sessions."""
import asyncio
from pathlib import Path
import tempfile
import unittest

from orchestrator_local.core import Store, UserError
import test_runtime as fixtures
from test_runtime import Backend, call, client


class AdmissionTests(unittest.TestCase):
    def test_default_off_persists_across_stores_and_does_not_cancel_running_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = {'data_dir': tmp, 'input_roots': [str(Path(tmp)/'inbox')],
                        'options': {'num_ctx': 65536, 'num_predict': 32768}}
            store = Store(settings)
            self.assertFalse(store.dispatch_state()['enabled'])
            with self.assertRaises(UserError): store.create('off', '集計する')
            self.assertFalse(list((Path(tmp)/'jobs').iterdir()))
            store.set_dispatch_enabled(True)
            running, _ = store.create('running', '集計する')
            self.assertTrue(store.claim(running['id']))
            waiting, _ = store.create('waiting', '続く作業')
            Store(settings).set_dispatch_enabled(False)
            self.assertEqual(store.get(running['id'])['state'], 'RUNNING')
            self.assertFalse(store.claim(waiting['id']))
            self.assertEqual(store.get(waiting['id'])['state'], 'QUEUED')
            self.assertFalse(store.create('running', '集計する')[1])
            with self.assertRaises(UserError): store.create('off-again', '新しい作業')
            store.set_dispatch_enabled(True)
            store.update(running['id'], state='CANCELLED')
            self.assertTrue(store.claim(waiting['id']))


class DispatchRuntimeTests(unittest.IsolatedAsyncioTestCase):
    setUpClass = classmethod(fixtures.RuntimeTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.RuntimeTests.tearDownClass.__func__)
    setUp = fixtures.RuntimeTests.setUp
    tearDown = fixtures.RuntimeTests.tearDown
    ready = fixtures.RuntimeTests.ready

    async def test_off_blocks_an_already_connected_mcp_session_but_allows_saving_existing_candidate(self):
        before = Backend.calls
        self.store.set_dispatch_enabled(False)
        async with client(self.config) as session:
            self.assertFalse((await call(session, 'local_status'))['local_dispatch']['enabled'])
            rejected = await session.call_tool('start_job', arguments={'request_key':'off','request':'集計する'})
            self.assertTrue(rejected.isError)
            self.assertEqual(Backend.calls, before)
            Store(self.settings).set_dispatch_enabled(True)
            job = await call(session, 'start_job', request_key='on', request='集計する')
            candidate = await self.ready(session, job['id'])
            self.store.set_dispatch_enabled(False)
            self.assertFalse((await call(session, 'local_status'))['local_dispatch']['enabled'])
            rejected = await session.call_tool('start_job', arguments={'request_key':'off-again','request':'新規作業'})
            self.assertTrue(rejected.isError)
            saved = await call(session, 'finalize_job', job_id=job['id'], candidate_hash=candidate['candidate_hash'])
            self.assertTrue((Path(saved['saved_path'])/'report.md').is_file())
            self.assertEqual(Backend.calls, before+1)

    async def test_off_holds_queued_work_while_running_work_finishes(self):
        before = Backend.calls
        async with client(self.config) as session:
            active = await call(session, 'start_job', request_key='slow-on', request='集計する', inputs={'scenario':'slow'})
            for _ in range(100):
                if Backend.calls == before+1: break
                await asyncio.sleep(.02)
            self.assertEqual(Backend.calls, before+1)
            waiting = await call(session, 'start_job', request_key='queued-on', request='次を集計する')
            self.store.set_dispatch_enabled(False)
            self.assertEqual((await self.ready(session, active['id']))['state'], 'CANDIDATE_READY')
            await asyncio.sleep(.4)
            self.assertEqual(self.store.get(waiting['id'])['state'], 'QUEUED')
            self.assertEqual(Backend.calls, before+1)
            self.store.set_dispatch_enabled(True)
            self.assertEqual((await self.ready(session, waiting['id']))['state'], 'CANDIDATE_READY')
            self.assertEqual(Backend.calls, before+2)


if __name__ == '__main__': unittest.main()
