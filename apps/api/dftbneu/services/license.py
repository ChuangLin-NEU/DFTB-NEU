"""课堂许可：激活、会话校验；经公网课堂中心（不依赖 Tailscale）。"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

import httpx

from ..config import load_user_config, save_user_config, settings


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
    import os

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
    base = hub_url()
    if not base:
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
    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            r = await client.post(f"{base}/v1/activate", json=payload)
    except httpx.TimeoutException:
        raise LicenseError(
            f"连接课堂中心超时（{base}）。请确认本机已连接 Tailscale/课题组网络后重试"
        ) from None
    except httpx.HTTPError as e:
        raise LicenseError(
            f"无法连接课堂中心（{base}）。请确认 Tailscale 已连接且课堂服务在线。详情：{e}"
        ) from None
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
    base = hub_url()
    token = access_token()
    if not base or not token:
        return {"ok": False, "mode": "locked", "message": "尚未登录"}

    cfg = load_user_config()
    try:
        async with httpx.AsyncClient(timeout=12.0, trust_env=False) as client:
            r = await client.get(
                f"{base}/v1/session",
                headers={"Authorization": f"Bearer {token}"},
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
    except LicenseError as e:
        return {
            "ok": False,
            "mode": "locked",
            "message": f"课堂许可校验失败：{e}"[:300],
            "license": public_license_status(),
        }
    except Exception as e:
        # 仅网络/超时等连接问题可走离线宽限
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
