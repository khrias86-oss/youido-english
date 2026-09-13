/* 감시 조건(prefs) 저장 API — Vercel 서버리스 함수.
 *
 * 웹앱에서 고른 요일·날짜·회차를 저장소의 webstate/prefs.json 에 커밋한다.
 * 감시는 GitHub Actions 가 돌리므로, 다음 실행이 이 파일을 읽어 조건을 적용한다.
 * 즉시 반영이 필요하면 워크플로를 한 번 깨운다(실패해도 저장은 유효).
 *
 * 필요한 환경변수 (Vercel 프로젝트 설정):
 *   UMPPA_GITHUB_TOKEN  저장소 contents 읽기/쓰기 권한 토큰 (필수)
 *   UMPPA_REPO          "owner/repo" (필수)
 *   UMPPA_PIN           저장 시 요구할 비밀번호. 비우면 누구나 저장 가능
 *   UMPPA_BRANCH        기본 main
 *   UMPPA_WORKFLOW      즉시 확인에 쓸 워크플로 파일명. 기본 monitor.yml
 */
'use strict';

const crypto = require('crypto');

const GH = 'https://api.github.com';
const PREFS_PATH = 'webstate/prefs.json';
const MAX_BODY = 64 * 1024;

const env = (k, dflt = '') => process.env[k] || dflt;

function ghHeaders() {
  return {
    authorization: `Bearer ${env('UMPPA_GITHUB_TOKEN')}`,
    accept: 'application/vnd.github+json',
    'x-github-api-version': '2022-11-28',
    'user-agent': 'umppa-monitor-prefs',
  };
}

function pinOk(req) {
  const want = env('UMPPA_PIN');
  if (!want) return true;
  const got = String(req.headers['x-umppa-pin'] || '');
  const a = Buffer.from(got);
  const b = Buffer.from(want);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

/** 웹에서 온 값을 그대로 믿지 않고 스키마에 맞게 정리한다. */
function sanitize(raw) {
  const ints = (v, lo, hi) => Array.isArray(v)
    ? [...new Set(v.map(Number).filter((n) => Number.isInteger(n) && n >= lo && n <= hi))].sort((x, y) => x - y)
    : [];
  const strs = (v, limit) => Array.isArray(v)
    ? [...new Set(v.filter((s) => typeof s === 'string' && s.trim()).map((s) => s.trim().slice(0, 80)))].slice(0, limit)
    : [];
  const targets = {};
  const rawTargets = (raw && typeof raw.targets === 'object' && raw.targets) || {};
  for (const key of Object.keys(rawTargets).slice(0, 50)) {
    const t = rawTargets[key] || {};
    targets[String(key).slice(0, 80)] = {
      enabled: t.enabled !== false,
      weekdays: ints(t.weekdays, 0, 6),
      dates: strs(t.dates, 120).filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d)),
      sessions: strs(t.sessions, 60),
      min_remaining: Math.min(999, Math.max(1, Number(t.min_remaining) || 1)),
    };
  }
  return {
    version: 1,
    updated_at: Math.floor(Date.now() / 1000),
    targets,
    programs: strs(raw && raw.programs, 40).filter((p) => /^[0-9A-Za-z]+$/.test(p)),
  };
}

async function readPrefs(repo, branch) {
  const url = `${GH}/repos/${repo}/contents/${PREFS_PATH}?ref=${encodeURIComponent(branch)}`;
  const res = await fetch(url, { headers: ghHeaders() });
  if (res.status === 404) return { sha: null, data: null };
  if (!res.ok) throw new Error(`GitHub ${res.status}`);
  const body = await res.json();
  let data = null;
  try {
    data = JSON.parse(Buffer.from(body.content || '', 'base64').toString('utf8'));
  } catch (_) { /* 손상된 파일은 없는 것으로 본다 */ }
  return { sha: body.sha, data };
}

async function writePrefs(repo, branch, prefs, sha) {
  const res = await fetch(`${GH}/repos/${repo}/contents/${PREFS_PATH}`, {
    method: 'PUT',
    headers: Object.assign({ 'content-type': 'application/json' }, ghHeaders()),
    body: JSON.stringify({
      message: '웹앱에서 감시 조건 변경',
      content: Buffer.from(`${JSON.stringify(prefs, null, 1)}\n`, 'utf8').toString('base64'),
      branch,
      sha: sha || undefined,
    }),
  });
  if (!res.ok) throw new Error(`GitHub ${res.status}: ${(await res.text()).slice(0, 200)}`);
}

/** 바뀐 조건을 바로 적용해 보도록 워크플로를 깨운다. 실패는 무시한다. */
async function kickWorkflow(repo, branch) {
  try {
    await fetch(`${GH}/repos/${repo}/actions/workflows/${env('UMPPA_WORKFLOW', 'monitor.yml')}/dispatches`, {
      method: 'POST',
      headers: Object.assign({ 'content-type': 'application/json' }, ghHeaders()),
      body: JSON.stringify({ ref: branch }),
    });
  } catch (_) { /* 즉시 확인은 부가 기능 */ }
}

function readBody(req) {
  if (req.body !== undefined) {
    return Promise.resolve(typeof req.body === 'string' ? JSON.parse(req.body || '{}') : req.body);
  }
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', (c) => {
      raw += c;
      if (raw.length > MAX_BODY) reject(new Error('본문이 너무 큽니다'));
    });
    req.on('end', () => {
      try { resolve(JSON.parse(raw || '{}')); } catch (e) { reject(e); }
    });
    req.on('error', reject);
  });
}

module.exports = async (req, res) => {
  res.setHeader('access-control-allow-origin', '*');
  res.setHeader('access-control-allow-methods', 'GET,PUT,OPTIONS');
  res.setHeader('access-control-allow-headers', 'content-type,x-umppa-pin');
  res.setHeader('cache-control', 'no-store');

  if (req.method === 'OPTIONS') return res.status(204).end();

  const repo = env('UMPPA_REPO');
  if (!repo || !env('UMPPA_GITHUB_TOKEN')) {
    return res.status(503).json({ error: 'not-configured', hint: 'UMPPA_REPO / UMPPA_GITHUB_TOKEN 환경변수를 설정하세요' });
  }
  const branch = env('UMPPA_BRANCH', 'main');

  try {
    if (req.method === 'GET') {
      const { data } = await readPrefs(repo, branch);
      return res.status(200).json(data || { version: 1, updated_at: 0, targets: {}, programs: [] });
    }
    if (req.method === 'PUT') {
      if (!pinOk(req)) return res.status(401).json({ error: 'pin-required' });
      const prefs = sanitize(await readBody(req));
      const { sha } = await readPrefs(repo, branch);
      await writePrefs(repo, branch, prefs, sha);
      await kickWorkflow(repo, branch);
      return res.status(200).json({ ok: true, updated_at: prefs.updated_at });
    }
    return res.status(405).json({ error: 'method-not-allowed' });
  } catch (e) {
    return res.status(502).json({ error: 'upstream', detail: String(e.message || e).slice(0, 300) });
  }
};
