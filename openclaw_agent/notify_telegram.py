from __future__ import annotations

import argparse
import html
import json
import os
import urllib.parse
import urllib.request
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
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode('utf-8'))


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
    diet = ins.get('diet_sleep_cross', {}).get('today_nutrition')
    corr = ins.get('diet_sleep_cross', {}).get('calories_vs_sleep_score_corr')
    both_days = ins.get('diet_sleep_cross', {}).get('days_with_both_data')

    lines = []
    lines.append("📊 <b>健康分析报告</b>")
    lines.append(f"🗓️ 统计窗口: {esc(period)}（口径: {esc(agg)}）")
    lines.append(f"🎯 节律评分: <b>{esc(score.get('total'))} ({esc(score.get('grade'))})</b>")
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

    if alerts:
        lines.append("")
        lines.append("🚨 <b>自动告警</b>")
        for a in alerts[:3]:
            lines.append(f"• {esc(a)}")
    if recs:
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
