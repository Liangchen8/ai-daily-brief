# AI Daily Brief

AI Daily Brief 是一个可每日自动执行的中文 AI 行业情报系统，面向 AI 产品经理、Agent/RAG/MCP/Skills/Coding Agent 开发者。系统先通过 RSS/API 采集真实内容，再做规则过滤、去重、事件聚类和确定性评分，最后才调用可切换的 LLM 进行分析。

## 1. 环境要求

- Python 3.12+
- 可访问外部 RSS/API 的网络
- 至少一个 LLM Provider 的 API Key 才能完成深度分析

macOS 使用 Homebrew 安装 Python 3.12：

```bash
brew install python@3.12
python3.12 --version
```

如果没有 Homebrew，可从 Python 官网安装 3.12+，然后确认 `python3.12 --version` 输出正确。

## 2. 本地安装与运行

```bash
cd "/Users/yangmanyu/Desktop/信息抓取"
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install ".[dev]"
cp .env.example .env
```

编辑 `.env`，至少设置一个 Provider 和对应模型，例如：

```env
OPENAI_API_KEY=你的密钥
NEWS_ANALYSIS_PROVIDER=openai
NEWS_ANALYSIS_MODEL=你的模型名
PAPER_ANALYSIS_PROVIDER=openai
PAPER_ANALYSIS_MODEL=你的模型名
```

查看当前模型配置：

```bash
python -m ai_daily.main --show-models
```

本地 dry-run：

```bash
python -m ai_daily.main --debug --dry-run
```

日报会写入 `output/AI_Daily_Brief_YYYY-MM-DD.md`。dry-run 不发送飞书，也不更新 `data/seen_items.json`。没有 API Key 时仍会真实执行采集、过滤、去重、聚类和评分；LLM 任务会明确标记为跳过，不生成假摘要。

正式发送：

```bash
python -m ai_daily.main --send --debug
```

第一版默认使用飞书 Webhook。只有推送成功后才写入历史记录。

`--dry-run` 不会写入历史。`--send` 只有在飞书所有分片都发送成功后，才会原子更新 `data/seen_items.json`；发送失败或历史落盘失败会使进程返回失败状态，避免把未送达日报误标为已发送。

## 3. 如何切换 AI 模型

配置优先级为：

```text
CLI 临时覆盖 > Environment / GitHub Variables > models.yaml > default
```

本地 `.env`：

```env
PAPER_ANALYSIS_PROVIDER=deepseek
PAPER_ANALYSIS_MODEL=YOUR_MODEL
```

GitHub Variables：在 Repository → Settings → Secrets and variables → Actions → Variables 中设置同名变量。下一次定时任务会自动生效。

CLI 临时覆盖，不会修改 YAML 或 `.env`：

```bash
python -m ai_daily.main \
  --paper-provider deepseek \
  --paper-model YOUR_MODEL \
  --dry-run
```

任务建议：Filter 使用便宜快速模型；新闻分析使用中高能力模型；论文分析使用长文本和推理能力较好的模型；社交分析使用中等成本模型；Digest 使用质量较好的总结模型。项目当前真实实现 OpenAI 和 DeepSeek，Provider 接口可扩展其他 OpenAI-compatible 服务。

## 4. Secret 与模型配置

Required（要完成相应功能）：

- `OPENAI_API_KEY`：使用 OpenAI 时需要
- `DEEPSEEK_API_KEY`：使用 DeepSeek 时需要
- `FEISHU_WEBHOOK_URL`：使用 `--send` 发送飞书时需要

Optional：

- `SEMANTIC_SCHOLAR_API_KEY`：论文引用 enrichment，不配置也能采集论文
- `HF_TOKEN`：启用 Hugging Face Daily Papers/Trending 入口；没有 Token 时仍会回退到官方 Papers 搜索入口，但不保证有 Trending 信号
- `X_BEARER_TOKEN`：启用 X Collector；不配置则显示 disabled 并继续
- `ANTHROPIC_API_KEY`、`GEMINI_API_KEY`：为未来 Provider 保留

API Key 只能放在本地 `.env`（该文件已被 Git 忽略）或 GitHub Secrets，不能写进源码、YAML 或日志。

## 5. 数据源配置

在 `config/sources.yaml` 增加 RSS：

```yaml
- name: Example
  url: https://example.com/feed
  type: rss
  authority_weight: 80
  enabled: true
```

在 `config/people.yaml` 增加人物和 Bluesky/X 账号，不需要修改 Collector 代码。`config/topics.yaml` 决定系统关注的主题；`config/ranking.yaml` 控制评分权重、去重和聚类阈值。

## 6. 飞书配置

1. 在飞书群聊中添加群机器人。
2. 复制 Webhook URL。
3. 本地写入 `.env` 的 `FEISHU_WEBHOOK_URL`，用 `--send` 测试。
4. GitHub 部署时把相同值添加到 Repository → Settings → Secrets and variables → Actions → Secrets。

日报超过单条消息长度时，`FeishuNotifier` 会自动拆分发送。网络超时和飞书错误会使 `--send` 失败，避免静默丢日报。

## 7. GitHub Actions 部署

```bash
cd "/Users/yangmanyu/Desktop/信息抓取"
git init
git add .
git commit -m "feat: initialize AI daily brief"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/YOUR_REPO.git
git push -u origin main
```

随后在 GitHub Repository → Settings → Secrets and variables → Actions → Secrets 添加：

```text
OPENAI_API_KEY
DEEPSEEK_API_KEY
SEMANTIC_SCHOLAR_API_KEY
HF_TOKEN
X_BEARER_TOKEN
FEISHU_WEBHOOK_URL
```

在 Variables 添加任务级模型配置：

```text
FILTER_PROVIDER / FILTER_MODEL
OPENAI_BASE_URL（使用兼容网关时设置，例如以 /v1 结尾的地址）
NEWS_ANALYSIS_PROVIDER / NEWS_ANALYSIS_MODEL
PAPER_ANALYSIS_PROVIDER / PAPER_ANALYSIS_MODEL
SOCIAL_ANALYSIS_PROVIDER / SOCIAL_ANALYSIS_MODEL
DIGEST_PROVIDER / DIGEST_MODEL
```

若使用 DeepSeek 的自定义兼容端点，可另设 `DEEPSEEK_BASE_URL` Variable。工作流只读取这些 Variable，不会改写本地 `.env` 或硬编码地址。

工作流位于 `.github/workflows/daily_digest.yml`，支持 `workflow_dispatch` 手动运行，并按 `17 0 * * *` 执行。GitHub cron 使用 UTC，因此每天 UTC 00:17 就是北京时间 08:17。

工作流固定使用 Python 3.12，并在日志中输出 Python executable 与 Python version 后执行 `pytest`。`--send` 成功且 `data/seen_items.json` 实际变化时，工作流才会以 `chore: update AI Daily state [skip ci]` 自动提交并推送该状态文件；不会提交 `output/`，也不会产生空提交。这样无论是定时任务还是 `workflow_dispatch`，第二天 checkout 后都能识别已发送内容。

仓库需保留 Workflow 的 `contents: write` 权限；若飞书发送失败，运行步骤会失败，后续持久化步骤不会执行，因此历史状态不会被错误提交。

## 8. 测试

```bash
source .venv/bin/activate
pytest
```

测试只使用 Mock，不调用真实 OpenAI、DeepSeek、外部 Collector 或飞书。

## 9. 已知限制

- 当前只真实实现 OpenAI 和 DeepSeek；Anthropic/Gemini 仅保留环境变量和扩展空间。
- X 依赖 Bearer Token、额度和 API 权限；没有 Token 时自动跳过。
- 论文分析第一版主要基于真实 Abstract、Trending 信号和 enrichment，不能替代完整论文复核。
- 事件聚类使用 URL、标题、实体词和时间窗口，没有引入向量数据库。
- GitHub Actions 需要仓库允许 Actions 写回内容，且必须正确配置 Secret/Variable。
- 本机验证必须使用 Python 3.12+；本项目不会因本机旧解释器而降低 `requires-python`。
