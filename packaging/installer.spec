from pathlib import Path

root=Path(SPECPATH).parent
resources=root/'build-resources'
import json
payload=json.loads((resources/'installer-payload.json').read_text(encoding='utf8'))
a=Analysis([str(root/'installer_entry.py')],pathex=[str(root)],
           datas=[(str(root/'dist'/payload['name']),'.'),(str(resources/'installer-payload.json'),'.')],
           hiddenimports=['win32com.client','pythoncom'],excludes=['pytest','unittest'])
exe=EXE(PYZ(a.pure),a.scripts,a.binaries,a.datas,name='OrchestratorLocal-'+payload['version']+'-Setup',
        console=False,upx=False)
