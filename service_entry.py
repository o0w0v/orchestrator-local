if __name__ == "__main__":
    import sys
    if "--background" in sys.argv:
        import json
        from pathlib import Path
        sys.argv.remove("--background")
        config_path=Path(sys.argv[sys.argv.index("--config")+1])
        settings=json.loads(config_path.read_text(encoding="utf-8"))
        folder=Path(settings["data_dir"])/"runtime"
        folder.mkdir(parents=True,exist_ok=True)
        sys.stdout=(folder/"login-service.stdout.log").open("a",encoding="utf-8",buffering=1)
        sys.stderr=(folder/"login-service.stderr.log").open("a",encoding="utf-8",buffering=1)
    from orchestrator_local.service import main
    main()
