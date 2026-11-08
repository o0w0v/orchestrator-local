"""Console stdio entry for bundled MCP; never writes UI messages to stdout."""
import argparse
from pathlib import Path
import sys

from orchestrator_local.paths import default_config


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['mcp', 'service'])
    p.add_argument('--config', type=Path, default=default_config())
    p.add_argument('--background', action='store_true')
    p.add_argument('--status', action='store_true')
    p.add_argument('--stop', action='store_true')
    args = p.parse_args(argv)
    from orchestrator_local.core import read_settings
    settings = read_settings(args.config)
    if args.mode == 'mcp':
        from orchestrator_local.server import create_server
        create_server(args.config).run(transport='stdio')
    else:
        from orchestrator_local.service import serve, status
        import asyncio
        import json
        folder = Path(settings['data_dir']) / 'runtime'
        folder.mkdir(parents=True, exist_ok=True)
        if args.status:
            print(json.dumps(status(settings))); return
        if args.stop:
            (folder / 'service.stop').write_text('stop', encoding='utf8'); return
        # A windowed executable has no console handles, including at login.
        previous = sys.stdout, sys.stderr
        with (folder / 'desktop-service.stdout.log').open('a', encoding='utf8', buffering=1) as stdout, (folder / 'desktop-service.stderr.log').open('a', encoding='utf8', buffering=1) as stderr:
            try:
                sys.stdout, sys.stderr = stdout, stderr
                asyncio.run(serve(settings))
            finally:
                sys.stdout, sys.stderr = previous


if __name__ == '__main__':
    main()
