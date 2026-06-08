"""
日志配置
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class FlushOnExitHandler(logging.Handler):
    """在程序退出时刷新日志的处理器"""
    
    def emit(self, record):
        try:
            self.flush()
        except Exception:
            pass


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    log_dir: str = "logs",
) -> logging.Logger:
    """
    配置日志

    Args:
        log_level: 日志级别
        log_file: 日志文件路径（可选，如不提供则自动生成）
        log_dir: 日志目录

    Returns:
        配置好的 logger 对象
    """
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 确定日志文件路径
    if log_file:
        log_path = Path(log_file)
    else:
        # 自动生成带时间戳的日志文件名
        log_dir_path = Path(log_dir)
        log_dir_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = log_dir_path / f"run_{timestamp}.log"

    log_path.parent.mkdir(parents=True, exist_ok=True)

    # 文件处理器
    file_handler = logging.FileHandler(log_path, encoding="utf-8", mode="w")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 记录日志文件路径（使用 root logger 直接记录）
    logging.info("日志文件：%s", log_path)
    
    return logging.getLogger(__name__)


def shutdown_logging():
    """
    关闭日志系统，确保所有日志已刷新到文件
    """
    logging.shutdown()
