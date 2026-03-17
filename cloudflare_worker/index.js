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
};

const CAPS = {
  heartRate: 200,
  stepCount: 80,
  activeEnergyBurned: 80,
  sleepAnalysis: 120,
  default: 60,
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

      const summary = {
        reqId,
        ts: now.toISOString(),
        metrics: Object.keys(filtered.metrics || {}),
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
          strategy: 'whitelist + stratified_tail_truncation',
          summary,
        },
        ...filtered,
      };

      await putGithubFile(env, latestPath, body, true);
      await putGithubFile(env, archivePath, body, false);

      console.log(
        JSON.stringify({
          event: 'ingest_written',
          reqId,
          latestPath,
          archivePath,
        }),
      );
      return json({ ok: true, summary, latestPath, archivePath });
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
