"""Guided setup and ownership-checked upgrades. Never runs the old application's code."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import tomlkit

from . import __version__
from .core import Store, UserError, read_settings
from .installation import connection_entry, initialize
from .paths import default_data_dir, resource_root


def files(folder):
    folder = Path(folder)
    if folder.is_symlink() or any(p.is_symlink() for p in folder.rglob('*')):
        raise UserError('リンクを含むSkillは自動更新できません。内容を確認してください。')
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file()}


def shortcut_state(controller):
    if sys.platform != 'win32': return None
    import pythoncom
    from win32com.client import Dispatch
    from .desktop import startup_folder
    pythoncom.CoInitialize()
    shell = link = None
    try:
        folder = controller.startup_dir or startup_folder()
        path = folder / 'Orchestrator Local.lnk'
        if not path.exists(): return None
        shell = Dispatch('WScript.Shell'); link = shell.CreateShortcut(str(path))
        return {'path': str(path), 'target': link.TargetPath, 'args': link.Arguments}
    finally:
        link = shell = None
        pythoncom.CoUninitialize()


def previous(controller):
    """Recognize only our documented command shapes and a matching packaged Skill/receipt."""
    raw = controller.codex_config.read_bytes() if controller.codex_config.exists() else b''
    document = tomlkit.parse(raw.decode('utf-8-sig'))
    entry = document.get('mcp_servers', {}).get('orchestrator_local')
    if entry is None: return None
    entry = dict(entry)
    args = list(entry.get('args', [])); command = Path(entry.get('command', ''))
    if len(args) != 3 or args[1] != '--config' or set(entry) - {'command','args','startup_timeout_sec','tool_timeout_sec'}:
        raise UserError('既存接続に独自の設定があります。自動更新せず、そのまま残します。')
    config = Path(args[2]).resolve(strict=True)
    if command.name.lower() == 'orchestratorlocal.runtime.exe' and args[0] == 'mcp':
        source = command.parent / '_internal'
        service = [str(command.with_name('OrchestratorLocal.exe')), '--service', '--config', str(config), '--background']
    elif command.name.lower() in {'python.exe','pythonw.exe','python','python3'} and Path(args[0]).name == 'serve.py':
        source = Path(args[0]).resolve().parent
        python = command.with_name('pythonw.exe') if sys.platform == 'win32' else command
        service = [str(python), str(source/'service_entry.py'), '--config', str(config), '--background']
    else:
        raise UserError('既存接続の導入元を確認できません。自動更新せず、そのまま残します。')
    settings = read_settings(config)
    dest = controller.skill_root/'orchestrator-local'
    observed = files(dest) if dest.exists() else None
    packaged = source/'skills/orchestrator-local'
    trusted = packaged.is_dir() and observed == files(packaged)
    for receipt in [source/'installation-receipt.json', Path(settings['data_dir'])/'runtime/installation-receipt.json']:
        if receipt.is_file():
            value = json.loads(receipt.read_text(encoding='utf-8-sig'))
            if value.get('registered') and value.get('server_name') == 'orchestrator_local' and Path(value.get('config_path','')).resolve() == controller.codex_config:
                trusted |= observed is not None and observed == value.get('skill_files_sha256')
    if observed is not None and not trusted:
        raise UserError('登録済みSkillに利用者の変更があります。上書きせず残しました。')
    return {'entry':entry, 'settings':settings, 'config':config, 'service':service, 'skill_hashes':observed}


def inspect_setup(controller):
    old = previous(controller)
    settings = old['settings'] if old else (controller.settings() if controller.config.exists() else None)
    skill=controller.skill_root/'orchestrator-local'
    if not old and skill.exists() and files(skill)!=files(resource_root()/'skills/orchestrator-local'):
        raise UserError('同名Skillの導入元を確認できません。内容を変更せず残します。')
    from .desktop import discover_ollama
    from .paths import runtime_command
    link = shortcut_state(controller)
    if link:
        expected = old['service'] if old else (runtime_command('service',controller.config)+['--background'] if settings else None)
        actual_args = [p.strip('"') for p in shlex.split(link['args'], posix=False)]
        if not expected or Path(link['target']).resolve() != Path(expected[0]).resolve() or actual_args != expected[1:]:
            raise UserError('同名の自動起動に独自の設定があります。自動更新せず残します。')
    return {'existing': bool(settings), 'data_dir': settings['data_dir'] if settings else str(default_data_dir()),
            'ollama_exe': settings.get('ollama_exe','') if settings else discover_ollama(),
            'models': settings.get('ollama_environment',{}).get('OLLAMA_MODELS','') if settings else os.environ.get('OLLAMA_MODELS',''),
            'auto_start': bool(link), 'previous_config': str(old['config']) if old else None,
            'codex_sha256': hashlib.sha256(controller.codex_config.read_bytes() if controller.codex_config.exists() else b'').hexdigest()}


def apply_setup(controller, plan, data_dir, ollama_exe, models='', auto_start=False):
    """Back up changed registration/settings/Skill/Startup; rollback on failure."""
    from .desktop import DesktopController
    from .service import status
    current_plan = inspect_setup(controller)
    if current_plan != plan:
        raise UserError('確認中に設定が変わりました。セットアップを開き直してください。')
    old = previous(controller)
    if plan['existing'] and (str(Path(data_dir).resolve()),str(Path(ollama_exe).resolve()),models or '') != (str(Path(plan['data_dir']).resolve()),str(Path(plan['ollama_exe']).resolve()),plan['models']):
        raise UserError('更新時は既存の保存先とモデル設定を引き継いでください。')
    if not Path(ollama_exe).is_file() or (models and not Path(models).is_dir()):
        raise UserError('Ollamaまたはモデルフォルダが見つかりません。場所を選び直してください。')
    settings = dict(old['settings']) if old else (dict(controller.settings()) if controller.config.exists() else None)
    if settings:
        store = Store(settings)
        with store.connection() as db:
            if db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('QUEUED','RUNNING')").fetchone()[0]:
                raise UserError('作業が残っています。完了または中止してから更新してください。')
        running = status(settings)
        if running['ready']:
            if Path(running.get('config','')).resolve() != Path(settings['config_path']).resolve():
                raise UserError('同じ保存先を別のサービスが使用中です。自動停止しません。')
            DesktopController(settings['config_path']).stop_service()
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = Path(data_dir).resolve()/'runtime'/('setup-backup-'+stamp)
    backup.mkdir(parents=True)
    config_before = controller.config.read_bytes() if controller.config.exists() else None
    codex_before = controller.codex_config.read_bytes() if controller.codex_config.exists() else None
    skill = controller.skill_root/'orchestrator-local'
    skill_before = files(skill) if skill.exists() else None
    link = shortcut_state(controller)
    if config_before is not None: (backup/'local-settings.json').write_bytes(config_before)
    if codex_before is not None: (backup/'config.toml').write_bytes(codex_before)
    if skill_before is not None: shutil.copytree(skill,backup/'skill')
    if link: shutil.copyfile(link['path'],backup/'startup.lnk')
    changed = []
    stage_root = controller.skill_root.parent/('.orchestrator-local-setup-'+stamp)
    stage = stage_root/'new'
    try:
        if settings:
            settings.pop('config_path',None)
            controller.config.parent.mkdir(parents=True,exist_ok=True)
            _write(controller.config,(json.dumps(settings,ensure_ascii=False,indent=2)+'\n').encode('utf8'))
        else:
            initialize(controller.config,data_dir,ollama_exe,models or None)
        changed.append('settings')
        settings = controller.settings()
        document = tomlkit.parse((codex_before or b'').decode('utf-8-sig'))
        document.setdefault('mcp_servers',tomlkit.table())['orchestrator_local'] = connection_entry(settings)
        after = tomlkit.dumps(document).encode('utf8')
        controller.codex_config.parent.mkdir(parents=True,exist_ok=True)
        controller.skill_root.mkdir(parents=True,exist_ok=True)
        shutil.copytree(resource_root()/'skills/orchestrator-local',stage)
        if (controller.codex_config.read_bytes() if controller.codex_config.exists() else None) != codex_before or (files(skill) if skill.exists() else None) != skill_before:
            raise UserError('更新中に接続設定が変わりました。変更せず停止します。')
        _write(controller.codex_config,after); changed.append('codex')
        changed.append('skill')
        if skill.exists(): skill.rename(stage_root/'previous')
        stage.rename(skill)
        if link: Path(link['path']).unlink()
        changed.append('startup')
        controller.set_startup(auto_start)
        Store(settings).set_dispatch_enabled(False)
        receipt = {'registered':True,'server_name':'orchestrator_local','application_version':__version__,
                   'config_path':str(controller.codex_config),'settings_path':str(controller.config),
                   'skill_files_sha256':files(skill),'backup':str(backup),'data_preserved':True,
                   'restart_connection_required':True,'local_dispatch_enabled':False}
        controller.start_service()
        (Path(settings['data_dir'])/'runtime/installation-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        return receipt
    except Exception:
        if 'settings' in changed:
            try:
                active=status(controller.settings())
                if active['ready'] and Path(active.get('config','')).resolve()==controller.config:
                    controller.stop_service()
            except Exception: pass
        if 'startup' in changed:
            try:controller.set_startup(False)
            except Exception:pass
            if link: shutil.copyfile(backup/'startup.lnk',link['path'])
        if 'skill' in changed:
            if skill.exists():shutil.rmtree(skill)
            if skill_before is not None: shutil.copytree(backup/'skill',skill)
        if 'codex' in changed: _restore(controller.codex_config,codex_before)
        if 'settings' in changed: _restore(controller.config,config_before)
        raise
    finally:
        if stage_root.exists() and stage_root.parent==controller.skill_root.parent and stage_root.name.startswith('.orchestrator-local-setup-'):
            shutil.rmtree(stage_root)


def _write(path, raw):
    temp = path.with_name(path.name+'.setup.tmp')
    with temp.open('xb') as f:
        f.write(raw);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


def _restore(path, raw):
    if raw is None: path.unlink(missing_ok=True)
    else: _write(path,raw)
