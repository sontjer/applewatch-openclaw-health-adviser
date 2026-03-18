from __future__ import annotations

import argparse
import html
import json
import os
import urllib.parse
import urllib.request
import time
from pathlib import Path


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def fmt(v, nd=1, suffix=''):
    if v is None:
        return 'N/A'
    try:
        return f"{round(float(v), nd)}{suffix}"
    except Exception:
        return f"{v}{suffix}"


def row(k: str, v: str, w: int = 12) -> str:
    return f"{k:<{w}} {v}"


def esc(v) -> str:
    return html.escape(str(v), quote=False)


def post(url: str, data: dict) -> dict:
    encoded = urllib.parse.urlencode(data).encode('utf-8')
    req = urllib.request.Request(url, data=encoded, method='POST')
    last_err = None
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            last_err = e
            if i < 2:
                time.sleep(1.5 * (i + 1))
    raise last_err


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo-dir', required=True)
    args = ap.parse_args()

    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        print('telegram_not_configured_skip')
        return

    repo = Path(args.repo_dir)
    insights_path = repo / 'data' / 'report' / 'insights.json'
    report_path = repo / 'data' / 'report' / 'daily_health_report.md'
    if not insights_path.exists() or not report_path.exists():
        print('telegram_missing_report_files_skip')
        return

    ins = load_json(insights_path)
    score = ins.get('latest_score', {})
    period_obj = ins.get('period', {})
    period = period_obj.get('text', 'N/A')
    agg = '均值' if period_obj.get('days', 1) > 1 else '当日值'
    alerts = ins.get('alerts', [])
    recs = ins.get('recommendations', [])
    trend = ins.get('trend', {})
    m = ins.get('core_metrics', {})
    activity = ins.get('activity_summary', {})
    diet = ins.get('diet_sleep_cross', {}).get('today_nutrition')
    corr = ins.get('diet_sleep_cross', {}).get('calories_vs_sleep_score_corr')
    both_days = ins.get('diet_sleep_cross', {}).get('days_with_both_data')
    rec_dim = ins.get('recommendations_by_dimension', {})
    dq = ins.get('data_quality', {})
    score_meta = ins.get('score_meta', {})

    min_cov = float(os.environ.get('HEALTH_DAILY_MIN_COVERAGE_PCT', '80').strip() or '80')
    cov = dq.get('required_metric_coverage_pct')
    is_incomplete = False
    try:
        is_incomplete = (cov is None) or (float(cov) < min_cov)
    except Exception:
        is_incomplete = True
    score_source = score_meta.get('score_source', 'unknown')
    freshness = score_meta.get('data_freshness_minutes')
    fb_count = score_meta.get('consecutive_fallback_count')

    lines = []
    title = "⚠️ <b>健康分析报告（草稿：数据不完整）</b>" if is_incomplete else "📊 <b>健康分析报告</b>"
    lines.append(title)
    lines.append(f"🗓️ 统计窗口: {esc(period)}（口径: {esc(agg)}）")
    lines.append(f"🎯 节律评分: <b>{esc(score.get('total'))} ({esc(score.get('grade'))})</b>")
    lines.append(f"🧩 数据完整度: {esc(fmt(dq.get('required_metric_coverage_pct'),1,' %'))}（{esc(dq.get('required_present'))}/{esc(dq.get('required_total'))}）")
    if is_incomplete:
        lines.append(f"🚧 发布门槛: 覆盖率低于 {esc(fmt(min_cov,1,' %'))}，本次按草稿推送")
    lines.append(f"🧪 评分来源: {esc(score_source)}，数据新鲜度: {esc(fmt(freshness,1,' 分钟'))}，连续fallback: {esc(fb_count)}")
    lines.append("")
    lines.append("🫀 <b>核心身体指标</b>")
    lines.append("<pre>")
    lines.append(row("静息心率", f"{fmt(m.get('rhr_avg'),1,' bpm')}" ))
    lines.append(row("最低心率", f"{fmt(m.get('hr_min'),1,' bpm')}" ))
    lines.append(row("平均心率", f"{fmt(m.get('hr_avg'),1,' bpm')}" ))
    lines.append(row("最高心率", f"{fmt(m.get('hr_max'),1,' bpm')}" ))
    lines.append(row("血氧饱和度", f"{fmt(m.get('spo2_avg_pct'),2,' %')}" ))
    lines.append(row("手腕温度", f"{fmt(m.get('wrist_temp_avg_c'),2,' °C')}" ))
    lines.append("</pre>")
    lines.append("")
    lines.append("😴 <b>睡眠结构</b>")
    lines.append("<pre>")
    lines.append(row("睡眠总时长", f"{fmt(m.get('sleep_total_h'),2,' h')}" ))
    lines.append(row("深度睡眠", f"{fmt(m.get('sleep_deep_h'),2,' h')}" ))
    lines.append(row("REM眼动", f"{fmt(m.get('sleep_rem_h'),2,' h')}" ))
    lines.append(row("清醒时长", f"{fmt(m.get('sleep_awake_h'),2,' h')}" ))
    lines.append("</pre>")
    lines.append("")
    lines.append("🏃 <b>运动情况</b>")
    lines.append("<pre>")
    lines.append(row("步数(日均)", f"{fmt(activity.get('steps_avg'),0,' 步')}"))
    lines.append(row("运动时长", f"{fmt(activity.get('exercise_min_avg'),1,' 分钟')}"))
    lines.append(row("活动能量", f"{fmt(activity.get('active_kcal_avg'),1,' kcal')}"))
    lines.append(row("爬楼层数", f"{fmt(activity.get('flights_avg'),1,' 层')}"))
    lines.append(row("步跑距离", f"{fmt(activity.get('distance_km_avg'),2,' km')}"))
    lines.append("</pre>")
    lines.append("")
    lines.append("📈 <b>趋势</b>")
    lines.append(f"• 近7天均分: {esc(fmt(trend.get('week_avg'),1))}（较前7天 {esc(fmt(trend.get('week_delta'),1))}）")
    lines.append(f"• 近30天均分: {esc(fmt(trend.get('month_avg'),1))}（较前30天 {esc(fmt(trend.get('month_delta'),1))}）")
    if both_days is not None:
        lines.append(f"• 饮食×睡眠样本天数: {esc(both_days)}，热量-评分相关: {esc(fmt(corr,2))}")

    if diet:
        eval_text = '；'.join(diet.get('evaluation', []))
        lines.append("")
        lines.append("🍽️ <b>饮食分析（当日）</b>")
        lines.append("<pre>")
        lines.append(row("热量", f"{fmt(diet.get('calories'),0,' kcal')}" ))
        lines.append(row("蛋白质", f"{fmt(diet.get('protein_g'),1,' g')}" ))
        lines.append(row("碳水", f"{fmt(diet.get('carbs_g'),1,' g')}" ))
        lines.append(row("脂肪", f"{fmt(diet.get('fat_g'),1,' g')}" ))
        lines.append("</pre>")
        lines.append(f"• 评价: {esc(eval_text if eval_text else 'N/A')}")
    else:
        lines.append("")
        lines.append("🍽️ <b>饮食分析（当日）</b>")
        lines.append("• 当日摄入: 暂无")
        lines.append("• 评价: 暂无")

    if alerts:
        lines.append("")
        lines.append("🚨 <b>自动告警</b>")
        for a in alerts[:3]:
            lines.append(f"• {esc(a)}")
    if rec_dim:
        lines.append("")
        lines.append("🧭 <b>执行建议</b>")
        for dim in ("摄入", "作息", "运动"):
            items = rec_dim.get(dim) or []
            if not items:
                continue
            lines.append(f"• <b>{dim}</b>")
            for r in items[:3]:
                lines.append(f"  - {esc(r)}")
    elif recs:
        lines.append("")
        lines.append("🧭 <b>执行建议</b>")
        for r in recs[:4]:
            lines.append(f"• {esc(r)}")

    text = '\n'.join(lines)
    send_url = f'https://api.telegram.org/bot{token}/sendMessage'
    ret = post(
        send_url,
        {
            'chat_id': chat_id,
            'text': text,
            'disable_web_page_preview': 'true',
            'parse_mode': 'HTML',
        },
    )
    if not ret.get('ok'):
        raise SystemExit(f'telegram_send_failed: {ret}')

    print('telegram_sent_ok')


if __name__ == '__main__':
    main()
