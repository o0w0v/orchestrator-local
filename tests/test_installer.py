"""Fresh and source-to-EXE migrations use only temporary profiles and fake backends."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

import tomlkit
from orchestrator_local.core import Store,UserError
from orchestrator_local.desktop import DesktopController
from orchestrator_local.installer import install_payload
from orchestrator_local.installation import initialize
from orchestrator_local.paths import resource_root
from orchestrator_local.setup_flow import apply_setup,files,inspect_setup


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.exe=self.root/'ollama.exe';self.exe.write_bytes(b'never executed')
        self.old=self.root/'old';self.old.mkdir()
        self.config=self.old/'local-settings.json'
        self.settings=initialize(self.config,self.root/'original-data',self.exe)
        (self.old/'serve.py').write_text('# recognized previous layout')
        shutil.copytree(resource_root()/'skills',self.old/'skills')
        self.controller=DesktopController(self.root/'new/local-settings.json',self.root/'codex/config.toml',self.root/'codex/skills',self.root/'startup')
        self.controller.codex_config.parent.mkdir()
        entry={'command':sys.executable,'args':[str(self.old/'serve.py'),'--config',str(self.config)],'startup_timeout_sec':20,'tool_timeout_sec':60}
        document=tomlkit.parse('model="keep"\n[mcp_servers.unrelated]\ncommand="keep"\n')
        document['mcp_servers']['orchestrator_local']=entry
        self.controller.codex_config.write_text(tomlkit.dumps(document),encoding='utf8')
        shutil.copytree(self.old/'skills/orchestrator-local',self.controller.skill_root/'orchestrator-local')

    def tearDown(self):self.temp.cleanup()

    def apply(self,plan):
        return apply_setup(self.controller,plan,plan['data_dir'],plan['ollama_exe'],plan['models'],False)

    def test_migration_preserves_registered_data_over_accidental_new_gui_settings(self):
        initialize(self.controller.config,self.root/'accidental-empty-data',self.exe)
        before=self.controller.config.read_bytes()
        sentinel=Path(self.settings['data_dir'])/'important.txt';sentinel.write_bytes(b'keep result')
        plan=inspect_setup(self.controller)
        self.assertEqual(plan['data_dir'],self.settings['data_dir'])
        with patch.object(self.controller,'start_service',return_value={'ready':True}):receipt=self.apply(plan)
        self.assertEqual(self.controller.settings()['data_dir'],self.settings['data_dir'])
        self.assertEqual((Path(receipt['backup'])/'local-settings.json').read_bytes(),before)
        self.assertEqual(sentinel.read_bytes(),b'keep result')
        document=tomlkit.parse(self.controller.codex_config.read_text())
        self.assertEqual(document['mcp_servers']['unrelated']['command'],'keep')
        self.assertEqual(document['model'],'keep')
        self.assertFalse(Store(self.controller.settings()).dispatch_state()['enabled'])
        self.assertEqual(inspect_setup(self.controller)['data_dir'],self.settings['data_dir'])

    def test_modified_skill_or_changed_plan_is_not_overwritten(self):
        plan=inspect_setup(self.controller)
        skill=self.controller.skill_root/'orchestrator-local/SKILL.md'
        skill.write_text(skill.read_text()+'\nuser customization\n',encoding='utf8')
        before=self.controller.codex_config.read_bytes()
        with self.assertRaises(UserError):self.apply(plan)
        self.assertEqual(self.controller.codex_config.read_bytes(),before)

    @unittest.skipUnless(sys.platform=='win32','Windows shortcut migration')
    def test_previous_startup_is_migrated_with_backup(self):
        import pythoncom
        from win32com.client import Dispatch
        from orchestrator_local.setup_flow import previous,shortcut_state
        self.controller.startup_dir.mkdir()
        pythoncom.CoInitialize();shell=shortcut=None
        path=self.controller.startup_dir/'Orchestrator Local.lnk'
        try:
            command=previous(self.controller)['service']
            shell=Dispatch('WScript.Shell');shortcut=shell.CreateShortcut(str(path))
            import subprocess
            shortcut.TargetPath=command[0];shortcut.Arguments=subprocess.list2cmdline(command[1:]);shortcut.Save()
        finally:shortcut=shell=None;pythoncom.CoUninitialize()
        before=path.read_bytes();plan=inspect_setup(self.controller)
        self.assertTrue(plan['auto_start'])
        with patch.object(self.controller,'start_service',return_value={'ready':True}):
            receipt=apply_setup(self.controller,plan,plan['data_dir'],plan['ollama_exe'],plan['models'],True)
        self.assertEqual((Path(receipt['backup'])/'startup.lnk').read_bytes(),before)
        self.assertTrue(self.controller.startup())

    def test_stale_plan_is_refused_before_changing_settings(self):
        plan=inspect_setup(self.controller)
        with self.controller.codex_config.open('a') as f:f.write('\n# user changed the configuration\n')
        with self.assertRaises(UserError):self.apply(plan)
        self.assertFalse(self.controller.config.exists())

    def test_running_or_queued_work_blocks_upgrade(self):
        store=Store(self.settings);store.set_dispatch_enabled(True);store.create('pending','preserve')
        plan=inspect_setup(self.controller)
        before=self.controller.codex_config.read_bytes()
        with self.assertRaises(UserError):self.apply(plan)
        self.assertEqual(self.controller.codex_config.read_bytes(),before)
        self.assertFalse(self.controller.config.exists())

    def test_failure_restores_connection_skill_and_target_settings(self):
        plan=inspect_setup(self.controller);before=self.controller.codex_config.read_bytes()
        old_files=files(self.controller.skill_root/'orchestrator-local')
        with patch.object(self.controller,'start_service',side_effect=RuntimeError('simulate start failure')):
            with self.assertRaisesRegex(RuntimeError,'simulate'):self.apply(plan)
        self.assertEqual(self.controller.codex_config.read_bytes(),before)
        self.assertEqual(files(self.controller.skill_root/'orchestrator-local'),old_files)
        self.assertFalse(self.controller.config.exists())

    def test_fresh_wizard_completes_and_returns_to_off(self):
        import tkinter as tk
        from orchestrator_local.gui import App
        self.controller.codex_config.unlink();shutil.rmtree(self.controller.skill_root)
        root=tk.Tk();root.withdraw();app=App(root,self.controller,auto_refresh=False)
        def settle():
            for _ in range(300):
                root.update()
                if not app.busy:return
                time.sleep(.01)
            self.fail('wizard did not settle')
        try:
            settle();app.open_setup();settle();wizard=app.wizard
            wizard.advance();wizard.data.set(str(self.root/'new-data'));wizard.ollama.set(str(self.exe));wizard.models.set('')
            wizard.advance();self.assertEqual(wizard.page,2)
            with patch.object(self.controller,'start_service',return_value={'ready':True}):wizard.advance();settle()
            self.assertEqual(wizard.page,3)
            self.assertFalse(Store(self.controller.settings()).dispatch_state()['enabled'])
            wizard.advance();self.assertIsNone(app.wizard)
        finally:app.close()

    def test_closing_wizard_during_discovery_does_not_break_the_app(self):
        import tkinter as tk
        from orchestrator_local.gui import App
        root=tk.Tk();root.withdraw();errors=[]
        root.report_callback_exception=lambda *args:errors.append(args)
        app=App(root,self.controller,auto_refresh=False)
        try:
            for _ in range(200):
                root.update()
                if not app.busy:break
                time.sleep(.01)
            app.open_setup();app.wizard.close()
            for _ in range(200):
                root.update()
                if not app.busy:break
                time.sleep(.01)
            self.assertFalse(app.busy);self.assertFalse(errors);self.assertIsNone(app.wizard)
        finally:app.close()


class PayloadTests(unittest.TestCase):
    def test_payload_verified_reinstall_and_reject_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=root/'app.zip'
            manifest=[{'path':'OrchestratorLocal.exe','sha256':hashlib.sha256(b'app').hexdigest()}]
            def write(extra=None):
                with zipfile.ZipFile(archive,'w') as z:
                    z.writestr('OrchestratorLocal/OrchestratorLocal.exe',b'app')
                    z.writestr('OrchestratorLocal/FILES.sha256.json',json.dumps(manifest))
                    if extra:z.writestr(extra,b'no')
                return hashlib.sha256(archive.read_bytes()).hexdigest()
            digest=write();destination=root/'installed'
            install_payload(archive,destination,digest);install_payload(archive,destination,digest)
            self.assertEqual((destination/'OrchestratorLocal.exe').read_bytes(),b'app')
            digest=write('OrchestratorLocal/../escape.exe')
            with self.assertRaises(ValueError):install_payload(archive,root/'bad',digest)
            self.assertFalse((root/'escape.exe').exists())
