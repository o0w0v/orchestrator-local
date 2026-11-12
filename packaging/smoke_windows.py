"""Exercise the actual Windows EXEs using a fake backend and isolated user paths."""
import argparse
import asyncio
import hashlib
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
from orchestrator_local.setup_flow import apply_setup, inspect_setup
import tomlkit


async def call(session, name, **arguments):
    result = await session.call_tool(name, arguments=arguments)
    if result.isError: raise RuntimeError(str(result.content))
    return result.structuredContent or json.loads(result.content[0].text)


async def check(folder):
    resources=folder/'_internal'
    assert (resources/'docs/ROUTING_JA.md').is_file()
    assert (resources/'DESIGN_JA.md').is_file()
    assert 'MCPの10ツール' in (resources/'README.md').read_text(encoding='utf8')
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
                    plan=inspect_setup(controller)
                    apply_setup(controller,plan,plan['data_dir'],plan['ollama_exe'],plan['models'],True)
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
                                assert len((await session.list_tools()).tools) == 10
                                status = await call(session, 'local_status')
                                assert not status['local_dispatch']['enabled'] and status['service']['ready']
                                routed = await call(session, 'route_task', request_key='off-routing', request='開始しない')
                                assert routed['route']=='SOL_DIRECT' and routed['model_called'] is False
                                rejected = await session.call_tool('start_job', arguments={'request_key':'off-before','request':'開始しない'})
                                assert rejected.isError and Backend.calls == before
                                controller.set_enabled(True)
                                status = await call(session, 'local_status')
                                assert status['local_dispatch']['enabled'] and status['backend']['digest_matches']
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
                                assert ui_state['tabs'] == ['設定', '履歴']
                                assert ui_state['details_hidden'] and ui_state['local_enabled'] and ui_state['toggle_label'] == 'OFFにする'
                                assert ui_state['configured'] and ui_state['jobs'] == 1
                                assert ui_state['states'] == ['AIの確認待ち']
                                assert ui_state['home_requested_height'] < 440 and ui_state['setup_requested_height'] < 630
                                assert ui_state['power_ring']=='#22a45a' and ui_state['power_state']=='ON'
                                controller.set_enabled(False)
                                assert not (await call(session, 'local_status'))['local_dispatch']['enabled']
                                rejected = await session.call_tool('start_job', arguments={'request_key':'off-after','request':'開始しない'})
                                assert rejected.isError and Backend.calls == before + 1
                                saved = await call(session, 'finalize_job', job_id=job['id'], candidate_hash=candidate['candidate_hash'])
                                assert (Path(saved['saved_path']) / 'report.md').is_file()
                                await asyncio.to_thread(subprocess.run, [str(gui), '--config', str(config),
                                    '--codex-config', str(controller.codex_config), '--skill-root', str(controller.skill_root),
                                    '--startup-dir', str(controller.startup_dir), '--check-ui', str(ui)], timeout=30, check=True)
                                off_ui = json.loads(ui.read_text(encoding='utf8'))
                                assert off_ui['states'] == ['完了'] and off_ui['details_hidden']
                                assert not off_ui['local_enabled'] and off_ui['toggle_label'] == 'ONにする'
                                assert off_ui['power_ring']=='#cbd2dc' and off_ui['power_state']=='OFF'
                    diagnostics = (root / 'mcp.stderr.log').read_text(encoding='utf8')
                    assert 'Traceback' not in diagnostics, diagnostics
                    async def bridge(name, arguments=None, success=True):
                        argsfile=root/('arguments-'+name+'.json')
                        argsfile.write_text(json.dumps(arguments or {},ensure_ascii=False),encoding='utf8')
                        process=await asyncio.to_thread(subprocess.run,
                            [str(Path(system_path)/'WindowsPowerShell/v1.0/powershell.exe'),'-NoProfile','-ExecutionPolicy','Bypass','-File',
                             str(controller.skill_root/'orchestrator-local/scripts/call_tool.ps1'),
                             '-Config',str(config),'-Tool',name,'-ArgumentsFile',str(argsfile)],
                            capture_output=True,text=True,encoding='utf8',timeout=30)
                        value=json.loads(process.stdout)
                        assert process.returncode==(0 if success else 1),(value,process.stderr)
                        return value
                    assert not (await bridge('local_status'))['local_dispatch']['enabled']
                    code_args={'request_key':'bundle-code','request':'加算関数の案',
                               'file_paths':['src/add.js'],'inputs':{'scenario':'code'}}
                    assert 'OFF' in (await bridge('start_code_job',code_args,False))['error']
                    assert Backend.calls==before+1
                    controller.set_enabled(True)
                    code=await bridge('start_code_job',code_args)
                    assert (await bridge('start_code_job',code_args))['id']==code['id']
                    candidate=await bridge('get_job',{'job_id':code['id'],'wait_seconds':25})
                    assert candidate['state']=='CANDIDATE_READY'
                    controller.set_enabled(False)
                    saved=await bridge('finalize_job',{'job_id':code['id'],'candidate_hash':candidate['candidate_hash']})
                    source=Path(saved['saved_path'])/'source/src/add.js'
                    assert source.read_text()=='export const add = (a, b) => a + b;\n'
                    manifest=json.loads((source.parents[2]/'manifest.json').read_text())
                    assert manifest['files']['source/src/add.js']==hashlib.sha256(source.read_bytes()).hexdigest()
                    assert Backend.calls == before + 2
                    return {'result': 'PASS', 'standalone_exes': True, 'python_removed_from_child_PATH': True,
                            'mcp_tools': 10, 'fake_generations': 2, 'real_model_calls': 0,
                            'gui': ui_state, 'temporary_registration_and_startup': True,
                            'singleton_start': True, 'review_and_save': True, 'default_off': True,
                            'hot_off_blocks_existing_mcp': True, 'compact_home': True,
                            'off_routing_no_cloud': True,
                            'linked_documentation_bundled': True,
                            'installed_skill_bridge': True, 'code_dedup_review_source_export': True}
                finally:
                    controller.stop_service()
                    assert all(child.returncode == 0 for child in controller.children), 'Service did not exit cleanly'
                    controller.set_startup(False)
                    controller.remove_connection()
    finally:
        backend.shutdown(); backend.server_close(); thread.join()


def main():
    p = argparse.ArgumentParser(); p.add_argument('folder', type=Path); p.add_argument('--report', type=Path)
    p.add_argument('--installer',type=Path)
    args = p.parse_args()
    if args.installer:
        with tempfile.TemporaryDirectory(prefix='orchestrator installer with spaces ') as tmp:
            root=Path(tmp);destination=root/'Programs/0.7.0';receipt=root/'installer.json'
            subprocess.run([str(args.installer.resolve()),'--check-payload','--destination',str(destination),
                            '--menu-folder',str(root/'menu'),'--report',str(receipt)],check=True,timeout=60)
            assert json.loads(receipt.read_text())['result']=='PASS'
            result=asyncio.run(check(destination));result['installer_payload']='PASS'
    else:result = asyncio.run(check(args.folder.resolve()))
    if args.report: args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
