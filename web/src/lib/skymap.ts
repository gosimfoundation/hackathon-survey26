/**
 * Shared sky-map drawing for the hero console and the submission "observed universe" map.
 * Pure canvas 2D, no chart library. Altitude / LST follow the scorer's formulas exactly.
 * Tiles carry the v3 scheduling class (REQUIRED drawn as a diamond, FLEXIBLE as a square);
 * observed marks are coloured by the scorer's action outcome.
 */
import { OUTCOME_COLORS, type OutcomeClass } from './report'

export type SchedulingClass = 'R' | 'F'
export interface SkyTile { id: string; ra: number; dec: number; cls: SchedulingClass; region: string; exp?: number }
export interface SkySite { lat: number; lon: number; min_alt: number }
export interface ObservedMark { state: OutcomeClass; doneSec: number }
export interface SkyFrame {
  /** Replay time (unix seconds) used for the meridian line and visibility rings; null hides both. */
  nowSec: number | null
  observed: Map<string, ObservedMark>
  /** Length (in replay seconds) of the glow after a tile fills in; 0 disables the pulse. */
  pulseSeconds?: number
  /**
   * How solid to draw the things that mark "now" — the meridian and the reach rings. Defaults to 1.
   * The replay drops it to 0 while it cuts across skipped hours, so the cursor dissolves rather than
   * appearing to leap to a new hour angle.
   */
  timeFade?: number
}

export const CLASS_COLORS: Record<SchedulingClass, string> = { R: '#f5f5f5', F: '#78a6ff' }
/** A point source on the sky, landed on by one fibre of some pointing; the demo console's unit, replacing the fixed-patch "tile". */
export interface SkyTarget { id: string; ra: number; dec: number; required: boolean }
/** The current pointing being drawn live: its sky-average centre and the targets its fibres are landing on. */
export interface LivePointing { ra: number; dec: number; targets: string[] }
const RA_MAX = 360, DEC_MIN = -10, DEC_MAX = 70
export const PAD = { left: 30, right: 10, top: 16, bottom: 18 }

const DEG = Math.PI / 180
const mod = (a: number, n: number) => ((a % n) + n) % n
/** The RA band label a point falls in — same eight 45°-wide bands the grid draws, R00 at ra=0. */
export const regionOf = (ra: number): string => `R0${Math.floor(mod(ra, 360) / 45)}`

/** Local sidereal time in degrees (GMST + east longitude). */
export function lstDeg(lon: number, unixSeconds: number): number {
  const jd = 2440587.5 + unixSeconds / 86400
  const d = jd - 2451545.0
  const gmst = 280.46061837 + 360.98564736629 * d
  return mod(gmst + lon, 360)
}

/** Altitude of a point (ra, dec in degrees) at a site and time, in degrees. */
export function altitudeDeg(site: SkySite, ra: number, dec: number, unixSeconds: number): number {
  const h = (mod(lstDeg(site.lon, unixSeconds) - ra + 180, 360) - 180) * DEG
  const sinAlt = Math.sin(site.lat * DEG) * Math.sin(dec * DEG) + Math.cos(site.lat * DEG) * Math.cos(dec * DEG) * Math.cos(h)
  return Math.asin(Math.max(-1, Math.min(1, sinAlt))) / DEG
}

export const isVisible = (site: SkySite, tile: SkyTile, unixSeconds: number) => altitudeDeg(site, tile.ra, tile.dec, unixSeconds) >= site.min_alt

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
}

/** Parse a v3 tiles.csv (tile_id, ra_deg, dec_deg, nominal_exptime_seconds, region_id, scheduling_class, ...). */
export function parseTilesCsv(text: string): SkyTile[] {
  const lines = text.replace(/^﻿/, '').split(/\r?\n/).filter(l => l.trim())
  if (!lines.length) return []
  const header = lines[0]!.split(',').map(h => h.trim())
  const col = (name: string) => header.indexOf(name)
  const [ci, cr, cd, cc, cg, ce] = [col('tile_id'), col('ra_deg'), col('dec_deg'), col('scheduling_class'), col('region_id'), col('nominal_exptime_seconds')]
  if (ci < 0 || cr < 0 || cd < 0) return []
  const out: SkyTile[] = []
  for (const line of lines.slice(1)) {
    const cells = line.split(',')
    const ra = Number(cells[cr]), dec = Number(cells[cd])
    if (!Number.isFinite(ra) || !Number.isFinite(dec)) continue
    const cls = String(cells[cc] ?? '').trim().toUpperCase().startsWith('R') ? 'R' : 'F'
    const region = cg >= 0 ? String(cells[cg] ?? '').trim() : `R${String(Math.floor(mod(ra, 360) / 45)).padStart(2, '0')}`
    out.push({ id: String(cells[ci]).trim(), ra, dec, cls, region, exp: ce >= 0 ? Number(cells[ce]) : undefined })
  }
  return out
}

/** Size the backing store to the CSS box × devicePixelRatio; returns the CSS size. */
export function fitCanvas(canvas: HTMLCanvasElement): { w: number; h: number } {
  const dpr = Math.min(window.devicePixelRatio || 1, 3)
  const w = Math.max(1, canvas.clientWidth), h = Math.max(1, canvas.clientHeight)
  const bw = Math.round(w * dpr), bh = Math.round(h * dpr)
  if (canvas.width !== bw || canvas.height !== bh) { canvas.width = bw; canvas.height = bh }
  canvas.getContext('2d')?.setTransform(dpr, 0, 0, dpr, 0, 0)
  return { w, h }
}

function tilePath(ctx: CanvasRenderingContext2D, cls: SchedulingClass, cx: number, cy: number, half: number) {
  ctx.beginPath()
  if (cls === 'R') {
    const r = half * 1.45
    ctx.moveTo(cx, cy - r); ctx.lineTo(cx + r, cy); ctx.lineTo(cx, cy + r); ctx.lineTo(cx - r, cy); ctx.closePath()
  } else {
    ctx.rect(cx - half, cy - half, half * 2, half * 2)
  }
}

/** Projection for the RA/Dec plot box; shared by the tile map and the target map so both read identically. */
function plot(canvas: HTMLCanvasElement) {
  const { w, h } = fitCanvas(canvas)
  const pw = w - PAD.left - PAD.right, ph = h - PAD.top - PAD.bottom
  return { w, h, pw, ph, x: (ra: number) => PAD.left + (ra / RA_MAX) * pw, y: (dec: number) => PAD.top + ((DEC_MAX - dec) / (DEC_MAX - DEC_MIN)) * ph }
}

/** Graticule (8 RA regions, 20° dec bands) and the "now" meridian line, identical on both maps. */
function drawGrid(ctx: CanvasRenderingContext2D, site: SkySite, nowSec: number | null, timeFade: number, geo: ReturnType<typeof plot>) {
  const { w, pw, ph, x, y } = geo
  ctx.clearRect(0, 0, geo.w, geo.h)
  ctx.font = '10px "IBM Plex Mono", ui-monospace, monospace'
  ctx.textBaseline = 'middle'
  ctx.lineWidth = 1
  ctx.strokeStyle = 'rgba(255,255,255,.12)'
  ctx.fillStyle = 'rgba(255,255,255,.4)'
  for (let ra = 0; ra <= 360; ra += 45) {
    const px = Math.round(x(ra)) + .5
    ctx.beginPath(); ctx.moveTo(px, PAD.top); ctx.lineTo(px, PAD.top + ph); ctx.stroke()
    ctx.textAlign = 'center'
    if (ra < 360) ctx.fillText(`R0${ra / 45}`, x(ra + 22.5), PAD.top / 2)
    ctx.fillText(ra === 360 ? '360°' : `${ra}°`, px, geo.h - PAD.bottom / 2)
  }
  ctx.textAlign = 'right'
  for (let dec = 0; dec <= DEC_MAX; dec += 20) {
    const py = Math.round(y(dec)) + .5
    ctx.beginPath(); ctx.moveTo(PAD.left, py); ctx.lineTo(PAD.left + pw, py); ctx.stroke()
    ctx.fillText(`${dec > 0 ? '+' : ''}${dec}°`, PAD.left - 5, py)
  }
  ctx.strokeStyle = 'rgba(255,255,255,.25)'
  ctx.strokeRect(PAD.left + .5, PAD.top + .5, pw - 1, ph - 1)

  if (nowSec != null && timeFade > 0.02) {
    const px = Math.round(x(lstDeg(site.lon, nowSec))) + .5
    ctx.strokeStyle = `rgba(49,94,251,${.75 * timeFade})`
    ctx.setLineDash([3, 3])
    ctx.beginPath(); ctx.moveTo(px, PAD.top); ctx.lineTo(px, PAD.top + ph); ctx.stroke()
    ctx.setLineDash([])
    ctx.fillStyle = `rgba(120,166,255,${timeFade})`
    ctx.textAlign = px > w - 40 ? 'right' : 'left'
    ctx.fillText('LST', px + (px > w - 40 ? -4 : 4), PAD.top + 8)
  }
}

export function drawSkyMap(canvas: HTMLCanvasElement, tiles: SkyTile[], site: SkySite, frame: SkyFrame): void {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const geo = plot(canvas)
  const { pw, x, y } = geo
  const timeFade = Math.max(0, Math.min(1, frame.timeFade ?? 1))
  drawGrid(ctx, site, frame.nowSec, timeFade, geo)

  const s = Math.max(4, Math.min(9, Math.round(pw / 90)))
  const half = s / 2
  const pulse = frame.pulseSeconds ?? 0
  for (const tile of tiles) {
    const cx = x(mod(tile.ra, 360)), cy = y(tile.dec)
    const outline = CLASS_COLORS[tile.cls]
    const mark = frame.observed.get(tile.id)
    ctx.globalAlpha = 1
    if (frame.nowSec != null && timeFade > 0.02 && isVisible(site, tile, frame.nowSec)) {
      ctx.strokeStyle = `rgba(255,255,255,${.4 * timeFade})`
      ctx.lineWidth = 1
      ctx.beginPath(); ctx.arc(cx, cy, half + 4, 0, Math.PI * 2); ctx.stroke()
    }
    if (mark && mark.state !== 'completed') {
      // interrupted / unsafe / invalid attempts: coloured outline, no fill
      ctx.strokeStyle = OUTCOME_COLORS[mark.state]
      ctx.lineWidth = 1.5
      tilePath(ctx, tile.cls, cx, cy, half)
      ctx.stroke()
      continue
    }
    if (mark) {
      const color = OUTCOME_COLORS.completed
      if (pulse > 0 && frame.nowSec != null) {
        const k = 1 - Math.min(1, Math.max(0, (frame.nowSec - mark.doneSec) / pulse))
        if (k > 0) {
          ctx.save()
          ctx.globalAlpha = k * .9
          ctx.shadowColor = color; ctx.shadowBlur = 10 + 10 * k
          ctx.fillStyle = color
          tilePath(ctx, tile.cls, cx, cy, half + 2 * k)
          ctx.fill()
          ctx.restore()
        }
      }
      ctx.fillStyle = color
      tilePath(ctx, tile.cls, cx, cy, half)
      ctx.fill()
      if (tile.cls === 'R') { ctx.strokeStyle = outline; ctx.lineWidth = 1; ctx.stroke() }
    } else {
      ctx.strokeStyle = outline
      ctx.lineWidth = tile.cls === 'R' ? 1.25 : 1
      ctx.globalAlpha = tile.cls === 'R' ? 1 : .8
      tilePath(ctx, tile.cls, cx, cy, half - .5)
      ctx.stroke()
    }
  }
  ctx.globalAlpha = 1
}

function targetPath(ctx: CanvasRenderingContext2D, required: boolean, cx: number, cy: number, half: number) {
  ctx.beginPath()
  if (required) {
    const r = half * 1.45
    ctx.moveTo(cx, cy - r); ctx.lineTo(cx + r, cy); ctx.lineTo(cx, cy + r); ctx.lineTo(cx - r, cy); ctx.closePath()
  } else {
    ctx.rect(cx - half, cy - half, half * 2, half * 2)
  }
}

export interface TargetFrame extends SkyFrame {
  /** The pointing being drawn live, if any — its 15-ish fibre hits are joined to its centre with thin spokes. */
  livePointing?: LivePointing | null
}

/**
 * Current-format sky map: point-source targets (◇ required, □ optional), each lit up once a pointing's
 * fibre lands on it, plus — while a pointing is live — its field centre joined to each of its hits.
 */
export function drawTargetMap(canvas: HTMLCanvasElement, targets: SkyTarget[], site: SkySite, frame: TargetFrame): void {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const geo = plot(canvas)
  const { pw, x, y } = geo
  const timeFade = Math.max(0, Math.min(1, frame.timeFade ?? 1))
  drawGrid(ctx, site, frame.nowSec, timeFade, geo)

  const s = Math.max(4, Math.min(9, Math.round(pw / 90)))
  const half = s / 2
  const pulse = frame.pulseSeconds ?? 0
  const byId = frame.livePointing ? new Map(targets.map(t => [t.id, t])) : null

  if (frame.livePointing && byId) {
    const { ra, dec, targets: hits } = frame.livePointing
    const cx = x(mod(ra, 360)), cy = y(dec)
    ctx.strokeStyle = 'rgba(120,166,255,.55)'
    ctx.lineWidth = 1
    for (const id of hits) {
      const t = byId.get(id)
      if (!t) continue
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x(mod(t.ra, 360)), y(t.dec)); ctx.stroke()
    }
    ctx.strokeStyle = '#78a6ff'
    ctx.lineWidth = 1.25
    ctx.beginPath(); ctx.moveTo(cx - half * 1.8, cy); ctx.lineTo(cx + half * 1.8, cy); ctx.moveTo(cx, cy - half * 1.8); ctx.lineTo(cx, cy + half * 1.8); ctx.stroke()
    ctx.beginPath(); ctx.arc(cx, cy, half * 2.4, 0, Math.PI * 2); ctx.stroke()
  }

  for (const target of targets) {
    const cx = x(mod(target.ra, 360)), cy = y(target.dec)
    const outline = target.required ? CLASS_COLORS.R : CLASS_COLORS.F
    const mark = frame.observed.get(target.id)
    ctx.globalAlpha = 1
    if (frame.nowSec != null && timeFade > 0.02 && altitudeDeg(site, target.ra, target.dec, frame.nowSec) >= site.min_alt) {
      ctx.strokeStyle = `rgba(255,255,255,${.4 * timeFade})`
      ctx.lineWidth = 1
      ctx.beginPath(); ctx.arc(cx, cy, half + 4, 0, Math.PI * 2); ctx.stroke()
    }
    if (mark && mark.state !== 'completed') {
      ctx.strokeStyle = OUTCOME_COLORS[mark.state]
      ctx.lineWidth = 1.5
      targetPath(ctx, target.required, cx, cy, half)
      ctx.stroke()
      continue
    }
    if (mark) {
      const color = OUTCOME_COLORS.completed
      if (pulse > 0 && frame.nowSec != null) {
        const k = 1 - Math.min(1, Math.max(0, (frame.nowSec - mark.doneSec) / pulse))
        if (k > 0) {
          ctx.save()
          ctx.globalAlpha = k * .9
          ctx.shadowColor = color; ctx.shadowBlur = 10 + 10 * k
          ctx.fillStyle = color
          targetPath(ctx, target.required, cx, cy, half + 2 * k)
          ctx.fill()
          ctx.restore()
        }
      }
      ctx.fillStyle = color
      targetPath(ctx, target.required, cx, cy, half)
      ctx.fill()
      if (target.required) { ctx.strokeStyle = outline; ctx.lineWidth = 1; ctx.stroke() }
    } else {
      ctx.strokeStyle = outline
      ctx.lineWidth = target.required ? 1.25 : 1
      ctx.globalAlpha = target.required ? 1 : .8
      targetPath(ctx, target.required, cx, cy, half - .5)
      ctx.stroke()
    }
  }
  ctx.globalAlpha = 1
}
