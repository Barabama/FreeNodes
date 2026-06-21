# P4 — GitHub 集成与 Actions 部署计划

> **目标:** 将新代码推送到旧仓库的新分支，配置 GitHub Actions 每日自动运行

---

## 步骤概览

```
本地 (FreeNodeSpider)
  │
  ├─ 1. 添加旧仓库为 remote
  ├─ 2. 创建新分支推送
  ├─ 3. 配置 GitHub Secrets (API keys)
  ├─ 4. 编写 GitHub Actions workflow
  └─ 5. 验证运行
```

---

## Step 1: Git Remote + 分支策略

```bash
# 添加旧仓库为 remote（用 origin2 避免冲突）
git remote add old-repo https://github.com/Barabama/FreeNodes.git

# 创建并切换到新分支
git checkout -b feat/ai-crawler-v2

# 推送新分支到旧仓库
git push old-repo feat/ai-crawler-v2
```

**分支策略:** 只在 `feat/ai-crawler-v2` 分支上工作，不接触 `master`/`main`。旧 Scrapy 代码保留不动。

**注意:** 推送时 `.env` 必须排除（已在 `.gitignore`），API keys 通过 GitHub Secrets 传入。

---

## Step 2: GitHub Secrets 配置

手动在旧仓库 Settings → Secrets and variables → Actions 添加：

| Secret 名称 | 值 | 来源 |
|-------------|-----|------|
| `OPENROUTER_API_KEY` | `sk-or-v1-...` | 已有 |
| `CEREBRAS_API_KEY` | `csk-...` | 已有 |
| `OPENCODE_API_KEY` | `sk-...` | 已有 |

---

## Step 3: GitHub Actions Workflow

创建 `.github/workflows/crawl.yml`：

```yaml
name: AI Crawl Daily Update

on:
  schedule:
    - cron: "0 4 * * *"   # 每天北京时间 12:00 (UTC 04:00)
  workflow_dispatch:       # 手动触发

jobs:
  crawl:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          ref: feat/ai-crawler-v2   # 指定分支

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          pip install crawl4ai openai httpx pyyaml python-dotenv
          pip install playwright
          playwright install --with-deps chromium

      - name: Run crawler
        env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
          CEREBRAS_API_KEY: ${{ secrets.CEREBRAS_API_KEY }}
          OPENCODE_API_KEY: ${{ secrets.OPENCODE_API_KEY }}
        run: python main.py

      - name: Commit output
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "auto: daily crawl update"
          file_pattern: "nodes/* config.yaml"
          branch: feat/ai-crawler-v2
          commit_user_name: "github-actions[bot]"
          commit_user_email: "github-actions[bot]@users.noreply.github.com"
```

### Workflow 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 运行分支 | `feat/ai-crawler-v2` | 不污染主线 |
| 输出提交 | `nodes/* config.yaml` | 自愈的 pattern 持久化到仓库 |
| commits 计入 | bot 身份 | 不占用户提交数 |
| 超时 | GitHub 默认 6h | 实际运行约 10-30min |
| Playwright 浏览器 | `playwright install chromium` | 只装 Chrome 最小依赖 |

---

## Step 4: 推送前检查清单

```bash
# 1. 确认 .env 在 gitignore 中
grep ".env" .gitignore
# → .env

# 2. 确认 .gitignore 也排除 nodes/（CI 会提交 nodes/*，但本地开发时不追踪）
# 在 workflow 的 git-auto-commit 中用 file_pattern 明确指定 nodes/*
# 确保 gitignore 不排除 nodes/

# 3. 确认所有依赖在 pip install 中列出
grep -E "^(crawl4ai|openai|httpx|pyyaml|python-dotenv)" requirements.txt || \
echo "pip install 命令已包含所有依赖"

# 4. 试运行 (需 API keys)
python main.py

# 5. 推送
git push old-repo feat/ai-crawler-v2
```

---

## Step 5: 验证

推送后：

1. 进入 GitHub `FreeNodes` 仓库 → 切换到 `feat/ai-crawler-v2` 分支
2. 手动触发 Action: Actions → AI Crawl Daily Update → Run workflow
3. 观察运行日志，确认：
   - Crawl4AI 正常启动
   - LLM API 调用成功
   - `nodes/*` 文件被提交回仓库
4. 检查 `config.yaml` 是否更新了自愈的 `link_pattern`

---

## 风险 / 注意事项

| 风险 | 影响 | 缓解 |
|------|------|------|
| GitHub Actions 免费额度 | 2000 分钟/月 ≈ ~200 次运行（~10min/次） | 每天 1 次绰绰有余 |
| Playwright 安装慢 | ~1-2 分钟 | 可加 `playwright` 缓存 |
| `node.freeclashnode.com` 等 CDN 403 | 文件下载失败但不崩溃 | 代码已有重试 + 跳过 |
| OpenRouter 50次/天限额 | 调用太多会被限 | 各站每天 ~3 次 LLM 调用，9 站 ≈ 27 次，在限额内 |

---

## 不做的

- **旧 Scrapy 代码迁移** — 旧代码保留不动，新分支只放新代码
- **合并到 master** — 等新分支稳定后再考虑
- **Docker 化** — GitHub Actions 直接跑 Python 足够
- **通知/告警** — Actions 失败时 GitHub 默认发邮件
