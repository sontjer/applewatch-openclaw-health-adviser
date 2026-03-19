/**
 * Apple Health Auto Export ingest worker
 *
 * Pipeline:
 * Auto Export -> Cloudflare Worker(filter + truncate + auth) -> GitHub private repo
 */

const DEFAULT_METRICS = [
  'heartRateVariabilitySDNN',
  'oxygenSaturation',
  'restingHeartRate',
  'respiratoryRate',
  'appleSleepingWristTemperature',
  'heartRate',
  'stepCount',
  'activeEnergyBurned',
  'basalEnergyBurned',
  'appleExerciseTime',
  'flightsClimbed',
  'vo2Max',
  'sleepAnalysis',
  'environmentalAudioExposure',
  'appleStandHour',
  'walkingRunningDistance',
  'workout',
];

const METRIC_ALIASES = {
  heartRateVariabilitySDNN: ['heartRateVariabilitySDNN', 'heart_rate_variability'],
  oxygenSaturation: ['oxygenSaturation', 'blood_oxygen_saturation'],
  restingHeartRate: ['restingHeartRate', 'resting_heart_rate'],
  respiratoryRate: ['respiratoryRate', 'respiratory_rate'],
  appleSleepingWristTemperature: ['appleSleepingWristTemperature', 'apple_sleeping_wrist_temperature'],
  heartRate: ['heartRate', 'heart_rate'],
  stepCount: ['stepCount', 'step_count'],
  activeEnergyBurned: ['activeEnergyBurned', 'active_energy'],
  basalEnergyBurned: ['basalEnergyBurned', 'basal_energy_burned'],
  appleExerciseTime: ['appleExerciseTime', 'apple_exercise_time'],
  flightsClimbed: ['flightsClimbed', 'flights_climbed'],
  vo2Max: ['vo2Max', 'vo2max', 'vo2_max'],
  sleepAnalysis: ['sleepAnalysis', 'sleep_analysis'],
  environmentalAudioExposure: ['environmentalAudioExposure', 'environmental_audio_exposure'],
  appleStandHour: ['appleStandHour', 'apple_stand_hour'],
  walkingRunningDistance: ['walkingRunningDistance', 'walking_running_distance'],
  workout: ['workout', 'workouts', 'appleWorkout', 'apple_workout'],
};

const CAPS = {
  // Report computes daily totals by summing per-record qty for many metrics.
  // Use high caps for additive minute-level series to avoid systemic undercount.
  heartRate: 2000,
  stepCount: 5000,
  activeEnergyBurned: 5000,
  appleExerciseTime: 2000,
  flightsClimbed: 2000,
  sleepAnalysis: 300,
  walkingRunningDistance: 5000,
  workout: 300,
  default: 300,
};

export default {
  async fetch(request, env) {
    const reqId = crypto.randomUUID();
    if (request.method !== 'POST') {
      console.log(
        JSON.stringify({
          event: 'reject_method',
          reqId,
          method: request.method,
          url: request.url,
        }),
      );
      return json({ ok: false, error: 'method_not_allowed' }, 405);
    }

    const auth = request.headers.get('X-Auth-Key');
    if (!auth || auth !== env.INGEST_KEY) {
      console.log(
        JSON.stringify({
          event: 'reject_auth',
          reqId,
          hasAuthHeader: Boolean(auth),
          url: request.url,
        }),
      );
      return json({ ok: false, error: 'unauthorized' }, 401);
    }

    const raw = await request.text();
    if (raw.length > (Number(env.MAX_REQ_BYTES || 2_000_000))) {
      console.log(
        JSON.stringify({
          event: 'reject_too_large',
          reqId,
          bytesIn: raw.length,
          maxBytes: Number(env.MAX_REQ_BYTES || 2_000_000),
        }),
      );
      return json({ ok: false, error: 'payload_too_large' }, 413);
    }

    let payload;
    try {
      payload = JSON.parse(raw);
    } catch {
      console.log(
        JSON.stringify({
          event: 'reject_invalid_json',
          reqId,
          bytesIn: raw.length,
        }),
      );
      return json({ ok: false, error: 'invalid_json' }, 400);
    }

    try {
      const whitelist = parseWhitelist(env.METRIC_WHITELIST);
      const filtered = filterAndTruncate(payload, whitelist);

      const now = new Date();
      const datePath = now.toISOString().slice(0, 10).replace(/-/g, '/');
      const stamp = now.toISOString().replace(/[:.]/g, '-');

      const latestPath = 'data/latest.json';
      const archivePath = `data/archive/${datePath}/${stamp}.json`;
      const manifestPath = 'data/manifests/ingest_log.jsonl';
      const ingestId = await sha256Hex(raw);

      const summary = {
        reqId,
        ts: now.toISOString(),
        metrics: Object.keys(filtered.metrics || {}),
        ingest_id: ingestId,
        bytes_in: raw.length,
        bytes_out: JSON.stringify(filtered).length,
        github: {
          owner: env.GITHUB_OWNER,
          repo: env.GITHUB_REPO,
          branch: env.GITHUB_BRANCH || 'main',
        },
      };

      console.log(JSON.stringify({ event: 'ingest_received', ...summary }));

      const body = {
        meta: {
          source: 'apple-health-auto-export',
          ingested_at: now.toISOString(),
          strategy: 'whitelist + stratified_tail_truncation + metric_key_merge_latest',
          ingest_id: ingestId,
          summary,
        },
        ...filtered,
      };

      const mergeInfo = await upsertLatestMerged(env, latestPath, body);
      await putGithubFile(env, archivePath, body, false);
      await appendGithubJsonl(env, manifestPath, {
        ts: now.toISOString(),
        ingest_id: ingestId,
        req_id: reqId,
        latest_path: latestPath,
        archive_path: archivePath,
        bytes_in: raw.length,
        bytes_out: JSON.stringify(filtered).length,
        merge: mergeInfo,
      });

      console.log(
        JSON.stringify({
          event: 'ingest_written',
          reqId,
          ingestId,
          latestPath,
          archivePath,
          manifestPath,
        }),
      );
      return json({ ok: true, summary, ingestId, latestPath, archivePath, manifestPath });
    } catch (e) {
      console.error(
        JSON.stringify({
          event: 'ingest_error',
          reqId,
          message: String(e && e.message ? e.message : e),
        }),
      );
      return json({ ok: false, error: 'internal_error', reqId }, 500);
    }
  },
};

function parseWhitelist(csv) {
  if (!csv || !csv.trim()) return DEFAULT_METRICS;
  return csv
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean);
}

function filterAndTruncate(payload, whitelist) {
  // supported source payloads:
  // 1) { data: { <metricKey>: [...] } }
  // 2) { data: { metrics: [ {name, data, units}, ... ] } }
  // 3) { metrics: { <metricKey>: [...] } } (already filtered shape)
  const data = payload?.data && typeof payload.data === 'object' ? payload.data : payload;
  const metricLookup = buildMetricLookup(data);
  const out = { metrics: {}, original_top_level_keys: Object.keys(payload || {}) };

  for (const key of whitelist) {
    const aliases = METRIC_ALIASES[key] || [key];
    let val = null;
    for (const a of aliases) {
      if (metricLookup[a] != null) {
        val = metricLookup[a];
        break;
      }
    }
    if (val == null) continue;

    if (Array.isArray(val)) {
      const cap = CAPS[key] || CAPS.default;
      out.metrics[key] = stratifiedTruncate(val, cap);
    } else {
      out.metrics[key] = val;
    }
  }

  return out;
}

function buildMetricLookup(data) {
  const lookup = {};
  if (!data || typeof data !== 'object') return lookup;

  // Direct object-style metrics.
  for (const [k, v] of Object.entries(data)) {
    if (k !== 'metrics') lookup[k] = v;
  }

  // Array-style metrics: [{name, data, units}]
  if (Array.isArray(data.metrics)) {
    for (const item of data.metrics) {
      if (!item || typeof item !== 'object') continue;
      if (typeof item.name !== 'string') continue;
      lookup[item.name] = item.data;
    }
  } else if (data.metrics && typeof data.metrics === 'object') {
    for (const [k, v] of Object.entries(data.metrics)) {
      lookup[k] = v;
    }
  }

  return lookup;
}

/**
 * Better than raw "latest N":
 * - preserve latest tail (for near real-time analysis)
 * - keep temporal coverage from older segment by bucket sampling
 */
function stratifiedTruncate(series, cap) {
  if (!Array.isArray(series) || series.length <= cap) return series;

  const tailN = Math.max(10, Math.floor(cap * 0.4));
  const headBudget = cap - tailN;

  const head = series.slice(0, series.length - tailN);
  const tail = series.slice(series.length - tailN);

  if (head.length <= headBudget) return [...head, ...tail];

  const buckets = Math.max(1, Math.floor(headBudget / 2));
  const bucketSize = Math.ceil(head.length / buckets);
  const sampled = [];

  for (let i = 0; i < head.length; i += bucketSize) {
    const chunk = head.slice(i, i + bucketSize);
    if (!chunk.length) continue;
    sampled.push(chunk[0]);
    if (chunk.length > 1) sampled.push(chunk[chunk.length - 1]);
  }

  return [...sampled.slice(0, headBudget), ...tail];
}

async function putGithubFile(env, path, contentObj, updateIfExists) {
  const owner = env.GITHUB_OWNER;
  const repo = env.GITHUB_REPO;
  const branch = env.GITHUB_BRANCH || 'main';
  const token = env.GITHUB_TOKEN;

  if (!owner || !repo || !token) {
    throw new Error('missing GitHub env vars');
  }

  const encodedPath = path
    .split('/')
    .map((p) => encodeURIComponent(p))
    .join('/');
  const endpoint = `https://api.github.com/repos/${owner}/${repo}/contents/${encodedPath}`;
  let sha;

  if (updateIfExists) {
    const getResp = await ghFetch(endpoint + `?ref=${encodeURIComponent(branch)}`, token, { method: 'GET' }, true);
    if (getResp && getResp.sha) sha = getResp.sha;
  }

  const text = JSON.stringify(contentObj, null, 2);
  const payload = {
    message: `[health] update ${path}`,
    content: toBase64(text),
    branch,
    sha,
  };

  await ghFetch(endpoint, token, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

async function getGithubFile(env, path) {
  const owner = env.GITHUB_OWNER;
  const repo = env.GITHUB_REPO;
  const branch = env.GITHUB_BRANCH || 'main';
  const token = env.GITHUB_TOKEN;

  if (!owner || !repo || !token) {
    throw new Error('missing GitHub env vars');
  }

  const encodedPath = path
    .split('/')
    .map((p) => encodeURIComponent(p))
    .join('/');
  const endpoint = `https://api.github.com/repos/${owner}/${repo}/contents/${encodedPath}`;
  const getResp = await ghFetch(endpoint + `?ref=${encodeURIComponent(branch)}`, token, { method: 'GET' }, true);
  if (!getResp) return null;

  let contentObj = null;
  try {
    contentObj = JSON.parse(decodeBase64(getResp.content || ''));
  } catch {
    contentObj = null;
  }

  return { sha: getResp.sha, contentObj };
}

async function putGithubFileWithSha(env, path, contentObj, sha) {
  const owner = env.GITHUB_OWNER;
  const repo = env.GITHUB_REPO;
  const branch = env.GITHUB_BRANCH || 'main';
  const token = env.GITHUB_TOKEN;

  if (!owner || !repo || !token) {
    throw new Error('missing GitHub env vars');
  }

  const encodedPath = path
    .split('/')
    .map((p) => encodeURIComponent(p))
    .join('/');
  const endpoint = `https://api.github.com/repos/${owner}/${repo}/contents/${encodedPath}`;

  const text = JSON.stringify(contentObj, null, 2);
  const payload = {
    message: `[health] update ${path}`,
    content: toBase64(text),
    branch,
    ...(sha ? { sha } : {}),
  };

  await ghFetch(endpoint, token, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

function parseRecordTimeMs(record) {
  if (!record || typeof record !== 'object') return null;
  const fields = ['date', 'startDate', 'timestamp', 'sleepEnd', 'sleepStart', 'endDate'];
  for (const f of fields) {
    const v = record[f];
    if (!v) continue;
    const ms = Date.parse(String(v));
    if (!Number.isNaN(ms)) return ms;
  }
  return null;
}

function inferMetricTimeMs(metricValue, fallbackMs) {
  if (Array.isArray(metricValue)) {
    let best = null;
    for (const item of metricValue) {
      const ms = parseRecordTimeMs(item);
      if (ms == null) continue;
      if (best == null || ms > best) best = ms;
    }
    return best == null ? fallbackMs : best;
  }
  if (metricValue && typeof metricValue === 'object') {
    const ms = parseRecordTimeMs(metricValue);
    return ms == null ? fallbackMs : ms;
  }
  return fallbackMs;
}

function normalizeMetricUpdatedAtMap(existing) {
  const out = {};
  if (!existing || typeof existing !== 'object') return out;
  for (const [k, v] of Object.entries(existing)) {
    if (typeof v === 'string') out[k] = v;
  }
  return out;
}

function mergeLatestBody(existingBody, incomingBody) {
  const nowIso = incomingBody?.meta?.ingested_at || new Date().toISOString();
  const nowMs = Date.parse(nowIso) || Date.now();
  const existingMetrics = (existingBody && typeof existingBody.metrics === 'object' && existingBody.metrics) || {};
  const incomingMetrics = (incomingBody && typeof incomingBody.metrics === 'object' && incomingBody.metrics) || {};
  const mergedMetrics = { ...existingMetrics };

  const existingMap = normalizeMetricUpdatedAtMap(existingBody?.meta?.metric_updated_at);
  const metricUpdatedAt = { ...existingMap };
  let applied = 0;
  let skippedStale = 0;

  for (const [key, incomingValue] of Object.entries(incomingMetrics)) {
    const incomingMs = inferMetricTimeMs(incomingValue, nowMs);
    const incomingIso = new Date(incomingMs).toISOString();
    const existingMs = Date.parse(metricUpdatedAt[key] || '') || 0;
    if (!metricUpdatedAt[key] || incomingMs >= existingMs) {
      mergedMetrics[key] = incomingValue;
      metricUpdatedAt[key] = incomingIso;
      applied += 1;
    } else {
      skippedStale += 1;
    }
  }

  const merged = {
    ...(existingBody && typeof existingBody === 'object' ? existingBody : {}),
    ...incomingBody,
    metrics: mergedMetrics,
    original_top_level_keys: incomingBody?.original_top_level_keys || [],
    meta: {
      ...((existingBody && existingBody.meta) || {}),
      ...(incomingBody.meta || {}),
      strategy: 'whitelist + stratified_tail_truncation + metric_key_merge_latest',
      metric_updated_at: metricUpdatedAt,
      merge: {
        mode: 'metric_key_merge',
        incoming_metrics: Object.keys(incomingMetrics),
        total_metrics_after_merge: Object.keys(mergedMetrics).length,
        applied,
        skipped_stale: skippedStale,
      },
    },
  };

  return {
    body: merged,
    info: merged.meta.merge,
  };
}

function isGithubShaConflict(err) {
  const s = String(err && err.message ? err.message : err);
  return s.includes('status=409') || s.includes('status=422');
}

async function upsertLatestMerged(env, latestPath, incomingBody) {
  const maxAttempts = 4;
  let lastErr = null;
  for (let i = 0; i < maxAttempts; i++) {
    const current = await getGithubFile(env, latestPath);
    const existingBody = current?.contentObj && typeof current.contentObj === 'object' ? current.contentObj : {};
    const merged = mergeLatestBody(existingBody, incomingBody);
    try {
      await putGithubFileWithSha(env, latestPath, merged.body, current?.sha);
      return merged.info;
    } catch (err) {
      lastErr = err;
      if (!isGithubShaConflict(err) || i === maxAttempts - 1) throw err;
      await sleep(120 * (i + 1));
    }
  }
  throw lastErr || new Error('latest_merge_failed');
}


async function appendGithubJsonl(env, path, rowObj) {
  const owner = env.GITHUB_OWNER;
  const repo = env.GITHUB_REPO;
  const branch = env.GITHUB_BRANCH || 'main';
  const token = env.GITHUB_TOKEN;

  if (!owner || !repo || !token) {
    throw new Error('missing GitHub env vars');
  }

  const encodedPath = path
    .split('/')
    .map((p) => encodeURIComponent(p))
    .join('/');
  const endpoint = `https://api.github.com/repos/${owner}/${repo}/contents/${encodedPath}`;

  const maxAttempts = 4;
  let lastErr = null;
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const getResp = await ghFetch(endpoint + `?ref=${encodeURIComponent(branch)}`, token, { method: 'GET' }, true);

      let sha;
      let current = '';
      if (getResp && getResp.sha) {
        sha = getResp.sha;
        current = decodeBase64(getResp.content || '');
        if (current && !current.endsWith('\n')) current += '\n';
      }

      current += JSON.stringify(rowObj) + '\n';

      const payload = {
        message: `[health] append ${path}`,
        content: toBase64(current),
        branch,
        sha,
      };

      await ghFetch(endpoint, token, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      return;
    } catch (err) {
      lastErr = err;
      if (!isGithubShaConflict(err) || i === maxAttempts - 1) throw err;
      await sleep(120 * (i + 1));
    }
  }
  throw lastErr || new Error('append_jsonl_failed');
}

async function sha256Hex(text) {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest('SHA-256', data);
  const bytes = new Uint8Array(digest);
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

async function ghFetch(url, token, init, allow404 = false) {
  const maxRetries = 3;
  for (let i = 0; i <= maxRetries; i++) {
    const resp = await fetch(url, {
      ...init,
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'User-Agent': 'apple-health-openclaw-worker',
        'Content-Type': 'application/json',
        ...(init.headers || {}),
      },
    });

    if (allow404 && resp.status === 404) return null;
    if (resp.ok) return await resp.json();

    // Retry on abuse/rate/5xx with simple backoff.
    if ((resp.status === 429 || resp.status >= 500) && i < maxRetries) {
      await sleep(250 * (i + 1));
      continue;
    }

    const t = await resp.text();
    throw new Error(`github_api_error status=${resp.status} body=${t}`);
  }

  throw new Error('github_api_error_exhausted');
}

function decodeBase64(base64Text) {
  const clean = (base64Text || '').replace(/\n/g, '');
  if (!clean) return '';
  const bin = atob(clean);
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

function toBase64(text) {
  const bytes = new TextEncoder().encode(text);
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
}
