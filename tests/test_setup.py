import json
import tempfile
import unittest
import shutil
import subprocess
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tomlkit
from setup_local import register,unregister


class SetupTests(unittest.TestCase):
    def test_clean_source_setup_and_remove_use_only_explicit_user_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);app=root/'source with spaces';app.mkdir()
            source=Path(__file__).resolve().parents[1]
            for name in ['orchestrator_local','examples','skills']:
                shutil.copytree(source/name,app/name,ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copyfile(source/'setup_local.py',app/'setup_local.py')
            backend=root/'ollama.exe';backend.write_bytes(b'not executed by setup')
            config=root/'user/config.toml';skills=root/'user/skills';data=root/'data'
            args=[sys.executable,'-X','utf8','-B',str(app/'setup_local.py'),'--data-dir',str(data),'--ollama-exe',str(backend),'--codex-config',str(config),'--skill-root',str(skills)]
            result=subprocess.run(args+['--register'],check=True,capture_output=True,text=True,encoding='utf8')
            self.assertTrue(json.loads(result.stdout)['connection']['registered'])
            settings=json.loads((app/'local-settings.json').read_text(encoding='utf8'))
            self.assertEqual(settings['data_dir'],str(data.resolve()))
            self.assertTrue((data/'inbox/inventory-example.json').exists())
            removed=subprocess.run(args+['--unregister'],check=True,capture_output=True,text=True,encoding='utf8')
            self.assertFalse(json.loads(removed.stdout)['registered'])
            self.assertNotIn('orchestrator_local',tomlkit.parse(config.read_text(encoding='utf8')).get('mcp_servers',{}))
            self.assertTrue((data/'inbox/inventory-example.json').exists())

    def test_preserves_existing_settings_and_registration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'config.toml'
            original='# user configuration\nmodel = "keep-me"\n[mcp_servers.existing]\ncommand = "original"\n'
            config.write_text(original,encoding='utf8')
            first=register({'config_path':str(root/'settings.json')},config,root/'skills',root/'receipt.json')
            after=config.read_bytes();parsed=tomlkit.parse(after.decode())
            self.assertEqual(parsed['model'],'keep-me');self.assertEqual(parsed['mcp_servers']['existing']['command'],'original')
            self.assertEqual(Path(first['backup']).read_text(encoding='utf8'),original)
            register({'config_path':str(root/'settings.json')},config,root/'skills',root/'receipt.json')
            self.assertEqual(config.read_bytes(),after)

    def test_name_conflict_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'config.toml'
            original='[mcp_servers.orchestrator_local]\ncommand = "someone-else"\n'
            config.write_text(original,encoding='utf8')
            with self.assertRaises(RuntimeError):register({'config_path':'settings.json'},config,root/'skills')
            self.assertEqual(config.read_text(encoding='utf8'),original)

    def test_unregister_preserves_other_config_and_moves_only_own_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'config.toml';skills=root/'skills'
            original='model="keep-me"\n[mcp_servers.existing]\ncommand="original"\n'
            config.write_text(original,encoding='utf8')
            settings={'config_path':str(root/'settings.json'),'data_dir':str(root/'data')}
            register(settings,config,skills,root/'receipt.json')
            original_skill=(skills/'orchestrator-local/SKILL.md').read_bytes()
            other=skills/'other';other.mkdir();(other/'SKILL.md').write_text('keep',encoding='utf8')
            result=unregister(settings,config,skills,root/'uninstall.json')
            self.assertEqual(tomlkit.parse(config.read_text(encoding='utf8')),tomlkit.parse(original))
            self.assertFalse((skills/'orchestrator-local').exists())
            self.assertEqual((Path(result['skill_backup'])/'SKILL.md').read_bytes(),original_skill)
            self.assertEqual((other/'SKILL.md').read_text(encoding='utf8'),'keep')
            unregister(settings,config,skills,root/'uninstall.json')

    def test_unregister_refuses_modified_skill_before_changing_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'config.toml';skills=root/'skills'
            settings={'config_path':str(root/'settings.json'),'data_dir':str(root/'data')}
            register(settings,config,skills,root/'receipt.json')
            before=config.read_bytes()
            target=skills/'orchestrator-local/SKILL.md';target.write_text('user edit',encoding='utf8')
            with self.assertRaises(RuntimeError):unregister(settings,config,skills,root/'uninstall.json')
            self.assertEqual(config.read_bytes(),before)
            self.assertEqual(target.read_text(encoding='utf8'),'user edit')


if __name__=='__main__':unittest.main()
