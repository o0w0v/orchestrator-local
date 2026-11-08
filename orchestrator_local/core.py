"""Durable jobs and checked artifact revisions. No model or shell execution here."""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from .paths import default_config

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
LIVE = {"QUEUED", "RUNNING"}
PROMPT = "依頼と元資料に照らし、使えるなら採用。利用に支障のある誤りだけ箇所と影響を示し差分修正。依頼にない要件・表現改善・採点表は追加しない。"
DEFAULT_DATA_SCHEMA = {"type": "object"}


class UserError(ValueError):
    pass


def parse(text: str):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise UserError("JSONに重複キーがあります: " + k)
            result[k] = v
        return result
    return json.loads(text, object_pairs_hook=unique,
                      parse_constant=lambda x: (_ for _ in ()).throw(UserError("非有限数は使えません")))


def packed(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(value) -> str:
    return hashlib.sha256(packed(value).encode("utf-8")).hexdigest()


def equal(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    return a == b


def artifact_schema(data_schema=None):
    data_schema = copy.deepcopy(data_schema or DEFAULT_DATA_SCHEMA)
    if data_schema.get("type") != "object":
        raise UserError("data_schemaはtype=objectにしてください")
    def check(v, depth=0):
        if depth > 40:
            raise UserError("schemaが深すぎます")
        if isinstance(v, dict):
            for k, x in v.items():
                if k in {"$ref", "$dynamicRef", "$id"}:
                    raise UserError("初期版のschemaは参照を展開して渡してください")
                check(x, depth + 1)
        elif isinstance(v, list):
            for x in v:
                check(x, depth + 1)
    check(data_schema)
    result = {"type": "object", "properties": {"data": data_schema,
              "report_md": {"type": "string", "minLength": 1}},
              "required": ["data", "report_md"], "additionalProperties": False}
    Draft202012Validator.check_schema(result)
    return result


def validate_artifact(value, schema):
    if len(packed(value).encode("utf-8")) > 128000:
        raise UserError("成果物が128KBの確認上限を超えます。対象を分割してください")
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        raise UserError("成果物の形式が不正です: " + errors[0].message[:500])
    if not value["report_md"].strip():
        raise UserError("report_mdが空です")


def pointer_parts(path):
    if not isinstance(path, str) or not path.startswith("/") or re.search(r"~(?![01])", path):
        raise UserError("JSON Pointerが不正です")
    return [p.replace("~1", "/").replace("~0", "~") for p in path[1:].split("/")]


def lookup(value, parts):
    for key in parts:
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", key):
                raise UserError("配列indexが不正です")
            key = int(key)
        try:
            value = value[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise UserError("JSON Pointerの対象がありません") from exc
    return value


def patch_artifact(candidate, changes, schema):
    if not isinstance(changes, list) or not 1 <= len(changes) <= 100:
        raise UserError("PATCHは1〜100箇所の明示差分が必要です")
    result = copy.deepcopy(candidate)
    seen = []
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"path", "before", "after"}:
            raise UserError("差分にはpath/before/afterだけを指定してください")
        parts = pointer_parts(change["path"])
        if any(parts == x or parts[:len(x)] == x or x[:len(parts)] == parts for x in seen):
            raise UserError("重複または親子が重なる差分です")
        seen.append(parts)
        before = lookup(candidate, parts)
        if not equal(before, change["before"]):
            raise UserError("変更前の値が一致しません: " + change["path"])
        parent = lookup(result, parts[:-1])
        key = int(parts[-1]) if isinstance(parent, list) else parts[-1]
        parent[key] = copy.deepcopy(change["after"])
    validate_artifact(result, schema)
    return result


def read_settings(path=None):
    path = Path(path or os.environ.get("ORCHESTRATOR_LOCAL_CONFIG", default_config())).resolve()
    if not path.is_file():
        raise UserError("初期設定がありません。Orchestrator Localの「初回設定」を開いてください")
    settings = parse(path.read_text(encoding="utf-8-sig"))
    endpoint = urlsplit(settings["ollama_url"])
    if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"} or endpoint.username or endpoint.password or endpoint.path not in {"", "/"} or endpoint.query or endpoint.fragment:
        raise UserError("Ollamaの接続先はこのPCのloopback HTTPに限定します")
    settings["config_path"] = str(path)
    settings["data_dir"] = str(Path(settings["data_dir"]).resolve())
    settings["input_roots"] = [str(Path(x).resolve()) for x in settings["input_roots"]]
    return settings


def input_document(settings, path):
    p = Path(path).resolve(strict=True)
    if not any(p.is_relative_to(Path(x)) for x in settings["input_roots"]):
        raise UserError("許可した入力フォルダ外です。inboxに置いてください")
    if p.suffix.lower() not in {".csv", ".json", ".txt", ".md"}:
        raise UserError("初期版はCSV/JSON/TXT/Markdownに対応します")
    if not p.is_file() or p.stat().st_size > 1024 * 1024:
        raise UserError("入力は1ファイル1MiB以下にしてください")
    raw = p.read_bytes()
    try:
        text, encoding = raw.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        text, encoding = raw.decode("cp932"), "cp932"
    if p.suffix.lower() == ".json":
        data = parse(text)
    elif p.suffix.lower() == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        columns = reader.fieldnames or []
        if not columns or len(set(columns)) != len(columns) or any(not c for c in columns):
            raise UserError("CSV列名が空または重複しています")
        data = list(reader)
        if any(None in row or any(v is None for v in row.values()) for row in data):
            raise UserError("CSVの列数が一致しません")
    else:
        data = text
    return {"name": p.name, "sha256": hashlib.sha256(raw).hexdigest(), "encoding": encoding, "data": data}


def check_exports(exports):
    names = set()
    for e in exports:
        if not isinstance(e, dict) or set(e) != {"name", "pointer", "columns"}:
            raise UserError("CSV指定はname/pointer/columnsが必要です")
        name = e["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[\w\-][\w\-. ]{0,70}\.csv", name, re.UNICODE) or ".." in name or name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1,10)], *[f"LPT{i}" for i in range(1,10)]}:
            raise UserError("CSVファイル名が不正です")
        if name.casefold() in names:
            raise UserError("CSVファイル名が重複しています")
        names.add(name.casefold())
        pointer_parts(e["pointer"])
        columns = e["columns"]
        if not isinstance(columns, list) or not columns or any(not isinstance(x, str) or not x for x in columns) or len(set(columns)) != len(columns):
            raise UserError("CSV列を重複なしで指定してください")
    return exports


class Store:
    def __init__(self, settings):
        self.settings = settings
        self.root = Path(settings["data_dir"])
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "jobs").mkdir(exist_ok=True)
        for x in settings["input_roots"]:
            Path(x).mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, payload_hash TEXT NOT NULL,
              payload TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
              worker_pid INTEGER, cancel INTEGER NOT NULL DEFAULT 0, phase TEXT, output_chars INTEGER DEFAULT 0,
              candidate TEXT, candidate_hash TEXT, result TEXT, result_hash TEXT,
              revision INTEGER DEFAULT 0, saved_path TEXT, last_review_hash TEXT, error TEXT,
              usage TEXT, elapsed REAL, executor TEXT NOT NULL,
              result_schema TEXT, result_exports TEXT)""")
            columns={r[1] for r in db.execute('PRAGMA table_info(jobs)')}
            for name in ['result_schema','result_exports']:
                if name not in columns:
                    db.execute('ALTER TABLE jobs ADD COLUMN '+name+' TEXT')
            db.execute('''CREATE TABLE IF NOT EXISTS local_control (
                id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), changed REAL NOT NULL)''')
            db.execute('INSERT OR IGNORE INTO local_control(id,enabled,changed) VALUES(1,0,?)', (time.time(),))

    def dispatch_state(self):
        with self.connection() as db:
            row = db.execute('SELECT enabled,changed FROM local_control WHERE id=1').fetchone()
            if row is None or row['enabled'] not in (0, 1):
                raise UserError('ローカル分担の設定を読み取れません。生成せず停止します')
            counts = dict(db.execute("SELECT state,COUNT(*) FROM jobs WHERE executor='gemma' AND state IN ('QUEUED','RUNNING') GROUP BY state").fetchall())
        return {'enabled': bool(row['enabled']), 'changed': row['changed'],
                'running': counts.get('RUNNING', 0), 'queued': counts.get('QUEUED', 0)}

    def set_dispatch_enabled(self, enabled):
        if type(enabled) is not bool:
            raise UserError('ローカル分担の切り替えはON/OFFで指定してください')
        with self.transaction() as db:
            db.execute('UPDATE local_control SET enabled=?,changed=? WHERE id=1', (int(enabled), time.time()))
        return self.dispatch_state()

    def connect(self):
        db = sqlite3.connect(self.root / "jobs.sqlite3", timeout=15)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def connection(self):
        db = self.connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, job_id, db=None):
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise UserError("job_idが不正です")
        if db is None:
            with self.connection() as conn:
                return self.get(job_id, conn)
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise UserError("ジョブがありません")
        return dict(row)

    def create(self, request_key, request, inputs=None, input_paths=None, data_schema=None, exports=None, executor="gemma",
               code_paths=None):
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 128 or not request.strip():
            raise UserError("空でないrequest_keyと元依頼が必要です")
        if len(input_paths or []) > 8:
            raise UserError("入力ファイルは8件までです")
        payload = {"request":request, "inputs": inputs or {},
                   "files":[input_document(self.settings, p) for p in input_paths or []],
                   "schema":artifact_schema(data_schema), "csv_exports":check_exports(exports or [])}
        if code_paths is not None:
            from .code_artifact import source_paths, data_schema as code_schema
            if data_schema is not None or exports:
                raise UserError('コード案ではCSVや別のdata_schemaを指定しません')
            payload.update(work_type='code',code_paths=source_paths(code_paths),schema=artifact_schema(code_schema(code_paths)))
        raw = packed(payload)
        if len(raw.encode("utf-8")) + self.settings["options"]["num_predict"] + 4096 > self.settings["options"]["num_ctx"]:
            raise UserError("入力がLocal上限を超えます。切り捨てずに対象を分割するか直接処理してください")
        fingerprint = sha({"payload":payload, "executor":executor})
        with self.transaction() as db:
            old = db.execute("SELECT * FROM jobs WHERE request_key=?", (request_key,)).fetchone()
            if old:
                if old["payload_hash"] != fingerprint:
                    raise UserError("同じrequest_keyに別の入力は使えません")
                return dict(old), False
            if executor == 'gemma' and not db.execute('SELECT enabled FROM local_control WHERE id=1').fetchone()[0]:
                raise UserError('ローカル分担はOFFです。通常のCodexで処理するか、画面でONにしてください')
            if db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('QUEUED','RUNNING')").fetchone()[0] >= 8:
                raise UserError("待ちジョブが多いため、完了後に依頼してください")
            job_id = uuid.uuid4().hex
            ts = time.time()
            db.execute("INSERT INTO jobs(id,request_key,payload_hash,payload,state,created,updated,phase,executor) VALUES(?,?,?,?,?,?,?,?,?)",
                       (job_id,request_key,fingerprint,raw,"QUEUED",ts,ts,"待機中",executor))
            folder = self.root / "jobs" / job_id
            folder.mkdir()
            (folder / "request.json").write_text(raw + "\n",encoding="utf-8")
            return self.get(job_id,db), True

    def update(self, job_id, **values):
        allowed = {"state","phase","worker_pid","output_chars","candidate","candidate_hash","error","usage","elapsed","cancel"}
        if not set(values) <= allowed:
            raise ValueError("Unknown column")
        values["updated"] = time.time()
        with self.transaction() as db:
            self.get(job_id, db)
            db.execute("UPDATE jobs SET " + ",".join(k + "=?" for k in values) + " WHERE id=?", [*values.values(),job_id])

    def claim(self, job_id):
        with self.transaction() as db:
            row = self.get(job_id, db)
            if row['executor'] == 'gemma' and not db.execute('SELECT enabled FROM local_control WHERE id=1').fetchone()[0]:
                return False
            if row["cancel"] or row["state"] != "QUEUED":
                return False
            first = db.execute("SELECT id FROM jobs WHERE state IN ('RUNNING','QUEUED') ORDER BY CASE state WHEN 'RUNNING' THEN 0 ELSE 1 END,created,id LIMIT 1").fetchone()
            if first is None or first["id"] != job_id:
                return False
            db.execute("UPDATE jobs SET state='RUNNING',phase='準備中',updated=? WHERE id=?",(time.time(),job_id))
            return True

    def cancel(self, job_id):
        with self.transaction() as db:
            row = self.get(job_id,db)
            if row["state"] in LIVE:
                state = "CANCELLED" if row["state"] == "QUEUED" else row["state"]
                db.execute("UPDATE jobs SET cancel=1,state=?,phase='中止要求',updated=? WHERE id=?",(state,time.time(),job_id))
        return self.view(job_id)

    def view(self, job_id, include_candidate=False):
        r = self.get(job_id)
        out = {k:r[k] for k in ["id","state","phase","created","updated","output_chars","candidate_hash","result_hash","revision","saved_path","error","elapsed","executor"]}
        out["cancel_requested"] = bool(r["cancel"])
        out["usage"] = parse(r["usage"]) if r["usage"] else None
        out["conversation_Credits"] = None
        payload=parse(r['payload'])
        out['work_type']=payload.get('work_type','data')
        if payload.get('work_type')=='code':
            out['requested_files']=payload['code_paths']
            if r['saved_path']:
                out['source_files']=[str(Path(r['saved_path'])/'source'/p) for p in payload['code_paths']]
        if include_candidate and r["candidate"]:
            out["candidate"] = parse(r["candidate"])
            payload = parse(r["payload"])
            out["original_request"] = payload["request"]
            out["review_inputs"] = {"inputs":payload["inputs"],"files":payload["files"]}
            out["review_instruction"] = PROMPT
        if r["result"]:
            out["artifact"] = parse(r["result"])
            out["csv_exports"] = parse(r["result_exports"]) if r["result_exports"] else parse(r["payload"])["csv_exports"]
        return out

    def save(self, job_id, expected_hash, decision="ACCEPT", changes=None, impact="", amend=False,
             data_schema=None, exports=None, requested_change=""):
        if (data_schema is not None or exports is not None) and (not amend or not requested_change.strip()):
            raise UserError("形式やCSV列の変更にはユーザーが依頼した変更内容が必要です")
        action_hash = sha({"expected":expected_hash,"decision":decision,"changes":changes or [],"impact":impact,"amend":amend,
                           "data_schema":data_schema,"exports":exports,"requested_change":requested_change})
        with self.transaction() as db:
            row = self.get(job_id,db)
            if row["last_review_hash"] == action_hash:
                return {"job_id":job_id,"saved_path":row["saved_path"],"result_hash":row["result_hash"],"revision":row["revision"],"reused":True}
            state = "COMPLETED" if amend else "CANDIDATE_READY"
            if row["state"] != state:
                raise UserError("この状態では保存できません: " + row["state"])
            base = parse(row["result"] if amend else row["candidate"])
            current_hash = row["result_hash"] if amend else row["candidate_hash"]
            if expected_hash != current_hash:
                raise UserError("候補が一致しません。最新のhashを取得してください")
            payload = parse(row["payload"])
            if payload.get('work_type')=='code' and (data_schema is not None or exports is not None):
                raise UserError('コード案のファイル一覧変更は、新しい依頼として作成してください')
            schema = parse(row['result_schema']) if amend and row['result_schema'] else payload['schema']
            export_spec = parse(row['result_exports']) if amend and row['result_exports'] else payload['csv_exports']
            if data_schema is not None:
                schema=artifact_schema(data_schema)
            if exports is not None:
                export_spec=check_exports(exports)
            if decision == "ACCEPT" and not changes and not amend:
                result = base
            elif decision == "PATCH" and impact.strip():
                result = patch_artifact(base, changes, schema)
            else:
                raise UserError("ACCEPTか、利用への影響を添えた明示PATCHが必要です")
            validate_artifact(result,schema)
            if payload.get('work_type')=='code':
                from .code_artifact import validate as validate_code
                validate_code(result,payload['code_paths'])
            version = row["revision"] + 1
            parent = self.root/"jobs"/job_id
            temp = parent/('.saving-' + uuid.uuid4().hex)
            temp.mkdir()
            self._export(temp,result,export_spec)
            if payload.get('work_type')=='code':
                from .code_artifact import export as export_code
                export_code(temp,result,payload['code_paths'])
            (temp/"review.json").write_text(packed({"decision":decision,"changes":changes or [],"impact":impact,"expected_hash":expected_hash,"reviewer":"conversation","independent_audit":False,
                "requested_change":requested_change,"data_schema":schema,"csv_exports":export_spec})+"\n",encoding="utf-8")
            files={p.relative_to(temp).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in temp.rglob('*') if p.is_file()}
            (temp/"manifest.json").write_text(packed({"files":files,"artifact_sha256":sha(result)})+"\n",encoding="utf-8")
            dest = parent/(f"result-{version:03d}-" + uuid.uuid4().hex[:8])
            temp.rename(dest)
            db.execute("UPDATE jobs SET state='COMPLETED',phase='保存済み',result=?,result_hash=?,revision=?,saved_path=?,last_review_hash=?,result_schema=?,result_exports=?,updated=? WHERE id=?",
                       (packed(result),sha(result),version,str(dest),action_hash,packed(schema),packed(export_spec),time.time(),job_id))
            return {"job_id":job_id,"saved_path":str(dest),"files":[str(p) for p in dest.rglob('*') if p.is_file()],"result_hash":sha(result),"revision":version,"reused":False}

    @staticmethod
    def _export(folder,result,exports):
        (folder/"artifact.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
        (folder/"data.json").write_text(json.dumps(result["data"],ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
        (folder/"report.md").write_text(result["report_md"]+"\n",encoding="utf-8")
        for spec in exports:
            rows = lookup(result,pointer_parts(spec["pointer"]))
            if not isinstance(rows,list) or any(not isinstance(r,dict) or any(c not in r for c in spec["columns"]) for r in rows):
                raise UserError("CSV対象は指定列を持つobjectの配列にしてください")
            def cell(value):
                if isinstance(value,(dict,list)):
                    raise UserError("CSVのセルには入れ子を含められません")
                if isinstance(value,str) and (value.lstrip().startswith(("=","+","-","@")) or value.startswith(("\t","\r","\n"))):
                    return "'"+value
                return value
            with (folder/spec["name"]).open("w",encoding="utf-8-sig",newline="") as f:
                writer=csv.writer(f,lineterminator="\n")
                writer.writerow([cell(c) for c in spec["columns"]])
                writer.writerows([[cell(r[c]) for c in spec["columns"]] for r in rows])
