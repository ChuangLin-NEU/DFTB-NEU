"""课堂许可：激活、会话校验；经公网课堂中心（不依赖 Tailscale / 校园网）。"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import ssl
import struct
import time
import uuid
from typing import Any, Optional

import httpx

from ..config import load_user_config, save_user_config, settings

# 公网 Funnel 域名。系统 DNS 解析失败时改走公网 IP + SNI，不要求 Tailscale。
_FUNNEL_HOST = "desktop-ibhgp7g.tailcc9705.ts.net"
_FUNNEL_URL = f"https://{_FUNNEL_HOST}"
# 运营商 DNS 失效时的备用 A 记录（与 scripts/_probe_funnel_public.py 一致）
_FUNNEL_PUBLIC_IPS = ("103.84.155.153", "103.84.155.217")
_PUBLIC_DNS = ("223.5.5.5", "119.29.29.29")
# 先公网域名，再本机/内网；避免同学每次先卡 3 秒连 127.0.0.1
_HUB_FALLBACKS = (
    _FUNNEL_URL,
    "http://127.0.0.1:8791",
    "http://100.127.118.69:8791",
)
_HUB_TIMEOUT = httpx.Timeout(20.0, connect=3.0)


class LicenseError(RuntimeError):
    pass


def _friendly_hub_error(raw: str) -> str:
    """把中心返回的嵌套 JSON 收成一句可读中文。"""
    text = (raw or "").strip()
    if not text:
        return "登录失败，请核对学号与本堂密码"
    msg = text
    for _ in range(3):
        try:
            data = __import__("json").loads(msg)
        except Exception:
            break
        if isinstance(data, dict) and "detail" in data:
            msg = str(data.get("detail") or "")
            continue
        break
    msg = str(msg).strip().strip('"')
    if not msg:
        return "登录失败，请核对学号与本堂密码"
    if msg.startswith("登录失败"):
        return msg
    return f"登录失败：{msg}"


def _friendly_llm_proxy_error(status_code: int, raw: str) -> str:
    """课堂 LLM 代理失败时给短句，避免把上游 JSON 整段甩给同学。"""
    text = (raw or "").strip()
    low = text.lower()
    if (
        "arrearage" in low
        or "overdue" in low
        or "欠费" in text
        or "Access denied" in text
        or "good standing" in low
    ):
        return "课堂助教说明暂不可用（中心 LLM 账户异常/欠费），不影响生成本地 DFTB+ 输入与计算"
    if status_code in (401, 403):
        return "课堂助教说明暂不可用（许可或鉴权失败），不影响生成本地输入与计算"
    if status_code >= 500:
        return "课堂助教说明暂不可用（中心服务异常），不影响生成本地输入与计算"
    # 尝试抽出短 message
    msg = text
    for _ in range(3):
        try:
            data = __import__("json").loads(msg)
        except Exception:
            break
        if isinstance(data, dict):
            if "detail" in data:
                msg = str(data.get("detail") or "")
                continue
            err = data.get("error")
            if isinstance(err, dict) and err.get("message"):
                msg = str(err.get("message") or "")
                continue
        break
    short = str(msg).strip().replace("\n", " ")[:120]
    if short:
        return f"课堂助教说明暂不可用：{short}"
    return "课堂助教说明暂不可用，不影响生成本地 DFTB+ 输入与计算"


def hub_url() -> str:
    cfg = load_user_config()
    return (
        (cfg.get("classroom_hub_url") or settings.classroom_hub_url or "")
        .strip()
        .rstrip("/")
    )


def hub_candidates(preferred: str = "") -> list[str]:
    out: list[str] = []

    def add(url: str) -> None:
        u = (url or "").strip().rstrip("/")
        if u and u not in out:
            out.append(u)

    add(preferred)
    add(os.environ.get("DFTB_NEU_CLASSROOM_HUB_URL") or "")
    add(hub_url())
    for item in _HUB_FALLBACKS:
        add(item)
    return out


def _is_lan_or_loopback(url: str) -> bool:
    u = (url or "").lower()
    return "127.0.0.1" in u or "localhost" in u or "://100." in u


def _is_funnel_base(url: str) -> bool:
    return _FUNNEL_HOST in (url or "").lower()


def _skip_dns_name(data: bytes, offset: int) -> int:
    while offset < len(data):
        length = data[offset]
        if length == 0:
            return offset + 1
        if length & 0xC0 == 0xC0:
            return offset + 2
        offset += 1 + length
    return offset


def _dns_a_records(host: str, server: str, timeout: float = 2.0) -> list[str]:
    """向指定 DNS 查 A 记录，绕过本机/校园网解析失败。"""
    tid = secrets.randbelow(65536)
    q = struct.pack("!HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    for label in host.rstrip(".").split("."):
        raw = label.encode("ascii")
        q += bytes([len(raw)]) + raw
    q += b"\x00" + struct.pack("!HH", 1, 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(q, (server, 53))
        data, _ = sock.recvfrom(1024)
    except OSError:
        return []
    finally:
        sock.close()
    if len(data) < 12:
        return []
    rtid, _flags, qdcount, ancount, _ns, _ar = struct.unpack("!HHHHHH", data[:12])
    if rtid != tid or ancount <= 0:
        return []
    off = 12
    for _ in range(qdcount):
        off = _skip_dns_name(data, off) + 4
    ips: list[str] = []
    for _ in range(ancount):
        off = _skip_dns_name(data, off)
        if off + 10 > len(data):
            break
        rtype, _cls, _ttl, rdlen = struct.unpack("!HHIH", data[off : off + 10])
        off += 10
        if rtype == 1 and rdlen == 4 and off + 4 <= len(data):
            ips.append(socket.inet_ntoa(data[off : off + 4]))
        off += rdlen
    return ips


def _funnel_connect_ips() -> list[str]:
    ips: list[str] = []
    for dns in _PUBLIC_DNS:
        for ip in _dns_a_records(_FUNNEL_HOST, dns):
            if ip not in ips:
                ips.append(ip)
        if ips:
            break
    for ip in _FUNNEL_PUBLIC_IPS:
        if ip not in ips:
            ips.append(ip)
    return ips


class _SimpleResponse:
    def __init__(self, status_code: int, text: str, reason: str = ""):
        self.status_code = status_code
        self.text = text
        self.reason_phrase = reason

    def json(self) -> Any:
        return json.loads(self.text or "{}")


def _decode_chunked(data: bytes) -> bytes:
    out = bytearray()
    pos = 0
    while pos < len(data):
        nl = data.find(b"\r\n", pos)
        if nl < 0:
            break
        try:
            size = int(data[pos:nl].split(b";", 1)[0], 16)
        except ValueError:
            break
        pos = nl + 2
        if size == 0:
            break
        out.extend(data[pos : pos + size])
        pos += size + 2
    return bytes(out)


def _parse_http11(data: bytes) -> _SimpleResponse:
    head, sep, rest = data.partition(b"\r\n\r\n")
    if not sep:
        return _SimpleResponse(0, "", "empty")
    lines = head.split(b"\r\n")
    status = lines[0].decode("ascii", "replace").split(" ", 2)
    code = int(status[1]) if len(status) > 1 and status[1].isdigit() else 0
    reason = status[2] if len(status) > 2 else ""
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if b":" not in line:
            continue
        k, v = line.split(b":", 1)
        headers[k.decode("latin-1").lower()] = v.decode("latin-1").strip()
    if "chunked" in headers.get("transfer-encoding", "").lower():
        rest = _decode_chunked(rest)
    return _SimpleResponse(code, rest.decode("utf-8", "replace"), reason)


async def _https_ip_sni(
    method: str,
    ip: str,
    path: str,
    *,
    json_body: Optional[dict[str, Any]],
    headers: Optional[dict[str, str]],
    timeout: float,
) -> _SimpleResponse:
    """直连公网 IP:443，TLS SNI 用课堂中心域名，不走系统 DNS。"""
    payload = b""
    hdrs = {
        "Host": _FUNNEL_HOST,
        "Connection": "close",
        "Accept": "application/json",
        "User-Agent": "dftb-neu-student",
    }
    if headers:
        hdrs.update({k: v for k, v in headers.items() if k.lower() != "host"})
    if json_body is not None:
        payload = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
        hdrs["Content-Length"] = str(len(payload))
    req = f"{method.upper()} {path} HTTP/1.1\r\n"
    req += "".join(f"{k}: {v}\r\n" for k, v in hdrs.items())
    req += "\r\n"
    raw = req.encode("ascii") + payload
    ctx = ssl.create_default_context()
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(ip, 443, ssl=ctx, server_hostname=_FUNNEL_HOST, family=family),
        timeout=timeout,
    )
    try:
        writer.write(raw)
        await writer.drain()
        data = await asyncio.wait_for(reader.read(), timeout=timeout)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
    return _parse_http11(data)


async def _request_funnel_direct(
    method: str,
    path: str,
    *,
    json_body: Optional[dict[str, Any]],
    headers: Optional[dict[str, str]],
    timeout: float,
) -> _SimpleResponse:
    errors: list[str] = []
    for ip in _funnel_connect_ips():
        try:
            r = await _https_ip_sni(
                method, ip, path, json_body=json_body, headers=headers, timeout=timeout
            )
            if r.status_code:
                return r
            errors.append(f"{ip}：空响应")
        except Exception as e:
            errors.append(f"{ip}：{e}")
    raise OSError("；".join(errors[:4]) or "公网 IP 均不可达")


def _timeout_seconds(timeout: httpx.Timeout | float) -> float:
    if isinstance(timeout, (int, float)):
        return float(timeout)
    try:
        return float(timeout.connect or timeout.read or 12.0)
    except Exception:
        return 12.0


async def _httpx_call(
    method: str,
    url: str,
    *,
    json: Optional[dict[str, Any]],
    headers: Optional[dict[str, str]],
    timeout: httpx.Timeout | float,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        return await client.request(method, url, json=json, headers=headers)


def _maybe_save_hub(base: str) -> None:
    if base != hub_url() and not _is_lan_or_loopback(base):
        save_hub_settings(hub_url_value=base)


async def _hub_request(
    method: str,
    path: str,
    *,
    json: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    timeout: httpx.Timeout | float = _HUB_TIMEOUT,
) -> tuple[str, httpx.Response]:
    """按候选地址请求课堂中心。域名解析失败时走公网 IP + SNI。"""
    errors: list[str] = []
    last_base = ""
    tried_funnel_ip = False
    for base in hub_candidates():
        last_base = base
        try:
            r = await _httpx_call(method, f"{base}{path}", json=json, headers=headers, timeout=timeout)
            if r.status_code < 500:
                _maybe_save_hub(base)
                return base, r
            errors.append(f"{base}：HTTP {r.status_code}")
        except (httpx.TimeoutException, httpx.HTTPError, OSError) as e:
            errors.append(f"{base}：{e}")
            if _is_funnel_base(base) and not tried_funnel_ip:
                tried_funnel_ip = True
                try:
                    r = await _request_funnel_direct(
                        method,
                        path,
                        json_body=json,
                        headers=headers,
                        timeout=_timeout_seconds(timeout),
                    )
                    if r.status_code < 500:
                        _maybe_save_hub(_FUNNEL_URL)
                        return _FUNNEL_URL, r
                    errors.append(f"{_FUNNEL_URL}(公网直连)：HTTP {r.status_code}")
                except (httpx.TimeoutException, httpx.HTTPError, OSError) as e2:
                    errors.append(f"{_FUNNEL_URL}(公网直连)：{e2}")
    if not tried_funnel_ip:
        try:
            r = await _request_funnel_direct(
                method,
                path,
                json_body=json,
                headers=headers,
                timeout=_timeout_seconds(timeout),
            )
            if r.status_code < 500:
                _maybe_save_hub(_FUNNEL_URL)
                return _FUNNEL_URL, r
            errors.append(f"{_FUNNEL_URL}(公网直连)：HTTP {r.status_code}")
        except (httpx.TimeoutException, httpx.HTTPError, OSError) as e:
            errors.append(f"{_FUNNEL_URL}(公网直连)：{e}")
    detail = "；".join(errors[:5]) if errors else "无可用地址"
    raise LicenseError(
        f"无法连接课堂中心。请确认本机已联网且课堂服务在线后重试。详情：{detail}"
    )


def license_required() -> bool:
    """默认强制登录；打包默认 True 时不可被本地配置关掉。"""
    if settings.license_required:
        return True
    cfg = load_user_config()
    if "license_required" in cfg:
        return bool(cfg.get("license_required"))
    return False


def use_hub_proxy() -> bool:
    """已激活且配置了中心时，可用于中心代理（结构 MP 等）。"""
    cfg = load_user_config()
    if cfg.get("use_hub_proxy") is False:
        return False
    return bool(hub_url() and access_token())


def use_hub_llm() -> bool:
    """LLM 是否走课堂中心。

    学生端默认否：DeepSeek 仅用本机「设置」中的 Key。
    开发机可用环境变量 DFTB_NEU_HUB_LLM_PROXY=1 临时打开中心 LLM。
    """
    flag = (os.environ.get("DFTB_NEU_HUB_LLM_PROXY") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return use_hub_proxy()
    return False


def access_token() -> str:
    cfg = load_user_config()
    return str(cfg.get("classroom_access_token") or "").strip()


def device_id() -> str:
    cfg = load_user_config()
    did = str(cfg.get("device_id") or "").strip()
    if did:
        return did
    did = uuid.uuid4().hex
    cfg["device_id"] = did
    save_user_config(cfg)
    return did


def save_hub_settings(*, hub_url_value: str = "", license_required_value: Optional[bool] = None) -> None:
    cfg = load_user_config()
    if hub_url_value:
        cfg["classroom_hub_url"] = hub_url_value.rstrip("/")
    # 默认强制登录时忽略关闭请求
    if license_required_value is not None and not settings.license_required:
        cfg["license_required"] = bool(license_required_value)
    save_user_config(cfg)


def clear_session() -> None:
    cfg = load_user_config()
    cfg.pop("classroom_access_token", None)
    cfg.pop("classroom_expires_at", None)
    cfg.pop("classroom_title", None)
    save_user_config(cfg)


def public_license_status() -> dict[str, Any]:
    cfg = load_user_config()
    exp = float(cfg.get("classroom_expires_at") or 0)
    token = access_token()
    alive = bool(token) and (not exp or exp > time.time())
    return {
        "license_required": license_required(),
        "hub_url": hub_url(),
        "activated": alive,
        "expires_at": exp or None,
        "expires_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exp)) if exp else "",
        "class_title": cfg.get("classroom_title") or "",
        "use_hub_proxy": use_hub_proxy(),
        "use_hub_llm": use_hub_llm(),
        "offline_grace_hours": settings.license_offline_grace_hours,
        "last_ok_at": cfg.get("classroom_last_ok_at"),
    }


async def activate(*, code: str, student_label: str = "", student_id: str = "", hub: str = "") -> dict[str, Any]:
    if hub:
        save_hub_settings(hub_url_value=hub)
    if not hub_candidates():
        raise LicenseError("未配置课堂服务地址，请联系教师或维护人员")
    sid = (student_id or student_label or "").strip()
    if not sid:
        raise LicenseError("请填写学号")
    if not (code or "").strip():
        raise LicenseError("请填写本堂密码")
    payload = {
        "code": code.strip(),
        "student_id": sid,
        "student_label": sid,
        "device_id": device_id(),
    }
    _used, r = await _hub_request("POST", "/v1/activate", json=payload)
    if r.status_code >= 400:
        raise LicenseError(_friendly_hub_error(r.text or r.reason_phrase or "登录失败"))
    try:
        data = r.json()
    except Exception as e:
        raise LicenseError(f"课堂中心返回异常数据：{e}") from None
    if not data.get("access_token"):
        raise LicenseError("课堂中心未返回访问令牌，请联系教师检查服务")
    cfg = load_user_config()
    cfg["classroom_access_token"] = data.get("access_token")
    cfg["classroom_expires_at"] = data.get("expires_at")
    cfg["classroom_title"] = data.get("class_title") or ""
    cfg["student_id"] = sid
    cfg["classroom_last_ok_at"] = time.time()
    cfg["license_required"] = True
    save_user_config(cfg)
    return data


async def check_session(*, allow_offline_grace: bool = True) -> dict[str, Any]:
    """向中心校验；失败时若在离线宽限内可临时放行（仅本地计算）。"""
    if not license_required():
        return {"ok": True, "mode": "open", "message": "未启用课堂许可（开发模式）"}
    token = access_token()
    if not token:
        return {"ok": False, "mode": "locked", "message": "尚未登录"}

    cfg = load_user_config()
    try:
        _used, r = await _hub_request(
            "GET",
            "/v1/session",
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(12.0, connect=3.0),
        )
        # 中心明确拒绝（吊销/结课/过期）：不得走离线宽限
        if r.status_code in (401, 403):
            clear_session()
            return {
                "ok": False,
                "mode": "locked",
                "message": "课堂许可已失效，请重新登录（会话可能已被注销或本堂已结束）",
                "license": public_license_status(),
            }
        if r.status_code >= 400:
            raise LicenseError((r.text or "")[:200])
        data = r.json()
        cfg["classroom_expires_at"] = data.get("expires_at")
        cfg["classroom_last_ok_at"] = time.time()
        save_user_config(cfg)
        return {
            "ok": True,
            "mode": "online",
            "message": "课堂许可有效",
            "session": data,
            "license": public_license_status(),
        }
    except (LicenseError, Exception) as e:
        # 连不上中心（含 DNS 失败）不当成已注销，有令牌则走离线宽限
        last = float(cfg.get("classroom_last_ok_at") or 0)
        grace = float(settings.license_offline_grace_hours or 0) * 3600
        local_exp = float(cfg.get("classroom_expires_at") or 0)
        now = time.time()
        if allow_offline_grace and last and grace and (now - last) <= grace and local_exp > now:
            return {
                "ok": True,
                "mode": "offline_grace",
                "message": f"暂时无法连接课堂中心，离线宽限内可继续本地计算（{e}）"[:240],
                "license": public_license_status(),
            }
        return {
            "ok": False,
            "mode": "locked",
            "message": f"课堂许可校验失败：{e}"[:300],
            "license": public_license_status(),
        }


async def hub_chat(messages: list[dict[str, str]], *, temperature: float = 0.3) -> str:
    base = hub_url()
    token = access_token()
    if not base or not token:
        raise LicenseError("未激活课堂许可，无法使用中心 LLM")
    async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
        r = await client.post(
            f"{base}/v1/llm/chat",
            json={"messages": messages, "temperature": temperature},
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code >= 400:
        raise LicenseError(_friendly_llm_proxy_error(r.status_code, r.text or ""))
    return str((r.json() or {}).get("content") or "")


async def hub_mp_search(query: str, limit: int = 8) -> list[dict]:
    base = hub_url()
    token = access_token()
    async with httpx.AsyncClient(timeout=45.0, trust_env=False) as client:
        r = await client.post(
            f"{base}/v1/mp/search",
            json={"query": query, "limit": limit},
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code >= 400:
        raise LicenseError(f"MP 代理失败：{(r.text or '')[:300]}")
    return list((r.json() or {}).get("results") or [])


async def hub_mp_fetch(query: str, material_id: str = "") -> dict:
    base = hub_url()
    token = access_token()
    async with httpx.AsyncClient(timeout=45.0, trust_env=False) as client:
        r = await client.post(
            f"{base}/v1/mp/fetch",
            json={"query": query, "material_id": material_id},
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code >= 400:
        raise LicenseError(f"MP 代理失败：{(r.text or '')[:300]}")
    return r.json()


def hub_mp_search_sync(query: str, limit: int = 8) -> list[dict]:
    base = hub_url()
    token = access_token()
    with httpx.Client(timeout=45.0, trust_env=False) as client:
        r = client.post(
            f"{base}/v1/mp/search",
            json={"query": query, "limit": limit},
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code >= 400:
        raise LicenseError(f"MP 代理失败：{(r.text or '')[:300]}")
    return list((r.json() or {}).get("results") or [])


def hub_mp_fetch_sync(query: str, material_id: str = "") -> dict:
    base = hub_url()
    token = access_token()
    with httpx.Client(timeout=45.0, trust_env=False) as client:
        r = client.post(
            f"{base}/v1/mp/fetch",
            json={"query": query, "material_id": material_id},
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code >= 400:
        raise LicenseError(f"MP 代理失败：{(r.text or '')[:300]}")
    return r.json()


async def teacher_set_gate(
    *,
    teacher_password: str,
    student_password: str,
    hub: str = "",
    session_days: int = 30,
) -> dict[str, Any]:
    if hub:
        save_hub_settings(hub_url_value=hub)
    base = hub_url()
    if not base:
        raise LicenseError("未配置课堂中心地址")
    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        r = await client.post(
            f"{base}/teacher/gate",
            json={
                "student_password": student_password.strip(),
                "session_days": session_days,
            },
            headers={"X-Teacher-Password": teacher_password.strip()},
        )
    if r.status_code >= 400:
        raise LicenseError(f"设置失败：{(r.text or '')[:300]}")
    return r.json()


async def teacher_get_gate(*, teacher_password: str, hub: str = "") -> dict[str, Any]:
    if hub:
        save_hub_settings(hub_url_value=hub)
    base = hub_url()
    if not base:
        raise LicenseError("未配置课堂中心地址")
    async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
        r = await client.get(
            f"{base}/teacher/gate",
            headers={"X-Teacher-Password": teacher_password.strip()},
        )
    if r.status_code >= 400:
        raise LicenseError(f"查询失败：{(r.text or '')[:300]}")
    return r.json()
