"""CLI access to the same registered tool handlers when a host omits custom MCP tools."""
import asyncio
import json
from pathlib import Path

from .core import UserError,parse

TOOLS={'local_status','read_input','start_job','start_code_job','get_job','cancel_job',
       'finalize_job','amend_result','save_direct_result'}


def invoke(config, name, arguments_file=None):
    if name not in TOOLS:raise UserError('未対応のツール名です')
    arguments={}
    if arguments_file:
        path=Path(arguments_file)
        if path.stat().st_size>256000:raise UserError('引数ファイルが大きすぎます')
        arguments=parse(path.read_text(encoding='utf-8-sig'))
        if not isinstance(arguments,dict):raise UserError('引数はJSON objectにしてください')
    from .server import create_server
    result=asyncio.run(create_server(config).call_tool(name,arguments))
    if isinstance(result,tuple) and len(result)==2 and isinstance(result[1],dict):return result[1]
    if isinstance(result,dict):return result
    # A plain dict annotation has no structured schema in SDK 1.30. Its
    # public handler returns one JSON TextContent, as it does over stdio.
    if isinstance(result,list) and len(result)==1 and getattr(result[0],'type',None)=='text':
        value=parse(result[0].text)
        if isinstance(value,dict):return value
    raise UserError('ツールの返却形式が不正です')
