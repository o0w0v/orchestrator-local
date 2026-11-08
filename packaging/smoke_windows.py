"""Exercise the actual Windows EXEs using a fake backend and isolated user paths."""
import argparse
import asyncio
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch
import pythoncom
import win32com.client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tests'))
from test_runtime import Backend
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from orchestrator_local.desktop import DesktopController
from orchestrator_local.installation import initialize
import tomlkit


async def call(session, name, **arguments):
    result = await session.call_tool(name, arguments=arguments)
    if result.isError: raise RuntimeError(str(result.content))
    return result.structuredContent or json.loads(result.content[0].text)


async def check(folder):
    backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
    thread = threading.Thread(target=backend.serve_forever, daemon=True); thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='orchestrator bundle with spaces ') as tmp:
            root = Path(tmp); config = root / 'settings.json'
            fake = root / 'ollama.exe'; fake.write_bytes(b'not executed')
            settings = initialize(config, root / 'data', fake)
            settings.pop('config_path')
            settings.update(ollama_url=f'http://127.0.0.1:{backend.server_port}', model_digest='test-digest', auto_start_ollama=False)
            config.write_text(json.dumps(settings), encoding='utf8')
            gui = folder / 'OrchestratorLocal.exe'
            helper = folder / 'OrchestratorLocal.Runtime.exe'
            controller = DesktopController(config, root / 'codex/config.toml', root / 'codex/skills', root / 'startup')
            system_path = str(Path(os.environ['SystemRoot']) / 'System32')
            # Child EXEs must work without Python or virtual-environment executables on PATH.
            with patch.dict(os.environ, {'PATH': system_path}), patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(gui)):
                try:
                    before = Backend.calls
                    controller.setup(root / 'data', fake, auto_start=True)
                    entry = tomlkit.parse(controller.codex_config.read_text(encoding='utf8'))['mcp_servers']['orchestrator_local']
                    assert entry['command'] == str(helper)
                    assert controller.startup()
                    a = controller.start_service(); b = controller.start_service()
                    assert a['pid'] == b['pid'] and Backend.calls == before
                    params = StdioServerParameters(command=entry['command'], args=entry['args'], cwd=str(folder))
                    with (root / 'mcp.stderr.log').open('w', encoding='utf8') as errlog:
                        async with stdio_client(params, errlog=errlog) as (r, w):
                            async with ClientSession(r, w) as session:
                                await session.initialize()
                                assert len((await session.list_tools()).tools) == 8
                                status = await call(session, 'local_status')
                                assert status['backend']['digest_matches'] and status['service']['ready']
                                job = await call(session, 'start_job', request_key='bundle-test', request='仮データの合計を整理する')
                                for _ in range(20):
                                    candidate = await call(session, 'get_job', job_id=job['id'], wait_seconds=1)
                                    if candidate['state'] not in {'QUEUED', 'RUNNING'}: break
                                assert candidate['state'] == 'CANDIDATE_READY'
                                ui = root / 'ui-report.json'
                                process = await asyncio.to_thread(subprocess.run, [str(gui), '--config', str(config),
                                    '--codex-config', str(controller.codex_config), '--skill-root', str(controller.skill_root),
                                    '--startup-dir', str(controller.startup_dir), '--check-ui', str(ui)], timeout=30, check=True)
                                ui_state = json.loads(ui.read_text(encoding='utf8'))
                                assert ui_state['tabs'] == ['ホーム', '作業履歴', '初回設定']
                                assert ui_state['configured'] and ui_state['jobs'] == 1
                                assert ui_state['states'] == ['AIの確認待ち']
                                assert ui_state['home_requested_height'] < 630 and ui_state['setup_requested_height'] < 630
                                saved = await call(session, 'finalize_job', job_id=job['id'], candidate_hash=candidate['candidate_hash'])
                                assert (Path(saved['saved_path']) / 'report.md').is_file()
                                await asyncio.to_thread(subprocess.run, [str(gui), '--config', str(config),
                                    '--codex-config', str(controller.codex_config), '--skill-root', str(controller.skill_root),
                                    '--startup-dir', str(controller.startup_dir), '--check-ui', str(ui)], timeout=30, check=True)
                                assert json.loads(ui.read_text(encoding='utf8'))['states'] == ['完了']
                    diagnostics = (root / 'mcp.stderr.log').read_text(encoding='utf8')
                    assert 'Traceback' not in diagnostics, diagnostics
                    assert Backend.calls == before + 1
                    return {'result': 'PASS', 'standalone_exes': True, 'python_removed_from_child_PATH': True,
                            'mcp_tools': 8, 'fake_generations': 1, 'real_model_calls': 0,
                            'gui': ui_state, 'temporary_registration_and_startup': True,
                            'singleton_start': True, 'review_and_save': True}
                finally:
                    controller.stop_service()
                    assert all(child.returncode == 0 for child in controller.children), 'Service did not exit cleanly'
                    controller.set_startup(False)
                    controller.remove_connection()
    finally:
        backend.shutdown(); backend.server_close(); thread.join()


def main():
    p = argparse.ArgumentParser(); p.add_argument('folder', type=Path); p.add_argument('--report', type=Path)
    args = p.parse_args()
    result = asyncio.run(check(args.folder.resolve()))
    if args.report: args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
