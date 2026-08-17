"""dftb-neu 配置与数据目录。测试版可从环境变量 / 并列 cmats-lab .env 读取密钥。"""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


def default_data_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "dftb-neu"
    return Path.home() / ".dftb-neu"


def _repo_root() -> Path:
    """仓库根，或安装包 resources 根（含 api / engines / web / templates）。"""
    env_root = os.environ.get("DFTB_NEU_ROOT", "").strip()
    if env_root:
        p = Path(env_root)
        if p.is_dir():
            return p
    here = Path(__file__).resolve()
    # 打包：resources/api/dftbneu/config.py → resources
    packaged = here.parents[2]
    if (packaged / "api").is_dir() and (packaged / "engines").is_dir():
        return packaged
    # 开发：apps/api/dftbneu/config.py → 仓库根
    return here.parents[3]


def _load_dotenv_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k:
                out[k] = v
    except Exception:
        return {}
    return out


def bootstrap_env_files() -> None:
    """把仓库 .env 与并列 cmats-lab/.env 中的键注入 os.environ（不覆盖已有）。

    分发策略：DeepSeek/通义 Key 不从并列 cmats-lab 自动导入（由本机设置页配置）；
    Materials Project Key 可从 cmats-lab/.env 导入，便于结构拉取。
    """
    root = _repo_root()
    files = [root / ".env"]
    sibling = root.parent / "cmats-lab" / ".env"
    if sibling.is_file():
        files.append(sibling)
    # 映射 CMATS_* → DFTB_NEU_*（仅当后者未设置）
    alias = {
        "CMATS_DEEPSEEK_API_KEY": "DFTB_NEU_DEEPSEEK_API_KEY",
        "CMATS_DEEPSEEK_BASE_URL": "DFTB_NEU_DEEPSEEK_BASE_URL",
        "CMATS_DEEPSEEK_MODEL": "DFTB_NEU_DEEPSEEK_MODEL",
        "CMATS_LLM_API_KEY": "DFTB_NEU_LLM_API_KEY",
        "CMATS_LLM_BASE_URL": "DFTB_NEU_LLM_BASE_URL",
        "CMATS_LLM_MODEL": "DFTB_NEU_LLM_MODEL",
        "CMATS_LLM_PROVIDER": "DFTB_NEU_LLM_PROVIDER",
        "CMATS_MP_API_KEY": "DFTB_NEU_MP_API_KEY",
    }
    # 并列实验室 .env 仅允许导入 MP / 非密钥类；禁止带入 LLM Key
    sibling_allow = {
        "CMATS_MP_API_KEY",
        "DFTB_NEU_MP_API_KEY",
        "CMATS_DEEPSEEK_BASE_URL",
        "CMATS_DEEPSEEK_MODEL",
        "CMATS_LLM_BASE_URL",
        "CMATS_LLM_MODEL",
        "CMATS_LLM_PROVIDER",
        "DFTB_NEU_DEEPSEEK_BASE_URL",
        "DFTB_NEU_DEEPSEEK_MODEL",
        "DFTB_NEU_LLM_BASE_URL",
        "DFTB_NEU_LLM_MODEL",
        "DFTB_NEU_LLM_PROVIDER",
        "DFTB_NEU_CLASSROOM_HUB_URL",
        "DFTB_NEU_LICENSE_REQUIRED",
        "DFTB_NEU_HOST",
        "DFTB_NEU_PORT",
    }
    sibling_deny_substrings = ("API_KEY", "SECRET", "TOKEN", "PASSWORD")
    for path in files:
        data = _load_dotenv_file(path)
        is_sibling = path.resolve() == sibling.resolve() if sibling.is_file() else False
        for k, v in data.items():
            if not v:
                continue
            if is_sibling:
                if k not in sibling_allow and any(s in k.upper() for s in sibling_deny_substrings):
                    continue
                if "DEEPSEEK_API_KEY" in k.upper() or "LLM_API_KEY" in k.upper():
                    continue
            if k not in os.environ:
                os.environ[k] = v
            mapped = alias.get(k)
            if mapped and mapped not in os.environ:
                if is_sibling and (
                    "DEEPSEEK_API_KEY" in mapped.upper() or "LLM_API_KEY" in mapped.upper()
                ):
                    continue
                os.environ[mapped] = v


bootstrap_env_files()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DFTB_NEU_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8765
    data_dir: str = ""
    wsl_distro: str = ""

    # DeepSeek（Key 仅来自本机设置页 / 本机环境变量；默认不走课堂中心）
    llm_provider: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    llm_api_key: str = ""
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen3.7-plus"

    # Materials Project（结构拉取；登录后可经课堂中心代理，或本机 MP Key）
    mp_api_key: str = ""

    # 课堂中心：默认指向课堂服务；可用环境变量覆盖
    classroom_hub_url: str = "https://desktop-ibhgp7g.tailcc9705.ts.net"
    license_required: bool = True
    license_offline_grace_hours: float = 12.0

    @property
    def root(self) -> Path:
        return _repo_root()

    @property
    def store(self) -> Path:
        p = Path(self.data_dir) if self.data_dir else default_data_dir()
        p.mkdir(parents=True, exist_ok=True)
        (p / "projects").mkdir(exist_ok=True)
        (p / "jobs").mkdir(exist_ok=True)
        return p

    @property
    def config_path(self) -> Path:
        return self.store / "config.json"

    @property
    def templates_dir(self) -> Path:
        return self.root / "templates"


settings = Settings()


def load_user_config() -> dict[str, Any]:
    path = settings.config_path
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_user_config(data: dict[str, Any]) -> None:
    path = settings.config_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
