"""OpenAPI 兼容 LLM：DeepSeek / 通义 Qwen；缺钥自动回退。"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from ..config import load_user_config, settings
from .secrets import public_settings, reveal_deepseek_key, reveal_llm_key


class LLMError(RuntimeError):
    pass


# 兼容旧导入名
DeepSeekError = LLMError


def _chat_url(base: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/v1"):
        return base + "/chat/completions"
    if "deepseek.com" in base and not base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def resolve_endpoint() -> tuple[str, str, str, str]:
    """返回 (api_key, base_url, model, provider_label)。"""
    cfg = load_user_config()
    prefer = (cfg.get("llm_provider") or settings.llm_provider or "deepseek").strip().lower()

    deepseek = (
        reveal_deepseek_key(cfg),
        (cfg.get("deepseek_base_url") or settings.deepseek_base_url).rstrip("/"),
        (cfg.get("deepseek_model") or settings.deepseek_model).strip(),
        "deepseek",
    )
    qwen = (
        reveal_llm_key(cfg),
        (cfg.get("llm_base_url") or settings.llm_base_url).rstrip("/"),
        (cfg.get("llm_model") or settings.llm_model).strip(),
        "qwen",
    )

    if prefer == "qwen":
        if qwen[0]:
            return qwen
        if deepseek[0]:
            return deepseek
        return qwen
    # deepseek 优先
    if deepseek[0]:
        return deepseek
    if qwen[0]:
        return qwen
    return deepseek


def _client_cfg() -> tuple[str, str, str]:
    key, base, model, _ = resolve_endpoint()
    if not key:
        raise LLMError("未配置 LLM API Key。请在「设置」填写 DeepSeek API Key。")
    return base, model, key


def readiness() -> dict[str, Any]:
    """轻量就绪状态：不发起真实聊天，避免拖慢 /api/status。"""
    from . import license as lic

    if lic.use_hub_llm():
        token = bool(lic.access_token())
        return {
            "ok": token,
            "message": "将经课堂中心代理调用 LLM" if token else "已启用课堂代理，待登录后可用",
            "active_provider": "classroom_hub",
            "results": [
                {
                    "provider": "classroom_hub",
                    "ok": token,
                    "message": "代理已配置" if token else "尚未登录",
                }
            ],
            "settings": public_settings(),
        }
    key, _base, model, label = resolve_endpoint()
    ok = bool(key)
    return {
        "ok": ok,
        "message": f"{label} 已配置" if ok else "未配置 LLM API Key",
        "active_provider": label if ok else "",
        "results": [
            {
                "provider": label,
                "ok": ok,
                "message": f"模型 {model}" if ok else "未配置 Key",
            }
        ],
        "settings": public_settings(),
    }


async def probe(provider: str = "") -> dict[str, Any]:
    """探测当前或指定提供方。"""
    from . import license as lic

    if lic.use_hub_llm():
        try:
            content = await lic.hub_chat(
                [{"role": "user", "content": "回复一个字：好"}],
                temperature=0,
            )
            return {
                "ok": True,
                "message": "课堂中心 LLM 代理可用",
                "active_provider": "classroom_hub",
                "results": [{"provider": "classroom_hub", "ok": True, "message": "可用", "sample": content[:80]}],
                "settings": public_settings(),
            }
        except Exception as e:
            return {
                "ok": False,
                "message": f"课堂中心 LLM 不可用：{e}"[:300],
                "active_provider": "classroom_hub",
                "results": [{"provider": "classroom_hub", "ok": False, "message": str(e)[:240]}],
                "settings": public_settings(),
            }

    cfg = load_user_config()
    targets: list[tuple[str, str, str, str]] = []
    if provider in ("", "active", "auto"):
        try:
            key, base, model, label = resolve_endpoint()
            targets.append((key, base, model, label))
        except Exception:
            pass
    if provider in ("", "all", "deepseek") or (provider == "active" and not targets):
        targets.append(
            (
                reveal_deepseek_key(cfg),
                (cfg.get("deepseek_base_url") or settings.deepseek_base_url).rstrip("/"),
                (cfg.get("deepseek_model") or settings.deepseek_model).strip(),
                "deepseek",
            )
        )
    if provider in ("", "all", "qwen"):
        targets.append(
            (
                reveal_llm_key(cfg),
                (cfg.get("llm_base_url") or settings.llm_base_url).rstrip("/"),
                (cfg.get("llm_model") or settings.llm_model).strip(),
                "qwen",
            )
        )

    # 去重
    seen = set()
    uniq = []
    for t in targets:
        if t[3] in seen:
            continue
        seen.add(t[3])
        uniq.append(t)

    results = []
    for key, base, model, label in uniq:
        if not key:
            results.append({"provider": label, "ok": False, "message": "未配置 Key"})
            continue
        url = _chat_url(base)
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "回复一个字：好"}],
            "max_tokens": 8,
            "temperature": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
                r = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                )
            if r.status_code >= 400:
                results.append(
                    {"provider": label, "ok": False, "message": f"HTTP {r.status_code}：{(r.text or '')[:240]}"}
                )
            else:
                content = (((r.json().get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
                results.append({"provider": label, "ok": True, "message": "可用", "sample": content[:80], "model": model})
        except Exception as e:
            results.append({"provider": label, "ok": False, "message": f"网络或接口错误：{e}"[:240]})

    any_ok = any(x.get("ok") for x in results)
    active = resolve_endpoint()[3] if any_ok or reveal_deepseek_key() or reveal_llm_key() else ""
    return {
        "ok": any_ok,
        "message": "至少一个 LLM 接口可用" if any_ok else "LLM 接口不可用",
        "active_provider": active,
        "results": results,
        "settings": public_settings(),
    }


async def chat(messages: list[dict[str, str]], *, temperature: float = 0.3) -> str:
    from . import license as lic

    if lic.use_hub_llm():
        return await lic.hub_chat(messages, temperature=temperature)

    key, base, model, label = resolve_endpoint()
    if not key:
        raise LLMError("未配置 LLM API Key。请在「设置」填写 DeepSeek API Key。")
    url = _chat_url(base)
    payload = {"model": model, "messages": messages, "temperature": temperature}
    async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
        r = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
    if r.status_code >= 400:
        raise LLMError(f"{label} 调用失败 HTTP {r.status_code}：{(r.text or '')[:400]}")
    data = r.json()
    return str((((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or "")
