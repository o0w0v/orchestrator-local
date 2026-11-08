"""Build a public, allowlisted onedir ZIP. No user settings or model weights."""
from importlib import metadata
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform != 'win32':
        raise SystemExit('Build this distribution on Windows')
    resources = ROOT / 'build-resources'
    licenses = resources / 'licenses'; licenses.mkdir(parents=True, exist_ok=True)
    notices = ['Orchestrator Local 0.6.0 — third-party components',
               'Application source: MIT, see LICENSE. Model weights and Ollama are not bundled.', '']
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        raise RuntimeError('Python license file is required for redistribution')
    (licenses / 'Python').mkdir(exist_ok=True)
    shutil.copyfile(python_license, licenses / 'Python/LICENSE.txt')
    notices.append('Python ' + sys.version.split()[0] + ' — see licenses/Python/LICENSE.txt')
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        name, version = dist.metadata['Name'], dist.version
        notices.append(f'{name} {version} — {dist.metadata.get("License-Expression") or dist.metadata.get("License", "See component license") }')
        for item in dist.files or []:
            if any(part.lower() in {'licenses', 'license', 'licenses.txt', 'license.txt', 'license.md', 'copying', 'notice'} for part in item.parts) or item.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    target = licenses / name / Path(*[p for p in item.parts if p not in {'.', '..'}])
                    target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
    (resources / 'THIRD_PARTY_NOTICES.txt').write_text('\n'.join(notices) + '\n', encoding='utf8')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', str(ROOT / 'packaging/windows.spec')], cwd=ROOT, check=True)
    folder = ROOT / 'dist/OrchestratorLocal'
    (folder / 'START_HERE_JA.txt').write_text(
        'Orchestrator Local 0.6.0\n\n通常はSetup.exeを開き、案内に沿って「次へ」で進んでください。\n'
        'ZIP版ではすべて展開してOrchestratorLocal.exeを開くとセットアップが始まります。\n'
        '接続を再起動して新しい会話を開き、いつも通り依頼してください。\n'
        '普段は主画面のローカル分担ON/OFFだけ。初期状態はOFFです。\n'
        'ONでも「今回は使わない」という会話の指示を優先します。\n'
        'Pythonの別途インストールは不要です。OllamaとGemma4:26bは別途準備が必要です。\n'
        'Runtime.exeと_internalフォルダも必要です。起動ファイルだけ移動しないでください。\n'
        '画面を閉じても起動済みサービスは継続します。OFFは新規作業の停止、サービス停止は「詳細」の設定。\n'
        '旧版を自動検出し、設定とモデルの場所・成果物を引き継ぎます。旧版で登録解除する必要はありません。\n'
        '成果物は残ります。未署名の初期配布版です。\n\n'
        '詳しい説明：https://github.com/o0w0v/orchestrator-local\n', encoding='utf-8-sig')
    manifest = []
    for p in sorted(folder.rglob('*')):
        if not p.is_file(): continue
        relative = p.relative_to(folder).as_posix()
        if p.name.lower().startswith(('local-settings', 'installation-receipt', 'uninstallation-receipt')) or p.suffix in {'.sqlite3', '.log'}:
            raise RuntimeError('Private file in build: ' + relative)
        manifest.append({'path': relative, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
    (folder / 'FILES.sha256.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    archive = ROOT / 'dist/OrchestratorLocal-0.6.0-windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob('*')):
            if p.is_file(): z.write(p, 'OrchestratorLocal/' + p.relative_to(folder).as_posix())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    print(json.dumps({'archive': str(archive), 'sha256': digest, 'files': len(manifest)}, ensure_ascii=False))
    (resources/'installer-payload.json').write_text(json.dumps({'version':'0.6.0','name':archive.name,'sha256':digest}),encoding='utf8')
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean',str(ROOT/'packaging/installer.spec')],cwd=ROOT,check=True)
    installer=ROOT/'dist/OrchestratorLocal-0.6.0-Setup.exe'
    installer_digest=hashlib.sha256(installer.read_bytes()).hexdigest()
    installer.with_suffix('.exe.sha256').write_text(f'{installer_digest}  {installer.name}\n',encoding='ascii')
    print(json.dumps({'installer':str(installer),'sha256':installer_digest}))


if __name__ == '__main__': main()
