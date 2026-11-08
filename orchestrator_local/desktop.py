"""Desktop operations. Reuse installation, singleton service and durable job store."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import time

import tomlkit

from .core import Store, UserError, parse, read_settings
from .health import backend_status
from .installation import connection_entry, initialize, register, unregister
from .paths import default_codex_paths, default_config, resource_root, runtime_command
from .service import status as service_status
from .worker import reap_interrupted


def discover_ollama():
    found = shutil.which('ollama')
    if found:
        return found
    candidate = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'Programs/Ollama/ollama.exe'
    return str(candidate) if candidate.is_file() else ''


def startup_folder():
    if sys.platform != 'win32':
        raise UserError('自動起動の登録はWindowsで利用できます')
    # Resolve the actual Windows Startup known folder, including redirected profiles.
    from win32com.client import Dispatch
    return Path(Dispatch('WScript.Shell').SpecialFolders('Startup'))


class DesktopController:
    def __init__(self, config=None, codex_config=None, skill_root=None, startup_dir=None):
        defaults = default_codex_paths()
        self.config = Path(config or default_config()).resolve()
        self.codex_config = Path(codex_config or defaults[0]).resolve()
        self.skill_root = Path(skill_root or defaults[1]).resolve()
        self.startup_dir = Path(startup_dir).resolve() if startup_dir else None
        self.children = []

    def settings(self):
        return read_settings(self.config)

    def connection_state(self, settings):
        if not self.codex_config.exists():
            return 'missing'
        document = tomlkit.parse(self.codex_config.read_text(encoding='utf-8-sig'))
        value = document.get('mcp_servers', {}).get('orchestrator_local')
        if value is None:
            return 'missing'
        return 'registered' if dict(value) == connection_entry(settings) else 'other_installation'

    def snapshot(self, probe=True):
        if not self.config.exists():
            return {'configured': False, 'jobs': [], 'config': str(self.config)}
        settings = self.settings()
        store = Store(settings)
        dispatch = store.dispatch_state()
        reap_interrupted(store)
        with store.connection() as db:
            rows = [dict(r) for r in db.execute(
                'SELECT id,request_key,payload,state,phase,created,saved_path,cancel,error FROM jobs ORDER BY created DESC LIMIT 200')]
        for row in rows:
            row['title'] = parse(row.pop('payload'))['request'].replace('\n', ' ')[:80]
        try:
            connection = self.connection_state(settings)
        except (ValueError, OSError):
            connection = 'invalid'
        return {'configured': True, 'config': str(self.config), 'settings': settings,
                'service': service_status(settings), 'connection': connection, 'jobs': rows,
                'local_dispatch': dispatch,
                'backend': backend_status(settings) if probe and dispatch['enabled'] else None}

    def setup(self, data_dir, ollama_exe, models=None, auto_start=False):
        existed = self.config.exists()
        if existed:
            saved = self.settings()
            requested = (Path(data_dir).resolve(), Path(ollama_exe).resolve(), str(Path(models).resolve()) if models else None)
            current = (Path(saved['data_dir']), Path(saved['ollama_exe']), saved.get('ollama_environment', {}).get('OLLAMA_MODELS'))
            if requested != current:
                raise UserError('既存設定の保存先・モデル場所は自動変更しません。現在の設定を使うか、別の設定ファイルを指定してください')
        settings = initialize(self.config, data_dir, ollama_exe, models)
        receipt = register(settings, self.codex_config, self.skill_root)
        self.set_startup(auto_start)
        return receipt

    def remove_connection(self):
        Store(self.settings()).set_dispatch_enabled(False)
        return unregister(self.settings(), self.codex_config, self.skill_root)

    def set_enabled(self, enabled):
        settings = self.settings()
        store = Store(settings)
        if enabled:
            if self.connection_state(settings) != 'registered':
                raise UserError('先に「詳細」の設定で、この導入先のCodex接続を登録してください')
            self.start_service()
        return store.set_dispatch_enabled(enabled)

    def start_service(self):
        settings = self.settings()
        def compatible(state):
            if state.get('control_version') != 1:
                raise UserError('旧版サービスが起動中です。「詳細」の停止で止めてからONにしてください')
            return state
        current = service_status(settings)
        if current['ready']:
            return compatible(current)
        folder = Path(settings['data_dir']) / 'runtime'
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.time_ns()
        with (folder / f'service-{stamp}.stdout.log').open('ab') as stdout, (folder / f'service-{stamp}.stderr.log').open('ab') as stderr:
            process = subprocess.Popen(runtime_command('service', self.config), stdin=subprocess.DEVNULL,
                stdout=stdout, stderr=stderr, cwd=resource_root(),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        self.children.append(process)
        for _ in range(60):
            state = service_status(settings)
            if state['ready']:
                return compatible(state)
            if process.poll() is not None:
                # A simultaneous starter can lose the singleton lock to a healthy runner.
                time.sleep(.2)
                state = service_status(settings)
                if state['ready']:
                    return compatible(state)
                raise UserError('起動できませんでした。「ログフォルダを開く」から詳細を確認してください')
            time.sleep(.1)
        raise UserError('起動確認が時間内に終わりませんでした。再生成せず状態を再確認してください')

    def stop_service(self):
        settings = self.settings()
        folder = Path(settings['data_dir']) / 'runtime'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'service.stop').write_text('stop', encoding='utf8')
        for _ in range(60):
            if not service_status(settings)['ready']:
                for child in self.children:
                    try: child.wait(timeout=1)
                    except subprocess.TimeoutExpired: pass
                return
            time.sleep(.1)
        raise UserError('停止を要求しました。処理終了を待って状態を再確認してください')

    def cancel_job(self, job_id):
        return Store(self.settings()).cancel(job_id)

    def import_inputs(self, paths):
        settings = self.settings()
        inbox = Path(settings['input_roots'][0]).resolve()
        inbox.mkdir(parents=True, exist_ok=True)
        sources = [Path(p).resolve(strict=True) for p in paths]
        for source in sources:
            if source.suffix.lower() not in {'.csv', '.json', '.txt', '.md'} or not source.is_file() or source.stat().st_size > 1024 * 1024:
                raise UserError('入力は1ファイル1MiB以下のCSV・JSON・TXT・MDを選んでください')
        imported = []
        for source in sources:
            raw = source.read_bytes()
            for i in range(1000):
                name = source.name if i == 0 else f'{source.stem} ({i}){source.suffix}'
                dest = inbox / name
                if dest.resolve().parent != inbox:
                    raise UserError('入力先が許可フォルダ外です')
                if dest.exists() and dest.is_file() and dest.read_bytes() == raw:
                    break
                try:
                    with dest.open('xb') as f:
                        f.write(raw)
                    break
                except FileExistsError:
                    continue
            else:
                raise UserError('同名ファイルが多すぎます。名前を変更してください')
            imported.append(str(dest))
        return imported

    def folder(self, kind, job_id=None):
        settings = self.settings()
        if kind == 'result':
            row = Store(settings).get(job_id)
            if row['state'] != 'COMPLETED' or not row['saved_path']:
                raise UserError('AIの確認・保存が完了した成果物を選択してください')
            path = Path(row['saved_path']).resolve()
            if not path.is_relative_to(Path(settings['data_dir']).resolve() / 'jobs'):
                raise UserError('成果物の保存先が不正です')
        else:
            path = {'inbox': Path(settings['input_roots'][0]), 'results': Path(settings['data_dir']) / 'jobs',
                    'logs': Path(settings['data_dir']) / 'runtime'}[kind]
        if not path.is_dir():
            raise UserError('フォルダがまだありません')
        return path

    def startup(self, enabled=None):
        if sys.platform != 'win32':
            return False
        import pythoncom
        from win32com.client import Dispatch
        pythoncom.CoInitialize()
        existing = shortcut = shell = None
        try:
            folder = self.startup_dir or startup_folder()
            link = folder / 'Orchestrator Local.lnk'
            command = runtime_command('service', self.config)
            arguments = subprocess.list2cmdline(command[1:] + ['--background'])
            shell = Dispatch('WScript.Shell')
            if link.exists():
                existing = shell.CreateShortcut(str(link))
                matches = (Path(existing.TargetPath).resolve() == Path(command[0]).resolve() and existing.Arguments == arguments)
                if not matches:
                    if enabled is None:
                        return False
                    raise UserError('別の導入先の自動起動が登録済みです。旧版で解除してから登録してください')
            if enabled is None:
                return link.exists()
            if not enabled:
                link.unlink(missing_ok=True)
                return False
            folder.mkdir(parents=True, exist_ok=True)
            shortcut = shell.CreateShortcut(str(link))
            shortcut.TargetPath = command[0]
            shortcut.Arguments = arguments
            shortcut.WorkingDirectory = str(resource_root())
            shortcut.WindowStyle = 7
            shortcut.Description = 'Orchestrator Local service; generation only when requested'
            shortcut.Save()
            return True
        finally:
            existing = shortcut = shell = None
            pythoncom.CoUninitialize()

    def set_startup(self, enabled):
        return self.startup(bool(enabled))
