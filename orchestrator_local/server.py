"""MCP adapter. Conversation model reviews; only the worker invokes Gemma."""
from __future__ import annotations

import argparse
import os
import sys
import time

from .health import backend_status
import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.stdio import stdio_server

from .core import Store,UserError,artifact_schema,input_document,packed,parse,read_settings,sha,validate_artifact
from .worker import reap_interrupted
from .service import status as service_status
from .routing import Router, fallback


class ProcessMCP(FastMCP):
    async def run_stdio_async(self):
        # SDK 1.30's default UTF-8 wrappers can close the original stdout
        # buffer at EOF. Own duplicates so source Python and the frozen
        # bootloader can both flush/close their original streams normally.
        with os.fdopen(os.dup(sys.stdin.fileno()), 'r', encoding='utf8', errors='replace') as stdin, os.fdopen(os.dup(sys.stdout.fileno()), 'w', encoding='utf8', newline='\n') as stdout:
            async with stdio_server(stdin=anyio.wrap_file(stdin), stdout=anyio.wrap_file(stdout)) as (reader, writer):
                await self._mcp_server.run(reader, writer, self._mcp_server.create_initialization_options())


def create_server(config_path=None):
    settings=read_settings(config_path)
    store=Store(settings)
    router=Router(store)
    mcp=ProcessMCP("Orchestrator Local",instructions="ローカル分担ON時、対応する依頼ではroute_taskでLunaが1回だけ振り分ける。利用者の「今回は使わない」「この会話では使わない」とOFFを優先し、その範囲では通常処理。SOL_DIRECTは会話側で実行。GEMMA_DIRECTは元依頼と同じ条件をstart_jobへ渡す。SOL_DESIGN_GEMMAは接続・担当だけ短く決めてから渡す。コード案はstart_code_job。get_jobで候補と同じ元条件を確認し、使えるならfinalize_jobのACCEPT、利用に支障がある誤りだけPATCH。好みの文体や新要件で再生成しない。最終確認はこの会話が担当し別の確認AIは追加しない。request_keyは再送時も同じ値。Job開始1回、get_job(wait_seconds=25)で待つ。コードの反映・実行確認は会話側が担当する。")

    @mcp.tool(annotations={"readOnlyHint":True,"openWorldHint":False})
    def local_status() -> dict:
        """生成せずにLocal接続、保存先、最近のジョブを確認する。"""
        reap_interrupted(store)
        dispatch=store.dispatch_state()
        backend=backend_status(settings) if dispatch['enabled'] else {'checked':False,'reason':'local_dispatch_off'}
        with store.connection() as db:
            jobs=[dict(r) for r in db.execute("SELECT id,state,phase,created,saved_path FROM jobs ORDER BY created DESC LIMIT 8")]
        return {"model":settings["model"],"service":service_status(settings),"backend":backend,"local_dispatch":dispatch,"routing":router.status(),"input_roots":settings["input_roots"],"data_dir":settings["data_dir"],"jobs":jobs,"conversation_Credits":None}

    @mcp.tool(annotations={"readOnlyHint":False,"destructiveHint":False,"idempotentHint":True,"openWorldHint":True})
    def route_task(request_key: str, request: str, inputs: dict | None=None,
                   input_paths: list[str] | None=None, data_schema: dict | None=None,
                   work_type: str='data', file_paths: list[str] | None=None,
                   local_allowed: bool=True) -> dict:
        """ON時の対象依頼をLuna lowで1回振り分ける。既存ChatGPT CLIのCloud消費あり。同じkeyの再送は再生成せず、OFF/今回は使わないならCloudも呼ばない。"""
        if local_allowed and store.dispatch_state()['enabled'] and not service_status(settings)['ready']:
            return fallback('ローカル実行サービスが停止しています。新しいCloud振り分けをせず通常処理へ戻します。')
        return router.route(request_key,request,inputs,input_paths,data_schema,work_type,file_paths,local_allowed)

    @mcp.tool(annotations={"readOnlyHint":True,"openWorldHint":False})
    def read_input(path: str) -> dict:
        """許可されたinbox内のCSV/JSON/TXT/MDを読む。小さい添付はinputsへ直接渡してもよい。"""
        result=input_document(settings,path)
        if len(packed(result)) > 45000:
            raise UserError("会話へ返すには大きすぎます。対象を分割してください")
        return result

    @mcp.tool(annotations={"readOnlyHint":False,"destructiveHint":False,"idempotentHint":True,"openWorldHint":False})
    def start_job(request_key: str, request: str, inputs: dict | None=None,
                  input_paths: list[str] | None=None, data_schema: dict | None=None,
                  csv_exports: list[dict] | None=None) -> dict:
        """元依頼・合意条件と入力でGemma作業を開始。固有request_keyは通信再送時も同じ値にする。CSV指定はname/pointer/columns。"""
        reap_interrupted(store)
        if not store.dispatch_state()['enabled']:
            raise UserError('ローカル分担はOFFです。通常のCodexで処理してください')
        service=service_status(settings)
        if not service['ready']:
            raise UserError("ローカル実行サービスが停止しています。Orchestrator LocalのON、または詳細の起動を使ってください")
        if service.get('control_version') != 1:
            raise UserError('旧版サービスはON/OFFに対応していません。停止して新版を起動してください')
        row,created=store.create(request_key,request,inputs,input_paths,data_schema,csv_exports)
        if created:
            store.update(row['id'],worker_pid=service['pid'])
        out=store.view(row["id"])
        out["reused"]=not created
        return out

    @mcp.tool(annotations={"readOnlyHint":False,"destructiveHint":False,"idempotentHint":True,"openWorldHint":False})
    def start_code_job(request_key: str, request: str, file_paths: list[str], inputs: dict | None=None) -> dict:
        """Gemmaに小規模なコード案を依頼。相対ファイル名を1〜12件指定する。反映・実行はせず、会話側の確認後に成果物内へ保存する。"""
        reap_interrupted(store)
        if not store.dispatch_state()['enabled']:
            raise UserError('ローカル分担はOFFです。通常のCodexで処理してください')
        service=service_status(settings)
        if not service['ready'] or 'code' not in service.get('capabilities',[]):
            raise UserError('コード案に対応した実行サービスが必要です。Orchestrator Localを更新してONにしてください')
        row,created=store.create(request_key,request,inputs,code_paths=file_paths)
        if created:store.update(row['id'],worker_pid=service['pid'])
        out=store.view(row['id']);out['reused']=not created
        return out

    @mcp.tool(annotations={"readOnlyHint":True,"openWorldHint":False})
    def get_job(job_id: str, wait_seconds: int=0, include_candidate: bool=True) -> dict:
        """状態または候補とhashを取得。実行中はwait_seconds=25で待ち、開始し直さない。候補を元資料で確認してから保存する。"""
        end=time.monotonic()+max(0,min(wait_seconds,25))
        while True:
            reap_interrupted(store)
            view=store.view(job_id,include_candidate)
            if view["state"] not in {"QUEUED","RUNNING"} or time.monotonic()>=end:
                return view
            time.sleep(.3)

    @mcp.tool(annotations={"readOnlyHint":False,"destructiveHint":False,"idempotentHint":True,"openWorldHint":False})
    def cancel_job(job_id: str) -> dict:
        """自分のジョブの生成を中止。既存の候補・保存済み成果物や他のOllama processを消さない。"""
        return store.cancel(job_id)

    @mcp.tool(annotations={"readOnlyHint":False,"destructiveHint":False,"idempotentHint":True,"openWorldHint":False})
    def finalize_job(job_id: str, candidate_hash: str, decision: str="ACCEPT",
                     changes: list[dict] | None=None, impact: str="") -> dict:
        """確認済み候補をACCEPT原物またはPATCH差分で保存。差分はpath/before/after、PATCHには利用への影響を添える。"""
        return store.save(job_id,candidate_hash,decision,changes,impact)

    @mcp.tool(annotations={"readOnlyHint":False,"destructiveHint":False,"idempotentHint":True,"openWorldHint":False})
    def amend_result(job_id: str, result_hash: str, changes: list[dict], impact: str,
                     requested_change: str="", data_schema: dict | None=None,
                     csv_exports: list[dict] | None=None) -> dict:
        """ユーザーが求めた追加修正を、保存済み成果物の対象箇所だけ差分で新しい版へ保存。Gemmaを再実行しない。"""
        return store.save(job_id,result_hash,"PATCH",changes,impact,amend=True,
                          data_schema=data_schema,exports=csv_exports,requested_change=requested_change)

    @mcp.tool(annotations={"readOnlyHint":False,"destructiveHint":False,"idempotentHint":True,"openWorldHint":False})
    def save_direct_result(request_key: str, request: str, artifact: dict,
                           data_schema: dict | None=None, csv_exports: list[dict] | None=None) -> dict:
        """会話側が直接処理した小さい仕事をdata/report_mdのJSONと任意CSVへ保存。Gemmaや別Cloudを呼ばない。"""
        validate_artifact(artifact,artifact_schema(data_schema))
        # Include the artifact fingerprint so a reused key cannot silently save different content.
        row,created=store.create(request_key,request,{"direct_artifact_sha256":sha(artifact)},[],data_schema,csv_exports,executor="conversation")
        validate_artifact(artifact,parse(row["payload"])["schema"])
        if created:
            store.update(row["id"],state="CANDIDATE_READY",phase="直接作成済み",candidate=packed(artifact),candidate_hash=sha(artifact))
        return store.save(row["id"],sha(artifact))

    return mcp


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--config")
    args=parser.parse_args()
    create_server(args.config).run(transport="stdio")
