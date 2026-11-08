"""Per-user installer: verify the bundled payload and launch its guided setup."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import queue
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile

from . import __version__


def install_payload(archive, destination, expected_sha256):
    archive, destination = Path(archive).resolve(), Path(destination).resolve()
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError('インストールファイルが壊れています。ダウンロードし直してください。')
    with zipfile.ZipFile(archive) as z:
        entries=z.infolist();names=[i.filename for i in entries]
        if len({n.casefold() for n in names}) != len(names) or sum(i.file_size for i in entries)>512*1024*1024:
            raise ValueError('配布ファイルの構成が不正です。')
        for item in entries:
            path=PurePosixPath(item.filename)
            if path.parts[0:1]!=('OrchestratorLocal',) or '..' in path.parts or '\\' in item.filename or ':' in item.filename or item.is_dir() or (item.external_attr>>16)&0o170000 == 0o120000:
                raise ValueError('配布ファイルの保存先が不正です。')
        manifest=json.loads(z.read('OrchestratorLocal/FILES.sha256.json'))
        expected={r['path']:r['sha256'] for r in manifest}
        if len(expected)!=len(manifest) or {'OrchestratorLocal/'+n for n in expected}|{'OrchestratorLocal/FILES.sha256.json'} != set(names):
            raise ValueError('配布ファイル一覧が一致しません。')
        for name,digest in expected.items():
            if hashlib.sha256(z.read('OrchestratorLocal/'+name)).hexdigest()!=digest:
                raise ValueError('配布ファイルの検証に失敗しました。')
        if destination.exists():
            installed={p.relative_to(destination).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in destination.rglob('*') if p.is_file() and p.name!='FILES.sha256.json'}
            if installed!=expected:raise ValueError('同じ版の導入先に異なるファイルがあります。上書きしません。')
            return destination
        destination.parent.mkdir(parents=True,exist_ok=True)
        stage=destination.with_name('.setup-'+uuid.uuid4().hex)
        stage.mkdir()
        try:
            for item in entries:
                target=stage.joinpath(*PurePosixPath(item.filename).parts[1:])
                target.parent.mkdir(parents=True,exist_ok=True)
                with target.open('xb') as output:output.write(z.read(item))
            stage.rename(destination)
        finally:
            if stage.exists() and stage.parent==destination.parent and stage.name.startswith('.setup-'):
                shutil.rmtree(stage)
    return destination


def menu_shortcut(destination, folder=None):
    import pythoncom
    from win32com.client import Dispatch
    pythoncom.CoInitialize()
    shell=link=None
    try:
        shell=Dispatch('WScript.Shell')
        folder=Path(folder) if folder else Path(shell.SpecialFolders('Programs'))/'Orchestrator Local'
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/'Orchestrator Local.lnk'
        if path.exists():
            link=shell.CreateShortcut(str(path))
            target=Path(link.TargetPath).resolve()
            if target.name!='OrchestratorLocal.exe' or target.parent.parent!=Path(destination).resolve().parent:
                raise ValueError('同名のショートカットがあります。上書きせず残します。')
        link=shell.CreateShortcut(str(path));link.TargetPath=str(Path(destination)/'OrchestratorLocal.exe')
        link.Arguments='';link.WorkingDirectory=str(destination);link.Description='Orchestrator Local ON/OFF'
        link.Save()
        return str(path)
    finally:
        link=shell=None;pythoncom.CoUninitialize()


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--check-payload',action='store_true')
    parser.add_argument('--destination');parser.add_argument('--menu-folder');parser.add_argument('--report')
    args=parser.parse_args()
    if args.check_payload:
        if not all([args.destination,args.menu_folder,args.report]):parser.error('Verification requires explicit destination, menu-folder and report')
        resources=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]/'build-resources'))
        metadata=json.loads((resources/'installer-payload.json').read_text(encoding='utf8'))
        destination=install_payload(resources/metadata['name'],args.destination,metadata['sha256'])
        link=menu_shortcut(destination,args.menu_folder)
        Path(args.report).write_text(json.dumps({'result':'PASS','installed':str(destination),'shortcut':link,'files_verified':True}),encoding='utf8')
        return
    import tkinter as tk
    from tkinter import ttk
    root=tk.Tk();root.title('Orchestrator Local セットアップ');root.geometry('540x240');root.resizable(False,False)
    frame=ttk.Frame(root,padding=24);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Orchestrator Local を準備しています',font=('Yu Gothic UI',16,'bold')).pack(anchor='w',pady=12)
    label=tk.StringVar(value='ファイルを確認しています。管理者権限は不要です。')
    ttk.Label(frame,textvariable=label,wraplength=480).pack(anchor='w',pady=10)
    progress=ttk.Progressbar(frame,mode='indeterminate');progress.pack(fill='x');progress.start()
    events=queue.Queue()
    root.protocol('WM_DELETE_WINDOW',lambda:None)
    def work():
        try:
            resources=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]/'build-resources'))
            metadata=json.loads((resources/'installer-payload.json').read_text(encoding='utf8'))
            base=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))
            target=base/'Programs/OrchestratorLocal'/__version__
            install_payload(resources/metadata['name'],target,metadata['sha256'])
            menu_shortcut(target)
            subprocess.Popen([str(target/'OrchestratorLocal.exe'),'--setup'],cwd=target,
                             creationflags=subprocess.CREATE_NO_WINDOW)
            events.put(None)
        except Exception as exc:events.put(str(exc))
    def poll():
        try:error=events.get_nowait()
        except queue.Empty:root.after(100,poll);return
        progress.stop()
        if error:
            label.set(error);root.protocol('WM_DELETE_WINDOW',root.destroy)
            ttk.Button(frame,text='閉じる',command=root.destroy).pack(anchor='e',pady=12)
        else:root.destroy()
    threading.Thread(target=work,daemon=True).start();root.after(100,poll);root.mainloop()
