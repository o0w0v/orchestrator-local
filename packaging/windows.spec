# Build on Windows x64 with requirements-build.lock installed.
from pathlib import Path

root = Path(SPECPATH).parent
resources = [(str(root / name), name) for name in ['skills', 'examples']]
resources += [(str(root / name), '.') for name in ['LICENSE', 'README.md']]
resources += [(str(root / 'build-resources/licenses'), 'licenses'),
              (str(root / 'build-resources/THIRD_PARTY_NOTICES.txt'), '.')]
gui = Analysis([str(root / 'desktop_entry.py')], pathex=[str(root)], datas=resources,
               hiddenimports=['win32com.client', 'pythoncom'], excludes=['pytest', 'unittest'])
runtime = Analysis([str(root / 'runtime_entry.py')], pathex=[str(root)],
                   hiddenimports=['mcp.server.fastmcp'], excludes=['pytest', 'unittest'])
gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name='OrchestratorLocal',
              console=False, upx=False)
runtime_exe = EXE(PYZ(runtime.pure), runtime.scripts, [], exclude_binaries=True, name='OrchestratorLocal.Runtime',
                  console=True, upx=False)
app = COLLECT(gui_exe, runtime_exe, gui.binaries, gui.datas, runtime.binaries, runtime.datas,
              upx=False, name='OrchestratorLocal')
