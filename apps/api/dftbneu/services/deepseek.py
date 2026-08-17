"""兼容旧导入：转发到 llm。"""

from .llm import DeepSeekError, LLMError, chat, probe, resolve_endpoint

__all__ = ["DeepSeekError", "LLMError", "chat", "probe", "resolve_endpoint"]
