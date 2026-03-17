from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple


def parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = str(s).strip()
    for fmt in (
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%d %H:%M:%S %z',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d',
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None


def to_float(v: Any) -> Optional[float]:
    try:
        if v is None or v == '':
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def avg(nums: List[float]) -> Optional[float]:
    return mean(nums) if nums else None


def median(nums: List[float]) -> Optional[float]:
    if not nums:
        return None
    xs = sorted(nums)
    n = len(xs)
    if n % 2:
        return xs[n // 2]
    return (xs[n // 2 - 1] + xs[n // 2]) / 2


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def append_or_replace_history(history_path: Path, row: Dict[str, Any]) -> List[Dict[str, Any]]:
    history: List[Dict[str, Any]] = []
    if history_path.exists():
        for line in history_path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                history.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    day = row.get('date')
    replaced = False
    for i, item in enumerate(history):
        if item.get('date') == day:
            history[i] = row
            replaced = True
            break
    if not replaced:
        history.append(row)

    history.sort(key=lambda x: x.get('date', ''))
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in history) + '\n', encoding='utf-8')
    return history


def pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denx = sum((x - mx) ** 2 for x in xs)
    deny = sum((y - my) ** 2 for y in ys)
    if denx <= 0 or deny <= 0:
        return None
    return num / (denx ** 0.5 * deny ** 0.5)


def get_metrics_map(latest_data: Dict[str, Any]) -> Dict[str, Any]:
    m = latest_data.get('metrics')
    return m if isinstance(m, dict) else {}


def parse_metric_series(series: Any) -> List[Dict[str, Any]]:
    return [x for x in (series or []) if isinstance(x, dict)]


def metric_dates(series: List[Dict[str, Any]]) -> List[datetime]:
    out: List[datetime] = []
    for r in series:
        dt = parse_dt(r.get('date') or r.get('startDate') or r.get('timestamp') or r.get('sleepEnd') or r.get('sleepStart'))
        if dt is not None:
            out.append(dt)
    return out


def select_recent(series: List[Dict[str, Any]], days: int, now: datetime) -> List[Dict[str, Any]]:
    out = []
    for r in series:
        dt = parse_dt(r.get('date') or r.get('startDate') or r.get('timestamp') or r.get('sleepEnd') or r.get('sleepStart'))
        if dt is None:
            continue
        if dt.tzinfo is None and now.tzinfo is not None:
            dt = dt.replace(tzinfo=now.tzinfo)
        if now - dt <= timedelta(days=days):
            out.append(r)
    return out


def summarize_heart_rate(series: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    mins, maxs, avgs = [], [], []
    for r in series:
        v = to_float(r.get('qty') or r.get('value'))
        mn = to_float(r.get('Min') or r.get('min'))
        mx = to_float(r.get('Max') or r.get('max'))
        av = to_float(r.get('Avg') or r.get('avg'))
        if v is not None:
            avgs.append(v)
            mins.append(v)
            maxs.append(v)
        if mn is not None:
            mins.append(mn)
        if mx is not None:
            maxs.append(mx)
        if av is not None:
            avgs.append(av)
    return {
        'hr_min': min(mins) if mins else None,
        'hr_max': max(maxs) if maxs else None,
        'hr_avg': avg(avgs),
    }


def summarize_sleep(series: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    total, deep, rem, awake = [], [], [], []
    for r in series:
        t = to_float(r.get('totalSleep'))
        d = to_float(r.get('deep'))
        re = to_float(r.get('rem'))
        aw = to_float(r.get('awake'))
        if t is not None:
            total.append(t)
        if d is not None:
            deep.append(d)
        if re is not None:
            rem.append(re)
        if aw is not None:
            awake.append(aw)
    return {
        'sleep_total_h': avg(total),
        'sleep_deep_h': avg(deep),
        'sleep_rem_h': avg(rem),
        'sleep_awake_h': avg(awake),
    }


FOOD_DB = {
    '米饭': (220, 4, 50, 0.5),
    '小碗米饭': (160, 3, 36, 0.4),
    '牛柳': (260, 24, 8, 16),
    '青椒牛柳': (320, 26, 10, 20),
    '鲫鱼': (220, 32, 4, 9),
    '红烧鲫鱼': (280, 34, 8, 12),
    '生菜': (70, 2, 5, 4),
    '炒生菜': (120, 2, 8, 8),
    '芹菜': (40, 2, 7, 0.5),
    '金针菇': (50, 3, 9, 0.5),
    '蛋汤': (90, 6, 3, 5),
    '芹菜金针菇蛋汤': (150, 10, 15, 5),
    '鸡蛋': (80, 6, 1, 5),
    '鸡胸': (180, 32, 0, 4),
    '鱼': (220, 30, 3, 9),
}

PORTION_FACTOR = {
    '半': 0.5,
    '小': 0.7,
    '大': 1.3,
}


def estimate_meal(description: str) -> Tuple[Dict[str, float], List[str]]:
    text = (description or '').replace('，', ',').replace('、', ',').replace('+', ',')
    tokens = [t.strip() for t in text.split(',') if t.strip()]
    total = {'calories': 0.0, 'protein_g': 0.0, 'carbs_g': 0.0, 'fat_g': 0.0}
    matched: List[str] = []

    for tk in tokens:
        factor = 1.0
        if '一小碗米饭' in tk or '小碗米饭' in tk:
            base = FOOD_DB['小碗米饭']
            matched.append('小碗米饭')
        else:
            base = None
            for key, vals in FOOD_DB.items():
                if key in tk:
                    base = vals
                    matched.append(key)
                    break

        for k, v in PORTION_FACTOR.items():
            if k in tk and '米饭' not in tk:
                factor *= v

        if base is None:
            continue
        total['calories'] += base[0] * factor
        total['protein_g'] += base[1] * factor
        total['carbs_g'] += base[2] * factor
        total['fat_g'] += base[3] * factor

    return total, matched


def parse_diet(repo_dir: Path) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}

    # Numeric log (preferred if available)
    numeric = repo_dir / 'data' / 'diet' / 'diet_log.csv'
    if numeric.exists():
        with numeric.open('r', encoding='utf-8') as f:
            r = csv.DictReader(f)
            for row in r:
                dt = parse_dt(row.get('timestamp', ''))
                if dt is None:
                    continue
                d = dt.date().isoformat()
                x = out.setdefault(d, {'calories': 0.0, 'protein_g': 0.0, 'carbs_g': 0.0, 'fat_g': 0.0, 'meals': 0.0})
                for k in ('calories', 'protein_g', 'carbs_g', 'fat_g'):
                    v = to_float(row.get(k))
                    if v is not None:
                        x[k] += v
                x['meals'] += 1

    # Text log fallback (auto estimate)
    textlog = repo_dir / 'data' / 'diet' / 'meal_text_log.csv'
    est_rows = []
    if textlog.exists():
        with textlog.open('r', encoding='utf-8') as f:
            r = csv.DictReader(f)
            for row in r:
                dt = parse_dt(row.get('timestamp', ''))
                if dt is None:
                    continue
                desc = row.get('description', '')
                est, matched = estimate_meal(desc)
                d = dt.date().isoformat()
                x = out.setdefault(d, {'calories': 0.0, 'protein_g': 0.0, 'carbs_g': 0.0, 'fat_g': 0.0, 'meals': 0.0})
                for k in ('calories', 'protein_g', 'carbs_g', 'fat_g'):
                    x[k] += est[k]
                x['meals'] += 1
                est_rows.append({
                    'timestamp': row.get('timestamp', ''),
                    'meal': row.get('meal', ''),
                    'description': desc,
                    'calories_est': round(est['calories'], 1),
                    'protein_g_est': round(est['protein_g'], 1),
                    'carbs_g_est': round(est['carbs_g'], 1),
                    'fat_g_est': round(est['fat_g'], 1),
                    'matched_items': '|'.join(matched),
                })

    if est_rows:
        est_path = repo_dir / 'data' / 'diet' / 'meal_text_estimated.csv'
        est_path.parent.mkdir(parents=True, exist_ok=True)
        with est_path.open('w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(est_rows[0].keys()))
            w.writeheader()
            w.writerows(est_rows)

    return out


def recommend(metrics: Dict[str, Optional[float]], score: Dict[str, Any], diet_day: Optional[Dict[str, float]]) -> List[str]:
    rec = []

    if metrics.get('sleep_total_h') is not None and metrics['sleep_total_h'] < 7:
        rec.append('未来7天把就寝时间前移20-30分钟，目标睡眠总时长稳定在 7-8.5 小时。')

    if metrics.get('sleep_deep_h') is not None and metrics['sleep_deep_h'] < 1.0:
        rec.append('深睡偏低：晚餐后减少酒精和重油，睡前90分钟避免高强度运动与强光屏幕。')

    if metrics.get('rhr_avg') is not None and metrics['rhr_avg'] >= 70:
        rec.append('静息心率偏高：本周以中低强度有氧为主，避免连续高强度训练。')

    if metrics.get('spo2_avg_pct') is not None and metrics['spo2_avg_pct'] < 95:
        rec.append('血氧平均偏低，建议关注鼻塞/打鼾等问题；若持续偏低请就医评估。')

    if score.get('details', {}).get('timing') is not None and score['details']['timing'] < 60:
        rec.append('节律时序偏移：连续7天固定起床时间（周末差异<1小时），优先修复生物钟。')

    if diet_day:
        cal = diet_day.get('calories', 0)
        p = diet_day.get('protein_g', 0)
        if cal < 1400:
            rec.append('当日热量摄入可能偏低，注意避免长期能量不足导致恢复变差。')
        if cal > 2600:
            rec.append('当日热量偏高，建议晚餐减少精制碳水并增加蔬菜占比。')
        if p < 60:
            rec.append('蛋白质摄入偏低，建议每餐补充优质蛋白（鱼/蛋/瘦肉/豆制品）。')

    if not rec:
        rec.append('保持当前节律：固定起床时间 + 晚间控光 + 每周3-4次中等强度运动。')
    return rec


def fmt(v: Optional[float], nd: int = 2, suffix: str = '') -> str:
    if v is None:
        return 'N/A'
    return f"{round(v, nd)}{suffix}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo-dir', required=True)
    args = ap.parse_args()

    repo = Path(args.repo_dir)
    latest_score_path = repo / 'data' / 'report' / 'latest_score.json'
    latest_data_path = repo / 'data' / 'latest.json'
    if not latest_score_path.exists() or not latest_data_path.exists():
        raise SystemExit('required input files are missing')

    latest_score = load_json(latest_score_path)
    score = latest_score.get('score', {})
    preview = latest_score.get('input_preview', {})
    latest_data = load_json(latest_data_path)
    metrics_map = get_metrics_map(latest_data)

    now = datetime.now().astimezone()

    hr_series = select_recent(parse_metric_series(metrics_map.get('heartRate')), 30, now)
    rhr_series = select_recent(parse_metric_series(metrics_map.get('restingHeartRate')), 30, now)
    spo2_series = select_recent(parse_metric_series(metrics_map.get('oxygenSaturation')), 30, now)
    temp_series = select_recent(parse_metric_series(metrics_map.get('appleSleepingWristTemperature')), 30, now)
    sleep_series = select_recent(parse_metric_series(metrics_map.get('sleepAnalysis')), 30, now)

    hr_sum = summarize_heart_rate(hr_series)
    rhr_vals = [to_float(r.get('qty') or r.get('value')) for r in rhr_series]
    rhr_vals = [x for x in rhr_vals if x is not None]

    spo2_vals = [to_float(r.get('qty') or r.get('value')) for r in spo2_series]
    spo2_vals = [x for x in spo2_vals if x is not None]
    # normalize [0,1] to percentage
    spo2_vals = [x * 100 if x <= 1.0 else x for x in spo2_vals]

    temp_vals = [to_float(r.get('qty') or r.get('value')) for r in temp_series]
    temp_vals = [x for x in temp_vals if x is not None]

    sleep_sum = summarize_sleep(sleep_series)

    # Determine period info
    all_dates: List[datetime] = []
    for series in (hr_series, rhr_series, spo2_series, temp_series, sleep_series):
        all_dates.extend(metric_dates(series))
    if all_dates:
        dmin, dmax = min(all_dates), max(all_dates)
        period_days = max(1, (dmax.date() - dmin.date()).days + 1)
        period_text = f"{dmin.date().isoformat()} ~ {dmax.date().isoformat()} ({period_days}天)"
    else:
        period_days = 1
        period_text = 'N/A'

    metric_summary: Dict[str, Optional[float]] = {
        'rhr_avg': avg(rhr_vals),
        'hr_min': hr_sum['hr_min'],
        'hr_max': hr_sum['hr_max'],
        'hr_avg': hr_sum['hr_avg'],
        'spo2_avg_pct': avg(spo2_vals),
        'wrist_temp_avg_c': avg(temp_vals),
        'sleep_total_h': sleep_sum['sleep_total_h'],
        'sleep_deep_h': sleep_sum['sleep_deep_h'],
        'sleep_rem_h': sleep_sum['sleep_rem_h'],
        'sleep_awake_h': sleep_sum['sleep_awake_h'],
    }

    # History for weekly/monthly trend
    wake_dt = parse_dt(preview.get('wake_time', ''))
    date_key = wake_dt.date().isoformat() if wake_dt else now.date().isoformat()
    history_row = {
        'date': date_key,
        'generated_at': latest_score.get('generated_at'),
        'total': score.get('total'),
        'grade': score.get('grade'),
        'timing': score.get('details', {}).get('timing'),
        'regularity': score.get('details', {}).get('regularity'),
        'duration': score.get('details', {}).get('duration'),
        'recovery': score.get('details', {}).get('recovery'),
        'bedtime': preview.get('bedtime'),
        'wake_time': preview.get('wake_time'),
        'hours': preview.get('duration'),
    }
    history_path = repo / 'data' / 'report' / 'score_history.jsonl'
    history = append_or_replace_history(history_path, history_row)

    def period_avg(days: int, offset_days: int = 0) -> Optional[float]:
        end = now.date() - timedelta(days=offset_days)
        start = end - timedelta(days=days - 1)
        vals = []
        for x in history:
            try:
                d = datetime.strptime(x['date'], '%Y-%m-%d').date()
            except Exception:
                continue
            if start <= d <= end and isinstance(x.get('total'), (int, float)):
                vals.append(float(x['total']))
        return avg(vals)

    week_avg = period_avg(7, 0)
    prev_week_avg = period_avg(7, 7)
    month_avg = period_avg(30, 0)
    prev_month_avg = period_avg(30, 30)

    # Alerts
    alerts: List[str] = []
    bedtime = parse_dt(preview.get('bedtime', '') or '')
    if bedtime and (bedtime.hour > 0 or (bedtime.hour == 0 and bedtime.minute >= 30)):
        alerts.append('熬夜告警：最近一次入睡晚于 00:30。')
    if isinstance(score.get('details', {}).get('timing'), (int, float)) and score['details']['timing'] < 60:
        alerts.append('节律告警：入睡时序明显偏移，建议固定起床时间。')
    if metric_summary['sleep_total_h'] is not None and metric_summary['sleep_total_h'] < 6.5:
        alerts.append('睡眠债告警：统计期平均睡眠不足 6.5 小时。')

    # Diet + cross analysis
    diet_map = parse_diet(repo)
    today_diet = diet_map.get(date_key)
    corr_x, corr_y = [], []
    for x in history[-30:]:
        d = x.get('date')
        if not d or d not in diet_map:
            continue
        t = x.get('total')
        if not isinstance(t, (int, float)):
            continue
        corr_x.append(float(diet_map[d].get('calories', 0)))
        corr_y.append(float(t))

    cal_sleep_corr = pearson(corr_x, corr_y)

    # Nutrition adequacy (generic adult reference)
    nutrition_eval = None
    if today_diet:
        cal = today_diet.get('calories', 0)
        p = today_diet.get('protein_g', 0)
        c = today_diet.get('carbs_g', 0)
        f = today_diet.get('fat_g', 0)
        adequacy = []
        adequacy.append('热量偏低' if cal < 1400 else '热量偏高' if cal > 2600 else '热量基本合理')
        adequacy.append('蛋白偏低' if p < 60 else '蛋白充足')
        adequacy.append('碳水偏低' if c < 130 else '碳水偏高' if c > 350 else '碳水合理')
        adequacy.append('脂肪偏低' if f < 35 else '脂肪偏高' if f > 90 else '脂肪合理')
        nutrition_eval = {
            'calories': cal,
            'protein_g': p,
            'carbs_g': c,
            'fat_g': f,
            'evaluation': adequacy,
        }

    recs = recommend(metric_summary, score, today_diet)

    insights = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'period': {
            'text': period_text,
            'days': period_days,
            'aggregation': 'average' if period_days > 1 else 'single_day',
        },
        'latest_score': score,
        'core_metrics': metric_summary,
        'alerts': alerts,
        'trend': {
            'week_avg': week_avg,
            'prev_week_avg': prev_week_avg,
            'week_delta': (week_avg - prev_week_avg) if week_avg is not None and prev_week_avg is not None else None,
            'month_avg': month_avg,
            'prev_month_avg': prev_month_avg,
            'month_delta': (month_avg - prev_month_avg) if month_avg is not None and prev_month_avg is not None else None,
        },
        'diet_sleep_cross': {
            'days_with_both_data': len(corr_x),
            'calories_vs_sleep_score_corr': cal_sleep_corr,
            'today_nutrition': nutrition_eval,
            'note': '相关系数仅用于趋势观察，不用于医学诊断。',
        },
        'recommendations': recs,
    }

    out_json = repo / 'data' / 'report' / 'insights.json'
    out_md = repo / 'data' / 'report' / 'daily_health_report.md'
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(insights, ensure_ascii=False, indent=2), encoding='utf-8')

    m = metric_summary
    agg = '平均值' if period_days > 1 else '当日值'

    lines: List[str] = []
    lines.append(f"# 健康分析报告（{date_key}）")
    lines.append('')
    lines.append(f"统计窗口：`{period_text}`，指标展示口径：`{agg}`")
    lines.append('')
    lines.append('## 总结')
    lines.append(f"- 节律评分：**{score.get('total')} ({score.get('grade')})**")
    lines.append(f"- 关键风险：{('；'.join(alerts) if alerts else '无高优先级告警')}" )
    lines.append(f"- 本周趋势：近7天均分 `{fmt(week_avg,1)}`（较前7天 `{fmt(insights['trend']['week_delta'],1)}`）")
    lines.append('')
    lines.append('## 基础身体指标')
    lines.append(f"- 静息心率：`{fmt(m['rhr_avg'],1,' bpm')}`")
    lines.append(f"- 心率（最低/平均/最高）：`{fmt(m['hr_min'],1)}` / `{fmt(m['hr_avg'],1)}` / `{fmt(m['hr_max'],1)} bpm`")
    lines.append(f"- 血氧饱和度：`{fmt(m['spo2_avg_pct'],2,' %')}`")
    lines.append(f"- 手腕温度：`{fmt(m['wrist_temp_avg_c'],2,' °C')}`")
    lines.append('')
    lines.append('## 睡眠结构')
    lines.append(f"- 睡眠总时长：`{fmt(m['sleep_total_h'],2,' h')}`")
    lines.append(f"- 深度睡眠：`{fmt(m['sleep_deep_h'],2,' h')}`")
    lines.append(f"- REM 眼动：`{fmt(m['sleep_rem_h'],2,' h')}`")
    lines.append(f"- 清醒时长：`{fmt(m['sleep_awake_h'],2,' h')}`")
    lines.append('')
    lines.append('## 饮食与睡眠交叉分析')
    if nutrition_eval:
        lines.append(f"- 当日摄入：热量 `{fmt(nutrition_eval['calories'],0,' kcal')}`，蛋白 `{fmt(nutrition_eval['protein_g'],1,' g')}`，碳水 `{fmt(nutrition_eval['carbs_g'],1,' g')}`，脂肪 `{fmt(nutrition_eval['fat_g'],1,' g')}`")
        lines.append(f"- 营养评价：{'；'.join(nutrition_eval['evaluation'])}")
    else:
        lines.append('- 未检测到可用饮食数据，已跳过营养评价。')
    lines.append(f"- 近30天热量 vs 睡眠评分相关系数：`{fmt(cal_sleep_corr,2)}`（样本天数 `{len(corr_x)}`）")
    lines.append('')
    lines.append('## 执行建议')
    for r in recs:
        lines.append(f"- {r}")

    out_md.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'ok': True, 'out_json': str(out_json), 'out_md': str(out_md)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
