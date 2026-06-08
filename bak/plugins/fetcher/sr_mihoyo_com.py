"""
sr.mihoyo.com 官网抓取器
"""

import asyncio
import logging
from typing import List, Optional

from playwright.async_api import async_playwright, ProxySettings, Error

from core.models import NewsItem
from plugins.fetcher.base import FetcherPlugin
from core.plugin import PluginMetadata, PluginRegistry
from urllib.parse import urljoin

logger = logging.getLogger("fetcher.sr_mihoyo_com")

NEWS_ITEM_SELECTOR = '.news-list .list-wrap > a[href*="/news/"]'
LOAD_MORE_BUTTON_SELECTOR = ".btn-more-wrap"

# 配置常量
MAX_CLICK_COUNT = 300  # 最大点击次数
CLICK_TIMEOUT_SECONDS = 1000  # 点击"加载更多"总超时时间 (秒)
PAGE_LOAD_TIMEOUT = 30000  # 页面加载超时 (毫秒)
INITIAL_WAIT_TIMEOUT = 20000  # 初始等待新闻加载超时 (毫秒)


class SrMihoyoComFetcher(FetcherPlugin):
    """sr.mihoyo.com 官网新闻抓取器"""

    metadata = PluginMetadata(
        name="sr.mihoyo.com",
        version="1.0.0",
        description="sr.mihoyo.com 官网新闻抓取器",
    )

    async def fetch_news(self, headless: bool = True, **kwargs) -> List[NewsItem]:
        """
        从 sr.mihoyo.com 官网抓取新闻列表

        Args:
            headless: 是否使用无头模式

        Returns:
            新闻条目列表

        Raises:
            RuntimeError: 当浏览器崩溃或抓取失败时
        """
        news_url = urljoin(self.base_url, "/news?nav=news")
        proxy_config: Optional[ProxySettings] = None

        if self.proxy:
            proxy_config = ProxySettings(server=self.proxy)

        browser = None
        context = None
        page = None
        browser_crashed = False

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(
                    headless=headless,
                    args=["--disable-blink-features=AutomationControlled"],
                )

                context = await browser.new_context(proxy=proxy_config)
                page = await context.new_page()

                # 注册页面崩溃监听器
                def on_page_crash(page):
                    nonlocal browser_crashed
                    browser_crashed = True
                    logger.error("页面已崩溃！")

                page.on("crash", on_page_crash)

                # 注册页面错误监听器
                def on_page_error(error):
                    logger.warning("页面 JavaScript 错误：%s", error)

                page.on("pageerror", on_page_error)

                logger.info("正在访问新闻列表：%s", news_url)
                await page.goto(news_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)

                try:
                    await page.wait_for_selector(
                        NEWS_ITEM_SELECTOR, timeout=INITIAL_WAIT_TIMEOUT
                    )
                except Exception as e:
                    logger.error("超时未加载出任何新闻：%s", str(e))
                    return []

                initial_count = await page.locator(NEWS_ITEM_SELECTOR).count()
                logger.info("初始加载了 %d 条新闻", initial_count)

                # 检查"加载更多"按钮是否存在
                load_more_btn = page.locator(LOAD_MORE_BUTTON_SELECTOR).first
                btn_exists = await load_more_btn.count() > 0
                logger.info("'加载更多' 按钮存在：%s", btn_exists)

                if btn_exists:
                    click_count = 0
                    start_time = asyncio.get_event_loop().time()
                    click_error = None

                    try:
                        while click_count < MAX_CLICK_COUNT:
                            # 检查总超时
                            elapsed = asyncio.get_event_loop().time() - start_time
                            if elapsed > CLICK_TIMEOUT_SECONDS:
                                logger.warning(
                                    "点击'加载更多' 已超时 (%.1f 秒 > %d 秒)，停止点击",
                                    elapsed,
                                    CLICK_TIMEOUT_SECONDS,
                                )
                                break

                            # 检查页面是否崩溃
                            if browser_crashed:
                                logger.error("浏览器已崩溃，停止点击")
                                raise RuntimeError("浏览器页面已崩溃")

                            if not await load_more_btn.is_visible():
                                logger.info("'加载更多' 按钮不可见，停止点击")
                                break

                            click_count += 1
                            logger.info("第 %d 次点击'加载更多'...", click_count)
                            await load_more_btn.click()
                            await page.wait_for_timeout(1500)

                            # 检查是否有新内容加载
                            new_count = await page.locator(NEWS_ITEM_SELECTOR).count()
                            logger.info("当前新闻数：%d", new_count)

                    except Error as e:
                        # Playwright 原生异常（包括 Target crashed）
                        click_error = str(e)
                        logger.error("点击过程出现 Playwright 异常：%s，停止点击", click_error)
                        if "crash" in str(e).lower() or "target" in str(e).lower():
                            browser_crashed = True
                    except Exception as e:
                        # 其他异常
                        click_error = str(e)
                        logger.error("点击过程出现异常：%s，停止点击", click_error)

                    logger.info("共点击了 %d 次'加载更多'", click_count)

                    # 如果是因为浏览器崩溃而退出，抛出异常让上层知道
                    if browser_crashed:
                        raise RuntimeError(f"抓取过程中浏览器崩溃：{click_error}")
                else:
                    logger.warning("未找到'加载更多' 按钮，可能是网页结构变更")

                # 如果浏览器已崩溃，不要继续执行 page.evaluate
                if browser_crashed:
                    raise RuntimeError("浏览器已崩溃，无法提取新闻数据")

                # 提取新闻项
                js_code = r"""(selector) => {
                    const elements = document.querySelectorAll(selector);
                    const results = [];
                    for (const el of elements) {
                        const href = el.getAttribute('href');
                        if (!href) continue;

                        const titleNode = el.querySelector('.title');
                        let title = '';
                        if (titleNode) {
                            title = titleNode.innerText.trim();
                        } else {
                            const text = el.innerText || '';
                            const lines = text.split('\n')
                                .map(l => l.trim())
                                .filter(Boolean);
                            title = lines[0] || '';
                        }

                        if (title) {
                            results.push({ title, href });
                        }
                    }
                    return results;
                }"""

                items = await page.evaluate(js_code, NEWS_ITEM_SELECTOR)

                news_items = [
                    NewsItem(
                        title=item["title"],
                        url=urljoin(self.base_url, item["href"]),
                    )
                    for item in items
                    if item.get("title")
                ]

                # resume 模式：过滤已缓存的 URL
                if self.resume:
                    original_count = len(news_items)
                    news_items = [
                        item for item in news_items
                        if not self._is_url_cached(item.url)
                    ]
                    filtered_count = original_count - len(news_items)
                    if filtered_count > 0:
                        logger.info("跳过 %d 条已抓取的新闻 (resume 模式)", filtered_count)

                # 缓存新抓取的 URL
                for item in news_items:
                    self._add_to_cache(item.url)

                logger.info("共抓取 %d 条新闻", len(news_items))
                return news_items

            except RuntimeError as e:
                # 重新抛出运行时异常（包括浏览器崩溃）
                logger.error("抓取失败：%s", str(e))
                raise
            except Exception as e:
                # 捕获其他异常并记录
                logger.error("抓取过程中发生未预期异常：%s", str(e))
                raise
            finally:
                # 安全关闭资源，带超时保护
                await self._safe_cleanup(page, context, browser, browser_crashed)

    async def _safe_cleanup(
        self,
        page,
        context,
        browser,
        crashed: bool = False,
    ) -> None:
        """
        安全关闭 Playwright 资源，防止挂起

        Args:
            page: 页面对象
            context: 浏览器上下文
            browser: 浏览器实例
            crashed: 是否已崩溃
        """
        # 如果已崩溃，不需要清理
        if crashed:
            logger.info("浏览器已崩溃，跳过清理")
            return

        # 关闭 page
        if page is not None:
            try:
                await asyncio.wait_for(page.close(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning("关闭 page 超时")
            except Exception as e:
                logger.debug("关闭 page 时异常：%s", str(e))

        # 关闭 context
        if context is not None:
            try:
                await asyncio.wait_for(context.close(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning("关闭 context 超时")
            except Exception as e:
                logger.debug("关闭 context 时异常：%s", str(e))

        # 关闭 browser
        if browser is not None:
            try:
                await asyncio.wait_for(browser.close(), timeout=10)
                logger.info("浏览器已正常关闭")
            except asyncio.TimeoutError:
                logger.error("关闭 browser 超时，强制退出")
            except Exception as e:
                logger.error("关闭 browser 时异常：%s", str(e))


PluginRegistry.register("sr.mihoyo.com", SrMihoyoComFetcher)
