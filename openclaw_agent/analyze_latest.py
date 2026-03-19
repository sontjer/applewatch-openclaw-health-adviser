from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sys
for p in ('/root/codex', '/root'):
    if p not in sys.path:
        sys.path.append(p)
from sleep_scorer_v21 import SleepScorerV21  # noqa: E402


ASLEEP_MARKERS = (
    'Asleep',
    'asleep',
    'HKCategoryValueSleepAnalysisAsleep',
)
INBED_MARKERS = (
    'InBed',
    'inBed',
    'HKCategoryValueSleepAnalysisInBed',
)


def parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    fmts = [
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%d %H:%M:%S %z',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%dT%H:%M:%S%z',
    ]
    for f in fmts:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None


def pick_time(record: Dict[str, Any], keys: List[str]) -> Optional[datetime]:
    for k in keys:
        v = record.get(k)
        if isinstance(v, str):
            dt = parse_dt(v)
            if dt is not None:
                return dt
    return None


def pick_float(record: Dict[str, Any], keys: List[str]) -> Optional[float]:
    for k in keys:
        v = record.get(k)
        try:
            if v is None:
                continue
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def normalize_series(series: Any) -> List[Dict[str, Any]]:
    if not isinstance(series, list):
        return []
    out = []
    for x in series:
        if isinstance(x, dict):
            out.append(x)
    return out


def normalize_metrics_map(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accepts:
    1) filtered worker payload: {"metrics": {key: [..]}}
    2) raw auto-export payload: {"data": {"metrics": [{"name": "...", "data": [...]}, ...]}}
    """
    if "metrics" in raw and isinstance(raw["metrics"], dict):
        return raw["metrics"]

    root = raw.get("data", raw)
    if not isinstance(root, dict):
        return {}

    m = root.get("metrics")
    if isinstance(m, dict):
        return m
    if isinstance(m, list):
        out: Dict[str, Any] = {}
        for item in m:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            data = item.get("data")
            if isinstance(name, str):
                out[name] = data
        return out
    return {}


def pick_metric(metrics: Dict[str, Any], *names: str) -> Any:
    for n in names:
        if n in metrics:
            return metrics[n]
    return None


def classify_sleep_value(v: Any) -> str:
    s = str(v)
    for m in ASLEEP_MARKERS:
        if m in s:
            return 'asleep'
    for m in INBED_MARKERS:
        if m in s:
            return 'inbed'
    return 'other'


def merge_intervals(intervals: List[Tuple[datetime, datetime]], gap_minutes: int = 45) -> List[Tuple[datetime, datetime]]:
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = [intervals[0]]
    for st, ed in intervals[1:]:
        lst, led = merged[-1]
        if st <= led + timedelta(minutes=gap_minutes):
            merged[-1] = (lst, max(led, ed))
        else:
            merged.append((st, ed))
    return merged


def derive_nights_from_sleep(series: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Format A: interval records with start/end + category values.
    # Format B: nightly aggregate records with sleepStart/sleepEnd/totalSleep.
    if series and isinstance(series[0], dict) and ("sleepStart" in series[0] or "sleepEnd" in series[0]):
        nights = []
        for r in series:
            st = pick_time(r, ["sleepStart", "inBedStart", "startDate", "start"])
            ed = pick_time(r, ["sleepEnd", "inBedEnd", "endDate", "end"])
            if st is None or ed is None or ed <= st:
                continue
            duration_h = pick_float(r, ["totalSleep", "inBed"])
            if duration_h is None or duration_h <= 0:
                duration_h = (ed - st).total_seconds() / 3600
            if duration_h < 2:
                continue
            mid = st + (ed - st) / 2
            night_key = (mid - timedelta(hours=12)).date().isoformat()
            night = {
                "night": night_key,
                "bedtime": st,
                "wake_time": ed,
                "duration_h": float(duration_h),
            }
            in_bed_h = pick_float(r, ["inBed"])
            if in_bed_h and in_bed_h > 0:
                night["efficiency"] = min(1.0, float(duration_h) / in_bed_h)
            nights.append(night)

        by_night: Dict[str, Dict[str, Any]] = {}
        for n in nights:
            k = n["night"]
            if k not in by_night or n["duration_h"] > by_night[k]["duration_h"]:
                by_night[k] = n
        return sorted(by_night.values(), key=lambda x: x["bedtime"])

    asleep_intervals: List[Tuple[datetime, datetime]] = []
    inbed_intervals: List[Tuple[datetime, datetime]] = []

    for r in series:
        st = pick_time(r, ['startDate', 'start', 'dateStart'])
        ed = pick_time(r, ['endDate', 'end', 'dateEnd'])
        if st is None or ed is None or ed <= st:
            continue

        kind = classify_sleep_value(r.get('value'))
        if kind == 'asleep':
            asleep_intervals.append((st, ed))
        elif kind == 'inbed':
            inbed_intervals.append((st, ed))

    merged_asleep = merge_intervals(asleep_intervals)
    merged_inbed = merge_intervals(inbed_intervals)

    nights = []
    for st, ed in merged_asleep:
        if (ed - st).total_seconds() < 2 * 3600:
            continue
        mid = st + (ed - st) / 2
        night_key = (mid - timedelta(hours=12)).date().isoformat()
        nights.append({
            'night': night_key,
            'bedtime': st,
            'wake_time': ed,
            'duration_h': (ed - st).total_seconds() / 3600,
        })

    # de-dup by night: keep longest interval
    by_night: Dict[str, Dict[str, Any]] = {}
    for n in nights:
        k = n['night']
        if k not in by_night or n['duration_h'] > by_night[k]['duration_h']:
            by_night[k] = n

    dedup = sorted(by_night.values(), key=lambda x: x['bedtime'])

    # efficiency proxy when inBed exists: asleep / inBed overlap by same night key
    inbed_by_night: Dict[str, float] = {}
    for st, ed in merged_inbed:
        mid = st + (ed - st) / 2
        k = (mid - timedelta(hours=12)).date().isoformat()
        inbed_by_night[k] = max(inbed_by_night.get(k, 0.0), (ed - st).total_seconds() / 3600)

    for n in dedup:
        ib = inbed_by_night.get(n['night'])
        if ib and ib > 0:
            n['efficiency'] = min(1.0, n['duration_h'] / ib)

    return dedup


def latest_numeric(series: List[Dict[str, Any]]) -> Optional[float]:
    best_t = None
    best_v = None
    for r in series:
        t = pick_time(r, ['date', 'startDate', 'start', 'timestamp'])
        v = pick_float(r, ['value', 'qty', 'amount'])
        if t is None or v is None:
            continue
        if (best_t is None) or (t > best_t):
            best_t = t
            best_v = v
    return best_v


def median_vals(vals: List[float]) -> Optional[float]:
    if not vals:
        return None
    xs = sorted(vals)
    n = len(xs)
    if n % 2 == 1:
        return xs[n // 2]
    return (xs[n // 2 - 1] + xs[n // 2]) / 2


def _align_tz(dt: datetime, ref: datetime) -> datetime:
    if dt.tzinfo is None and ref.tzinfo is not None:
        return dt.replace(tzinfo=ref.tzinfo)
    return dt


def window_median_numeric(
    series: List[Dict[str, Any]],
    start: datetime,
    end: datetime,
    now: datetime,
) -> Optional[float]:
    vals: List[float] = []
    st = _align_tz(start, now)
    ed = _align_tz(end, now)
    if ed <= st:
        return None
    for r in series:
        t = pick_time(r, ['date', 'startDate', 'start', 'timestamp'])
        v = pick_float(r, ['value', 'qty', 'amount'])
        if t is None or v is None:
            continue
        t = _align_tz(t, now)
        if st <= t <= ed:
            vals.append(v)
    return median_vals(vals)


def median_numeric(series: List[Dict[str, Any]], days: int = 28) -> Optional[float]:
    now = datetime.now().astimezone()
    vals = []
    for r in series:
        t = pick_time(r, ['date', 'startDate', 'start', 'timestamp'])
        v = pick_float(r, ['value', 'qty', 'amount'])
        if t is None or v is None:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=now.tzinfo)
        if (now - t).days <= days:
            vals.append(v)
    return median_vals(vals)


def build_input(filtered: Dict[str, Any]) -> Dict[str, Any]:
    metrics = normalize_metrics_map(filtered)

    sleep_series = normalize_series(pick_metric(metrics, 'sleepAnalysis', 'sleep_analysis'))
    nights = derive_nights_from_sleep(sleep_series)
    if len(nights) < 1:
        raise ValueError('not enough sleep nights parsed from sleepAnalysis')

    recent = nights[-7:]
    valid = []
    for x in recent:
        bt = x['bedtime']
        dur = float(x['duration_h'])
        # keep plausible overnight sleep windows
        if dur >= 4.5 and (bt.hour >= 18 or bt.hour <= 6):
            valid.append(x)
    last = valid[-1] if valid else recent[-1]

    hrv_series = normalize_series(pick_metric(metrics, 'heartRateVariabilitySDNN', 'heart_rate_variability'))
    rhr_series = normalize_series(pick_metric(metrics, 'restingHeartRate', 'resting_heart_rate'))
    rr_series = normalize_series(pick_metric(metrics, 'respiratoryRate', 'respiratory_rate'))

    now = datetime.now().astimezone()
    hrv = window_median_numeric(hrv_series, last['bedtime'], last['wake_time'], now)
    if hrv is None:
        # Safety fallback when sleep window has no HRV samples.
        hrv = latest_numeric(hrv_series)

    baseline_hrv_vals: List[float] = []
    for n in nights:
        bt = _align_tz(n['bedtime'], now)
        wt = _align_tz(n['wake_time'], now)
        if wt <= bt:
            continue
        if (now - wt).days > 28:
            continue
        v = window_median_numeric(hrv_series, bt, wt, now)
        if v is not None:
            baseline_hrv_vals.append(v)
    baseline_hrv = median_vals(baseline_hrv_vals)
    if baseline_hrv is None:
        baseline_hrv = median_numeric(hrv_series, 28)
    rhr = latest_numeric(rhr_series)
    baseline_rhr = median_numeric(rhr_series, 28)
    rr = latest_numeric(rr_series)
    baseline_rr = median_numeric(rr_series, 28)

    bedtime_list = [x['bedtime'] for x in recent]
    wake_list = [x['wake_time'] for x in recent]

    # weekend mid-sleep difference proxy
    weekday_mids = []
    weekend_mids = []
    for x in recent:
        st = x['bedtime']
        ed = x['wake_time']
        mid = st + (ed - st) / 2
        if st.weekday() >= 5:
            weekend_mids.append(mid)
        else:
            weekday_mids.append(mid)

    def avg_minutes(ds: List[datetime]) -> Optional[float]:
        if not ds:
            return None
        return sum(d.hour * 60 + d.minute for d in ds) / len(ds)

    wkd = avg_minutes(weekday_mids)
    wke = avg_minutes(weekend_mids)
    sjl = abs((wke - wkd) / 60.0) if (wkd is not None and wke is not None) else None

    return {
        'bedtime': last['bedtime'],
        'wake_time': last['wake_time'],
        'duration': float(last['duration_h']),
        'recent_bedtimes': bedtime_list,
        'recent_wake_times': wake_list,
        'recent_mid_sleeps': [x['bedtime'] + (x['wake_time'] - x['bedtime']) / 2 for x in recent],
        'weekend_mid_sleep_diff_hours': sjl,
        'sri_proxy': None,
        'hrv': hrv,
        'baseline_hrv': baseline_hrv,
        'rhr': rhr,
        'baseline_rhr': baseline_rhr,
        'resp_rate': rr,
        'baseline_resp_rate': baseline_rr,
        'sleep_efficiency': last.get('efficiency'),
        'waso_minutes': None,
        'awakenings': None,
        'quality_flags': {'sync_delay_hours': 0},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, help='Path to data/latest.json')
    parser.add_argument('--output', required=True, help='Path to write score json')
    args = parser.parse_args()

    raw = json.loads(Path(args.input).read_text(encoding='utf-8'))
    scorer_input = build_input(raw)

    scorer = SleepScorerV21()
    result = scorer.calculate(scorer_input)

    out = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'score': result,
        'input_preview': {
            'bedtime': scorer_input['bedtime'].isoformat(),
            'wake_time': scorer_input['wake_time'].isoformat(),
            'duration': scorer_input['duration'],
            'hrv': scorer_input['hrv'],
            'baseline_hrv': scorer_input['baseline_hrv'],
        },
    }

    op = Path(args.output)
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(out['score'], ensure_ascii=False))


if __name__ == '__main__':
    main()
