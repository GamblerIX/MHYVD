"""
WebsitesVideosAutoDownloader - 网站视频自动下载工具

统一入口：执行完整流水线（抓取 → 分类 → 下载）
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Optional

from core.pipeline import Pipeline
from config.settings import Config
from utils.logging_config import setup_logging, shutdown_logging

logger = None  # 在 setup_logging 后初始化


# 全局 pipeline 引用，用于信号处理
_pipeline: Optional[Pipeline] = None
_shutdown_requested = False


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="网站视频自动下载工具"
    )
    parser.add_argument("--config", "-c", type=str, help="配置文件路径")
    parser.add_argument(
        "--proxy", "-p",
        type=str,
        help="代理服务器地址（如 http://127.0.0.1:10808）"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="使用无头模式运行浏览器（默认：True）"
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="不使用无头模式（显示浏览器窗口）"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        help="限制下载数量（用于测试）"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别"
    )
    parser.add_argument("--log-file", type=str, help="日志文件路径")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="断点续传模式：跳过已抓取和已下载的内容"
    )
    return parser.parse_args()


def signal_handler(signum, frame):
    """信号处理函数"""
    global _shutdown_requested
    _shutdown_requested = True
    
    # 确保日志已刷新
    shutdown_logging()
    
    print("\n收到中断信号，正在停止...")

    # 通知 pipeline 关闭
    if _pipeline:
        if hasattr(_pipeline, 'downloader') and _pipeline.downloader:
            if hasattr(_pipeline.downloader, 'request_shutdown'):
                _pipeline.downloader.request_shutdown()


def is_shutdown_requested() -> bool:
    """检查是否已请求关闭"""
    return _shutdown_requested


async def run_with_timeout(coro, timeout_seconds: int = 300) -> None:
    """
    带超时保护的异步任务执行
    
    Args:
        coro: 要执行的协程
        timeout_seconds: 超时时间（秒）
    
    Raises:
        asyncio.TimeoutError: 当任务超时时
    """
    try:
        await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        raise asyncio.TimeoutError(f"任务执行超时 {timeout_seconds} 秒")


def main() -> None:
    """主函数"""
    global _pipeline, logger

    args = parse_args()

    log_file = args.log_file or None
    setup_logging(log_level=args.log_level, log_file=log_file)
    logger = logging.getLogger("main")
    logger.info("程序启动")
    logger.debug("启动参数：%s", args)

    try:
        config = Config(args.config) if args.config else Config()
    except Exception as e:
        logger.exception("配置加载失败：%s", str(e))
        print(f"配置加载失败：{e}")
        sys.exit(1)

    if args.proxy:
        import os
        os.environ["HTTP_PROXY"] = args.proxy
        os.environ["HTTPS_PROXY"] = args.proxy
        logger.info("已设置代理：%s", args.proxy)

    headless = not args.no_headless

    try:
        _pipeline = Pipeline(config, resume=args.resume)
    except Exception as e:
        logger.exception("流水线初始化失败：%s", str(e))
        print(f"流水线初始化失败：{e}")
        sys.exit(1)

    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 配置总超时时间（秒）
    pipeline_timeout = 600  # 10 分钟

    try:
        # 使用 asyncio.run 执行主协程，带超时保护
        result = asyncio.run(
            run_with_timeout(_pipeline.run(headless=headless), pipeline_timeout)
        )

        if result.news_count == 0:
            logger.warning("未抓取到任何新闻")
            print("未抓取到任何新闻，请检查网络连接或代理设置")
            sys.exit(1)

        logger.info("程序执行完成")

    except asyncio.TimeoutError as e:
        logger.error(str(e))
        print(f"执行超时，程序终止")
        sys.exit(124)
    except KeyboardInterrupt:
        logger.info("用户中断")
        print("\n已终止")
        sys.exit(130)
    except RuntimeError as e:
        logger.error("运行时错误：%s", str(e))
        print(f"执行失败：{e}")
        sys.exit(1)
    except Exception as e:
        logger.exception("未预期的异常")
        print(f"执行失败：{e}")
        sys.exit(1)
    finally:
        # 清理全局状态
        _pipeline = None
        # 确保日志已刷新到文件
        shutdown_logging()


if __name__ == "__main__":
    main()
