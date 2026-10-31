// Health check for https://create.gosim.org/survey26/platform — the Agent Observer hackathon site.
//
// Runs as the pre-run check of a scheduled task. It does the whole inspection itself, with no model:
//   exit 2 + CINDY_PRECHECK_OK  everything is fine; the task is skipped and nobody is disturbed
//   exit 0                      something is wrong; the task wakes an agent, which reads the report
// A crash inside the checker is itself reported as a problem (exit 0), never swallowed.
//
// What it covers: the site answers and every file it loads exists; the pages open in a real browser
// without script errors or raw translation keys; the homepage replay and standings load real data;
// sign-up is open and its service answers; logging in works end to end through the real form, with a
// dedicated account that is excluded from every public count; a wrong password shows the right error;
// the release pipeline is not stuck; the submission queue is moving.
//
// Report: ~/.site-health/last-report.json (and a dated copy under ~/.site-health/reports/).
import { spawn, execFile } from 'node:child_process'
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { promisify } from 'node:util'

const pexec = promisify(execFile)
const SITE = 'https://create.gosim.org/survey26/platform'
// Paths and Chrome come from the environment on the GitHub runner (.github/workflows/site-patrol.yml);
// the defaults are the owner's Mac.
const REPO = process.env.SITE_REPO || '/Users/yao/Desktop/code/agent/survey26-ops-jobs/site-repo'
const HOME = process.env.SITE_HEALTH_HOME || join(homedir(), '.site-health')
const CHROME = process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const PERM_DIR = process.env.SITE_HEALTH_PERM || join(HOME, 'perm')
const PORT = 18977
const PATH = process.env.CI ? process.env.PATH : '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'

const problems = []
const passed = []
const bad = (area, msg) => problems.push({ area, msg })
const ok = (area, msg) => passed.push({ area, msg })
const sleep = ms => new Promise(r => setTimeout(r, ms))

function envFile(p) {
  const out = {}
  for (const line of readFileSync(p, 'utf8').split('\n')) {
    const m = line.match(/^([A-Z0-9_]+)=(.*)$/)
    if (m) out[m[1]] = m[2].trim()
  }
  return out
}

async function get(url, opts = {}, tries = 2) {
  let last
  for (let i = 0; i < tries; i++) {
    try {
      const res = await fetch(url, { ...opts, signal: AbortSignal.timeout(20_000) })
      return res
    } catch (e) { last = e; await sleep(2000) }
  }
  throw last
}

async function gh(args) {
  const { stdout } = await pexec('gh', args, { env: { ...process.env, PATH }, timeout: 60_000, maxBuffer: 8 << 20 })
  return stdout
}

// ---------------------------------------------------------------------------------------------
async function pageFiles() {
  const idx = await get(`${SITE}/index.html?hc=${Date.now()}`, { cache: 'no-store' })
  if (!idx.ok) return { status: idx.status }
  const html = await idx.text()
  const assets = [...new Set([...html.matchAll(/(?:src|href)="([^"]+\.(?:js|css))"/g)].map(m => m[1]))]
  const missing = []
  for (const a of assets) {
    const url = a.startsWith('http') ? a : new URL(a, 'https://create.gosim.org').toString()
    const r = await get(url, { method: 'HEAD' })
    if (!r.ok) missing.push(`${a} → ${r.status}`)
  }
  return { status: 200, assets, missing }
}

async function checkFiles() {
  let f = await pageFiles()
  if (f.status !== 200) return bad('site', `the site itself answers HTTP ${f.status}`)
  // Right after a release the edge servers switch over one by one, and for a minute or two a page from
  // the old release can name files the new release has already removed. Only a gap that outlasts that
  // switch-over is a problem (visitors caught inside it are retried once by index.html).
  if (f.missing.length) { await sleep(90_000); f = await pageFiles() }
  if (f.status !== 200) return bad('site', `the site itself answers HTTP ${f.status}`)
  if (!f.assets.some(a => /assets\/index-/.test(a))) bad('site', 'index.html no longer names the app bundle')
  if (f.missing.length) bad('site', `files the page loads are still missing after 90 s: ${f.missing.join(', ')}`)
  else ok('site', `site answers; all ${f.assets.length} files it loads exist`)
  const dep = await get(`${SITE}/deployment.json?hc=${Date.now()}`)
  if (!dep.ok) { bad('site', `deployment.json answers ${dep.status}`); return null }
  return (await dep.json()).revision ?? null
}

async function checkPipeline(liveRev) {
  const rel = JSON.parse(await gh(['release', 'list', '--repo', 'gosimfoundation/hackathon-survey26', '--limit', '1', '--json', 'tagName,publishedAt']))[0]
  if (rel && liveRev) {
    const relSha = rel.tagName.split('-')[1] ?? ''
    const ageMin = (Date.now() - Date.parse(rel.publishedAt)) / 60000
    if (relSha && !relSha.startsWith(liveRev.slice(0, 12)) && !liveRev.startsWith(relSha.slice(0, 12)) && ageMin > 40) {
      bad('deploy', `the newest release (${relSha.slice(0, 7)}, ${Math.round(ageMin)} min old) is not live; the site still serves ${liveRev.slice(0, 7)}`)
    } else ok('deploy', `live site is on the newest release (${liveRev.slice(0, 7)})`)
  }
  const runs = JSON.parse(await gh(['run', 'list', '--repo', 'gosimfoundation/hackathon', '--workflow', 'deploy.yml', '--limit', '6', '--json', 'conclusion,status,createdAt,event']))
  const done = runs.filter(r => r.status === 'completed' && r.event !== 'pull_request')
  if (done.length >= 2 && done[0].conclusion === 'failure' && done[1].conclusion === 'failure') {
    bad('deploy', `the last ${done.filter((r, i) => i < 6 && r.conclusion === 'failure').length} site deploys in gosimfoundation/hackathon failed (latest ${done[0].createdAt}) — new changes cannot go live`)
  } else ok('deploy', 'site deploy pipeline is succeeding')
}

// SQL for the checks: the self-hosted backend answers at <SUPABASE_URL>/pg/query for the service role key,
// Supabase cloud at its management API for an access token (perm/sandbox.py picks the same way).
const queryUrl = sec => sec.SUPABASE_SERVICE_ROLE_KEY ? `${sec.SUPABASE_URL.replace(/\/$/, '')}/pg/query`
  : `https://api.supabase.com/v1/projects/${sec.SUPABASE_PROJECT_REF}/database/query`
const queryHeaders = sec => sec.SUPABASE_SERVICE_ROLE_KEY
  ? { apikey: sec.SUPABASE_SERVICE_ROLE_KEY, Authorization: `Bearer ${sec.SUPABASE_SERVICE_ROLE_KEY}` }
  : { Authorization: `Bearer ${sec.SUPABASE_ACCESS_TOKEN}` }

async function checkQueue(sec) {
  const q = async sql => {
    const r = await get(queryUrl(sec), { method: 'POST', headers: { ...queryHeaders(sec), 'Content-Type': 'application/json' }, body: JSON.stringify({ query: sql }) })
    if (!r.ok) throw new Error(`database query answered ${r.status}`)
    return r.json()
  }
  const rows = await q(`select count(*)::int n, min(created_at) oldest from public.submissions
    where status in ('queued','running') and created_at < now() - interval '3 hours'`)
  const stuck = rows[0]?.n ?? 0
  if (stuck > 0) {
    bad('evaluation', `${stuck} submission(s) have been waiting or running for over 3 hours (oldest ${rows[0].oldest}) — the evaluator may be down`)
  } else ok('evaluation', 'no submission has been stuck in the queue for 3 hours')
  const w = JSON.parse(await gh(['run', 'list', '--repo', 'BH3GEI/agent-observer', '--workflow', 'worker.yml', '--limit', '5', '--json', 'status,conclusion,createdAt']))
  const alive = w.some(r => r.status === 'in_progress' || r.status === 'queued' || (Date.now() - Date.parse(r.createdAt)) < 90 * 60_000)
  const waiting = (await q(`select count(*)::int n from public.submissions where status = 'queued'`))[0]?.n ?? 0
  if (!alive && waiting > 0) bad('evaluation', `${waiting} submission(s) are queued and the evaluator has not run in 90 minutes`)
  else ok('evaluation', `evaluator ${alive ? 'is running' : 'idle with an empty queue'}`)
}

async function checkAuthApi(sec, monitor) {
  const H = { apikey: sec.SUPABASE_ANON_KEY, 'Content-Type': 'application/json' }
  const s = await (await get(`${sec.SUPABASE_URL}/auth/v1/settings`, { headers: H })).json()
  if (s.disable_signup) bad('sign-up', 'sign-up is switched off in the login service')
  if (s.external && s.external.email === false) bad('sign-up', 'email sign-up is switched off in the login service')
  // An address that cannot be valid: the service must reject it for its shape, not be down or closed.
  const r = await get(`${sec.SUPABASE_URL}/auth/v1/signup`, { method: 'POST', headers: H, body: JSON.stringify({ email: 'not-an-address', password: 'x-health-check-123' }) })
  const body = await r.json().catch(() => ({}))
  if (r.status >= 500) bad('sign-up', `the sign-up service is failing (HTTP ${r.status})`)
  else if (/signup.*disabled|not allowed/i.test(`${body.error_code} ${body.msg}`)) bad('sign-up', `sign-up is refused: ${body.msg}`)
  else ok('sign-up', 'sign-up service is up and accepting new accounts')
  const lg = await get(`${sec.SUPABASE_URL}/auth/v1/token?grant_type=password`, { method: 'POST', headers: H, body: JSON.stringify(monitor) })
  const tok = await lg.json().catch(() => ({}))
  if (!tok.access_token) return bad('login', `the monitoring account cannot log in (HTTP ${lg.status}: ${tok.msg ?? tok.error_code ?? ''})`)
  const me = await get(`${sec.SUPABASE_URL}/rest/v1/rpc/me`, { method: 'POST', headers: { ...H, Authorization: `Bearer ${tok.access_token}` }, body: '{}' })
  const meBody = await me.json().catch(() => null)
  if (!me.ok || !meBody) bad('login', `logged in, but the account's own profile does not load (HTTP ${me.status})`)
  else {
    ok('login', 'login service works and a logged-in account can read its profile')
    // Saving a profile: the exact fields the profile page sends, re-saved with the account's own values.
    // (2026-09-23: every save failed for three days with "permission denied for table profiles".)
    const save = await get(`${sec.SUPABASE_URL}/rest/v1/profiles?id=eq.${meBody.id}`, {
      method: 'PATCH', headers: { ...H, Authorization: `Bearer ${tok.access_token}`, Prefer: 'return=minimal' },
      body: JSON.stringify({
        name: meBody.name || 'Site health check', github: meBody.github ?? '', affiliation: meBody.affiliation ?? '', role: meBody.role ?? '',
        locale: meBody.locale || 'en', seeking: '', seeking_count: 0, looking_for_team: false,
        astro_level: meBody.astro_level ?? 0, ai_level: meBody.ai_level ?? 0, city: meBody.city ?? '', contact: meBody.contact ?? '',
        blurb: meBody.blurb ?? '', show_on_wall: false,
      }),
    })
    if (save.ok) ok('profile', 'a participant can save their own profile')
    else bad('profile', `saving a profile fails (HTTP ${save.status}): ${(await save.text()).slice(0, 160)}`)
  }
  const st = await (await get(`${sec.SUPABASE_URL}/rest/v1/rpc/participants_stats`, { method: 'POST', headers: H, body: '{}' })).json()
  if (!(st.total > 0)) bad('data', `participant stats came back empty: ${JSON.stringify(st)}`)
}

// --- a real browser ---------------------------------------------------------------------------
class Cdp {
  constructor(ws) { this.ws = ws; this.id = 0; this.wait = new Map(); ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && this.wait.has(m.id)) { this.wait.get(m.id)(m); this.wait.delete(m.id) } } }
  call(method, params = {}) {
    const id = ++this.id
    return new Promise((res, rej) => {
      const t = setTimeout(() => { this.wait.delete(id); rej(new Error(`browser did not answer ${method}`)) }, 60_000)
      this.wait.set(id, m => { clearTimeout(t); m.error ? rej(new Error(m.error.message)) : res(m.result) })
      this.ws.send(JSON.stringify({ id, method, params }))
    })
  }
  async ev(expr) {
    const r = await this.call('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? 'page script error')
    return r.result.value
  }
}

// Chrome can still be writing into its profile for a moment after it is killed; retry the cleanup
// and never let a leftover temp folder fail the run.
function clearProfile(dir) {
  try { rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 }) } catch { /* removed next run */ }
}

async function withBrowser(fn) {
  const profile = join(HOME, 'chrome-profile')
  clearProfile(profile)
  const proc = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--no-first-run',
    '--no-default-browser-check', '--use-gl=angle', '--enable-unsafe-swiftshader', '--window-size=1440,900', '--lang=en-US',
    // Ubuntu 24.04 runners block the user namespaces Chrome's sandbox needs.
    ...(process.env.CI ? ['--no-sandbox'] : [])], { stdio: 'ignore' })
  try {
    let target
    for (let i = 0; i < 40 && !target; i++) {
      await sleep(500)
      try { target = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find(t => t.type === 'page') } catch { /* starting */ }
    }
    if (!target) throw new Error('headless Chrome did not start')
    const ws = new WebSocket(target.webSocketDebuggerUrl)
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('could not attach to Chrome')) })
    const cdp = new Cdp(ws)
    await cdp.call('Page.enable'); await cdp.call('Runtime.enable')
    await cdp.call('Page.addScriptToEvaluateOnNewDocument', { source:
      "window.__errs=[];addEventListener('error',e=>window.__errs.push(String(e.message)));" +
      "addEventListener('unhandledrejection',e=>window.__errs.push('rejected: '+String(e.reason&&e.reason.message||e.reason)));" +
      "try{localStorage.setItem('sac.sky-tour.seen','1')}catch(e){}" })
    try { return await fn(cdp) } finally { ws.close() }
  } finally {
    proc.kill('SIGKILL')
    await sleep(500)
    clearProfile(profile)
  }
}

async function open(cdp, path, settle = 3500) {
  const url = `${SITE}${path}`
  const marker = `health-${Date.now()}-${Math.random()}`
  await cdp.ev(`window.__healthOldDocument=${JSON.stringify(marker)}`)
  // The local proxy this Mac goes through sometimes drops a connection (SSL/tunnel/closed errors) while
  // the site itself is fine. Retry only those connection-level failures, a few seconds apart; a site
  // that is really down fails all three and is still reported.
  const TRANSIENT = /ERR_(SSL_PROTOCOL_ERROR|TUNNEL_CONNECTION_FAILED|CONNECTION_CLOSED|CONNECTION_RESET|PROXY_CONNECTION_FAILED|TIMED_OUT|NETWORK_CHANGED)/
  let navigation
  for (let attempt = 1; ; attempt++) {
    navigation = await cdp.call('Page.navigate', { url })
    if (!navigation.errorText || !TRANSIENT.test(navigation.errorText) || attempt === 3) break
    await sleep(3000)
  }
  if (navigation.errorText) throw new Error(`navigation failed: ${navigation.errorText}`)
  let ready = false
  for (let i = 0; i < 80 && !ready; i++) {
    await sleep(250)
    ready = await cdp.ev(`window.__healthOldDocument!==${JSON.stringify(marker)} &&
      location.href===${JSON.stringify(url)} && document.readyState==='complete' &&
      !!document.querySelector('#app main')`)
  }
  if (!ready) throw new Error(`requested page did not finish loading: ${path}`)
  await sleep(settle)
}

// Raw translation keys ("home.vision.title") showing on the page mean a missing string.
const RAW_KEY = /\b(?:home|hero|nav|auth|common|leaderboard|team|faq|footer|docs_page|browser_notice|kind|dashboard|submit|profile|rules|start|resources|teammates|phase_clock)\.[a-z_]+(?:\.[a-z_0-9]+)*\b/

async function checkPages(cdp) {
  const routes = ['/', '/register', '/leaderboard', '/start', '/brief', '/rules', '/docs', '/faq', '/resources', '/teammates']
  for (const r of routes) {
    await open(cdp, r)
    const s = await cdp.ev(`JSON.stringify({ errs: window.__errs, len: document.body.innerText.length,
      text: document.body.innerText.slice(0, 20000), notFound: !!document.querySelector('.egg-object-card'),
      safari: !!document.querySelector('[data-testid=browser-notice]') })`).then(JSON.parse)
    const issues = []
    if (s.errs.length) issues.push(`script errors: ${s.errs.slice(0, 3).join(' | ')}`)
    if (s.len < 400) issues.push(`page is nearly empty (${s.len} characters)`)
    if (s.notFound) issues.push('shows the 404 page')
    if (s.safari) issues.push('shows the Safari warning in Chrome')
    const key = s.text.match(RAW_KEY)
    if (key) issues.push(`raw text key on screen: "${key[0]}"`)
    if (issues.length) bad('pages', `${r}: ${issues.join('; ')}`)
  }
  if (!problems.some(p => p.area === 'pages')) ok('pages', `all ${routes.length} public pages open cleanly`)
}

async function checkHome(cdp) {
  await open(cdp, '/', 2000)
  let src = '', rows = 0
  // The board's own state: rows, or the "00" empty panel whose sentence says why (no scores yet /
  // hidden by organizers / failed to load). A board that loaded fine with no scores yet is not a fault.
  const boardState = "(function(){ var z=document.querySelector('#board .empty-zero, #leaderboard .empty-zero'); if(!z) return ''; var p=z.parentElement.querySelector('p'); return p ? p.innerText.trim() : '' })()"
  let empty = ''
  for (let i = 0; i < 40 && (src !== 'demo' || (!rows && !empty)); i++) {
    src = await cdp.ev("(document.querySelector('[data-testid=sky-console]')||{dataset:{}}).dataset.replaySource||''")
    rows = await cdp.ev("document.querySelectorAll('[data-testid=lb-row]').length")
    empty = await cdp.ev(boardState)
    if (src !== 'demo' || (!rows && !empty)) await sleep(500)
  }
  if (src !== 'demo') bad('homepage', 'the official example replay never loaded')
  const h = await cdp.ev(`JSON.stringify({ rows: document.querySelectorAll('[data-testid=lb-row]').length,
    film: !!document.querySelector('.film-video') })`).then(JSON.parse)
  h.canvas = await skyDrawn(cdp)
  if (!h.rows) {
    const en = JSON.parse(readFileSync(join(REPO, 'web/src/i18n/en.json'), 'utf8'))
    const zh = JSON.parse(readFileSync(join(REPO, 'web/src/i18n/zh.json'), 'utf8'))
    const noScoresYet = [en.leaderboard.empty, zh.leaderboard.empty].includes(empty)
    if (noScoresYet) ok('homepage', 'the homepage board loaded and is empty because no team has a score on it yet')
    else bad('homepage', `the standings table on the homepage has no rows${empty ? ` (it says: "${empty}")` : ''}`)
  }
  if (!h.canvas) bad('homepage', 'the replay sky map is blank')
  if (!h.film) bad('homepage', 'the event film is missing')
  if (src === 'demo' && h.rows && h.canvas && h.film) ok('homepage', `official example replay, standings (${h.rows} rows) and film all load`)
}

// The sky replay is a WebGL dome now (a flat 2D map only when WebGL is missing), so its pixels cannot be
// read back from the canvas. Screenshot the canvas area instead and count pixels that stand out from the
// average: a drawn sky has stars, lines and labels; a blank or failed canvas is one flat colour.
async function skyDrawn(cdp) {
  const rect = await cdp.ev(`(function(){ var c=document.querySelector('.sky-console canvas'); if(!c) return null;
    c.scrollIntoView({block:'center'}); var r=c.getBoundingClientRect();
    return r.width > 20 && r.height > 20 ? { x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height } : null })()`)
  if (!rect) return 0
  await sleep(2000)
  const shot = await cdp.call('Page.captureScreenshot', { format: 'png', clip: { x: rect.x, y: rect.y, width: rect.w, height: rect.h, scale: 0.5 } })
  return cdp.ev(`new Promise(function(res){ var i=new Image(); i.onerror=function(){ res(0) }; i.onload=function(){
    var c=document.createElement('canvas'); c.width=i.width; c.height=i.height; var x=c.getContext('2d'); x.drawImage(i,0,0);
    var d=x.getImageData(0,0,c.width,c.height).data, n=d.length/4, sum=0, k;
    for (k=0;k<d.length;k+=4) sum+=d[k]+d[k+1]+d[k+2];
    var mean=sum/n, off=0; for (k=0;k<d.length;k+=4) if (Math.abs(d[k]+d[k+1]+d[k+2]-mean) > 75) off++;
    res(off > n*0.002 ? off : 0) }; i.src='data:image/png;base64,${shot.data}' })`)
}

async function fill(cdp, testid, value) {
  await cdp.ev(`(function(){ var el=document.querySelector('[data-testid=${testid}]'); if(!el) throw new Error('missing ${testid}');
    var set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; set.call(el, ${JSON.stringify(value)});
    el.dispatchEvent(new Event('input',{bubbles:true})); return 1 })()`)
}

// The sign-up / login page is loaded on demand, so on a slow connection the frame is ready before the
// form is. Wait for the element itself; a form that never shows up is reported as such.
async function waitFor(cdp, testid, ms = 30000) {
  for (let t = 0; t < ms; t += 500) {
    if (await cdp.ev(`!!document.querySelector('[data-testid=${testid}]')`)) return true
    await sleep(500)
  }
  return false
}

async function checkAuthUi(cdp, monitor) {
  const en = JSON.parse(readFileSync(join(REPO, 'web/src/i18n/en.json'), 'utf8'))
  // sign-up form: opens, and its first step can be submitted (it is disabled when registration is closed)
  await open(cdp, '/register')
  await waitFor(cdp, 'reg-email')
  const reg = await cdp.ev(`JSON.stringify({ form: !!document.querySelector('[data-testid=reg-email]'),
    next: (function(){ var b=document.querySelector('[data-testid=reg-next]'); return b ? !b.disabled : null })() })`).then(JSON.parse)
  if (!reg.form) bad('sign-up', 'the sign-up form does not appear on /register')
  else if (reg.next === false) bad('sign-up', 'the sign-up button is greyed out — registration looks closed')
  else ok('sign-up', 'sign-up form opens and can be submitted')

  // wrong password: the real form must say so
  await open(cdp, '/register?mode=login')
  if (!(await waitFor(cdp, 'login-email'))) return bad('login', 'the login form did not appear on /register?mode=login within 30 s')
  await fill(cdp, 'login-email', monitor.email)
  await fill(cdp, 'login-password', 'definitely-not-the-password')
  await cdp.ev("document.querySelector('[data-testid=login-submit]').click(); 1")
  let shown = false
  for (let i = 0; i < 24 && !shown; i++) { await sleep(500); shown = await cdp.ev(`document.body.innerText.includes(${JSON.stringify(en.auth.errors.bad_credentials)})`) }
  if (!shown) bad('login', 'a wrong password does not produce the "incorrect" message on the login form')

  // right password: the real form must land on the dashboard
  await open(cdp, '/register?mode=login')
  if (!(await waitFor(cdp, 'login-email'))) return bad('login', 'the login form did not appear on /register?mode=login within 30 s')
  await fill(cdp, 'login-email', monitor.email)
  await fill(cdp, 'login-password', monitor.password)
  await cdp.ev("document.querySelector('[data-testid=login-submit]').click(); 1")
  let path = ''
  for (let i = 0; i < 30 && !path.endsWith('/dashboard'); i++) { await sleep(500); path = await cdp.ev('location.pathname') }
  if (!path.endsWith('/dashboard')) bad('login', `logging in through the form did not reach the dashboard (stuck on ${path})`)
  else {
    await sleep(2500)
    const errs = await cdp.ev('JSON.stringify(window.__errs)').then(JSON.parse)
    if (errs.length) bad('login', `the dashboard throws after login: ${errs.slice(0, 2).join(' | ')}`)
    else if (shown) ok('login', 'logging in through the real form works, and a wrong password is refused with the right message')
  }
}

// Every read and write the site makes, run as a participant, a teammate, a visitor and an admin inside
// database transactions that are always thrown away (perm/suite.py). Catches the "permission denied"
// family: a column the pages save but the role may not write, a setting a page reads but may not see,
// and the reverse — data one participant must not reach, such as another team's invite code.
async function checkPermissions(sec) {
  const keys = ['SUPABASE_URL', 'SUPABASE_PROJECT_REF', 'SUPABASE_ACCESS_TOKEN', 'SUPABASE_SERVICE_ROLE_KEY']
  const env = { ...process.env, PATH, ...Object.fromEntries(keys.filter(k => sec[k]).map(k => [k, sec[k]])) }
  const { stdout } = await pexec('python3', ['suite.py'], { cwd: PERM_DIR, env, timeout: 240_000, maxBuffer: 8 << 20 })
  const total = stdout.match(/==== (\d+) problem/)
  if (!total) return bad('permissions', 'the permission suite did not finish')
  const failed = stdout.split('\n').filter(l => /^\s+FAIL|BLOCK FAILED/.test(l)).map(l => l.trim().replace(/\s+/g, ' '))
  if (Number(total[1]) > 0) bad('permissions', `${total[1]} permission problem(s): ${failed.slice(0, 6).join(' || ')}`)
  else ok('permissions', 'every read and write the site makes works for the right people and is refused for the rest')
}

// ---------------------------------------------------------------------------------------------
async function main() {
  const started = Date.now()
  // On the runner the same values arrive as environment variables (repository secrets).
  const sec = process.env.SUPABASE_URL ? process.env : envFile(join(REPO, '.secrets/supabase.env'))
  const monitor = process.env.PATROL_EMAIL
    ? { email: process.env.PATROL_EMAIL, password: process.env.PATROL_PASSWORD }
    : JSON.parse(readFileSync(join(HOME, 'monitor.json'), 'utf8'))
  const step = async (area, fn) => { try { await fn() } catch (e) { bad(area, `check could not run: ${e.message}`) } }
  let liveRev = null
  await step('site', async () => { liveRev = await checkFiles() })
  await step('deploy', () => checkPipeline(liveRev))
  await step('evaluation', () => checkQueue(sec))
  await step('login', () => checkAuthApi(sec, monitor))
  await step('permissions', () => checkPermissions(sec))
  await step('browser', () => withBrowser(async cdp => {
    await step('pages', () => checkPages(cdp))
    await step('homepage', () => checkHome(cdp))
    await step('login', () => checkAuthUi(cdp, monitor))
  }))
  const report = { checkedAt: new Date().toISOString(), seconds: Math.round((Date.now() - started) / 1000), liveRevision: liveRev, ok: problems.length === 0, problems, passed }
  mkdirSync(join(HOME, 'reports'), { recursive: true })
  writeFileSync(join(HOME, 'last-report.json'), JSON.stringify(report, null, 2))
  writeFileSync(join(HOME, 'reports', `${report.checkedAt.replace(/[:.]/g, '-')}.json`), JSON.stringify(report, null, 2))
  for (const p of passed) console.log(`ok       [${p.area}] ${p.msg}`)
  for (const p of problems) console.log(`PROBLEM  [${p.area}] ${p.msg}`)
  console.log(`${problems.length} problem(s) in ${report.seconds}s — report: ${join(HOME, 'last-report.json')}`)
  if (problems.length === 0) { console.log('CINDY_PRECHECK_OK'); process.exit(2) }
  process.exit(0)
}

main().catch(e => {
  try {
    mkdirSync(HOME, { recursive: true })
    writeFileSync(join(HOME, 'last-report.json'), JSON.stringify({ checkedAt: new Date().toISOString(), ok: false, problems: [{ area: 'checker', msg: `the health check itself crashed: ${e.stack || e}` }], passed }, null, 2))
  } catch { /* nothing more to do */ }
  console.log(`PROBLEM  [checker] the health check itself crashed: ${e.message}`)
  process.exit(0)
})
