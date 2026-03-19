from __future__ import annotations

import argparse
import csv
import json
import os
import re
import urllib.error
import urllib.request
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


def pick_number(record: Dict[str, Any], *keys: str) -> Optional[float]:
    # Preserve numeric zero: `or` treats 0 as falsy and may skip valid data.
    for k in keys:
        if k in record and record.get(k) is not None:
            return to_float(record.get(k))
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
        dt = parse_dt(
            r.get('date')
            or r.get('startDate')
            or r.get('start')
            or r.get('timestamp')
            or r.get('sleepEnd')
            or r.get('sleepStart')
        )
        if dt is not None:
            out.append(dt)
    return out


def count_on_date(series: List[Dict[str, Any]], day: str) -> int:
    n = 0
    for r in series:
        dt = parse_dt(
            r.get('date')
            or r.get('startDate')
            or r.get('start')
            or r.get('timestamp')
            or r.get('sleepEnd')
            or r.get('sleepStart')
        )
        if dt is None:
            continue
        if dt.date().isoformat() == day:
            n += 1
    return n


def select_recent(series: List[Dict[str, Any]], days: int, now: datetime) -> List[Dict[str, Any]]:
    out = []
    for r in series:
        dt = parse_dt(
            r.get('date')
            or r.get('startDate')
            or r.get('start')
            or r.get('timestamp')
            or r.get('sleepEnd')
            or r.get('sleepStart')
        )
        if dt is None:
            continue
        if dt.tzinfo is None and now.tzinfo is not None:
            dt = dt.replace(tzinfo=now.tzinfo)
        if now - dt <= timedelta(days=days):
            out.append(r)
    return out


def select_day(series: List[Dict[str, Any]], day_key: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in series:
        dt = parse_dt(
            r.get('date')
            or r.get('startDate')
            or r.get('start')
            or r.get('timestamp')
            or r.get('sleepEnd')
            or r.get('sleepStart')
        )
        if dt is None:
            continue
        if dt.date().isoformat() == day_key:
            out.append(r)
    return out


def select_between(series: List[Dict[str, Any]], start: datetime, end: datetime, now: datetime) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in series:
        dt = parse_dt(
            r.get('date')
            or r.get('startDate')
            or r.get('start')
            or r.get('timestamp')
            or r.get('sleepEnd')
            or r.get('sleepStart')
        )
        if dt is None:
            continue
        if dt.tzinfo is None and now.tzinfo is not None:
            dt = dt.replace(tzinfo=now.tzinfo)
        if start <= dt <= end:
            out.append(r)
    return out


def summarize_heart_rate(series: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    mins, maxs, avgs = [], [], []
    for r in series:
        v = pick_number(r, 'qty', 'value')
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


def summarize_activity(
    step_series: List[Dict[str, Any]],
    exercise_series: List[Dict[str, Any]],
    active_energy_series: List[Dict[str, Any]],
    flights_series: List[Dict[str, Any]],
    distance_series: List[Dict[str, Any]],
) -> Dict[str, Optional[float]]:
    def daily_sum(series: List[Dict[str, Any]], is_kj: bool = False) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for r in series:
            dt = parse_dt(r.get('date') or r.get('startDate') or r.get('timestamp'))
            v = pick_number(r, 'qty', 'value')
            if dt is None or v is None:
                continue
            if is_kj:
                v = v / 4.184  # kJ -> kcal
            d = dt.date().isoformat()
            out[d] = out.get(d, 0.0) + float(v)
        return out

    steps_day = daily_sum(step_series)
    exercise_day = daily_sum(exercise_series)
    active_kcal_day = daily_sum(active_energy_series, is_kj=True)
    flights_day = daily_sum(flights_series)
    distance_day = daily_sum(distance_series)

    def avg_day(m: Dict[str, float]) -> Optional[float]:
        return avg(list(m.values())) if m else None

    def sum_day(m: Dict[str, float]) -> Optional[float]:
        return sum(m.values()) if m else None

    return {
        'steps_avg': avg_day(steps_day),
        'steps_total': sum_day(steps_day),
        'exercise_min_avg': avg_day(exercise_day),
        'exercise_min_total': sum_day(exercise_day),
        'active_kcal_avg': avg_day(active_kcal_day),
        'active_kcal_total': sum_day(active_kcal_day),
        'flights_avg': avg_day(flights_day),
        'flights_total': sum_day(flights_day),
        'distance_km_avg': avg_day(distance_day),
        'distance_km_total': sum_day(distance_day),
    }


def _to_bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ('1', 'true', 'yes', 'y'):
            return True
        if s in ('0', 'false', 'no', 'n'):
            return False
    return None


def _pick_nested_value(record: Dict[str, Any], paths: List[str]) -> Any:
    for p in paths:
        cur: Any = record
        ok = True
        for part in p.split('.'):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok:
            return cur
    return None


def _normalize_workout_type(record: Dict[str, Any]) -> str:
    raw = (
        record.get('workoutActivityType')
        or record.get('activityType')
        or record.get('workoutType')
        or record.get('type')
        or record.get('name')
        or ''
    )
    s = str(raw).strip().lower()
    s = s.replace('hkworkoutactivitytype', '')

    indoor = _to_bool(
        _pick_nested_value(
            record,
            [
                'isIndoor',
                'indoor',
                'metadata.HKIndoorWorkout',
                'metadata.HKMetadataKeyIndoorWorkout',
                'metadata.indoor',
            ],
        )
    )

    if 'running' in s or 'run' in s:
        if indoor is True:
            return '室内跑步'
        if indoor is False:
            return '室外跑步'
        return '跑步'
    if 'elliptical' in s:
        return '椭圆机'
    if 'swimming' in s or 'swim' in s:
        if 'open' in s:
            return '公开水域游泳'
        if 'pool' in s:
            return '泳池游泳'
        return '游泳'
    if 'walking' in s or 'walk' in s:
        return '步行'
    if 'cycling' in s or 'bike' in s:
        return '骑行'
    if 'rowing' in s:
        return '划船机'
    if 'stair' in s:
        return '爬楼训练'
    # Chinese labels fallback
    if '跑' in s:
        if indoor is True:
            return '室内跑步'
        if indoor is False:
            return '室外跑步'
        return '跑步'
    if '椭圆' in s:
        return '椭圆机'
    if '游泳' in s:
        return '游泳'
    if '骑行' in s:
        return '骑行'
    if '步行' in s:
        return '步行'
    return '其他训练'


def _workout_duration_min(record: Dict[str, Any]) -> Optional[float]:
    v = (
        to_float(record.get('durationMin'))
        or to_float(record.get('durationMinutes'))
        or to_float(record.get('duration_min'))
    )
    if v is not None:
        return v

    v = to_float(record.get('duration') or record.get('workoutDuration'))
    if v is not None:
        unit = str(record.get('durationUnit') or record.get('unit') or '').lower()
        if 'sec' in unit:
            return v / 60.0
        if unit in ('h', 'hour', 'hours'):
            return v * 60.0
        # auto-export workout duration is often seconds without explicit unit
        if v > 300:
            return v / 60.0
        return v

    st = parse_dt(str(record.get('startDate') or record.get('start') or record.get('date') or ''))
    ed = parse_dt(str(record.get('endDate') or record.get('end') or ''))
    if st is not None and ed is not None and ed > st:
        return (ed - st).total_seconds() / 60.0
    return None


def _workout_distance_km(record: Dict[str, Any]) -> Optional[float]:
    candidates = [
        record.get('totalDistance'),
        record.get('distance'),
        record.get('walkingAndRunningDistance'),
    ]
    for raw in candidates:
        if raw is None:
            continue
        if isinstance(raw, dict):
            v = pick_number(raw, 'qty', 'value')
            unit = str(raw.get('units') or raw.get('unit') or '')
        else:
            v = to_float(raw)
            unit = str(record.get('distanceUnit') or record.get('distance_unit') or record.get('unit') or '')
        if v is None:
            continue
        unit = unit.lower()
        if unit in ('m', 'meter', 'meters'):
            return v / 1000.0
        return v
    return None


def _workout_active_kcal(record: Dict[str, Any]) -> Optional[float]:
    raw = record.get('activeEnergyBurned') or record.get('totalEnergyBurned') or record.get('energy')
    # handle series-form activeEnergy samples
    if raw is None and isinstance(record.get('activeEnergy'), list):
        total_kj = 0.0
        total_kcal = 0.0
        for x in record.get('activeEnergy') or []:
            if not isinstance(x, dict):
                continue
            q = pick_number(x, 'qty', 'value')
            if q is None:
                continue
            unit = str(x.get('units') or x.get('unit') or '').lower()
            if 'kj' in unit:
                total_kj += q
            else:
                total_kcal += q
        kcal = total_kcal + (total_kj / 4.184)
        return kcal if kcal > 0 else None

    if isinstance(raw, dict):
        v = pick_number(raw, 'qty', 'value')
        unit = str(raw.get('units') or raw.get('unit') or '')
    else:
        v = to_float(raw)
        unit = str(record.get('energyUnit') or record.get('energy_unit') or record.get('unit') or '')
    if v is None:
        return None
    if 'kj' in unit.lower():
        return v / 4.184
    return v


def _workout_avg_hr_bpm(record: Dict[str, Any]) -> Optional[float]:
    v = to_float(record.get('avgHeartRate') or record.get('averageHeartRate'))
    if v is not None:
        return v
    hr = record.get('heartRate')
    if isinstance(hr, dict):
        v = pick_number(hr, 'qty', 'Avg', 'avg', 'value')
        if v is not None:
            return v
    data = record.get('heartRateData')
    if isinstance(data, list):
        vals = [pick_number(x, 'Avg', 'avg', 'qty', 'value') for x in data if isinstance(x, dict)]
        vals = [x for x in vals if x is not None]
        if vals:
            return avg(vals)
    return None


def _workout_pace_min_per_km(record: Dict[str, Any], duration_min: Optional[float], distance_km: Optional[float]) -> Optional[float]:
    sp = record.get('speed')
    if isinstance(sp, dict):
        v = pick_number(sp, 'qty', 'value')
        units = str(sp.get('units') or sp.get('unit') or '').lower()
        if v is not None:
            if 'km/hr' in units or 'km/h' in units or units == 'kmhr':
                return 60.0 / v if v > 0 else None
            if 'm/s' in units:
                kmh = v * 3.6
                return 60.0 / kmh if kmh > 0 else None
    if duration_min is not None and distance_km is not None and distance_km > 0:
        return duration_min / distance_km
    return None


def summarize_workout_today(workout_series: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_type: Dict[str, Dict[str, Any]] = {}
    total_duration = 0.0
    total_distance = 0.0
    total_pace_weighted = 0.0
    total_pace_weight = 0.0
    hr_vals: List[float] = []

    for r in workout_series:
        if not isinstance(r, dict):
            continue
        t = _normalize_workout_type(r)
        dmin = _workout_duration_min(r)
        dkm = _workout_distance_km(r)
        hr = _workout_avg_hr_bpm(r)
        pace = _workout_pace_min_per_km(r, dmin, dkm)
        row = by_type.setdefault(t, {'duration': 0.0, 'distance': 0.0, 'hr_vals': [], 'pace_w': 0.0, 'pace_wv': 0.0})
        if dmin is not None:
            total_duration += dmin
            row['duration'] += dmin
        if dkm is not None:
            total_distance += dkm
            row['distance'] += dkm
        if hr is not None:
            hr_vals.append(hr)
            row['hr_vals'].append(hr)
        if pace is not None:
            w = dkm if (dkm is not None and dkm > 0) else 1.0
            total_pace_weight += w
            total_pace_weighted += pace * w
            row['pace_w'] += w
            row['pace_wv'] += pace * w

    type_rows = []
    for k, v in by_type.items():
        type_rows.append(
            {
                'type': k,
                'duration_min': round(v['duration'], 1) if v['duration'] > 0 else None,
                'distance_km': round(v['distance'], 2) if v['distance'] > 0 else None,
                'pace_min_per_km': round(v['pace_wv'] / v['pace_w'], 2) if v['pace_w'] > 0 else None,
                'avg_hr_bpm': round(avg(v['hr_vals']), 1) if v['hr_vals'] else None,
            }
        )
    type_rows.sort(key=lambda x: (x['type']))

    return {
        'duration_min': round(total_duration, 1) if total_duration > 0 else None,
        'distance_km': round(total_distance, 2) if total_distance > 0 else None,
        'pace_min_per_km': round(total_pace_weighted / total_pace_weight, 2) if total_pace_weight > 0 else None,
        'avg_hr_bpm': round(avg(hr_vals), 1) if hr_vals else None,
        'types': type_rows,
    }


def summarize_workout_window_avg(workout_series: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for r in workout_series:
        if not isinstance(r, dict):
            continue
        dt = parse_dt(str(r.get('startDate') or r.get('start') or r.get('date') or ''))
        if dt is None:
            continue
        day = dt.date().isoformat()
        by_day.setdefault(day, []).append(r)

    day_summaries = [summarize_workout_today(rows) for rows in by_day.values()]
    dur = [x['duration_min'] for x in day_summaries if isinstance(x.get('duration_min'), (int, float))]
    dist = [x['distance_km'] for x in day_summaries if isinstance(x.get('distance_km'), (int, float))]
    pace = [x['pace_min_per_km'] for x in day_summaries if isinstance(x.get('pace_min_per_km'), (int, float))]
    hr = [x['avg_hr_bpm'] for x in day_summaries if isinstance(x.get('avg_hr_bpm'), (int, float))]

    return {
        'days_with_workout': len(by_day),
        'duration_min_avg': round(avg(dur), 1) if dur else None,
        'distance_km_avg': round(avg(dist), 2) if dist else None,
        'pace_min_per_km_avg': round(avg(pace), 2) if pace else None,
        'avg_hr_bpm_avg': round(avg(hr), 1) if hr else None,
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
    '芝麻糊': (180, 4, 22, 8),
    '鸡胸': (180, 32, 0, 4),
    '鱼': (220, 30, 3, 9),
    '虾仁': (99, 24, 0.2, 0.3),
    '章鱼': (82, 14, 2, 1),
    '蘑菇': (22, 3, 3, 0.3),
    '番茄': (18, 0.9, 3.9, 0.2),
    '西葫芦': (17, 1.2, 3.1, 0.3),
    '大米': (220, 4, 50, 0.5),
}

PORTION_FACTOR = {
    '半': 0.5,
    '小': 0.7,
    '大': 1.3,
}


FOOD_ALIASES = {
    '水煮蛋': '鸡蛋',
    '白煮蛋': '鸡蛋',
    '煎蛋': '鸡蛋',
    '油煎蛋': '鸡蛋',
    '蒸蛋': '鸡蛋',
    '炖蛋': '鸡蛋',
    '蛋羹': '鸡蛋',
    '荷包蛋': '鸡蛋',
    '炒蛋': '鸡蛋',
    '煮鸡蛋': '鸡蛋',
    '鸡子': '鸡蛋',
    '海虾仁': '虾仁',
    '八抓鱼': '章鱼',
    '八爪鱼': '章鱼',
    '小番茄': '番茄',
}

EGG_COOKING_MARKERS = ('水煮', '白煮', '油煎', '煎', '蒸', '炖', '炒', '荷包')
QUANTITY_MAP = {
    '半': 0.5,
    '一': 1.0,
    '两': 2.0,
    '二': 2.0,
    '三': 3.0,
    '四': 4.0,
}
NOISE_WORDS = (
    '今天', '早上', '中午', '晚上', '吃了', '一个', '一份', '一碗', '包含', '轻食', '能量碗', '西班牙',
)


def normalize_food_text(text: str) -> str:
    t = text or ''
    for src, dst in FOOD_ALIASES.items():
        t = t.replace(src, dst)
    return t


def _contains_egg_variant(token: str) -> bool:
    if '蛋' not in token:
        return False
    if '鸡蛋' in token:
        return True
    return any(m in token for m in EGG_COOKING_MARKERS)


def _clean_token(token: str) -> str:
    t = token.strip()
    for x in NOISE_WORDS:
        t = t.replace(x, '')
    return t.strip()


def _quantity_factor(token: str) -> float:
    t = token.strip()
    # e.g. 2个鸡蛋 / 3颗蛋
    m = re.search(r'(\d+(?:\.\d+)?)\s*(个|颗|只|枚)', t)
    if m:
        try:
            return max(0.1, float(m.group(1)))
        except ValueError:
            pass
    # e.g. 两个鸡蛋 / 三颗蛋
    m2 = re.search(r'(半|一|两|二|三|四)\s*(个|颗|只|枚)', t)
    if m2:
        return QUANTITY_MAP.get(m2.group(1), 1.0)
    return 1.0


def _portion_factor(token: str) -> float:
    t = token.strip()
    f = 1.0
    # keep "小番茄/小蘑菇" from being treated as smaller portion
    if re.search(r'(^|[^一-龥])半(份|碗|盘|个)?', t):
        f *= PORTION_FACTOR['半']
    if re.search(r'(小份|小碗|小盘|少量)', t) and '米饭' not in t:
        f *= PORTION_FACTOR['小']
    if re.search(r'(大份|大碗|大盘|加量)', t) and '米饭' not in t:
        f *= PORTION_FACTOR['大']
    return f


def _fuzzy_match_food(token: str) -> Optional[str]:
    # direct include first
    for key in sorted(FOOD_DB.keys(), key=len, reverse=True):
        if key in token:
            return key

    # normalized token fallback
    t = _clean_token(token)
    if not t:
        return None
    if _contains_egg_variant(t):
        return '鸡蛋'

    # simple char-overlap scoring for tolerant matching
    tset = set(t)
    best_key = None
    best_score = 0.0
    for key in FOOD_DB.keys():
        kset = set(key)
        inter = len(tset & kset)
        if inter == 0:
            continue
        score = inter / max(1, len(kset))
        if score > best_score:
            best_score = score
            best_key = key
    return best_key if best_score >= 0.66 else None


def _ai_fallback_enabled() -> bool:
    v = os.environ.get('HEALTH_DIET_AI_FALLBACK', '').strip().lower()
    return v in ('1', 'true', 'yes', 'on')


def _to_float0(v: Any) -> float:
    x = to_float(v)
    return float(x) if x is not None else 0.0


def _ai_estimate_meal(description: str) -> Optional[Tuple[Dict[str, float], List[str]]]:
    if not _ai_fallback_enabled():
        return None
    api_key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not api_key:
        return None

    base_url = os.environ.get('HEALTH_DIET_AI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
    model = os.environ.get('HEALTH_DIET_AI_MODEL', 'gpt-4.1-mini').strip()
    url = f'{base_url}/chat/completions'
    prompt = (
        '你是营养估算器。只返回JSON，不要解释。'
        '根据这段饮食描述，估算总热量和三大营养素，并列出识别到的食物。'
        '输出格式: {"calories":number,"protein_g":number,"carbs_g":number,"fat_g":number,"items":["..."]}'
    )
    payload = {
        'model': model,
        'temperature': 0.1,
        'messages': [
            {'role': 'system', 'content': prompt},
            {'role': 'user', 'content': description},
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        method='POST',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    try:
        text = body['choices'][0]['message']['content']
        if isinstance(text, list):
            text = ''.join(str(x.get('text', '')) for x in text if isinstance(x, dict))
        text = str(text).strip()
        m = re.search(r'\{[\s\S]*\}', text)
        if not m:
            return None
        obj = json.loads(m.group(0))
    except Exception:
        return None

    est = {
        'calories': _to_float0(obj.get('calories')),
        'protein_g': _to_float0(obj.get('protein_g')),
        'carbs_g': _to_float0(obj.get('carbs_g')),
        'fat_g': _to_float0(obj.get('fat_g')),
    }
    items = obj.get('items')
    matched = [str(x) for x in items if isinstance(x, (str, int, float))] if isinstance(items, list) else []
    return est, matched


def estimate_meal(description: str) -> Tuple[Dict[str, float], List[str], str]:
    text = normalize_food_text((description or '').replace('，', ',').replace('、', ',').replace('+', ','))
    tokens = [t.strip() for t in text.split(',') if t.strip()]
    total = {'calories': 0.0, 'protein_g': 0.0, 'carbs_g': 0.0, 'fat_g': 0.0}
    matched: List[str] = []

    for tk in tokens:
        factor = _quantity_factor(tk) * _portion_factor(tk)
        if '一小碗米饭' in tk or '小碗米饭' in tk:
            base = FOOD_DB['小碗米饭']
            matched.append('小碗米饭')
        else:
            mk = _fuzzy_match_food(tk)
            base = FOOD_DB.get(mk) if mk else None
            if mk:
                matched.append(mk)

        if base is None:
            continue
        total['calories'] += base[0] * factor
        total['protein_g'] += base[1] * factor
        total['carbs_g'] += base[2] * factor
        total['fat_g'] += base[3] * factor

    # AI fallback: only when rule estimate is very sparse.
    if (not matched) or total['calories'] <= 80:
        ai = _ai_estimate_meal(description)
        if ai is not None:
            ai_total, ai_matched = ai
            if ai_total['calories'] > total['calories']:
                return ai_total, (ai_matched or matched), 'ai_fallback'
    return total, matched, 'rule'


def parse_diet(repo_dir: Path) -> Tuple[Dict[str, Dict[str, float]], Dict[str, List[Dict[str, Any]]]]:
    out: Dict[str, Dict[str, float]] = {}
    details: Dict[str, List[Dict[str, Any]]] = {}

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
                details.setdefault(d, []).append(
                    {
                        'timestamp': row.get('timestamp', ''),
                        'meal': row.get('meal', ''),
                        'description': row.get('description', ''),
                        'calories_est': round(to_float(row.get('calories')) or 0.0, 1),
                        'protein_g_est': round(to_float(row.get('protein_g')) or 0.0, 1),
                        'carbs_g_est': round(to_float(row.get('carbs_g')) or 0.0, 1),
                        'fat_g_est': round(to_float(row.get('fat_g')) or 0.0, 1),
                        'matched_items': '',
                        'source': 'numeric_log',
                    }
                )

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
                est, matched, method = estimate_meal(desc)
                d = dt.date().isoformat()
                x = out.setdefault(d, {'calories': 0.0, 'protein_g': 0.0, 'carbs_g': 0.0, 'fat_g': 0.0, 'meals': 0.0})
                for k in ('calories', 'protein_g', 'carbs_g', 'fat_g'):
                    x[k] += est[k]
                x['meals'] += 1
                details.setdefault(d, []).append(
                    {
                        'timestamp': row.get('timestamp', ''),
                        'meal': row.get('meal', ''),
                        'description': desc,
                        'calories_est': round(est['calories'], 1),
                        'protein_g_est': round(est['protein_g'], 1),
                        'carbs_g_est': round(est['carbs_g'], 1),
                        'fat_g_est': round(est['fat_g'], 1),
                        'matched_items': '|'.join(matched),
                        'source': f'meal_text_log_estimated_{method}',
                    }
                )
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

    for d in details:
        details[d].sort(key=lambda x: x.get('timestamp', ''))

    return out, details


def recommend_by_dimension(
    metrics: Dict[str, Optional[float]],
    activity: Dict[str, Optional[float]],
    score: Dict[str, Any],
    diet_day: Optional[Dict[str, float]],
) -> Dict[str, List[str]]:
    rec = {'摄入': [], '作息': [], '运动': []}

    # 摄入
    if diet_day:
        cal = diet_day.get('calories', 0)
        p = diet_day.get('protein_g', 0)
        c = diet_day.get('carbs_g', 0)
        if cal < 1400:
            rec['摄入'].append('当日热量偏低，建议加一份主食或优质脂肪，避免恢复不足。')
        elif cal > 2600:
            rec['摄入'].append('当日热量偏高，晚餐主食减量并控制烹调油。')
        if p < 60:
            rec['摄入'].append('蛋白偏低，建议每餐补充鱼/蛋/瘦肉/豆制品，目标≥60g/日。')
        if c < 130:
            rec['摄入'].append('碳水偏低，若有训练建议补充全谷物和薯类。')
    else:
        rec['摄入'].append('今日未记录摄入，建议至少记录主餐以启用营养针对性建议。')

    # 作息
    if metrics.get('sleep_total_h') is not None and metrics['sleep_total_h'] < 7:
        rec['作息'].append('睡眠时长不足，未来7天将入睡时间前移20-30分钟，目标7-8.5小时。')
    if metrics.get('sleep_deep_h') is not None and metrics['sleep_deep_h'] < 1.0:
        rec['作息'].append('深睡偏低：睡前90分钟避免强光与高强度运动，晚餐减少酒精重油。')
    if score.get('details', {}).get('timing') is not None and score['details']['timing'] < 60:
        rec['作息'].append('节律偏移：固定起床时间（含周末），将周末作息差控制在1小时内。')
    if metrics.get('spo2_avg_pct') is not None and metrics['spo2_avg_pct'] < 95:
        rec['作息'].append('血氧偏低，关注鼻塞/打鼾；若持续偏低建议做睡眠医学评估。')

    # 运动
    if activity.get('exercise_min_avg') is not None and activity['exercise_min_avg'] < 30:
        rec['运动'].append('运动时长偏低：每周至少150分钟中等强度有氧，可拆分为每日30分钟。')
    if activity.get('steps_avg') is not None and activity['steps_avg'] < 7000:
        rec['运动'].append('步数偏低：建议日均步数提升到7000-10000步。')
    if metrics.get('rhr_avg') is not None and metrics['rhr_avg'] >= 70:
        rec['运动'].append('静息心率偏高：优先中低强度有氧+规律力量训练，避免连续高强度冲刺。')
    if activity.get('active_kcal_avg') is not None and activity['active_kcal_avg'] < 300:
        rec['运动'].append('活动能量偏低：增加通勤步行、爬楼或晚间快走，提升日常活动消耗。')

    # defaults
    for k in rec:
        if not rec[k]:
            rec[k].append('当前维度整体表现可接受，按现有节奏持续并每周复盘一次。')
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
    score_meta = latest_score.get('score_meta', {})
    preview = latest_score.get('input_preview', {})
    latest_data = load_json(latest_data_path)
    metrics_map = get_metrics_map(latest_data)

    now = datetime.now().astimezone()

    wake_dt = parse_dt(preview.get('wake_time', ''))
    date_key = wake_dt.date().isoformat() if wake_dt else now.date().isoformat()

    # Daily report: strict day window only.
    hr_series = select_day(parse_metric_series(metrics_map.get('heartRate')), date_key)
    rhr_series = select_day(parse_metric_series(metrics_map.get('restingHeartRate')), date_key)
    spo2_series = select_day(parse_metric_series(metrics_map.get('oxygenSaturation')), date_key)
    # Wrist temperature is sleep-associated and often timestamped before midnight;
    # use bedtime->wake window to avoid losing valid same-night samples.
    temp_base = parse_metric_series(metrics_map.get('appleSleepingWristTemperature'))
    bedtime_dt = parse_dt(preview.get('bedtime', '')) if isinstance(preview, dict) else None
    wake_time_dt = parse_dt(preview.get('wake_time', '')) if isinstance(preview, dict) else None
    if bedtime_dt is not None and wake_time_dt is not None:
        temp_series = select_between(temp_base, bedtime_dt - timedelta(hours=6), wake_time_dt + timedelta(hours=6), now)
    else:
        temp_series = select_day(temp_base, date_key)
    sleep_series = select_day(parse_metric_series(metrics_map.get('sleepAnalysis')), date_key)
    step_series = select_day(parse_metric_series(metrics_map.get('stepCount')), date_key)
    exercise_series = select_day(parse_metric_series(metrics_map.get('appleExerciseTime')), date_key)
    active_energy_series = select_day(parse_metric_series(metrics_map.get('activeEnergyBurned')), date_key)
    flights_series = select_day(parse_metric_series(metrics_map.get('flightsClimbed')), date_key)
    distance_series = select_day(parse_metric_series(metrics_map.get('walkingRunningDistance')), date_key)
    workout_all_series = parse_metric_series(
        metrics_map.get('workout')
        or metrics_map.get('workouts')
        or metrics_map.get('appleWorkout')
    )
    workout_series = select_day(workout_all_series, date_key)
    workout_series_7d = select_recent(workout_all_series, 7, now)
    workout_series_30d = select_recent(workout_all_series, 30, now)

    hr_sum = summarize_heart_rate(hr_series)
    rhr_vals = [pick_number(r, 'qty', 'value') for r in rhr_series]
    rhr_vals = [x for x in rhr_vals if x is not None]

    spo2_vals = [pick_number(r, 'qty', 'value') for r in spo2_series]
    spo2_vals = [x for x in spo2_vals if x is not None]
    # normalize [0,1] to percentage
    spo2_vals = [x * 100 if x <= 1.0 else x for x in spo2_vals]

    temp_vals = [pick_number(r, 'qty', 'value') for r in temp_series]
    temp_vals = [x for x in temp_vals if x is not None]

    sleep_sum = summarize_sleep(sleep_series)
    activity_sum = summarize_activity(step_series, exercise_series, active_energy_series, flights_series, distance_series)
    workout_today = summarize_workout_today(workout_series)
    workout_7d_avg = summarize_workout_window_avg(workout_series_7d)
    workout_30d_avg = summarize_workout_window_avg(workout_series_30d)

    # Determine period info (daily report only)
    period_days = 1
    period_text = f"{date_key} ~ {date_key} (1天)"

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
    diet_map, diet_details_map = parse_diet(repo)
    # Strict daily mode: only use diet records on the report date.
    # Do not fallback to previous days; otherwise "today" panel may show stale values.
    today_diet = diet_map.get(date_key)
    today_meals = diet_details_map.get(date_key, [])
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

    recs_by_dim = recommend_by_dimension(metric_summary, activity_sum, score, today_diet)
    recs = [f"[{k}] {item}" for k in ('摄入', '作息', '运动') for item in recs_by_dim[k]]

    required_daily = {
        'sleepAnalysis': sleep_series,
        'restingHeartRate': rhr_series,
        'heartRate': hr_series,
        'stepCount': step_series,
        'activeEnergyBurned': active_energy_series,
        'appleExerciseTime': exercise_series,
    }
    optional_daily = {
        'oxygenSaturation': spo2_series,
        'appleSleepingWristTemperature': temp_series,
        'flightsClimbed': flights_series,
        'walkingRunningDistance': distance_series,
        'workout': workout_series,
    }

    req_counts = {k: count_on_date(v, date_key) for k, v in required_daily.items()}
    opt_counts = {k: count_on_date(v, date_key) for k, v in optional_daily.items()}
    req_present = sum(1 for v in req_counts.values() if v > 0)
    req_total = len(required_daily)
    completeness_pct = round((req_present / req_total) * 100, 1) if req_total else None
    missing_required = [k for k, v in req_counts.items() if v == 0]

    data_quality = {
        'target_date': date_key,
        'required_metric_coverage_pct': completeness_pct,
        'required_present': req_present,
        'required_total': req_total,
        'missing_required_metrics': missing_required,
        'required_counts': req_counts,
        'optional_counts': opt_counts,
        'status': 'ok' if not missing_required else 'incomplete',
    }

    if missing_required:
        alerts.append('数据完整性告警：日报必需指标缺失（' + ', '.join(missing_required) + '）。')

    insights = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'period': {
            'text': period_text,
            'days': period_days,
            'aggregation': 'average' if period_days > 1 else 'single_day',
        },
        'latest_score': score,
        'score_meta': score_meta,
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
            'today_nutrition_date': date_key if nutrition_eval else None,
            'today_meals': today_meals,
            'note': '相关系数仅用于趋势观察，不用于医学诊断。',
        },
        'activity_summary': activity_sum,
        'workout_summary': {
            'today': workout_today,
            'avg_7d': workout_7d_avg,
            'avg_30d': workout_30d_avg,
            # legacy fields for backward compatibility
            'days_with_workout': workout_30d_avg.get('days_with_workout', 0),
            'sessions_total': len(workout_series),
            'duration_min_total': workout_today.get('duration_min'),
            'distance_km_total': workout_today.get('distance_km'),
            'types': workout_today.get('types', []),
        },
        'data_quality': data_quality,
        'recommendations_by_dimension': recs_by_dim,
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
    lines.append('## 数据完整性检查')
    lines.append(f"- 目标日期：`{data_quality['target_date']}`")
    lines.append(f"- 必需指标覆盖率：`{fmt(data_quality['required_metric_coverage_pct'],1,' %')}`（{data_quality['required_present']}/{data_quality['required_total']}）")
    lines.append(f"- 缺失必需指标：`{', '.join(data_quality['missing_required_metrics']) if data_quality['missing_required_metrics'] else '无'}`")
    lines.append('')

    lines.append('## 运动情况')
    lines.append(f"- 步数（日均）：`{fmt(activity_sum['steps_avg'],0,' 步')}`")
    lines.append(f"- 运动时长（日均）：`{fmt(activity_sum['exercise_min_avg'],1,' 分钟')}`")
    lines.append(f"- 活动能量（日均）：`{fmt(activity_sum['active_kcal_avg'],1,' kcal')}`")
    lines.append(f"- 爬楼层数（日均）：`{fmt(activity_sum['flights_avg'],1,' 层')}`")
    lines.append(f"- 步行/跑步距离（日均）：`{fmt(activity_sum['distance_km_avg'],2,' km')}`")
    lines.append('')
    lines.append('### 训练类型（当日）')
    lines.append(f"- 时长：`{fmt(workout_today.get('duration_min'),1,' 分钟')}`")
    lines.append(f"- 里程：`{fmt(workout_today.get('distance_km'),2,' km')}`")
    lines.append(f"- 配速：`{fmt(workout_today.get('pace_min_per_km'),2,' min/km')}`")
    lines.append(f"- 平均心率：`{fmt(workout_today.get('avg_hr_bpm'),1,' bpm')}`")
    if workout_today.get('types'):
        for x in workout_today['types'][:8]:
            lines.append(
                "- "
                + f"{x.get('type')}：时长 `{fmt(x.get('duration_min'),1,' 分钟')}`"
                + f"，里程 `{fmt(x.get('distance_km'),2,' km')}`"
                + f"，配速 `{fmt(x.get('pace_min_per_km'),2,' min/km')}`"
                + f"，平均心率 `{fmt(x.get('avg_hr_bpm'),1,' bpm')}`"
            )
    else:
        lines.append('- 当日未检测到训练类型数据。')
    lines.append('')
    lines.append('### 近7天运动均值')
    lines.append(f"- 时长：`{fmt(workout_7d_avg.get('duration_min_avg'),1,' 分钟')}`")
    lines.append(f"- 里程：`{fmt(workout_7d_avg.get('distance_km_avg'),2,' km')}`")
    lines.append(f"- 配速：`{fmt(workout_7d_avg.get('pace_min_per_km_avg'),2,' min/km')}`")
    lines.append(f"- 平均心率：`{fmt(workout_7d_avg.get('avg_hr_bpm_avg'),1,' bpm')}`")
    lines.append('')
    lines.append('### 近30天运动均值')
    lines.append(f"- 时长：`{fmt(workout_30d_avg.get('duration_min_avg'),1,' 分钟')}`")
    lines.append(f"- 里程：`{fmt(workout_30d_avg.get('distance_km_avg'),2,' km')}`")
    lines.append(f"- 配速：`{fmt(workout_30d_avg.get('pace_min_per_km_avg'),2,' min/km')}`")
    lines.append(f"- 平均心率：`{fmt(workout_30d_avg.get('avg_hr_bpm_avg'),1,' bpm')}`")
    lines.append('')
    lines.append('## 饮食与睡眠交叉分析')
    if nutrition_eval:
        lines.append(f"- 当日摄入：热量 `{fmt(nutrition_eval['calories'],0,' kcal')}`，蛋白 `{fmt(nutrition_eval['protein_g'],1,' g')}`，碳水 `{fmt(nutrition_eval['carbs_g'],1,' g')}`，脂肪 `{fmt(nutrition_eval['fat_g'],1,' g')}`")
        lines.append(f"- 营养评价：{'；'.join(nutrition_eval['evaluation'])}")
        if today_meals:
            lines.append('- 当日三餐明细：')
            for meal in today_meals:
                meal_name = meal.get('meal') or 'meal'
                desc = meal.get('description') or ''
                lines.append(
                    f"  - `{meal_name}` {meal.get('timestamp','')}: {desc} "
                    f"（估算: {fmt(meal.get('calories_est'),0,' kcal')}, "
                    f"P {fmt(meal.get('protein_g_est'),1,' g')}, "
                    f"C {fmt(meal.get('carbs_g_est'),1,' g')}, "
                    f"F {fmt(meal.get('fat_g_est'),1,' g')}）"
                )
    else:
        lines.append('- 当日摄入：暂无')
        lines.append('- 营养评价：暂无')
    if len(corr_x) < 3:
        lines.append(f"- 热量 vs 睡眠评分相关：样本不足（当前 `{len(corr_x)}` 天，至少需要 3 天）。")
    else:
        lines.append(f"- 近30天热量 vs 睡眠评分相关系数：`{fmt(cal_sleep_corr,2)}`（样本天数 `{len(corr_x)}`）")
    lines.append('')
    lines.append('## 趋势')
    lines.append(f"- 近7天均分：`{fmt(week_avg,1)}`（较前7天 `{fmt(insights['trend']['week_delta'],1)}`）")
    lines.append(f"- 近30天均分：`{fmt(month_avg,1)}`（较前30天 `{fmt(insights['trend']['month_delta'],1)}`）")
    lines.append('')
    lines.append('## 执行建议')
    lines.append('### 摄入')
    for r in recs_by_dim['摄入']:
        lines.append(f"- {r}")
    lines.append('### 作息')
    for r in recs_by_dim['作息']:
        lines.append(f"- {r}")
    lines.append('### 运动')
    for r in recs_by_dim['运动']:
        lines.append(f"- {r}")

    out_md.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'ok': True, 'out_json': str(out_json), 'out_md': str(out_md)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
