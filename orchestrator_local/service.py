"""Local job runner, deliberately independent of any MCP stdio connection."""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from .core import Store,packed,read_settings
from .worker import pid_alive,reap_interrupted,run_job


def status(settings):
    path=Path(settings['data_dir'])/'runtime/service.json'
    try:
        value=json.loads(path.read_text(encoding='utf8'))
        value['ready']=time.time()-value['heartbeat']<12 and pid_alive(value['pid'])
        return value
    except (OSError,ValueError,KeyError):
        return {'ready':False}


async def serve(settings):
    store=Store(settings)
    runtime=store.root/'runtime';runtime.mkdir(exist_ok=True)
    lock=(runtime/'service.lock').open('a+b')
    if not (runtime/'service.lock').stat().st_size:
        lock.write(b'0');lock.flush()
    lock.seek(0)
    try:
        if sys.platform=='win32':
            import msvcrt
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        lock.close();return
    stop=runtime/'service.stop'
    stop.unlink(missing_ok=True)
    started=time.time()
    active=None
    async def heartbeat():
        while not stop.exists():
            temp=runtime/f'.service-{os.getpid()}.tmp'
            temp.write_text(packed({'pid':os.getpid(),'started':started,'heartbeat':time.time(),'config':settings['config_path']}),encoding='utf8')
            os.replace(temp,runtime/'service.json')
            await asyncio.sleep(1)
        if active is not None:
            store.cancel(active)
    hb=asyncio.create_task(heartbeat())
    try:
        # Holding the singleton runner lock proves no previous service is still
        # running these jobs, even if Windows has reused its old process ID.
        with store.transaction() as db:
            db.execute("UPDATE jobs SET state='INTERRUPTED',phase='実行中断',error='前の実行サービスが終了しました。自動再生成はしません',updated=? WHERE state='RUNNING'",(time.time(),))
        reap_interrupted(store)
        while not stop.exists():
            with store.connection() as db:
                row=db.execute("SELECT id FROM jobs WHERE state='QUEUED' AND executor='gemma' ORDER BY created,id LIMIT 1").fetchone()
            if row is None:
                reap_interrupted(store)
                await asyncio.sleep(.2);continue
            active=row['id']
            store.update(active,worker_pid=os.getpid())
            await run_job(settings,active)
            active=None
    finally:
        hb.cancel()
        try:await hb
        except asyncio.CancelledError:pass
        try:
            owner=json.loads((runtime/'service.json').read_text(encoding='utf8'))
            if owner['pid']==os.getpid():(runtime/'service.json').unlink()
        except (OSError,ValueError,KeyError):pass
        lock.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--config');p.add_argument('--status',action='store_true');p.add_argument('--stop',action='store_true');a=p.parse_args()
    settings=read_settings(a.config)
    if a.status:
        print(json.dumps(status(settings),ensure_ascii=False));return
    if a.stop:
        runtime=Path(settings['data_dir'])/'runtime';runtime.mkdir(exist_ok=True)
        (runtime/'service.stop').write_text('stop',encoding='utf8');return
    asyncio.run(serve(settings))


if __name__=='__main__':main()
