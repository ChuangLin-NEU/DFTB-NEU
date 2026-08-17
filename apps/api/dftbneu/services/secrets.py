"""本机配置中的 API Key 保护存储。"""

from __future__ import annotations

import base64
import hashlib
import platform
from typing import Any, Optional

from ..config import load_user_config, save_user_config, settings


def _xor_obfuscate(raw: str, token: str) -> str:
    key = hashlib.sha256(token.encode()).digest()
    data = raw.encode("utf-8")
    out = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return base64.urlsafe_b64encode(out).decode("ascii")


def _xor_deobfuscate(blob: str, token: str) -> str:
    key = hashlib.sha256(token.encode()).digest()
    data = base64.urlsafe_b64decode(blob.encode("ascii"))
    out = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return out.decode("utf-8")


def _machine_token() -> str:
    return f"dftb-neu|{platform.node()}|{settings.store}"


def protect_secret(raw: str) -> dict[str, Optional[str]]:
    if platform.system() == "Windows":
        try:
            import win32crypt  # type: ignore

            encrypted = win32crypt.CryptProtectData(raw.encode("utf-8"), None, None, None, None, 0)
            return {"dpapi": base64.b64encode(encrypted[1]).decode("ascii"), "enc": None}
        except Exception:
            pass
    return {"enc": _xor_obfuscate(raw, _machine_token()), "dpapi": None}


def reveal_secret(enc: str = "", dpapi: str = "") -> str:
    if dpapi and platform.system() == "Windows":
        try:
            import win32crypt  # type: ignore

            raw = base64.b64decode(dpapi)
            return win32crypt.CryptUnprotectData(raw, None, None, None, 0)[1].decode("utf-8")
        except Exception:
            pass
    if enc:
        try:
            return _xor_deobfuscate(enc, _machine_token())
        except Exception:
            return ""
    return ""


def _key_from_cfg(cfg: dict, prefix: str, env_fallback: str = "") -> str:
    k = reveal_secret(cfg.get(f"{prefix}_enc") or "", cfg.get(f"{prefix}_dpapi") or "")
    if k:
        return k
    plain = cfg.get(prefix.replace("_api_key", "").replace("api_key", "api_key"))
    # 兼容字段名
    for alt in (prefix, prefix.replace("_api_key", "") + "_key"):
        if cfg.get(alt) and isinstance(cfg[alt], str) and not str(cfg[alt]).startswith("{"):
            # 跳过误存
            pass
    if prefix == "deepseek_api_key":
        if cfg.get("api_key"):
            return str(cfg["api_key"])
        return env_fallback
    if prefix == "llm_api_key":
        return env_fallback
    if prefix == "mp_api_key":
        return env_fallback
    return env_fallback


def reveal_deepseek_key(cfg: Optional[dict] = None) -> str:
    cfg = cfg if cfg is not None else load_user_config()
    k = reveal_secret(cfg.get("api_key_enc") or "", cfg.get("api_key_dpapi") or "")
    if k:
        return k
    if cfg.get("api_key"):
        return str(cfg["api_key"])
    return (settings.deepseek_api_key or "").strip()


def reveal_llm_key(cfg: Optional[dict] = None) -> str:
    cfg = cfg if cfg is not None else load_user_config()
    k = reveal_secret(cfg.get("llm_api_key_enc") or "", cfg.get("llm_api_key_dpapi") or "")
    if k:
        return k
    return (settings.llm_api_key or "").strip()


def reveal_mp_key(cfg: Optional[dict] = None) -> str:
    cfg = cfg if cfg is not None else load_user_config()
    k = reveal_secret(cfg.get("mp_api_key_enc") or "", cfg.get("mp_api_key_dpapi") or "")
    if k:
        return k
    return (settings.mp_api_key or "").strip()


# 兼容旧名
def reveal_api_key(cfg: Optional[dict] = None) -> str:
    return reveal_deepseek_key(cfg)


def save_llm_settings(
    *,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    llm_provider: str = "",
    llm_api_key: str = "",
    llm_base_url: str = "",
    llm_model: str = "",
    mp_api_key: str = "",
    wsl_distro: str = "",
) -> dict:
    cfg = load_user_config()
    if llm_provider:
        cfg["llm_provider"] = llm_provider.strip().lower()
    if base_url:
        cfg["deepseek_base_url"] = base_url.rstrip("/")
    if model:
        cfg["deepseek_model"] = model
    if llm_base_url:
        cfg["llm_base_url"] = llm_base_url.rstrip("/")
    if llm_model:
        cfg["llm_model"] = llm_model
    if wsl_distro:
        cfg["wsl_distro"] = wsl_distro
    if api_key:
        cfg.pop("api_key", None)
        packed = protect_secret(api_key)
        cfg["api_key_enc"] = packed["enc"]
        cfg["api_key_dpapi"] = packed["dpapi"]
    if llm_api_key:
        packed = protect_secret(llm_api_key)
        cfg["llm_api_key_enc"] = packed["enc"]
        cfg["llm_api_key_dpapi"] = packed["dpapi"]
    if mp_api_key:
        packed = protect_secret(mp_api_key)
        cfg["mp_api_key_enc"] = packed["enc"]
        cfg["mp_api_key_dpapi"] = packed["dpapi"]
    save_user_config(cfg)
    return public_settings()


def public_settings() -> dict[str, Any]:
    cfg = load_user_config()
    ds = reveal_deepseek_key(cfg)
    qwen = reveal_llm_key(cfg)
    mp = reveal_mp_key(cfg)
    provider = (cfg.get("llm_provider") or settings.llm_provider or "deepseek").strip().lower()

    def hint(k: str) -> str:
        if not k:
            return ""
        return (k[:4] + "…" + k[-4:]) if len(k) > 8 else "已设置"

    return {
        "llm_provider": provider,
        "deepseek_base_url": cfg.get("deepseek_base_url") or settings.deepseek_base_url,
        "deepseek_model": cfg.get("deepseek_model") or settings.deepseek_model,
        "api_key_set": bool(ds),
        "api_key_hint": hint(ds),
        "llm_base_url": cfg.get("llm_base_url") or settings.llm_base_url,
        "llm_model": cfg.get("llm_model") or settings.llm_model,
        "llm_api_key_set": bool(qwen),
        "llm_api_key_hint": hint(qwen),
        "mp_api_key_set": bool(mp),
        "mp_api_key_hint": hint(mp),
        "wsl_distro": cfg.get("wsl_distro") or settings.wsl_distro or "",
        "env_bootstrap": {
            "deepseek_from_env": bool((settings.deepseek_api_key or "").strip()),
            "llm_from_env": bool((settings.llm_api_key or "").strip()),
            "mp_from_env": bool((settings.mp_api_key or "").strip()),
        },
        "classroom_hub_url": cfg.get("classroom_hub_url") or settings.classroom_hub_url or "",
        "license_required": True if settings.license_required else (
            bool(cfg["license_required"]) if "license_required" in cfg else False
        ),
    }
