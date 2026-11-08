"""Desktop setup and control use temporary user paths and a fake model backend."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import tomlkit
from unittest.mock import patch
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orchestrator_local.core import Store, UserError, sha
from orchestrator_local.desktop import DesktopController
from orchestrator_local.installation import initialize
from orchestrator_local.paths import default_config, runtime_command
from test_runtime import Backend, BASE


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
        cls.thread = threading.Thread(target=cls.backend.serve_forever, daemon=True); cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.backend.shutdown(); cls.backend.server_close(); cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = self.root / 'settings.json'
        self.exe = self.root / 'ollama.exe'; self.exe.write_bytes(b'not executed')
        self.data = self.root / 'data'
        settings = initialize(self.config, self.data, self.exe)
        settings.pop('config_path')
        settings.update(ollama_url=f'http://127.0.0.1:{self.backend.server_port}', model_digest='test-digest', auto_start_ollama=False)
        self.config.write_text(json.dumps(settings), encoding='utf8')
        self.controller = DesktopController(self.config, self.root / 'codex/config.toml', self.root / 'codex/skills', self.root / 'startup')

    def tearDown(self):
        self.controller.stop_service()
        self.temp.cleanup()

    def test_setup_status_and_removal_never_generate_or_replace_existing_settings(self):
        before = Backend.calls
        self.controller.codex_config.parent.mkdir()
        self.controller.codex_config.write_text('model="preserved"\n', encoding='utf8')
        self.controller.setup(self.data, self.exe, auto_start=sys.platform == 'win32')
        status = self.controller.snapshot()
        self.assertEqual(status['connection'], 'registered')
        self.assertTrue(status['backend']['digest_matches'])
        self.assertFalse(status['service']['ready'])
        if sys.platform == 'win32':
            self.assertTrue(self.controller.startup())
            link = self.root / 'startup/Orchestrator Local.lnk'
            import win32com.client
            import pythoncom
            pythoncom.CoInitialize()
            shortcut = None
            try:
                shortcut = win32com.client.Dispatch('WScript.Shell').CreateShortcut(str(link))
                self.assertIn('pythonw.exe', shortcut.TargetPath.lower())
                self.assertIn('--background', shortcut.Arguments)
            finally:
                shortcut = None
                pythoncom.CoUninitialize()
            self.controller.set_startup(False); self.assertFalse(link.exists())
        raw = self.config.read_bytes()
        with self.assertRaises(UserError): self.controller.setup(self.root / 'elsewhere', self.exe)
        self.assertEqual(self.config.read_bytes(), raw)
        self.controller.remove_connection()
        self.assertEqual(tomlkit.parse(self.controller.codex_config.read_text(encoding='utf8')), {'model': 'preserved'})
        self.assertTrue((self.data / 'inbox/inventory-example.json').exists())
        self.assertEqual(Backend.calls, before)

    def test_service_singleton_history_candidate_and_saved_result(self):
        store = Store(self.controller.settings())
        before = Backend.calls
        first = self.controller.start_service(); second = self.controller.start_service()
        self.assertEqual(first['pid'], second['pid'])
        self.assertEqual(Backend.calls, before)
        row, _ = store.create('desktop-job', '合計を集計する')
        store.update(row['id'], worker_pid=first['pid'])
        for _ in range(100):
            if store.get(row['id'])['state'] not in {'QUEUED', 'RUNNING'}: break
            time.sleep(.1)
        self.assertEqual(store.get(row['id'])['state'], 'CANDIDATE_READY')
        with self.assertRaises(UserError): self.controller.folder('result', row['id'])
        snap = self.controller.snapshot()
        self.assertEqual(snap['jobs'][0]['title'], '合計を集計する')
        store.save(row['id'], sha(BASE))
        self.assertTrue((self.controller.folder('result', row['id']) / 'report.md').is_file())
        queued, _ = store.create('cancel-desktop-job', '中止する作業')
        self.controller.cancel_job(queued['id'])
        self.assertTrue(store.get(queued['id'])['cancel'])

    def test_input_import_preserves_names_and_bytes_without_overwrite(self):
        source = self.root / 'inventory-example.json'; source.write_text('{"new":true}', encoding='utf8')
        old = (self.data / 'inbox/inventory-example.json').read_bytes()
        first = self.controller.import_inputs([source])[0]
        self.assertNotEqual(Path(first).name, source.name)
        self.assertEqual(self.controller.import_inputs([source]), [first])
        self.assertEqual((self.data / 'inbox/inventory-example.json').read_bytes(), old)
        forbidden = self.root / 'bad.exe'; forbidden.write_bytes(b'no')
        with self.assertRaises(UserError): self.controller.import_inputs([source, forbidden])

    def test_frozen_commands_do_not_reference_python_or_temporary_extraction_scripts(self):
        if sys.platform == 'win32':
            with patch.object(sys, 'executable', str(Path(sys.executable).with_name('pythonw.exe'))):
                self.assertEqual(Path(runtime_command('mcp', self.config)[0]).name, 'python.exe')
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(self.root / 'Program Files/OrchestratorLocal.exe')):
            self.assertEqual(Path(runtime_command('mcp', self.config)[0]).name, 'OrchestratorLocal.Runtime.exe')
            self.assertEqual(runtime_command('service', self.config)[1], '--service')
            self.assertNotIn('python', str(default_config()).lower())

    @unittest.skipUnless(sys.platform == 'win32', 'Windows Startup shortcut')
    def test_another_installations_startup_shortcut_is_never_replaced(self):
        self.controller.set_startup(True)
        link = self.root / 'startup/Orchestrator Local.lnk'
        before = link.read_bytes()
        other = DesktopController(self.root / 'other/settings.json', self.controller.codex_config,
                                  self.controller.skill_root, self.controller.startup_dir)
        self.assertFalse(other.startup())
        for enabled in [False, True]:
            with self.assertRaises(UserError): other.set_startup(enabled)
            self.assertEqual(link.read_bytes(), before)
        self.controller.set_startup(False)

    def test_gui_renders_unconfigured_then_review_wait_and_completed_without_adoption(self):
        import tkinter as tk
        from orchestrator_local.gui import App
        root = tk.Tk(); root.withdraw()
        app = App(root, self.controller, auto_refresh=False)
        try:
            for _ in range(100):
                root.update()
                if not app.busy: break
                time.sleep(.02)
            self.assertFalse(app.busy)
            app.render({'configured': False, 'jobs': []})
            self.assertIn('初回設定', app.headline.get())
            snap = self.controller.snapshot(probe=False)
            snap['backend'] = {'reachable': True, 'model_installed': True, 'digest_matches': True}
            snap['jobs'] = [dict(id='1'*32, title='在庫一覧を作成', state='CANDIDATE_READY', phase='確認待ち', created=time.time(), cancel=0, error=None)]
            app.render(snap); root.update_idletasks()
            self.assertEqual(app.tree.item('1'*32)['values'][-1], 'AIの確認待ち')
            self.assertNotIn('採用', ' '.join(str(b['text']) for b in app.action_buttons))
            self.assertLess(app.home.winfo_reqheight(), 630)
        finally:
            app.close()


if __name__ == '__main__': unittest.main()
