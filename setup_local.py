"""Source CLI for the same installation functions used by the desktop app."""
import argparse
import json
import shutil
from pathlib import Path
from orchestrator_local.core import read_settings
from orchestrator_local.installation import register, unregister, initialize
from orchestrator_local.paths import default_config, default_data_dir, default_codex_paths


def main():
    config_path,skill_path=default_codex_paths()
    p=argparse.ArgumentParser()
    p.add_argument("--config",type=Path,default=default_config())
    p.add_argument("--data-dir",type=Path,default=default_data_dir())
    p.add_argument("--ollama-models",type=Path)
    p.add_argument("--ollama-exe",default=shutil.which("ollama"))
    action=p.add_mutually_exclusive_group()
    action.add_argument("--register",action="store_true")
    action.add_argument("--unregister",action="store_true")
    p.add_argument("--codex-config",type=Path,default=config_path)
    p.add_argument("--skill-root",type=Path,default=skill_path)
    args=p.parse_args()
    if args.unregister:
        result=unregister(read_settings(args.config),args.codex_config,args.skill_root)
    else:
        settings=initialize(args.config,args.data_dir,args.ollama_exe,args.ollama_models)
        result={"settings":str(args.config),"input_folder":settings["input_roots"][0],"output_folder":str(Path(settings["data_dir"])/"jobs"),"sample":str(Path(settings["data_dir"])/"inbox/inventory-example.json")}
        if args.register:
            result["connection"]=register(settings,args.codex_config,args.skill_root)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
