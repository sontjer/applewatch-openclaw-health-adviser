# Apple Watch + OpenClaw Health Adviser

## 🚨 最终报告效果

![Telegram收到最终报告效果](docs/images/telegram-final-report.png)
![健康报告效果图2](docs/images/health-record2.jpg)

从零搭建一条可运行的健康数据闭环：

- iOS `Health Auto Export` 自动导出 JSON
- Cloudflare Worker 鉴权 + 过滤 + 截断 + 入库 GitHub
- OpenClaw Agent 定时 `git pull` 分析打分
- 自动生成结构化健康报告（告警/趋势/饮食交叉）
- 自动推送 Telegram/discord/飞书等

> 目标：**可读、可执行、可复盘、可扩展**。

---

## ⚡ 0. 5分钟快速启动

1. 准备私有数据仓（例如 `data_sync_analysis`）和 iOS Auto Export（JSON + POST + `X-Auth-Key`）。
2. 在 `cloudflare_worker/wrangler.toml` 填 `GITHUB_OWNER/GITHUB_REPO`，并设置 secrets：
   - `INGEST_KEY`
   - `GITHUB_TOKEN`
3. `wrangler deploy` 后拿到 URL（或绑定自定义域）。
4. 在 Agent 主机配置 `/root/.health_pipeline.env`（仓库、PAT、Telegram）。
5. 执行：

```bash
set -a; source /root/.health_pipeline.env; set +a
/root/applewatch-openclaw-health-adviser/openclaw_agent/pull_and_score.sh
```

6. 验收：确认生成 `data/report/*.json|*.md` 且 Telegram 收到报告。

### 快速入口

- 运行手册（部署/验收/排障）：[`docs/runbook.md`](docs/runbook.md)
- 常见问题（错误码/修复）：[`docs/faq.md`](docs/faq.md)

---

## 1. 架构总览

```mermaid
flowchart TD
    A[iPhone Health + Apple Watch] -->|Auto Export JSON POST| B[Cloudflare Worker]
    B -->|Whitelist + Truncate + Auth| C[(GitHub Data Repo)]
    D[OpenClaw Agent Host] -->|systemd timer pull| C
    D --> E[analyze_latest.py]
    E --> F[generate_health_report.py]
    F --> G[daily_health_report.md / insights.json]
    F --> H[notify_telegram.py]
    H --> I[Telegram]
```

---

## 2. 仓库角色（强烈建议分层）

- **代码仓（公开）**：本仓库（pipeline 代码 + 文档）
- **数据仓（私有）**：仅存健康数据与报告产物（`latest.json` / `archive` / `report`）

这样可避免隐私数据或敏感配置泄露。

---

## 3. 目录结构

```text
cloudflare_worker/
  index.js               # Worker: ingest/filter/truncate/write GitHub
  wrangler.toml          # Worker 配置模板（无密钥）

openclaw_agent/
  pull_and_score.sh      # 一键 pull + 分析 + 报告 + Telegram
  run_health_pipeline_once.sh # 带锁的一次执行入口（systemd 调用）
  run_health_reconcile_once.sh # 带锁的一次对账入口
  log_meal_from_text.sh  # 自然语言“记饮食：...”固定入口（含写入校验）
  analyze_latest.py      # 节律评分输入构建与计算
  generate_health_report.py # 结构化健康报告 + 告警 + 周月趋势 + 饮食交叉
  enrich_report_meta.py  # 评分来源/新鲜度/连续fallback元数据
  reconcile_health_ingest.py # manifest/archive/latest 对账
  notify_telegram.py     # Telegram 推送
  diet_log_template.csv  # 精确营养录入模板
  meal_text_log_template.csv # 自然语言餐食录入模板

systemd/
  health-pipeline.service
  health-pipeline.timer
  health-reconcile.service
  health-reconcile.timer
```

---

## 4. 先决条件

- iPhone 安装 `Health Auto Export`
- Cloudflare 账号（Workers）
- GitHub 账号（可创建私有数据仓）
- OpenClaw Agent 主机（Linux/macOS 均可）
- 主机工具：`python3` `git` `systemd` `node/npm`

---

## 5. 密钥管理（统一走 env / secret）

**绝不入仓库**：

- `INGEST_KEY`
- `GITHUB_TOKEN`
- `CLOUDFLARE_API_TOKEN`
- `TELEGRAM_BOT_TOKEN`

推荐：

- Worker 内密钥 -> `wrangler secret put`
- 系统脚本密钥 -> `/root/.health_pipeline.env`（`chmod 600`）

---

## 6. 从零部署步骤

### Step A. 创建私有数据仓

例如：`<your-user>/data_sync_analysis`（private）

### Step B. 配置并部署 Worker

1) 编辑 `cloudflare_worker/wrangler.toml`：

- `GITHUB_OWNER`
- `GITHUB_REPO`
- `GITHUB_BRANCH`

2) 设置 Worker secrets：

```bash
cd cloudflare_worker
wrangler secret put INGEST_KEY
wrangler secret put GITHUB_TOKEN
```

3) 部署：

```bash
wrangler deploy
```

### Step C. iOS Auto Export 配置

- Export Format: `JSON`
- Export Method: `REST API (POST)`
- URL: `https://<your-worker-or-custom-domain>`
- Header:
  - Key: `X-Auth-Key`
  - Value: 与 `INGEST_KEY` 一致
- 日期范围（日报推荐）：`今天`

> 说明：  
> 为了“日报完整性优先”，建议使用 `今天` 全量快照，而不是 `Since Last Sync` 增量。  
> `Since Last Sync` 需要更复杂的累积/去重逻辑，容易出现周期内指标缺失或口径漂移。

### Step D. Agent 主机部署

将本仓 `openclaw_agent/` 放到主机，例如：

- `/root/applewatch-openclaw-health-adviser/openclaw_agent`

准备环境变量文件 `/root/.health_pipeline.env`：

```bash
HEALTH_REPO_URL=https://github.com/<you>/<data-repo>.git
HEALTH_REPO_BRANCH=main
HEALTH_REPO_DIR=/root/.openclaw/workspace/health-data
HEALTH_GITHUB_PAT=<github_pat_for_private_repo>

# Telegram (optional but recommended)
TELEGRAM_BOT_TOKEN=<bot_token>
TELEGRAM_CHAT_ID=<chat_id>
```

权限：

```bash
chmod 600 /root/.health_pipeline.env
```

### Step E. 首次手动验证

```bash
set -a; source /root/.health_pipeline.env; set +a
/root/applewatch-openclaw-health-adviser/openclaw_agent/pull_and_score.sh
```

成功标志：

- `data/report/latest_score.json`
- `data/report/insights.json`
- `data/report/daily_health_report.md`
- 终端出现 `telegram_sent_ok`

### Step F. 定时任务（推荐 systemd timer）

```bash
sudo install -m 644 systemd/health-pipeline.service /etc/systemd/system/health-pipeline.service
sudo install -m 644 systemd/health-pipeline.timer /etc/systemd/system/health-pipeline.timer
sudo install -m 644 systemd/health-reconcile.service /etc/systemd/system/health-reconcile.service
sudo install -m 644 systemd/health-reconcile.timer /etc/systemd/system/health-reconcile.timer

sudo systemctl daemon-reload
sudo systemctl enable --now health-pipeline.timer
sudo systemctl enable --now health-reconcile.timer
```

查看下次触发：

```bash
systemctl list-timers --all | rg 'health-pipeline|health-reconcile'
```

---

## 7. 报告内容设计（已实现）

### 7.1 核心指标（多天自动取平均）

- 静息心率
- 最高/最低/平均心率
- 血氧饱和度
- 手腕温度
- 睡眠总时长
- 深度睡眠
- REM（眼动）
- 清醒时长

> 缺失数据自动输出 `N/A`，不会中断报告。

### 7.2 自动告警

- 熬夜告警（最近入睡晚于 00:30）
- 节律偏移告警（Timing 低）
- 睡眠债告警（均值偏低）

### 7.3 饮食分析（有数据才显示）

支持两种输入：

1) 精确营养（推荐）
- `data/diet/diet_log.csv`

2) 自然语言（你只写吃了什么）
- `data/diet/meal_text_log.csv`
- 会自动估算热量/蛋白/碳水/脂肪，输出 `meal_text_estimated.csv`

#### OpenClaw 自然语言录入示例

在 OpenClaw 对话里可以用自然语言记录餐饮（由 Agent 落盘到 `meal_text_log.csv`）：

```text
今天中午吃了芹菜金针菇蛋汤、青椒牛柳、红烧鲫鱼、炒生菜、一小碗米饭
```

对应落盘格式：

```csv
timestamp,meal,description
2026-03-17 12:30:00,lunch,芹菜金针菇蛋汤、青椒牛柳、红烧鲫鱼、炒生菜、一小碗米饭
```

然后在下一次 `pull_and_score.sh` 执行时自动完成：

1. 菜品识别与营养估算（热量/蛋白/碳水/脂肪）
2. 当日营养合理度评价（够不够、过不过）
3. 纳入“饮食 × 睡眠”交叉分析与趋势报告

#### 推荐触发方式（固定短句）

建议在 OpenClaw 中统一使用前缀触发，降低歧义：

```text
记饮食：今天中午吃了芹菜金针菇蛋汤、青椒牛柳、红烧鲫鱼、炒生菜、一小碗米饭
```

Agent 处理约定：

1. 去掉前缀 `记饮食：`
2. 调用固定入口 `openclaw_agent/log_meal_from_text.sh` 落盘（内部调用 `meal-intake-log` skill）
3. 可选立即触发一次 `pull_and_score.sh`（即时更新 Telegram 报告）

固定入口命令（推荐）：

```bash
/root/applewatch-openclaw-health-adviser/openclaw_agent/log_meal_from_text.sh \
  "记饮食：今天中午吃了芹菜金针菇蛋汤、青椒牛柳、红烧鲫鱼、炒生菜、一小碗米饭"
```

Skill 底层命令（脚本内部调用）：

```bash
python3 /root/codex/skills/meal-intake-log/scripts/log_meal_text.py \
  --repo-dir /root/.openclaw/workspace/health-data \
  --text "今天中午吃了芹菜金针菇蛋汤、青椒牛柳、红烧鲫鱼、炒生菜、一小碗米饭"
```

支持参数：

- `--timestamp \"YYYY-mm-dd HH:MM:SS\"`（补录历史）
- `--meal breakfast|lunch|dinner|snack|unspecified`（覆盖自动识别）

固定入口脚本保证：

- 必须写入 `data/diet/meal_text_log.csv`
- 写入后校验 CSV 最后一行与脚本输出一致才回执成功
- 避免“只写 memory 文件就回复已记录”的伪成功

并自动做：

- 当日营养搭配合理度评估
- 近30天“热量 vs 睡眠评分”相关性

### 7.4 周度/月度趋势

- 近7天均分与前7天对比
- 近30天均分与前30天对比

### 7.5 数据完整性门槛（日报）

- 报告内置“必需指标覆盖率”检查（例如 `sleepAnalysis/heartRate/stepCount/...`）
- 输出字段：
  - `data_quality.required_metric_coverage_pct`
  - `data_quality.missing_required_metrics`
  - `data_quality.status`
- Telegram 推送支持门槛策略：
  - 环境变量 `HEALTH_DAILY_MIN_COVERAGE_PCT`（默认 `80`）
  - 低于阈值自动标记为“草稿：数据不完整”

---

## 8. 运行与验收清单

1) Worker `tail` 能看到 `ingest_received` + `ingest_written`
2) 数据仓出现：
- `data/latest.json`
- `data/archive/YYYY/MM/DD/*.json`
3) Agent 侧生成：
- `latest_score.json`
- `insights.json`
- `daily_health_report.md`
4) Telegram 收到分列式报告（含 emoji）

### Telegram 最终报告效果

> Telegram收到最终报告效果

![Telegram收到最终报告效果](docs/images/telegram-final-report.png)

---

## 9. 常见问题与修复

### Q1. iOS 导出成功，但 GitHub 没更新

看 Worker tail：

- 若出现 `reject_too_large`：调大 `MAX_REQ_BYTES`
- 若出现 `reject_auth`：`X-Auth-Key` 不匹配
- 若 `ingest_written` 有但仓库不变：检查 `GITHUB_OWNER/GITHUB_REPO/BRANCH`

### Q2. Telegram 推送失败

- 检查 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`
- Bot 是否已在目标聊天中收到过消息
- 若使用 HTML parse mode，动态文本需转义（本仓已处理）

### Q3. 报告指标缺失

- 源数据本期不存在该指标时会显示 `N/A`
- 不会中断主流程

---

## 10. 安全建议

- 所有 token 最小权限、短 TTL、定期轮换
- 数据仓保持 private
- 不在日志中打印明文密钥
- 公开仓只保留模板和说明，不含敏感配置

---

## 11. 一句话执行命令（主机）

```bash
set -a; source /root/.health_pipeline.env; set +a; /root/applewatch-openclaw-health-adviser/openclaw_agent/pull_and_score.sh
```

查看最新一次评分时间戳与分数（避免手写内联 Python）：

```bash
python3 /root/applewatch-openclaw-health-adviser/openclaw_agent/print_latest_score.py --repo-dir /root/.openclaw/workspace/health-data
```

---

## 12. 许可证

建议 MIT（可自行添加 `LICENSE` 文件）
