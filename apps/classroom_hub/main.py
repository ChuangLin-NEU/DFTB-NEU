"""DFTB 课堂中心 — 部署于 4060；学生经公网/校园 HTTPS 访问（不依赖 Tailscale）。"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="DFTB 课堂中心",
    version="0.1.0",
    description="激活许可、会话校验、LLM/MP 代理。Key 仅存中心。",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def data_dir() -> Path:
    raw = os.environ.get("DFTB_CLASS_DATA") or ""
    if raw:
        p = Path(raw)
    else:
        p = Path.home() / ".dftb-neu-classroom"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "classroom.sqlite3"


def _default_admin_secret() -> str:
    return (
        os.environ.get("DFTB_CLASS_TEACHER_PASSWORD")
        or os.environ.get("DFTB_CLASS_ADMIN_SECRET")
        or "zl303@"
    ).strip()


def admin_secret() -> str:
    """教师永久密码：库内自定义优先，否则环境变量，默认 zl303@。"""
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT password_plain FROM teacher_auth WHERE id=1"
            ).fetchone()
            if row and (row["password_plain"] or "").strip():
                return str(row["password_plain"]).strip()
    except Exception:
        pass
    return _default_admin_secret()


def token_secret() -> bytes:
    env = (os.environ.get("DFTB_CLASS_TOKEN_SECRET") or admin_secret() or "dftb-neu-dev").encode()
    return hashlib.sha256(env).digest()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(db_path()))
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS classes (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              code_hash TEXT NOT NULL,
              code_hint TEXT NOT NULL,
              valid_days INTEGER NOT NULL,
              max_activations INTEGER NOT NULL DEFAULT 200,
              daily_llm_limit INTEGER NOT NULL DEFAULT 80,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at REAL NOT NULL,
              notes TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS gate (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              code_hash TEXT NOT NULL DEFAULT '',
              code_hint TEXT NOT NULL DEFAULT '',
              generation INTEGER NOT NULL DEFAULT 1,
              daily_llm_limit INTEGER NOT NULL DEFAULT 80,
              session_days INTEGER NOT NULL DEFAULT 0,
              updated_at REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sessions (
              token_id TEXT PRIMARY KEY,
              class_id TEXT NOT NULL,
              student_label TEXT NOT NULL,
              device_id TEXT NOT NULL,
              issued_at REAL NOT NULL,
              expires_at REAL NOT NULL,
              revoked INTEGER NOT NULL DEFAULT 0,
              generation INTEGER NOT NULL DEFAULT 1,
              is_master INTEGER NOT NULL DEFAULT 0,
              last_seen REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS usage_daily (
              day TEXT NOT NULL,
              session_token_id TEXT NOT NULL,
              llm_calls INTEGER NOT NULL DEFAULT 0,
              mp_calls INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (day, session_token_id)
            );
            CREATE TABLE IF NOT EXISTS teacher_auth (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              password_plain TEXT NOT NULL DEFAULT '',
              updated_at REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS gate_passwords (
              id TEXT PRIMARY KEY,
              code_hash TEXT NOT NULL,
              code_plain TEXT NOT NULL DEFAULT '',
              code_hint TEXT NOT NULL DEFAULT '',
              created_at REAL NOT NULL,
              revoked INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        # 兼容旧库
        cols = {r[1] for r in c.execute("PRAGMA table_info(sessions)").fetchall()}
        if "generation" not in cols:
            c.execute("ALTER TABLE sessions ADD COLUMN generation INTEGER NOT NULL DEFAULT 1")
        if "is_master" not in cols:
            c.execute("ALTER TABLE sessions ADD COLUMN is_master INTEGER NOT NULL DEFAULT 0")
        if "last_seen" not in cols:
            c.execute("ALTER TABLE sessions ADD COLUMN last_seen REAL NOT NULL DEFAULT 0")
        if "password_id" not in cols:
            c.execute("ALTER TABLE sessions ADD COLUMN password_id TEXT NOT NULL DEFAULT ''")
        gate_cols = {r[1] for r in c.execute("PRAGMA table_info(gate)").fetchall()}
        if "code_plain" not in gate_cols:
            c.execute("ALTER TABLE gate ADD COLUMN code_plain TEXT NOT NULL DEFAULT ''")
        if not c.execute("SELECT 1 FROM gate WHERE id=1").fetchone():
            c.execute(
                "INSERT INTO gate(id, code_hash, code_hint, code_plain, generation, daily_llm_limit, session_days, updated_at) "
                "VALUES(1,'','','',1,80,30,?)",
                (time.time(),),
            )
        if not c.execute("SELECT 1 FROM teacher_auth WHERE id=1").fetchone():
            c.execute(
                "INSERT INTO teacher_auth(id, password_plain, updated_at) VALUES(1,'',0)"
            )
        # 将旧版单密码迁移到 gate_passwords
        gate_row = c.execute("SELECT * FROM gate WHERE id=1").fetchone()
        if gate_row and str(gate_row["code_hash"] or "").strip():
            exists = c.execute(
                "SELECT 1 FROM gate_passwords WHERE code_hash=? AND revoked=0",
                (gate_row["code_hash"],),
            ).fetchone()
            if not exists:
                plain = ""
                try:
                    plain = str(gate_row["code_plain"] or "").strip()
                except (IndexError, KeyError):
                    plain = ""
                if not plain:
                    hint = str(gate_row["code_hint"] or "").strip()
                    if hint and "***" not in hint:
                        plain = hint
                c.execute(
                    """
                    INSERT INTO gate_passwords(id, code_hash, code_plain, code_hint, created_at, revoked)
                    VALUES(?,?,?,?,?,0)
                    """,
                    (
                        secrets.token_hex(8),
                        gate_row["code_hash"],
                        plain,
                        plain or str(gate_row["code_hint"] or ""),
                        float(gate_row["updated_at"] or time.time()),
                    ),
                )


def _hash_code(code: str) -> str:
    return hashlib.sha256(f"dftb-class|{code.strip()}".encode()).hexdigest()


def _get_gate() -> sqlite3.Row:
    with _conn() as c:
        row = c.execute("SELECT * FROM gate WHERE id=1").fetchone()
        if not row:
            raise HTTPException(503, "课堂门禁未初始化")
        return row


def _list_active_passwords(c: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        c.execute(
            "SELECT * FROM gate_passwords WHERE revoked=0 ORDER BY created_at DESC, id DESC"
        ).fetchall()
    )


def _password_public(row: sqlite3.Row) -> dict[str, Any]:
    plain = str(row["code_plain"] or "").strip()
    if not plain:
        hint = str(row["code_hint"] or "").strip()
        if hint and "***" not in hint:
            plain = hint
    return {
        "id": row["id"],
        "student_password": plain,
        "code_hint": plain,
        "plain_available": bool(plain),
        "created_at": float(row["created_at"] or 0),
        "created_at_iso": datetime.fromtimestamp(
            float(row["created_at"] or 0), tz=timezone.utc
        ).isoformat()
        if row["created_at"]
        else "",
    }


def _sync_gate_legacy(c: sqlite3.Connection, now: Optional[float] = None) -> None:
    """保持 gate 单行字段与最新有效密码同步，兼容旧客户端。"""
    ts = time.time() if now is None else now
    rows = _list_active_passwords(c)
    if not rows:
        c.execute(
            "UPDATE gate SET code_hash='', code_hint='', code_plain='', updated_at=? WHERE id=1",
            (ts,),
        )
        return
    latest = rows[0]
    plain = str(latest["code_plain"] or "").strip()
    if not plain:
        hint = str(latest["code_hint"] or "").strip()
        if hint and "***" not in hint:
            plain = hint
    c.execute(
        """
        UPDATE gate SET code_hash=?, code_hint=?, code_plain=?, updated_at=? WHERE id=1
        """,
        (latest["code_hash"], plain, plain, ts),
    )


def _require_teacher(x_teacher_password: Optional[str] = None, x_admin_secret: Optional[str] = None) -> None:
    """教师永久密码校验（默认 zl303@）。"""
    got = (x_teacher_password or x_admin_secret or "").strip()
    expect = admin_secret()
    if not got or not hmac.compare_digest(got, expect):
        raise HTTPException(403, "教师密码错误")


def _b64(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    import base64

    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def issue_session_token(*, class_id: str, student: str, device: str, expires_at: float) -> str:
    payload = {
        "tid": secrets.token_hex(8),
        "cid": class_id,
        "sub": student,
        "dev": device,
        "iat": int(time.time()),
        "exp": int(expires_at),
        "iss": "dftb-classroom",
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(token_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_session_token(token: str) -> Optional[dict[str, Any]]:
    try:
        body, sig = (token or "").split(".", 1)
    except ValueError:
        return None
    expect = hmac.new(token_secret(), body.encode(), hashlib.sha256).digest()
    try:
        got = _unb64(sig)
    except Exception:
        return None
    if not hmac.compare_digest(expect, got):
        return None
    try:
        payload = json.loads(_unb64(body))
    except Exception:
        return None
    if int(payload.get("exp") or 0) < int(time.time()):
        return None
    return payload


def _require_admin(x_admin_secret: Optional[str]) -> None:
    _require_teacher(x_admin_secret=x_admin_secret)


def _require_session(authorization: Optional[str]) -> dict[str, Any]:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    payload = verify_session_token(token)
    if not payload:
        raise HTTPException(401, "课堂会话无效或已过期，请重新登录")
    gate = _get_gate()
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM sessions WHERE token_id=? AND revoked=0",
            (payload.get("tid"),),
        ).fetchone()
        if not row:
            raise HTTPException(401, "课堂会话已失效，请重新登录")
        if float(row["expires_at"]) < time.time():
            raise HTTPException(401, "课堂许可已过期，请重新登录")
        is_master = bool(row["is_master"])
        if not is_master and int(row["generation"] or 0) != int(gate["generation"]):
            raise HTTPException(401, "教师已结束本堂或更换门禁，请重新登录")
        try:
            password_id = str(row["password_id"] or "").strip()
        except (IndexError, KeyError):
            password_id = ""
        if not is_master and password_id:
            prow = c.execute(
                "SELECT revoked FROM gate_passwords WHERE id=?",
                (password_id,),
            ).fetchone()
            if not prow or int(prow["revoked"] or 0):
                raise HTTPException(401, "本堂密码已吊销，请重新登录")
        now = time.time()
        c.execute("UPDATE sessions SET last_seen=? WHERE token_id=?", (now, row["token_id"]))
    return {
        "token_id": payload["tid"],
        "class_id": row["class_id"],
        "student_label": row["student_label"],
        "expires_at": float(row["expires_at"]),
        "daily_llm_limit": int(gate["daily_llm_limit"]),
        "is_master": is_master,
        "token": token,
    }


def _bump_usage(token_id: str, kind: str) -> None:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    col = "llm_calls" if kind == "llm" else "mp_calls"
    with _conn() as c:
        c.execute(
            f"""
            INSERT INTO usage_daily(day, session_token_id, llm_calls, mp_calls)
            VALUES(?,?,?,?)
            ON CONFLICT(day, session_token_id) DO UPDATE SET {col} = {col} + 1
            """,
            (day, token_id, 1 if kind == "llm" else 0, 1 if kind == "mp" else 0),
        )


def _llm_count_today(token_id: str) -> int:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _conn() as c:
        row = c.execute(
            "SELECT llm_calls FROM usage_daily WHERE day=? AND session_token_id=?",
            (day, token_id),
        ).fetchone()
    return int(row["llm_calls"]) if row else 0


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health():
    prefer = (os.environ.get("DFTB_CLASS_LLM_PROVIDER") or "deepseek").strip().lower()
    ds_key = bool(
        (os.environ.get("DFTB_CLASS_DEEPSEEK_API_KEY") or os.environ.get("CMATS_DEEPSEEK_API_KEY") or "").strip()
    )
    qw_key = bool(
        (os.environ.get("DFTB_CLASS_LLM_API_KEY") or os.environ.get("CMATS_LLM_API_KEY") or "").strip()
    )
    llm_configured = (prefer == "qwen" and (qw_key or ds_key)) or (prefer != "qwen" and (ds_key or qw_key))
    mp_key = bool(
        (os.environ.get("DFTB_CLASS_MP_API_KEY") or os.environ.get("CMATS_MP_API_KEY") or "").strip()
    )
    return {
        "ok": True,
        "service": "dftb-classroom-hub",
        "version": "0.2.1",
        "server_time": datetime.now(timezone.utc).isoformat(),
        "data": str(data_dir()),
        "llm_provider": prefer,
        "llm_configured": llm_configured,
        "deepseek_key_set": ds_key,
        "qwen_key_set": qw_key,
        "mp_key_set": mp_key,
        "features": {"teacher_gate_clear": True, "multi_gate_passwords": True},
    }


class CreateClassIn(BaseModel):
    title: str = "DFTB 课堂"
    code: str = Field(..., min_length=1, max_length=64)
    valid_days: int = Field(7, ge=1, le=120)
    max_activations: int = 200
    daily_llm_limit: int = 80
    notes: str = ""


class SetGateIn(BaseModel):
    student_password: str = Field(..., min_length=1, max_length=64)
    # 0 = 本堂密码/会话不设过期（直至吊销或清空）；>0 为兼容旧客户端的可选天数
    session_days: int = Field(0, ge=0, le=3650)
    daily_llm_limit: int = Field(80, ge=1, le=10000)


class RevokeGatePasswordIn(BaseModel):
    password_id: str = ""
    student_password: str = ""


class ChangeTeacherPasswordIn(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=1, max_length=128)


@app.post("/teacher/gate")
def teacher_set_gate(
    body: SetGateIn,
    x_teacher_password: Optional[str] = Header(None),
    x_admin_secret: Optional[str] = Header(None),
):
    """新增一本堂密码；已有口令仍有效，不影响已登录短密码会话。"""
    _require_teacher(x_teacher_password, x_admin_secret)
    pwd = body.student_password.strip()
    if not pwd:
        raise HTTPException(400, "本堂密码不能为空")
    now = time.time()
    digest = _hash_code(pwd)
    with _conn() as c:
        existing = c.execute(
            "SELECT * FROM gate_passwords WHERE code_hash=?",
            (digest,),
        ).fetchone()
        if existing and not int(existing["revoked"] or 0):
            passwords = [_password_public(r) for r in _list_active_passwords(c)]
            gate = c.execute("SELECT * FROM gate WHERE id=1").fetchone()
            return {
                "ok": True,
                "message": "该本堂密码已存在，未重复添加。",
                "student_password": pwd,
                "code_hint": pwd,
                "password_id": existing["id"],
                "passwords": passwords,
                "password_count": len(passwords),
                "has_password": True,
                "generation": int(gate["generation"] or 1),
                "session_days": int(body.session_days),
            }
        if existing and int(existing["revoked"] or 0):
            c.execute(
                """
                UPDATE gate_passwords
                SET revoked=0, code_plain=?, code_hint=?, created_at=?
                WHERE id=?
                """,
                (pwd, pwd, now, existing["id"]),
            )
            pwd_id = existing["id"]
            message = "已重新启用该本堂密码。"
        else:
            pwd_id = secrets.token_hex(8)
            c.execute(
                """
                INSERT INTO gate_passwords(id, code_hash, code_plain, code_hint, created_at, revoked)
                VALUES(?,?,?,?,?,0)
                """,
                (pwd_id, digest, pwd, pwd, now),
            )
            message = "已添加本堂密码；学生可使用任一有效口令登录。"
        c.execute(
            """
            UPDATE gate SET daily_llm_limit=?, session_days=?, updated_at=? WHERE id=1
            """,
            (int(body.daily_llm_limit), int(body.session_days), now),
        )
        _sync_gate_legacy(c, now)
        passwords = [_password_public(r) for r in _list_active_passwords(c)]
        gate = c.execute("SELECT * FROM gate WHERE id=1").fetchone()
    return {
        "ok": True,
        "message": message,
        "student_password": pwd,
        "code_hint": pwd,
        "password_id": pwd_id,
        "passwords": passwords,
        "password_count": len(passwords),
        "has_password": True,
        "generation": int(gate["generation"] or 1),
        "session_days": body.session_days,
    }


@app.get("/teacher/gate")
def teacher_get_gate(
    x_teacher_password: Optional[str] = Header(None),
    x_admin_secret: Optional[str] = Header(None),
):
    _require_teacher(x_teacher_password, x_admin_secret)
    gate = _get_gate()
    with _conn() as c:
        n = c.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE revoked=0 AND expires_at>? AND (is_master=1 OR generation=?)",
            (time.time(), int(gate["generation"])),
        ).fetchone()["n"]
        passwords = [_password_public(r) for r in _list_active_passwords(c)]
    latest = passwords[0]["student_password"] if passwords else ""
    return {
        "ok": True,
        "has_password": bool(passwords),
        "student_password": latest,
        "code_hint": latest,
        "plain_available": bool(latest),
        "passwords": passwords,
        "password_count": len(passwords),
        "generation": int(gate["generation"]),
        "session_days": int(gate["session_days"]),
        "daily_llm_limit": int(gate["daily_llm_limit"]),
        "active_sessions": n,
        "updated_at": gate["updated_at"],
    }


@app.post("/teacher/gate/revoke")
def teacher_revoke_gate_password(
    body: RevokeGatePasswordIn,
    x_teacher_password: Optional[str] = Header(None),
    x_admin_secret: Optional[str] = Header(None),
):
    """吊销单个本堂密码，并注销使用该口令登录的会话。"""
    _require_teacher(x_teacher_password, x_admin_secret)
    pwd_id = (body.password_id or "").strip()
    pwd = (body.student_password or "").strip()
    if not pwd_id and not pwd:
        raise HTTPException(400, "请提供 password_id 或 student_password")
    now = time.time()
    with _conn() as c:
        row = None
        if pwd_id:
            row = c.execute("SELECT * FROM gate_passwords WHERE id=?", (pwd_id,)).fetchone()
        if not row and pwd:
            row = c.execute(
                "SELECT * FROM gate_passwords WHERE code_hash=? AND revoked=0",
                (_hash_code(pwd),),
            ).fetchone()
        if not row:
            raise HTTPException(404, "未找到该本堂密码")
        if int(row["revoked"] or 0):
            passwords = [_password_public(r) for r in _list_active_passwords(c)]
            return {
                "ok": True,
                "message": "该本堂密码此前已吊销。",
                "passwords": passwords,
                "password_count": len(passwords),
                "has_password": bool(passwords),
            }
        c.execute("UPDATE gate_passwords SET revoked=1 WHERE id=?", (row["id"],))
        c.execute(
            "UPDATE sessions SET revoked=1 WHERE revoked=0 AND is_master=0 AND password_id=?",
            (row["id"],),
        )
        passwords_left = _list_active_passwords(c)
        if not passwords_left:
            # 已无有效口令：一并注销旧版未绑定 password_id 的短密码会话
            c.execute(
                "UPDATE sessions SET revoked=1 WHERE revoked=0 AND is_master=0"
            )
        _sync_gate_legacy(c, now)
        passwords = [_password_public(r) for r in passwords_left]
    return {
        "ok": True,
        "message": "已吊销该本堂密码，并注销对应短密码会话。",
        "passwords": passwords,
        "password_count": len(passwords),
        "has_password": bool(passwords),
    }


@app.post("/teacher/password")
def teacher_change_password(
    body: ChangeTeacherPasswordIn,
    x_teacher_password: Optional[str] = Header(None),
    x_admin_secret: Optional[str] = Header(None),
):
    """修改教师永久密码（zl303@ 一类凭证）。"""
    _require_teacher(x_teacher_password, x_admin_secret)
    current = (body.current_password or "").strip()
    new_pwd = (body.new_password or "").strip()
    if not hmac.compare_digest(current, admin_secret()):
        raise HTTPException(403, "当前永久密码不正确")
    if len(new_pwd) < 4:
        raise HTTPException(400, "新永久密码至少 4 位")
    if new_pwd == current:
        raise HTTPException(400, "新永久密码不能与当前相同")
    now = time.time()
    with _conn() as c:
        if not c.execute("SELECT 1 FROM teacher_auth WHERE id=1").fetchone():
            c.execute(
                "INSERT INTO teacher_auth(id, password_plain, updated_at) VALUES(1,?,?)",
                (new_pwd, now),
            )
        else:
            c.execute(
                "UPDATE teacher_auth SET password_plain=?, updated_at=? WHERE id=1",
                (new_pwd, now),
            )
    return {
        "ok": True,
        "message": "永久密码已更新。请同步更新本机教师端配置。",
        "teacher_password": new_pwd,
    }


@app.post("/teacher/gate/clear")
def teacher_clear_gate(
    x_teacher_password: Optional[str] = Header(None),
    x_admin_secret: Optional[str] = Header(None),
):
    """清空全部本堂口令，并注销短密码会话；永久凭证（长期）会话保留。"""
    _require_teacher(x_teacher_password, x_admin_secret)
    now = time.time()
    with _conn() as c:
        gate = c.execute("SELECT * FROM gate WHERE id=1").fetchone()
        gen = int(gate["generation"] or 1) + 1 if gate else 1
        c.execute("UPDATE gate_passwords SET revoked=1 WHERE revoked=0")
        c.execute(
            """
            UPDATE gate SET code_hash='', code_hint='', code_plain='', generation=?, updated_at=? WHERE id=1
            """,
            (gen, now),
        )
        revoked = c.execute(
            "UPDATE sessions SET revoked=1 WHERE revoked=0 AND is_master=0"
        ).rowcount
    return {
        "ok": True,
        "message": "已清空全部本堂口令，短密码会话已注销；永久凭证登录不受影响。",
        "generation": gen,
        "has_password": False,
        "passwords": [],
        "password_count": 0,
        "revoked_sessions": int(revoked or 0),
    }


@app.get("/teacher/sessions")
def teacher_sessions(
    x_teacher_password: Optional[str] = Header(None),
    x_admin_secret: Optional[str] = Header(None),
):
    """在线学生监管列表。"""
    _require_teacher(x_teacher_password, x_admin_secret)
    gate = _get_gate()
    now = time.time()
    with _conn() as c:
        rows = c.execute(
            """
            SELECT * FROM sessions
            WHERE revoked=0 AND expires_at>?
              AND (is_master=1 OR generation=?)
            ORDER BY last_seen DESC, issued_at DESC
            """,
            (now, int(gate["generation"])),
        ).fetchall()
        out = []
        for r in rows:
            tid = r["token_id"]
            out.append(
                {
                    "token_id": tid,
                    "student_id": r["student_label"],
                    "device_id": r["device_id"],
                    "is_master": bool(r["is_master"]),
                    "issued_at": r["issued_at"],
                    "issued_at_iso": datetime.fromtimestamp(r["issued_at"], tz=timezone.utc).isoformat(),
                    "expires_at": r["expires_at"],
                    "expires_at_iso": datetime.fromtimestamp(r["expires_at"], tz=timezone.utc).isoformat(),
                    "last_seen": r["last_seen"] or r["issued_at"],
                    "last_seen_iso": datetime.fromtimestamp(
                        float(r["last_seen"] or r["issued_at"]), tz=timezone.utc
                    ).isoformat(),
                    "llm_calls_today": _llm_count_today(tid),
                    "online_hint": "活跃"
                    if (now - float(r["last_seen"] or r["issued_at"])) < 600
                    else "空闲/可能离线",
                }
            )
    return {"ok": True, "server_time": datetime.now(timezone.utc).isoformat(), "students": out, "count": len(out)}


class RevokeIn(BaseModel):
    token_id: str = ""
    student_id: str = ""


@app.post("/teacher/sessions/revoke")
def teacher_revoke(
    body: RevokeIn,
    x_teacher_password: Optional[str] = Header(None),
    x_admin_secret: Optional[str] = Header(None),
):
    _require_teacher(x_teacher_password, x_admin_secret)
    with _conn() as c:
        if body.token_id:
            c.execute("UPDATE sessions SET revoked=1 WHERE token_id=?", (body.token_id,))
        elif body.student_id:
            c.execute(
                "UPDATE sessions SET revoked=1 WHERE student_label=? AND revoked=0",
                (body.student_id.strip(),),
            )
        else:
            raise HTTPException(400, "请提供 token_id 或 student_id")
    return {"ok": True, "message": "已注销指定会话"}


@app.post("/admin/classes")
def create_class(body: CreateClassIn, x_admin_secret: Optional[str] = Header(None)):
    """兼容旧接口：同时写入本堂门禁口令。"""
    _require_admin(x_admin_secret)
    return teacher_set_gate(
        SetGateIn(student_password=body.code, session_days=body.valid_days, daily_llm_limit=body.daily_llm_limit),
        x_admin_secret=x_admin_secret,
    )


@app.get("/admin/classes")
def list_classes(x_admin_secret: Optional[str] = Header(None)):
    return teacher_get_gate(x_admin_secret=x_admin_secret)


class DisableIn(BaseModel):
    enabled: bool = False


@app.post("/admin/classes/{class_id}/enabled")
def set_enabled(class_id: str, body: DisableIn, x_admin_secret: Optional[str] = Header(None)):
    _require_admin(x_admin_secret)
    if not body.enabled:
        with _conn() as c:
            c.execute("UPDATE gate_passwords SET revoked=1 WHERE revoked=0")
            c.execute("UPDATE gate SET code_hash='', code_hint='', code_plain='' WHERE id=1")
            c.execute("UPDATE sessions SET revoked=1 WHERE revoked=0 AND is_master=0")
        return {"ok": True, "message": "已清空学生口令并注销短密码会话"}
    return {"ok": True}


class ActivateIn(BaseModel):
    code: str
    student_label: str = ""
    student_id: str = ""
    device_id: str = ""


@app.post("/v1/activate")
def activate(body: ActivateIn):
    code = (body.code or "").strip()
    student = (body.student_id or body.student_label or "").strip()
    if not student:
        raise HTTPException(400, "请填写学号")
    if not code:
        raise HTTPException(400, "请填写本堂密码")
    device = (body.device_id or "").strip() or secrets.token_hex(8)
    gate = _get_gate()
    teacher_pwd = admin_secret()
    is_master = hmac.compare_digest(code, teacher_pwd)
    password_id = ""
    now = time.time()
    if not is_master:
        digest = _hash_code(code)
        with _conn() as c:
            active = _list_active_passwords(c)
            matched = next((r for r in active if r["code_hash"] == digest), None)
            if not matched and gate["code_hash"] and digest == gate["code_hash"]:
                # 兼容尚未迁完的旧单密码
                matched_legacy = True
            else:
                matched_legacy = False
            if not matched and not matched_legacy:
                if not active and not str(gate["code_hash"] or "").strip():
                    raise HTTPException(403, "教师尚未发布本堂密码")
                raise HTTPException(403, "本堂密码错误")
            if matched:
                password_id = str(matched["id"])
    days = int(gate["session_days"] or 0)
    # 本堂密码默认不过期：仅吊销口令 / 清空 / 教师注销会话时失效
    if days <= 0:
        expires = now + 100 * 365 * 86400
        days = 0
    else:
        expires = now + days * 86400
    gen = int(gate["generation"] or 1)
    token = issue_session_token(class_id="gate", student=student, device=device, expires_at=expires)
    payload = verify_session_token(token) or {}
    with _conn() as c:
        # 同一学号旧会话作废（避免列表重复）
        c.execute(
            "UPDATE sessions SET revoked=1 WHERE student_label=? AND revoked=0",
            (student,),
        )
        c.execute(
            """
            INSERT INTO sessions(token_id, class_id, student_label, device_id, issued_at, expires_at,
                                 revoked, generation, is_master, last_seen, password_id)
            VALUES(?,?,?,?,?,?,0,?,?,?,?)
            """,
            (
                payload.get("tid"),
                "gate",
                student,
                device,
                now,
                expires,
                0 if is_master else gen,
                1 if is_master else 0,
                now,
                "" if is_master else password_id,
            ),
        )
    return {
        "ok": True,
        "access_token": token,
        "expires_at": expires,
        "expires_at_iso": datetime.fromtimestamp(expires, tz=timezone.utc).isoformat(),
        "valid_days": days,
        "student_id": student,
        "is_master": is_master,
        "class_title": "DFTB 课堂",
        "server_time": datetime.now(timezone.utc).isoformat(),
        "message": "登录成功。"
        + (
            ""
            if is_master
            else "本堂密码不过期；教师吊销口令、清空或注销会话后需重新登录。"
        ),
    }


@app.get("/v1/session")
def session(authorization: Optional[str] = Header(None)):
    s = _require_session(authorization)
    return {
        "ok": True,
        "student_label": s["student_label"],
        "class_id": s["class_id"],
        "expires_at": s["expires_at"],
        "expires_at_iso": datetime.fromtimestamp(s["expires_at"], tz=timezone.utc).isoformat(),
        "server_time": datetime.now(timezone.utc).isoformat(),
        "llm_calls_today": _llm_count_today(s["token_id"]),
        "daily_llm_limit": s["daily_llm_limit"],
    }


class ChatIn(BaseModel):
    messages: list[dict[str, str]]
    temperature: float = 0.3


def _resolve_hub_llm() -> tuple[str, str, str]:
    prefer = (os.environ.get("DFTB_CLASS_LLM_PROVIDER") or "deepseek").strip().lower()
    ds_key = (os.environ.get("DFTB_CLASS_DEEPSEEK_API_KEY") or os.environ.get("CMATS_DEEPSEEK_API_KEY") or "").strip()
    ds_base = (os.environ.get("DFTB_CLASS_DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
    ds_model = (os.environ.get("DFTB_CLASS_DEEPSEEK_MODEL") or "deepseek-v4-flash").strip()
    qw_key = (os.environ.get("DFTB_CLASS_LLM_API_KEY") or os.environ.get("CMATS_LLM_API_KEY") or "").strip()
    qw_base = (
        os.environ.get("DFTB_CLASS_LLM_BASE_URL")
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ).rstrip("/")
    qw_model = (os.environ.get("DFTB_CLASS_LLM_MODEL") or "qwen3.7-plus").strip()
    if prefer == "qwen":
        if qw_key:
            return qw_key, qw_base, qw_model
        if ds_key:
            return ds_key, ds_base, ds_model
    else:
        if ds_key:
            return ds_key, ds_base, ds_model
        if qw_key:
            return qw_key, qw_base, qw_model
    raise HTTPException(503, "课堂中心未配置 LLM API Key")


def _chat_url(base: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/v1"):
        return base + "/chat/completions"
    if "deepseek.com" in base and not base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


@app.post("/v1/llm/chat")
async def llm_chat(body: ChatIn, authorization: Optional[str] = Header(None)):
    import httpx

    s = _require_session(authorization)
    if _llm_count_today(s["token_id"]) >= s["daily_llm_limit"]:
        raise HTTPException(429, f"今日 LLM 调用已达上限（{s['daily_llm_limit']}）")
    key, base, model = _resolve_hub_llm()
    url = _chat_url(base)
    payload = {"model": model, "messages": body.messages, "temperature": body.temperature}
    async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
        r = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
    if r.status_code >= 400:
        raise HTTPException(502, f"上游 LLM 失败 HTTP {r.status_code}: {(r.text or '')[:300]}")
    _bump_usage(s["token_id"], "llm")
    data = r.json()
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    return {"ok": True, "content": content, "model": model}


def _mp_key() -> str:
    return (os.environ.get("DFTB_CLASS_MP_API_KEY") or os.environ.get("CMATS_MP_API_KEY") or "").strip()


class MpIn(BaseModel):
    query: str = ""
    material_id: str = ""
    limit: int = 8


@app.post("/v1/mp/search")
def mp_search(body: MpIn, authorization: Optional[str] = Header(None)):
    import httpx

    s = _require_session(authorization)
    key = _mp_key()
    if not key:
        raise HTTPException(503, "课堂中心未配置 Materials Project Key")
    q = (body.query or "").strip()
    if not q:
        raise HTTPException(400, "化学式为空")
    with httpx.Client(timeout=45.0, trust_env=False) as client:
        r = client.get(
            "https://api.materialsproject.org/materials/summary/",
            params={
                "formula": q,
                "_limit": str(max(body.limit, 8)),
                "_fields": "material_id,formula_pretty,nsites,symmetry,energy_above_hull,is_stable",
            },
            headers={"X-API-KEY": key, "Accept": "application/json"},
        )
    if r.status_code >= 400:
        raise HTTPException(502, f"MP HTTP {r.status_code}: {r.text[:300]}")
    _bump_usage(s["token_id"], "mp")
    docs = (r.json().get("data") or r.json().get("results") or [])[: body.limit]
    return {
        "results": [
            {
                "material_id": d.get("material_id"),
                "formula": d.get("formula_pretty") or q,
                "nsites": d.get("nsites"),
                "energy_above_hull": d.get("energy_above_hull"),
                "is_stable": d.get("is_stable"),
            }
            for d in docs
        ]
    }


@app.post("/v1/mp/fetch")
def mp_fetch(body: MpIn, authorization: Optional[str] = Header(None)):
    import httpx

    s = _require_session(authorization)
    key = _mp_key()
    if not key:
        raise HTTPException(503, "课堂中心未配置 Materials Project Key")
    mid = (body.material_id or body.query or "").strip()
    if not mid:
        raise HTTPException(400, "缺少 material_id / query")
    with httpx.Client(timeout=45.0, trust_env=False) as client:
        if not (mid.lower().startswith("mp-") or mid.lower().startswith("mvc-")):
            r0 = client.get(
                "https://api.materialsproject.org/materials/summary/",
                params={
                    "formula": mid,
                    "_limit": "1",
                    "_fields": "material_id,formula_pretty,energy_above_hull,is_stable",
                },
                headers={"X-API-KEY": key, "Accept": "application/json"},
            )
            if r0.status_code >= 400:
                raise HTTPException(502, f"MP HTTP {r0.status_code}: {r0.text[:300]}")
            docs0 = r0.json().get("data") or r0.json().get("results") or []
            if not docs0:
                raise HTTPException(404, f"未找到 {mid}")
            mid = str(docs0[0].get("material_id") or "")
        r = client.get(
            "https://api.materialsproject.org/materials/summary/",
            params={
                "material_ids": mid,
                "_limit": "1",
                "_fields": "material_id,formula_pretty,structure,nsites",
            },
            headers={"X-API-KEY": key, "Accept": "application/json"},
        )
    if r.status_code >= 400:
        raise HTTPException(502, f"MP HTTP {r.status_code}: {r.text[:300]}")
    docs = r.json().get("data") or r.json().get("results") or []
    if not docs:
        raise HTTPException(404, f"未找到 {mid}")
    doc = docs[0]
    structure = doc.get("structure") or {}
    lattice = (structure.get("lattice") or {}).get("matrix")
    sites = structure.get("sites") or []
    if not lattice or not sites:
        raise HTTPException(502, "结构数据不完整")
    order: list[str] = []
    counts: dict[str, int] = {}
    coords: list[tuple[str, list[float]]] = []
    for site in sites:
        species = site.get("species") or []
        if not species:
            continue
        el = species[0].get("element") or "?"
        if el not in counts:
            order.append(el)
            counts[el] = 0
        counts[el] += 1
        abc = site.get("abc") or site.get("frac_coords")
        coords.append((el, [float(abc[0]), float(abc[1]), float(abc[2])]))
    formula = doc.get("formula_pretty") or mid
    lines = [
        f"{formula} ({mid}) via classroom hub",
        "1.0",
        f"{lattice[0][0]:.10f} {lattice[0][1]:.10f} {lattice[0][2]:.10f}",
        f"{lattice[1][0]:.10f} {lattice[1][1]:.10f} {lattice[1][2]:.10f}",
        f"{lattice[2][0]:.10f} {lattice[2][1]:.10f} {lattice[2][2]:.10f}",
        " ".join(order),
        " ".join(str(counts[e]) for e in order),
        "Direct",
    ]
    for el in order:
        for e, abc in coords:
            if e == el:
                lines.append(f"{abc[0]:.10f} {abc[1]:.10f} {abc[2]:.10f}")
    _bump_usage(s["token_id"], "mp")
    return {
        "material_id": mid,
        "formula": formula,
        "poscar": "\n".join(lines) + "\n",
        "nsites": doc.get("nsites"),
        "source": "classroom-hub",
    }
