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

可能是“睡眠日与用餐日错位”。当前已做回退：

- 当睡眠日期无饮食时，使用最近一天饮食记录。

## Q6. 怎么快速确认当前最新评分？

```bash
python3 /root/applewatch-openclaw-health-adviser/openclaw_agent/print_latest_score.py \
  --repo-dir /root/.openclaw/workspace/health-data
```
