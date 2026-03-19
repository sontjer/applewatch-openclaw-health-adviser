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

推荐使用固定入口，避免“回执成功但未落盘”：

```bash
/root/applewatch-openclaw-health-adviser/openclaw_agent/log_meal_from_text.sh \
  "记饮食：今天早上吃了一个水煮蛋、一碗芝麻糊"
```

## Q6. 怎么快速确认当前最新评分？

```bash
python3 /root/applewatch-openclaw-health-adviser/openclaw_agent/print_latest_score.py \
  --repo-dir /root/.openclaw/workspace/health-data
```

## Q7. 为什么 HRV 不再用“当天最新单点”或“全天均值”？

当前评分已改为：**睡眠窗口 HRV 中位数**（并用近 28 天睡眠窗口中位数序列做 baseline）。

原因：

1. 最新单点对取样时刻极其敏感，容易被晚间训练后短时波动放大。
2. 全天均值混入白天活动与体位变化噪声，不利于恢复状态判读。
3. 睡眠窗口 + 中位数在工程上更稳健、可比性更好。

详细说明见：[`docs/hrv_scoring_validation.md`](hrv_scoring_validation.md)
评分体系全量依据见：[`docs/scoring_scientific_basis.md`](scoring_scientific_basis.md)

关键参考：

- Task Force HRV 标准（1996）：https://pubmed.ncbi.nlm.nih.gov/8598068/
- 夜间短时 HRV 与整夜平均对比（2025）：https://pubmed.ncbi.nlm.nih.gov/39670869/
- 夜间 HR/HRV 训练负荷监测可靠性（2022）：https://pubmed.ncbi.nlm.nih.gov/35894977/
