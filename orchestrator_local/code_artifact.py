"""Text source drafts saved inside reviewed artifacts, never executed or applied to a repo."""
import re
from pathlib import PurePosixPath

from .core import UserError


def source_paths(paths):
    if not isinstance(paths,list) or not 1 <= len(paths) <= 12:
        raise UserError('コード案のファイル名を1〜12件指定してください')
    seen=set()
    for name in paths:
        if not isinstance(name,str) or not name or len(name)>180:
            raise UserError('コード案の相対ファイル名が不正です')
        p=PurePosixPath(name)
        if p.is_absolute() or p.as_posix()!=name or any(x in {'','.','..'} for x in name.split('/')):
            raise UserError('コード案は成果物内の相対ファイル名にしてください')
        for part in p.parts:
            if re.search(r'[\\<>:"|?*\x00-\x1f]',part) or part.endswith((' ','.')) or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',part):
                raise UserError('Windowsで保存できないコードファイル名です')
        key=name.casefold()
        if key in seen or any(key.startswith(x+'/') or x.startswith(key+'/') for x in seen):
            raise UserError('コードファイル名が重複するか親子で衝突しています')
        seen.add(key)
    return list(paths)


def data_schema(paths):
    paths=source_paths(paths)
    return {'type':'object','properties':{'files':{'type':'array','minItems':len(paths),'maxItems':len(paths),
        'items':{'type':'object','properties':{'path':{'type':'string','enum':paths},'content':{'type':'string','minLength':1}},
                 'required':['path','content'],'additionalProperties':False}}},'required':['files'],'additionalProperties':False}


def validate(value, paths):
    paths=source_paths(paths)
    actual=[item['path'] for item in value['data']['files']]
    if len(actual)!=len(paths) or set(actual)!=set(paths):
        raise UserError('コード案のファイル名・件数が依頼した一覧と一致しません')


def export(folder, value, paths):
    validate(value,paths)
    for item in value['data']['files']:
        target=folder/'source'/PurePosixPath(item['path'])
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('x',encoding='utf8',newline='') as f:f.write(item['content'])
