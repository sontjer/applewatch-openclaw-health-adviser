# Runbook

## 1. 部署最短路径

1. 创建私有数据仓（建议：`data_sync_analysis`）。
2. 配置 Worker：
   - `wrangler.toml` 填 `GITHUB_OWNER/GITHUB_REPO/GITHUB_BRANCH`
   - `wrangler secret put INGEST_KEY`
   - `wrangler secret put GITHUB_TOKEN`
   - `wrangler deploy`
3. iOS Auto Export：
   - JSON + REST POST
   - URL=`workers.dev` 或自定义域
   - Header=`X-Auth-Key=<INGEST_KEY>`
   - 日期范围推荐=`今天`（日报完整性优先）
4. Agent 主机：
   - 配置 `/root/.health_pipeline.env`
   - 手动执行 `pull_and_score.sh`
5. 配置 systemd timer（推荐，支持重启补跑）：
   - `health-pipeline.timer`（08:18）
   - `health-reconcile.timer`（08:28）

## 2. 验收清单

1. Worker tail 出现：`ingest_received` + `ingest_written`
2. GitHub 数据仓出现：
   - `data/latest.json`
   - `data/archive/YYYY/MM/DD/*.json`
3. Agent 生成：
   - `data/report/latest_score.json`
   - `data/report/insights.json`
   - `data/report/daily_health_report.md`
4. Telegram 收到分列式报告。

## 3. 即时演练命令

```bash
set -a; source /root/.health_pipeline.env; set +a
/root/applewatch-openclaw-health-adviser/openclaw_agent/pull_and_score.sh
```

## 4. 饮食自然语言录入（即时生效）

```bash
/root/applewatch-openclaw-health-adviser/openclaw_agent/log_meal_from_text.sh \
  "记饮食：今天中午吃了芹菜金针菇蛋汤、青椒牛柳、红烧鲫鱼、炒生菜、一小碗米饭"

# 可选：直接调用底层 skill（不推荐作为默认入口）
python3 /root/codex/skills/meal-intake-log/scripts/log_meal_text.py \
  --repo-dir /root/.openclaw/workspace/health-data \
  --text "今天中午吃了芹菜金针菇蛋汤、青椒牛柳、红烧鲫鱼、炒生菜、一小碗米饭"

set -a; source /root/.health_pipeline.env; set +a
/root/applewatch-openclaw-health-adviser/openclaw_agent/pull_and_score.sh
```

固定入口 `log_meal_from_text.sh` 会做写入校验：

1. 解析并去掉前缀 `记饮食：`
2. 调用 `log_meal_text.py` 写入 `meal_text_log.csv`
3. 校验 CSV 最后一行与写入输出一致，成功才回执

## 5. 最少维护动作

1. 每月轮换 `PAT / Cloudflare Token / Telegram Token`。
2. 查看 `/root/.openclaw/ops/health_pipeline.log` 是否有连续失败。
3. 每周检查一次 `data/latest.json` 更新时间是否连续。
