"""
插件基类定义
"""

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, Optional, Type
from dataclasses import dataclass, field


@dataclass
class PluginMetadata:
    """插件元数据"""

    name: str
    version: str
    description: str = ""
    author: str = ""


class Plugin(ABC):
    """插件基类"""

    metadata: ClassVar[PluginMetadata]

    @abstractmethod
    async def execute(self, data: Any, **kwargs: Any) -> Any:
        """执行插件逻辑"""
        pass

    def validate(self) -> bool:
        """验证插件配置"""
        return True


class PluginRegistry:
    """插件注册表"""

    _plugins: ClassVar[Dict[str, Type[Plugin]]] = {}

    @classmethod
    def register(cls, name: str, plugin_class: Type[Plugin]) -> None:
        """注册插件"""
        cls._plugins[name] = plugin_class

    @classmethod
    def get(cls, name: str) -> Optional[Type[Plugin]]:
        """获取插件类"""
        return cls._plugins.get(name)

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> Plugin:
        """创建插件实例"""
        plugin_class = cls._plugins.get(name)
        if plugin_class is None:
            raise ValueError(f"Plugin '{name}' not found")
        return plugin_class(**kwargs)

    @classmethod
    def list_plugins(cls) -> list[str]:
        """列出所有已注册的插件"""
        return list(cls._plugins.keys())

    @classmethod
    def has_plugin(cls, name: str) -> bool:
        """检查插件是否已注册"""
        return name in cls._plugins

    @classmethod
    def unregister(cls, name: str) -> bool:
        """注销插件"""
        if name in cls._plugins:
            del cls._plugins[name]
            return True
        return False
