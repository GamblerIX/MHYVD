# MHYVD

本仓库用于抓取和下载米哈游（miHoYo / HoYoverse）游戏视频。MHYVD 在配置了 stealth 模式的 Chromium 浏览器中遍历游戏的公告列表，通过关键字规则将每篇公告分类到相应的目录树中（如 `videos/pv/character`、`music`、`activity` 等），然后解析出 `videos/*` 分类下公告背后的视频，并将其下载到按分类组织好的输出目录中。

整个流水线遵循 **抓取（Fetch） → 分类（Classify） → 下载（Download）** 的流程，具备“无头（headless）模式 → 有头（headed）模式”的自动回退机制、全局时间预算控制、中断处理，以及可选的断点续传（resume）模式（可跳过已抓取的公告和已下载的文件）。

## 回退机制与退出状态码

* 如果浏览器发生错误/崩溃 **或者** 抓取到的公告数量为零，则视为抓取尝试**失败**。在开启回退功能的情况下，流水线会记录原因并切换到有头模式进行重试。如果所有模式均告失败，则本次运行将报告错误，并携带每次尝试的失败原因。
* 退出状态码优先级：超时 `124` > 中断 `130` > 运行时错误 `1` > 成功 `0`。Markdown 运行摘要**仅**在流水线正常运行结束时打印（发生超时或中断时绝不打印）。

## 环境要求

* Python 3.11
* [uv](https://docs.astral.sh/uv/) 包管理器
* [Playwright](https://playwright.dev/python/) + `playwright-stealth`
* `PyYAML`

依赖由 `pyproject.toml` 声明，使用 uv 管理。Python 版本固定为 3.11（见 `.python-version`）。

```bash
uv sync                          # 创建 .venv 并安装依赖（含 dev 组的 hypothesis）
uv run playwright install chromium
```

> 浏览器相关的依赖采用延迟导入（lazily imported）的方式，因此在未安装真实浏览器的情况下，配置、分类器和流水线的单元测试仍可正常运行。

## 使用方法

在项目根目录下运行（该包以 `src` 形式导入）：

```bash
# 使用默认配置运行完整流水线 (config/default.yaml)
uv run python -m src.main run

# 列出所有已注册的数据源 Key (Source_Key)
uv run python -m src.main list-sources

# 已安装脚本入口（等价于 run/list-sources 的分发）
uv run mhyvd run
```

### `run` 命令的可选参数

| 参数 | 描述 |
| --- | --- |
| `-c, --config PATH` | YAML 配置文件路径（默认使用内置的 `config/default.yaml`）。 |
| `-s, --source KEY` | 要运行的数据源 Key（例如 `honkai-star-rail/cn`）。会覆盖配置文件中的设置。 |
| `-p, --proxy ADDR` | 代理服务器地址。会覆盖配置文件中的设置。 |
| `-o, --timeout SECONDS` | 整体时间预算 / 单次操作超时时长（秒）。会覆盖配置文件中的 `timeout` 设置。 |
| `--headless` / `--headed` | 浏览器运行模式（互斥参数；默认为无头 headless 模式）。 |
| `-l, --limit N` | 限制处理的视频数量（用于测试）。 |
| `--log-level` | 日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR`（默认为 `INFO`）。 |
| `--log-file PATH` | 日志文件路径（默认带有时间戳）。 |
| `--resume` | 启用断点续传模式 —— 跳过已缓存的抓取记录和已存在的文件。 |
| `--list-only` | 仅抓取、分类并导出 URL 列表（`<output_dir>/cache.json`），不下载视频。 |
| `--no-fallback` | 禁用“无头 → 有头”的自动回退机制。 |

```bash
# 示例：在有头模式下运行、启用断点续传、限制最多下载 5 个视频、设置 300 秒超时，并通过代理服务器访问
uv run python -m src.main run --headed --resume --limit 5 --timeout 300 --proxy http://127.0.0.1:10808

```

## 配置说明

`config/default.yaml` 与 `src/config/defaults.py` 中内置的默认值完全对应。用户配置会深度合并（deep-merge）到默认配置之上，因此所有必需的配置项（`source_key`、`classifier`、`output_dir`、`concurrency`、`retry_count`、`timeout`）始终能确保正确解析。

```yaml
source_key: honkai-star-rail/cn
classifier: rule_based
output_dir: downloads
concurrency: 1
retry_count: 3        # 设为 0 将禁用自动恢复（并记录警告日志）
timeout: 300          # 单次操作的超时时间（秒）；同时也是全局时间预算
rules:
  - category: videos/pv/character
    keywords: ["角色 PV"]
  # ...

```

分类规则是有序的：公告标题将匹配**第一条**包含其对应关键字的规则，并归入该分类。系统只会下载 `videos/*` 分类下的内容；其他分类（如 `music`、`activity` 等）仅进行分类和计数，不会执行实际的视频抓取和下载。

## 测试

```bash
uv run python -m unittest discover -s tests

```

测试通过组件的衔接点（如 `pipeline_factory`、`driver_factory`、`resolve_attempt`、`download_file` 等）注入伪对象（fakes），因此无需启动 Chromium 浏览器或请求真实网络，即可对包含回退和崩溃路径在内的完整编排流程进行测试。

## 添加新数据源

1. 在 `src/sources/` 目录下继承 `SourceAdapter` 实现子类。设置其元数据 `SourceMetadata`（包含 `source_key`、`game`、`region`、`base_url`）并实现 `fetch_news` 方法。
2. 将新数据源注册到 `src/sources/registry.py` 中。
3. 复用 `src/sources/base.py` 中与浏览器无关的辅助函数（如 `build_news_items`、`filter_resume_cached`、`should_continue_load_more`）。
4. 随后即可通过 `--source <game>/<region>` 参数或在配置文件中修改 `source_key` 来指定使用该数据源。
