// hermes-key-doctor: desktop half. Plain ESM, loaded uncompiled by Hermes Desktop (no JSX, no build).
//
// Surfaces: route /keys (sidebar row "Key Doctor" + ⌘K "Open Key Doctor") and a status-bar chip.
// Data: host.requestProfile(route, "cli.exec", { argv: ["--profile", p, "keydoctor", "--json"] })
//       -> a fresh, read-only `hermes keydoctor` process; refreshed every 60 s while visible.
// Look: theme variables only (--ui-*), so it follows Nous dark and every other skin.

import { host, PALETTE_AREA, ROUTES_AREA, SIDEBAR_NAV_AREA, STATUSBAR_AREAS } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'hermes-key-doctor'
const ROUTE = '/keys'
const REFRESH_MS = 60000
const CLI_TIMEOUT_MS = 60000

// ── data ────────────────────────────────────────────────────────────────────
async function resolveRoute() {
  const owner = host.state?.focusedSessionOwner?.get?.() || null
  const routes = await host.profileRoutes()
  const exact = owner ? routes.filter((r) => r.connectionId === owner.connectionId && r.profile === owner.profile) : []
  if (exact.length === 1) return exact[0]
  const fallback = routes.find((r) => r.primary) || routes.find((r) => r.mode === 'local') || routes[0]
  if (!fallback) throw new Error('No Hermes profile route available')
  return fallback
}

function parseCliJson(output) {
  const lines = String(output || '').split('\n').map((l) => l.trim()).filter(Boolean)
  for (let i = lines.length - 1; i >= 0; i--) {
    if (!lines[i].startsWith('{')) continue
    try { return JSON.parse(lines[i]) } catch { /* keep looking */ }
  }
  throw new Error(lines.slice(-2).join(' ') || 'empty output from hermes keydoctor')
}

async function fetchKeys() {
  const route = await resolveRoute()
  const res = await host.requestProfile(route, 'cli.exec',
    { argv: ['--profile', route.targetProfile, 'keydoctor', '--json'], timeout: CLI_TIMEOUT_MS / 1000 }, CLI_TIMEOUT_MS + 5000)
  if (res && res.blocked) throw new Error(res.hint || 'cli.exec blocked')
  const payload = parseCliJson(res && res.output)
  if (payload.error) throw new Error(payload.error)
  return payload
}

// One shared poller so the page and the status chip never double-fetch.
const store = { data: null, error: null, at: 0, listeners: new Set(), inflight: null }
function notify() { store.listeners.forEach((fn) => fn()) }
function refresh() {
  if (store.inflight) return store.inflight
  store.inflight = fetchKeys()
    .then((d) => { store.data = d; store.error = null; store.at = Date.now() })
    .catch((e) => { store.error = String((e && e.message) || e) })
    .finally(() => { store.inflight = null; notify() })
  notify()
  return store.inflight
}
function useKeys() {
  const [, bump] = useState(0)
  useEffect(() => {
    const fn = () => bump((n) => n + 1)
    store.listeners.add(fn)
    if (!store.data && !store.inflight) refresh()
    return () => store.listeners.delete(fn)
  }, [])
  return store
}
function startPolling(ctx) {
  const tick = () => { if (!document.hidden) refresh() }
  ctx.setInterval(tick, REFRESH_MS)
  ctx.addEventListener(document, 'visibilitychange', tick)
  refresh()
}

// ── theme ───────────────────────────────────────────────────────────────────
const V = (name, fallback) => `var(${name}, ${fallback})`
const C = {
  accent: V('--ui-accent', '#4a84fe'), red: V('--ui-red', '#ff7b72'), yellow: V('--ui-yellow', '#d29922'),
  green: V('--ui-green', '#3fb950'), orange: V('--ui-orange', '#ffa657'),
  t1: V('--ui-text-primary', '#e6edf3'), t2: V('--ui-text-secondary', '#b1bac4'), t3: V('--ui-text-tertiary', '#7d8590'), t4: V('--ui-text-quaternary', '#6e7681'),
  stroke: V('--ui-stroke-tertiary', '#30363d'), panel: V('--ui-bg-elevated', '#010409'), sunk: V('--ui-bg-tertiary', '#0d1117'),
}
const tint = (v, fb, pct) => `color-mix(in srgb, var(${v}, ${fb}) ${pct}%, transparent)`
const MONO = 'ui-monospace, SFMono-Regular, "JetBrains Mono", Menlo, monospace'
const STATE = {
  ok: { label: 'OK', fg: C.green, bg: tint('--ui-green', '#3fb950', 14) },
  benched: { label: 'BENCHED', fg: '#fff', bg: C.red },
  dead: { label: 'DEAD', fg: '#fff', bg: C.red },
  'model-cooldown': { label: 'MODEL BLOCKED', fg: C.orange, bg: tint('--ui-orange', '#ffa657', 16) },
  stale: { label: 'STALE BENCH', fg: C.yellow, bg: tint('--ui-yellow', '#d29922', 14) },
  expired: { label: 'EXPIRED', fg: '#fff', bg: C.red },
  expiring: { label: 'EXPIRING', fg: C.yellow, bg: tint('--ui-yellow', '#d29922', 14) },
  'wrong-auth-mode': { label: 'WRONG AUTH MODE', fg: '#fff', bg: C.red },
}
const stateOf = (c) => c.state || (c.status === 'ok' && c.stale_bench ? 'stale' : c.status)
// Labels are often the account email; mask them so a screenshot or a screen recording never shows one.
const maskLabel = (label) => String(label || '').replace(/([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})/g, '$1•••@$2')

// ── pieces ──────────────────────────────────────────────────────────────────
function Pill({ k }) {
  const s = STATE[k] || STATE.ok
  return jsx('span', { style: { fontFamily: MONO, fontSize: 10.5, fontWeight: 700, letterSpacing: '.07em', padding: '2px 8px', borderRadius: 4, color: s.fg, background: s.bg, whiteSpace: 'nowrap' }, children: s.label })
}

function Tile({ label, value, color, hint }) {
  return jsxs('div', {
    style: { background: C.panel, border: `1px solid ${value && color !== C.green ? color : C.stroke}`, borderRadius: 10, padding: '10px 14px', minWidth: 0 },
    children: [
      jsx('div', { style: { fontSize: 10, letterSpacing: '.09em', color: C.t3, textTransform: 'uppercase' }, children: label }),
      jsx('div', { style: { fontFamily: MONO, fontSize: 30, fontWeight: 700, lineHeight: 1.1, color: value || color === C.green ? color : C.t4, fontVariantNumeric: 'tabular-nums' }, children: value }),
      jsx('div', { style: { fontSize: 10.5, color: C.t4 }, children: hint }),
    ],
  })
}

function CopyFix({ text }) {
  const [done, setDone] = useState(false)
  const command = text.split('   #')[0]
  return jsxs('div', {
    style: { display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 },
    children: [
      jsx('code', { style: { flex: 1, minWidth: 0, fontFamily: MONO, fontSize: 11.5, color: C.t1, background: C.sunk, border: `1px solid ${C.stroke}`, borderRadius: 6, padding: '5px 8px', overflowWrap: 'anywhere' }, children: command }),
      jsx('button', {
        type: 'button',
        onClick: () => { navigator.clipboard?.writeText(command).then(() => { setDone(true); setTimeout(() => setDone(false), 1500) }) },
        style: { fontSize: 11, padding: '4px 10px', borderRadius: 6, border: `1px solid ${C.stroke}`, background: 'transparent', color: done ? C.green : C.t2, cursor: 'pointer' },
        children: done ? 'Copied' : 'Copy fix',
      }),
    ],
  })
}

function Login({ c }) {
  const k = stateOf(c)
  const problem = k !== 'ok'
  return jsxs('div', {
    style: { padding: '7px 0', borderTop: `1px solid ${C.stroke}` },
    children: [
      jsxs('div', {
        style: { display: 'grid', gridTemplateColumns: '120px 1fr 64px auto', gap: 10, alignItems: 'center', fontSize: 12 },
        children: [
          jsx('span', { style: { fontFamily: MONO, color: C.t1 }, children: c.provider }),
          jsx('span', { style: { color: C.t3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }, children: maskLabel(c.label) }),
          jsx('span', { style: { fontFamily: MONO, fontSize: 10.5, color: C.t4 }, children: c.auth_type }),
          jsxs('span', { style: { display: 'flex', gap: 6, alignItems: 'center', justifyContent: 'flex-end' }, children: [
            problem && c.shared_with && c.shared_with.length ? jsx('span', { title: `Also used by: ${c.shared_with.join(', ')}`, style: { fontFamily: MONO, fontSize: 10, color: C.t3, border: `1px solid ${C.stroke}`, borderRadius: 4, padding: '1px 6px' }, children: `shared ×${c.shared_with.length + 1}` }) : null,
            jsx(Pill, { k })] }),
        ],
      }),
      problem ? jsxs('div', {
        style: { marginTop: 5, fontSize: 11.5, color: C.t2, lineHeight: 1.5 },
        children: [
          c.why ? jsx('div', { children: `Why: ${c.why}${c.until_text ? ` · until ${c.until_text}` : ''}${c.sole_credential ? ' · the only login for this provider' : ''}` }) : null,
          ...(c.cooldowns || []).map((m) => jsx('div', { style: { color: m.stuck ? C.orange : C.t2 }, children: `${m.model} blocked until ${m.until_text}${m.stuck ? ' · longer than any rate limit (stuck-cooldown bug, hermes-agent#127917)' : ''}` }, m.model)),
          c.note ? jsx('div', { children: c.note }) : null,
          k === 'stale' ? jsx('div', { children: 'Marked exhausted, but the bench time has passed. A reset makes sure Hermes retries it.' }) : null,
          k === 'dead' ? jsx('div', { children: 'The provider rejected this login outright.' }) : null,
          c.fix ? jsx(CopyFix, { text: c.fix }) : null,
          c.fix && c.shared_with && c.shared_with.length ? jsx('div', { style: { color: C.t3, marginTop: 4 }, children: `Shared with ${c.shared_with.length} other Bot${c.shared_with.length === 1 ? '' : 's'}: one fix clears all of them.` }) : null,
        ],
      }) : null,
    ],
  })
}

function Bot({ p }) {
  const creds = p.credentials || []
  const bad = creds.filter((c) => stateOf(c) !== 'ok').length + (p.default_model && p.default_model.stopped ? 1 : 0) + (p.crons || []).filter((j) => j.reach && j.reach.verdict === 'blocked').length
  return jsxs('div', {
    style: { background: C.panel, border: `1px solid ${bad ? C.red : C.stroke}`, borderRadius: 10, padding: '10px 14px' },
    children: [
      jsxs('div', {
        style: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 2 },
        children: [
          jsx('span', { style: { fontFamily: MONO, fontSize: 14, fontWeight: 700, color: C.t1, letterSpacing: '.03em' }, children: p.profile.toUpperCase() }),
          jsx('span', { style: { fontSize: 11, color: C.t4 }, children: `${creds.length} login${creds.length === 1 ? '' : 's'}` }),
          jsx('span', { style: { marginLeft: 'auto', fontSize: 11, fontWeight: 600, color: p.error ? C.red : bad ? C.red : C.green }, children: p.error ? 'unreadable' : bad ? `${bad} need attention` : 'all healthy' }),
        ],
      }),
      p.default_model && p.default_model.line ? jsx('div', {
        style: { fontSize: 11.5, margin: '2px 0 4px', color: p.default_model.stopped ? C.red : p.default_model.reach && p.default_model.reach.verdict === 'no-backup' && !p.default_model.covered ? C.orange : C.t3 },
        children: p.default_model.line.replace(/^DEFAULT MODEL BLOCKED: /, 'Default model blocked: ').replace(/^default model /, 'Model ') }) : null,
      p.env_shadow ? jsx('div', { style: { fontSize: 11.5, color: C.orange, marginBottom: 4 }, children: "ANTHROPIC_API_KEY in this Bot's .env can take over from its subscription login and bill the paid API (hermes-agent#97085). Remove it from .env if that's not what you want." }) : null,
      ...(p.crons || []).filter((j) => j.reach && j.reach.verdict === 'blocked').map((j) => jsx('div', { style: { fontSize: 11.5, color: C.red, marginBottom: 4 }, children: `Cron "${j.name}" will fail (next ${j.next_run_at ? new Date(j.next_run_at).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' }) : '?'})` }, j.id)),
      p.error ? jsx('div', { style: { color: C.red, fontSize: 11.5 }, children: p.error }) : creds.map((c) => jsx(Login, { c }, `${c.provider}-${c.id}`)),
    ],
  })
}

function attentionParts(sum) {
  const logins = sum.attention - (sum.bots_stopped || 0) - (sum.crons_failing || 0)
  return [
    logins ? `${logins} login${logins === 1 ? '' : 's'}` : null,
    sum.bots_stopped ? `${sum.bots_stopped} Bot${sum.bots_stopped === 1 ? " that can't reach its model" : "s that can't reach their model"}` : null,
    sum.crons_failing ? `${sum.crons_failing} cron job${sum.crons_failing === 1 ? '' : 's'} that will fail` : null,
  ].filter(Boolean).join(' · ')
}

function KeysPage() {
  const s = useKeys()
  const d = s.data
  const sum = d && d.summary
  const head = jsxs('div', {
    style: { display: 'flex', alignItems: 'baseline', gap: 14, marginBottom: 12 },
    children: [
      jsx('div', { style: { fontSize: 13, color: C.t1, fontWeight: 600 }, children: 'Key Doctor' }),
      jsx('div', { style: { fontSize: 11.5, color: C.t3 }, children: 'why did my key stop working? · read-only · never shows a key' }),
      jsx('div', { style: { marginLeft: 'auto', fontFamily: MONO, fontSize: 11, color: C.t3 }, children: sum ? `${sum.logins} LOGINS · ${sum.bots} BOTS · checked ${new Date(s.at).toLocaleTimeString()}` : s.error ? '' : 'checking every login…' }),
      jsx('button', {
        type: 'button', onClick: () => refresh(), disabled: Boolean(s.inflight),
        style: { fontSize: 11, padding: '4px 10px', borderRadius: 6, border: `1px solid ${C.stroke}`, background: 'transparent', color: C.t2, cursor: 'pointer' },
        children: s.inflight ? 'Checking…' : 'Check now',
      }),
    ],
  })
  if (!d) {
    return jsxs('div', { style: { padding: '20px 28px', height: '100%', overflow: 'auto' }, children: [head,
      s.error ? jsx('div', { style: { color: C.red, fontSize: 12.5 }, children: `Could not read logins: ${s.error}. Is the hermes-key-doctor Python plugin enabled (hermes plugins enable hermes-key-doctor)?` }) : null] })
  }
  const healthy = sum.attention === 0
  return jsxs('div', {
    style: { padding: '20px 28px 28px', height: '100%', overflow: 'auto' },
    children: [
      head,
      jsx('div', {
        style: { display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 10 },
        children: [
          jsx(Tile, { label: 'Healthy', value: sum.ok, color: C.green, hint: 'Hermes will use these' }),
          jsx(Tile, { label: 'Benched', value: sum.benched, color: C.red, hint: 'skipped until a time' }),
          jsx(Tile, { label: 'Model blocked', value: sum['model-cooldown'], color: C.orange, hint: 'works, one model off' }),
          jsx(Tile, { label: 'Dead', value: sum.dead, color: C.red, hint: 'rejected outright' }),
          jsx(Tile, { label: 'Stale bench', value: sum.stale, color: C.yellow, hint: 'time passed, still flagged' }),
        ],
      }),
      jsx('div', {
        style: { margin: '12px 0', padding: '10px 14px', borderRadius: 10, fontSize: 13, fontWeight: 600,
          color: healthy ? C.green : C.red, background: healthy ? tint('--ui-green', '#3fb950', 10) : tint('--ui-red', '#ff7b72', 10),
          border: `1px solid ${healthy ? tint('--ui-green', '#3fb950', 35) : C.red}` },
        children: healthy ? `All ${sum.logins} logins across ${sum.bots} Bots are healthy, every default model is reachable, and ${sum.crons} active cron job${sum.crons === 1 ? '' : 's'} can run.` : `Needs attention: ${attentionParts(sum)}. Each one shows why, until when, and the fix.`,
      }),
      ...(d.risks || []).map((r) => jsxs('div', {
        style: { marginBottom: 12, padding: '10px 14px', borderRadius: 10, fontSize: 12.5, color: C.orange, background: tint('--ui-orange', '#ffa657', 9), border: `1px solid ${tint('--ui-orange', '#ffa657', 40)}` },
        children: [jsx('b', { children: `Risk: ${r.bots.length} Bots depend on one ${r.provider} login with no backup. ` }),
          `One rate limit on it stops all ${r.bots.length} (${r.bots.join(', ')}). Add a second login or a fallback model.`],
      }, `${r.provider}-${r.id}`)),
      jsx('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))', gap: 12 },
        children: d.profiles.map((p) => jsx(Bot, { p }, p.profile)) }),
      jsx('div', { style: { marginTop: 14, fontSize: 11, color: C.t4, lineHeight: 1.6 },
        children: 'After a 429, a 402 or a model the account is not entitled to, Hermes benches that login or blocks one model on it. `hermes auth status` still says "logged in". These end times come from Hermes\'s own credential code.' }),
    ],
  })
}

function StatusChip() {
  const s = useKeys()
  const sum = s.data && s.data.summary
  if (!sum) return null
  const bad = sum.attention
  return jsx('button', {
    type: 'button', title: 'Open Key Doctor', onClick: () => host.navigate(ROUTE),
    style: { background: 'transparent', border: 0, cursor: 'pointer', padding: '0 6px', fontSize: 11, color: bad ? C.red : C.green, fontFamily: MONO },
    children: sum.bots_stopped ? `⚿ ${sum.bots_stopped} Bot${sum.bots_stopped === 1 ? '' : 's'} can't reach a model` : bad ? `⚿ ${bad} need${bad === 1 ? 's' : ''} attention` : `⚿ ${sum.logins} keys ok`,
  })
}

export default {
  id: ID,
  name: 'Key Doctor',
  register(ctx) {
    ctx.register({ id: 'page', area: ROUTES_AREA, data: { path: ROUTE }, render: () => jsx(KeysPage, {}) })
    ctx.register({ id: 'nav', area: SIDEBAR_NAV_AREA, order: 87, data: { path: ROUTE, label: 'Key Doctor', codicon: 'key' } })
    ctx.register({ id: 'open', area: PALETTE_AREA, data: { id: `${ID}.open`, label: 'Open Key Doctor', keywords: ['keys', 'auth', 'credentials', 'benched', 'rate limit', 'login'], run: () => host.navigate(ROUTE) } })
    ctx.register({ id: 'statusbar', area: STATUSBAR_AREAS.right, order: 132, render: () => jsx(StatusChip, {}) })
    startPolling(ctx)
  },
}
