"""Locations and child argv shared by source and self-contained Windows builds."""
import os
from pathlib import Path
import sys


def resource_root():
    return Path(__file__).resolve().parent.parent


def default_config():
    if getattr(sys, 'frozen', False):
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'OrchestratorLocal/local-settings.json'
    return resource_root() / 'local-settings.json'


def runtime_command(mode, config):
    if mode not in {'mcp', 'service', 'call'}:
        raise ValueError('Unknown runtime mode')
    if getattr(sys, 'frozen', False):
        name = 'OrchestratorLocal.Runtime.exe' if mode in {'mcp','call'} else 'OrchestratorLocal.exe'
        prefix = [mode] if mode in {'mcp','call'} else ['--service']
        return [str(Path(sys.executable).parent / name), *prefix, '--config', str(Path(config).resolve())]
    script = 'runtime_entry.py' if mode=='call' else ('serve.py' if mode == 'mcp' else 'service_entry.py')
    executable = Path(sys.executable)
    if mode in {'mcp','call'} and executable.name.lower() == 'pythonw.exe' and executable.with_name('python.exe').is_file():
        executable = executable.with_name('python.exe')
    if mode == 'service' and sys.platform == 'win32' and executable.with_name('pythonw.exe').is_file():
        executable = executable.with_name('pythonw.exe')
    return [str(executable), str(resource_root() / script), *(['call'] if mode=='call' else []), '--config', str(Path(config).resolve())]


def tool_launcher(settings):
    return {'application':'orchestrator-local','config_path':str(Path(settings['config_path']).resolve()),
            'command':runtime_command('call',settings['config_path'])}


def default_data_dir():
    return Path.home() / 'Documents/Codex/OrchestratorLocal'


def default_codex_paths():
    root = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
    return root / 'config.toml', root / 'skills'
