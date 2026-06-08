# MHYVD - MihoyoVideosDownloader

Mihoyo网站视频自动下载工具。自动从网站抓取视频列表，支持分类筛选与视频批量下载。

> 由于米哈游当前对爬虫审查不严，可以通过Github Actions无头自动抓取。

## 环境要求

- Python 3.10+
- [Playwright](https://playwright.dev/python/)

```bash
pip install playwright
playwright install chromium
```

## 快速开始

```bash
python main.py
```

运行后将执行以下流水线：

1. **抓取** — 打开官网新闻页，自动加载全部新闻
2. **分类** — 按标题关键词将新闻分类到不同目录
3. **下载** — 解析新闻页面并下载视频文件

## 项目结构

```
WebsitesVideosAutoDownloader/
├── main.py              # 统一入口
├── core/
│   ├── pipeline.py      # 流水线管理
│   ├── models.py        # 数据模型定义
│   └── plugin.py        # 插件基类与注册表
├── config/
│   ├── settings.py      # 配置管理
│   └── default.yaml     # 默认配置
├── plugins/
│   ├── fetcher/         # 抓取器插件
│   ├── classifier/      # 分类器插件
│   └── downloader/      # 下载器插件
└── utils/
    └── logging_config.py # 日志配置
```

## 命令行参数

| 参数 | 说明 |
|------|------|
| `--config`, `-c` | 配置文件路径 |
| `--proxy`, `-p` | 代理服务器地址 |
| `--headless` | 使用无头模式（默认） |
| `--no-headless` | 显示浏览器窗口 |
| `--limit`, `-l` | 限制下载数量（测试用） |
| `--log-level` | 日志级别 (DEBUG/INFO/WARNING/ERROR) |
| `--log-file` | 日志文件路径 |
| `--resume` | 断点续传模式：跳过已抓取和已下载的内容 |

## 配置说明

编辑 `config/default.yaml` 自定义配置：

```yaml
fetcher:
  plugin: "mihoyo"
  base_url: "https://sr.mihoyo.com"

classifier:
  plugin: "rule_based"

downloader:
  plugin: "playwright"
  output_dir: "downloads"
  max_concurrent: 1  # 并发数（默认 1，避免风控）
  retry_count: 3
  timeout: 60
```

## 日志

运行时会在 `logs/` 目录下生成带时间戳的日志文件（如 `logs/run_20260312_180000.log`），避免日志被意外覆盖。

## 断点续传

使用 `--resume` 参数可跳过已抓取和已下载的内容：

```bash
# 首次下载
python main.py

# 中断后继续下载（跳过已完成的内容）
python main.py --resume
```

- **抓取缓存**：已抓取的新闻 URL 会保存到 `cache/fetch_cache.json`
- **下载缓存**：已下载的视频文件会通过检查文件是否存在来跳过

## 架构设计

本项目采用**插件化架构**：

- **Fetcher** - 负责从网站抓取新闻列表
- **Classifier** - 负责将新闻按规则分类
- **Downloader** - 负责解析页面并下载视频

各模块通过 `PluginRegistry` 注册和解耦，便于扩展新的抓取源、分类规则或下载方式。
