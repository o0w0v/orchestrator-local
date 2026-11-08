"""Windowed entry point; also the invisible login service in bundled builds."""
if __name__ == '__main__':
    import sys
    if '--service' in sys.argv:
        from runtime_entry import main
        main(['service', *[x for x in sys.argv[1:] if x != '--service']])
    else:
        from orchestrator_local.gui import main
        main()
