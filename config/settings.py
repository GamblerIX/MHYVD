"""
配置管理模块
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any, Union

import yaml

ROOT_DIR = Path(__file__).parent.parent


class Config:
    """配置类"""

    DEFAULT_CONFIG: Dict[str, Any] = {
        "project_name": "WebsitesVideosAutoDownloader",
        "log_level": "INFO",
        "fetcher": {
            "plugin": "mihoyo",
            "base_url": "https://sr.mihoyo.com",
            "news_path": "/news?nav=news",
        },
        "classifier": {"plugin": "rule_based"},
        "downloader": {
            "plugin": "playwright",
            "output_dir": "downloads",
            "max_concurrent": 1,
            "retry_count": 3,
            "timeout": 60,
        },
    }

    def __init__(self, config_path: Optional[Union[str, Path]] = None):
        if config_path is None:
            self.config_path = ROOT_DIR / "config" / "default.yaml"
        else:
            self.config_path = Path(config_path)
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        if not self.config_path.exists():
            return self.DEFAULT_CONFIG.copy()

        with self.config_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or self.DEFAULT_CONFIG.copy()

    def get_proxy(self) -> Optional[str]:
        """
        获取代理设置，优先级：
        1. 环境变量 HTTP_PROXY/HTTPS_PROXY
        2. Windows 系统代理（自动检测）
        3. 返回 None（不使用代理）
        """
        http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        proxy_server = https_proxy or http_proxy

        if proxy_server:
            return proxy_server

        if os.name == "nt":
            try:
                import winreg

                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                ) as key:
                    proxy_enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                    if proxy_enabled:
                        proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
                        if proxy_server and not proxy_server.startswith(
                            ("http://", "https://")
                        ):
                            proxy_server = f"http://{proxy_server}"
                        return proxy_server
            except (ImportError, OSError, FileNotFoundError):
                pass

        return None

    def __getitem__(self, key: str) -> Any:
        return self._config.get(key)

    def __getattr__(self, name: str) -> Any:
        if name in self._config:
            return self._config[name]
        raise AttributeError(f"'Config' object has no attribute '{name}'")

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        return self._config.get(key, default)
