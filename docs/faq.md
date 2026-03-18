# FAQ

## Q1. iOS 显示已导出，但 GitHub 没更新？

先看 Worker tail：

- `reject_auth`：`X-Auth-Key` 与 `INGEST_KEY` 不一致
- `reject_too_large`：请求体超限，调大 `MAX_REQ_BYTES`
- 只有 `POST ... Ok` 但无 `ingest_written`：看 `ingest_error` 详情

## Q2. Worker 写错仓库了？

检查 `wrangler.toml`：

- `GITHUB_OWNER`
- `GITHUB_REPO`
- `GITHUB_BRANCH`

改完重新 `wrangler deploy`。

## Q3. latest.json 缺少睡眠段导致评分失败？

当前流程已容错：

- `analyze_latest.py` 失败时保留上次 `latest_score.json`
- 报告和 Telegram 仍会继续生成

## Q4. Telegram 400 Bad Request？

常见原因：

1. `BOT_TOKEN/CHAT_ID` 错误
2. Bot 没在目标聊天里收到过消息
3. 文本中 HTML 特殊字符未转义（本仓已处理）

## Q5. 饮食写了但报告显示“无饮食数据”？

当前逻辑是“严格当日”：

- 只统计报告目标日(`date_key`)的饮食
- 不再回退使用昨天或最近一天数据

如果你当天确实已记录但仍显示“暂无”，请检查：

1. `meal_text_log.csv` 的 `timestamp` 是否落在当天
2. 时区是否一致（建议统一 `+0800`）
3. 该条记录是否被成功写入数据仓

## Q6. 怎么快速确认当前最新评分？

```bash
python3 /root/applewatch-openclaw-health-adviser/openclaw_agent/print_latest_score.py \
  --repo-dir /root/.openclaw/workspace/health-data
```
