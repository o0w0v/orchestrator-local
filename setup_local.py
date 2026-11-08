"""Create local settings and optionally register only this MCP and its skill."""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import tomlkit

from orchestrator_local.core import Store,read_settings

ROOT=Path(__file__).resolve().parent
DIGEST="08ae7ec1744bd7f451c4a530afb39d2673ad9d07a8369b8a33a3613b41212a68"


def connection_entry(settings):
    return {"command":sys.executable,"args":[str(ROOT/"serve.py"),"--config",settings["config_path"]],
            "startup_timeout_sec":20,"tool_timeout_sec":60}


def register(settings, codex_config, skill_root, receipt_path=None):
    codex_config=Path(codex_config).resolve()
    before=codex_config.read_bytes() if codex_config.exists() else b""
    document=tomlkit.parse(before.decode("utf-8-sig"))
    entries=document.setdefault("mcp_servers",tomlkit.table())
    entry=connection_entry(settings)
    if "orchestrator_local" in entries and dict(entries["orchestrator_local"])!=entry:
        raise RuntimeError("既存のorchestrator_local設定が異なります。自動上書きしません")
    src=ROOT/"skills/orchestrator-local"
    dest=Path(skill_root).resolve()/"orchestrator-local"
    if dest.exists():
        source_files={p.relative_to(src).as_posix():p.read_bytes() for p in src.rglob('*') if p.is_file()}
        target_files={p.relative_to(dest).as_posix():p.read_bytes() for p in dest.rglob('*') if p.is_file()}
        if source_files!=target_files:
            raise RuntimeError("同名Skillが存在し内容が違います。自動上書きしません")
    entries["orchestrator_local"]=entry
    after=tomlkit.dumps(document).encode("utf-8")
    codex_config.parent.mkdir(parents=True,exist_ok=True)
    backup=None
    if before and before!=after:
        suffix=datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup=codex_config.with_name(codex_config.name+".orchestrator-local-"+suffix+".bak")
        backup.write_bytes(before)
    if before!=after:
        temp=codex_config.with_name(codex_config.name+".orchestrator-local.tmp")
        with temp.open("xb") as f:
            f.write(after);f.flush();os.fsync(f.fileno())
        os.replace(temp,codex_config)
    if not dest.exists():
        shutil.copytree(src,dest)
    receipt={"registered":True,"config_path":str(codex_config),"backup":str(backup) if backup else None,
             "previous_sha256":hashlib.sha256(before).hexdigest(),"installed_sha256":hashlib.sha256(after).hexdigest(),
             "skill_path":str(dest),"server_name":"orchestrator_local","restart_connection_required":True}
    Path(receipt_path or ROOT/"installation-receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return receipt


def unregister(settings, codex_config, skill_root, receipt_path=None):
    """Detach this exact installation, keeping data and backups of removed settings."""
    codex_config=Path(codex_config).resolve()
    before=codex_config.read_bytes() if codex_config.exists() else b""
    document=tomlkit.parse(before.decode("utf-8-sig"))
    entries=document.get("mcp_servers",{})
    if "orchestrator_local" in entries and dict(entries["orchestrator_local"])!=connection_entry(settings):
        raise RuntimeError("接続が別の導入先を参照しています。自動削除しません")
    src=ROOT/"skills/orchestrator-local"
    dest=Path(skill_root).resolve()/"orchestrator-local"
    if dest.exists():
        source_files={p.relative_to(src).as_posix():p.read_bytes() for p in src.rglob('*') if p.is_file()}
        target_files={p.relative_to(dest).as_posix():p.read_bytes() for p in dest.rglob('*') if p.is_file()}
        if dest.resolve()!=dest or source_files!=target_files:
            raise RuntimeError("Skillに利用者の変更があります。自動削除しません")
    stamp=datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    skill_backup=(Path(settings["data_dir"])/"runtime"/("unregistered-skill-"+stamp)).resolve() if dest.exists() else None
    if skill_backup and (skill_backup==dest.resolve() or dest.resolve() in skill_backup.parents):
        raise RuntimeError("Skill保全先が不正です")
    backup=None
    if "orchestrator_local" in entries:
        del entries["orchestrator_local"]
        after=tomlkit.dumps(document).encode("utf-8")
        backup=codex_config.with_name(codex_config.name+".orchestrator-local-unregister-"+stamp+".bak")
        backup.write_bytes(before)
        temp=codex_config.with_name(codex_config.name+".orchestrator-local.tmp")
        with temp.open("xb") as f:
            f.write(after);f.flush();os.fsync(f.fileno())
        os.replace(temp,codex_config)
    if dest.exists():
        skill_backup.parent.mkdir(parents=True,exist_ok=True)
        shutil.move(str(dest),str(skill_backup))
    receipt={"registered":False,"config_path":str(codex_config),"backup":str(backup) if backup else None,
             "skill_backup":str(skill_backup) if skill_backup else None,"data_preserved":True,
             "startup_shortcut":"enable-startup.ps1 -Disableで別途解除","restart_connection_required":True}
    Path(receipt_path or ROOT/"uninstallation-receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return receipt


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir",type=Path,default=Path.home()/"Documents/Codex/OrchestratorLocal")
    p.add_argument("--ollama-models",type=Path)
    p.add_argument("--ollama-exe",default=shutil.which("ollama"))
    action=p.add_mutually_exclusive_group()
    action.add_argument("--register",action="store_true")
    action.add_argument("--unregister",action="store_true")
    p.add_argument("--codex-config",type=Path,default=Path.home()/".codex/config.toml")
    p.add_argument("--skill-root",type=Path,default=Path.home()/".codex/skills")
    args=p.parse_args()
    config=ROOT/"local-settings.json"
    if args.unregister:
        if not config.exists():
            raise RuntimeError("このフォルダのlocal-settings.jsonがありません")
        print(json.dumps(unregister(read_settings(config),args.codex_config,args.skill_root),ensure_ascii=False,indent=2))
        return
    if not config.exists():
        if not args.ollama_exe or not Path(args.ollama_exe).is_file():
            raise RuntimeError("既存Ollamaが見つかりません。--ollama-exeで指定してください")
        data=args.data_dir.resolve()
        env={"OLLAMA_HOST":"127.0.0.1:11434","OLLAMA_FLASH_ATTENTION":"1","OLLAMA_KV_CACHE_TYPE":"f16",
             "OLLAMA_MAX_LOADED_MODELS":"1","OLLAMA_NUM_PARALLEL":"1"}
        if args.ollama_models:
            if not args.ollama_models.is_dir():
                raise RuntimeError("指定した既存モデルフォルダがありません")
            env["OLLAMA_MODELS"]=str(args.ollama_models.resolve())
        value={"data_dir":str(data),"input_roots":[str(data/"inbox")],"ollama_url":"http://127.0.0.1:11434",
               "ollama_exe":str(Path(args.ollama_exe).resolve()),"auto_start_ollama":True,"ollama_environment":env,
               "model":"gemma4:26b","model_digest":DIGEST,"think":True,"keep_alive":"5m",
               "options":{"num_ctx":65536,"num_predict":32768,"seed":20260926,"temperature":1,"top_p":.95,"top_k":64},
               "job_timeout_seconds":1200}
        with config.open("x",encoding="utf-8") as f:
            json.dump(value,f,ensure_ascii=False,indent=2);f.write("\n")
    settings=read_settings(config)
    store=Store(settings)
    sample=store.root/"inbox/inventory-example.json"
    if not sample.exists():
        shutil.copyfile(ROOT/"examples/inventory.json",sample)
    result={"settings":str(config),"input_folder":settings["input_roots"][0],"output_folder":str(store.root/"jobs"),"sample":str(sample)}
    if args.register:
        result["connection"]=register(settings,args.codex_config,args.skill_root)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
