/* Sky view with three zooms (Review of Task 2 fix):
 *   sky       — alt/az polar plot, zenith centre, horizon edge, min-alt ring, N/E marks.
 *   footprint — linear alt-az projection centred on the observable targets' centroid,
 *               scaled to fit them (default once targets are up). x = az·cos(alt0).
 *   field     — ~4× the FOV around the commanded pointing; draws the 4×4 fibre cells
 *               (instrument geometry: rows along alt, columns along az·cos(alt)) and
 *               each candidate target inside its fibre cell, assigned ones highlighted.
 * Tap/click sets the pointing in every zoom. Required targets ringed, observed dimmed.
 */

const CLASS_COLORS = {
  ELG: '#4cc9f0', LRG: '#f0724c', QSO: '#c86ef0', BGS: '#7ce08a', Star: '#e8e8e8',
};
const DIR_AZ = { N: 0, NE: 45, E: 90, SE: 135, S: 180, SW: 225, W: 270, NW: 315 };
const wrap180 = (d) => ((d + 540) % 360) - 180;
const rad = (d) => (d * Math.PI) / 180;

export class SkyView {
  constructor(canvas, onPoint) {
    this.canvas = canvas;
    this.onPoint = onPoint;
    this.state = null;
    this.zoom = 'footprint'; // default toggle; draws a note until targets are up
    canvas.addEventListener('click', (ev) => this._click(ev));
    new ResizeObserver(() => this.draw()).observe(canvas);
  }

  setZoom(z) { this.zoom = z; this.draw(); }

  update(state) {
    this.state = state;
    this.draw();
  }

  /* --- projections ------------------------------------------------------- */

  _geom() {
    const w = this.canvas.width;
    return { cx: w / 2, cy: w / 2, R: w / 2 - Math.max(18, w * 0.045) };
  }

  _polar(alt, az, cx, cy, R) {
    const r = ((90 - alt) / 90) * R;
    return [cx + r * Math.sin(rad(az)), cy - r * Math.cos(rad(az))];
  }

  /* Linear projection for footprint/field: returns {cAlt, cAz, half, px, inv}. */
  _linear() {
    const st = this.state || {};
    const { cx, cy, R } = this._geom();
    let cAlt, cAz, half;
    const fov = st.fovSideDeg || 2.5;
    if (this.zoom === 'field' && st.pointing) {
      cAlt = st.pointing.alt_deg; cAz = st.pointing.az_deg;
      half = 2 * fov; // ~4× the FOV across
    } else {
      const rows = (st.view && st.view.targets) || [];
      if (!rows.length) return null;
      let sx = 0, sy = 0, sz = 0;
      for (const [, alt, az] of rows) {
        sx += Math.cos(rad(alt)) * Math.cos(rad(az));
        sy += Math.cos(rad(alt)) * Math.sin(rad(az));
        sz += Math.sin(rad(alt));
      }
      cAlt = Math.atan2(sz, Math.hypot(sx, sy)) * 180 / Math.PI;
      cAz = (Math.atan2(sy, sx) * 180 / Math.PI + 360) % 360;
      const cosC = Math.max(0.15, Math.cos(rad(cAlt)));
      half = fov / 2;
      for (const [, alt, az] of rows) {
        half = Math.max(half, Math.abs(alt - cAlt), Math.abs(wrap180(az - cAz)) * cosC);
      }
      half += fov / 2; // margin so the FOV square fits at the edges
    }
    const scale = R / half;
    const cosC = Math.max(0.15, Math.cos(rad(cAlt)));
    return {
      cAlt, cAz, half, cosC, scale,
      px: (alt, az) => [cx + scale * wrap180(az - cAz) * cosC, cy - scale * (alt - cAlt)],
      inv: (x, y) => [cAlt + (cy - y) / scale, (cAz + (x - cx) / (scale * cosC) + 360) % 360],
    };
  }

  _click(ev) {
    if (!this.state || !this.onPoint) return;
    const rect = this.canvas.getBoundingClientRect();
    const s = this.canvas.width / rect.width;
    const x = (ev.clientX - rect.left) * s;
    const y = (ev.clientY - rect.top) * s;
    let alt, az;
    if (this.zoom === 'sky') {
      const { cx, cy, R } = this._geom();
      const dx = x - cx, dy = y - cy;
      const r = Math.hypot(dx, dy);
      if (r > R) return;
      alt = 90 - (r / R) * 90;
      az = (Math.atan2(dx, -dy) * 180) / Math.PI;
    } else {
      const L = this._linear();
      if (!L) return;
      [alt, az] = L.inv(x, y);
    }
    alt = Math.min(90, Math.max(0, Math.round(alt * 100) / 100));
    az = Math.round(((az + 360) % 360) * 100) / 100;
    this.onPoint(alt, az);
  }

  /* --- drawing ------------------------------------------------------------ */

  draw() {
    const canvas = this.canvas;
    const css = canvas.clientWidth || 320;
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(css * dpr)) canvas.width = Math.round(css * dpr);
    canvas.height = canvas.width;
    const ctx = canvas.getContext('2d');
    const st = this.state;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#0d1523';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (this.zoom === 'sky') this._drawSkyFrame(ctx); else this._drawLinearFrame(ctx);
    if (!st || !st.view) return;
    this._bulletins(ctx, st.snapshot);
    this._targets(ctx, st.view.targets || []);
    if (this.zoom === 'field') this._fibres(ctx, st);
    if (st.pointing) this._pointing(ctx, st);
  }

  _px(alt, az) {
    if (this.zoom === 'sky') {
      const { cx, cy, R } = this._geom();
      return this._polar(alt, az, cx, cy, R);
    }
    const L = this._L || (this._L = this._linear());
    return L ? L.px(alt, az) : [-100, -100];
  }

  _drawSkyFrame(ctx) {
    const { cx, cy, R } = this._geom();
    const st = this.state;
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, 7); ctx.fillStyle = '#0d1523'; ctx.fill();
    ctx.strokeStyle = '#2c3750'; ctx.lineWidth = 1;
    for (const alt of [60, 30]) {
      ctx.beginPath(); ctx.arc(cx, cy, ((90 - alt) / 90) * R, 0, 7); ctx.stroke();
    }
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, 7); ctx.stroke();
    const minAlt = st && st.view ? st.view.min_alt_deg : 30;
    ctx.strokeStyle = '#e0a83c'; ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.arc(cx, cy, ((90 - minAlt) / 90) * R, 0, 7); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#93a0b8';
    ctx.font = `${Math.max(11, this.canvas.width * 0.03)}px sans-serif`;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText('N', cx, cy - R - 10); ctx.fillText('S', cx, cy + R + 10);
    ctx.fillText('E', cx + R + 10, cy); ctx.fillText('W', cx - R - 10, cy);
  }

  _drawLinearFrame(ctx) {
    const { cx, cy, R } = this._geom();
    const L = this._L = this._linear();
    if (!L) {
      ctx.fillStyle = '#93a0b8'; ctx.textAlign = 'center';
      ctx.fillText('暂无可观测目标 No observable targets', cx, cy);
      return;
    }
    const st = this.state;
    ctx.strokeStyle = '#2c3750'; ctx.lineWidth = 1;
    ctx.strokeRect(cx - R, cy - R, 2 * R, 2 * R);
    const minAlt = st && st.view ? st.view.min_alt_deg : 30;
    ctx.fillStyle = '#93a0b8'; ctx.font = `${Math.max(10, this.canvas.width * 0.024)}px sans-serif`;
    ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    for (let alt = Math.ceil((L.cAlt - L.half) / 10) * 10; alt <= L.cAlt + L.half; alt += 10) {
      const y = cy - L.scale * (alt - L.cAlt);
      if (Math.abs(y - cy) > R) continue;
      ctx.strokeStyle = alt === minAlt ? '#e0a83c' : '#1d2637';
      ctx.setLineDash(alt === minAlt ? [5, 4] : []);
      ctx.beginPath(); ctx.moveTo(cx - R, y); ctx.lineTo(cx + R, y); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillText(`alt ${alt}°`, cx - R + 4, y - 8);
    }
    for (let dAz = -180; dAz <= 180; dAz += 30) {
      const az = Math.round(L.cAz + dAz);
      const x = cx + L.scale * wrap180(az - L.cAz) * L.cosC;
      if (Math.abs(x - cx) > R) continue;
      ctx.strokeStyle = '#1d2637';
      ctx.beginPath(); ctx.moveTo(x, cy - R); ctx.lineTo(x, cy + R); ctx.stroke();
      ctx.fillStyle = '#93a0b8';
      ctx.fillText(`${((az % 360) + 360) % 360}°`, x + 2, cy + R - 10);
    }
  }

  _bulletins(ctx, snapshot) {
    const notices = (snapshot && snapshot.latest_bulletin && snapshot.latest_bulletin.notices) || [];
    for (const n of notices) {
      if (!n.direction || n.direction === 'ALL' || !(n.direction in DIR_AZ)) continue;
      const az = DIR_AZ[n.direction];
      ctx.fillStyle = 'rgba(224, 86, 86, 0.16)';
      if (this.zoom === 'sky') {
        const { cx, cy, R } = this._geom();
        ctx.beginPath(); ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, R, rad(az - 22.5) - Math.PI / 2, rad(az + 22.5) - Math.PI / 2);
        ctx.closePath(); ctx.fill();
      } else {
        const L = this._L;
        if (!L) continue;
        const [x0] = this._px(L.cAlt, az - 22.5);
        const [x1] = this._px(L.cAlt, az + 22.5);
        const { cx, cy, R } = this._geom();
        const a = Math.max(cx - R, Math.min(x0, x1));
        const b = Math.min(cx + R, Math.max(x0, x1));
        if (b > a) ctx.fillRect(a, cy - R, b - a, 2 * R);
      }
    }
  }

  _targets(ctx, rows) {
    const dot = Math.max(1.5, this.canvas.width * 0.004);
    for (const [id, alt, az, cls, weight, required, observed] of rows) {
      const [x, y] = this._px(alt, az);
      ctx.fillStyle = CLASS_COLORS[cls] || '#cccccc';
      ctx.globalAlpha = observed > 0 ? 0.3 : 0.95;
      ctx.beginPath(); ctx.arc(x, y, dot, 0, 7); ctx.fill();
      if (required) {
        ctx.globalAlpha = 0.9; ctx.strokeStyle = ctx.fillStyle;
        ctx.beginPath(); ctx.arc(x, y, dot * 2, 0, 7); ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
  }

  /* Field zoom: 4×4 fibre cells around the pointing + candidates per cell. */
  _fibres(ctx, st) {
    const inst = st.instrument;
    if (!inst || !st.pointing) return;
    const side = inst.grid_side || Math.round(Math.sqrt(inst.n_fibers || 16));
    const pitch = inst.pitch_deg || 0;
    const halfGlass = (inst.glass_side_deg || 0) / 2;
    const cosAlt = Math.max(0.15, Math.cos(rad(st.pointing.alt_deg)));
    const assigned = st.assignments || {};
    const cands = (st.field && st.field.fibres) || {};
    for (let fid = 0; fid < side * side; fid++) {
      const row = Math.floor(fid / side), col = fid % side;
      const dAlt = (row - (side - 1) / 2) * pitch;
      const dAz = (col - (side - 1) / 2) * pitch; // az·cos(alt) space
      const fAlt = st.pointing.alt_deg + dAlt;
      const fAz = st.pointing.az_deg + dAz / cosAlt;
      const corners = [
        [fAlt - halfGlass, fAz - halfGlass / cosAlt], [fAlt + halfGlass, fAz + halfGlass / cosAlt],
      ];
      const [x0, y1] = this._px(corners[0][0], corners[0][1]);
      const [x1, y0] = this._px(corners[1][0], corners[1][1]);
      ctx.strokeStyle = assigned[String(fid)] ? '#3fb96b' : '#35507e';
      ctx.lineWidth = assigned[String(fid)] ? 1.8 : 1;
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
      ctx.fillStyle = '#93a0b8';
      ctx.font = `${Math.max(9, this.canvas.width * 0.02)}px sans-serif`;
      ctx.textAlign = 'left'; ctx.textBaseline = 'top';
      ctx.fillText(`F${fid}`, x0 + 2, y0 + 1);
      for (const c of cands[String(fid)] || []) {
        const [tx, ty] = this._px(c.alt_deg, c.az_deg);
        const mine = assigned[String(fid)] === c.target_id;
        ctx.fillStyle = CLASS_COLORS[c.class] || '#cccccc';
        ctx.globalAlpha = c.observed > 0 ? 0.35 : 0.95;
        ctx.beginPath(); ctx.arc(tx, ty, mine ? 4 : 2.4, 0, 7); ctx.fill();
        if (mine || c.required) {
          ctx.strokeStyle = mine ? '#3fb96b' : ctx.fillStyle;
          ctx.beginPath(); ctx.arc(tx, ty, mine ? 6.5 : 5, 0, 7); ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }
    }
  }

  _pointing(ctx, st) {
    const { alt_deg, az_deg } = st.pointing;
    const [x, y] = this._px(alt_deg, az_deg);
    const half = (st.fovSideDeg || 2.5) / 2;
    const cosAlt = Math.max(0.2, Math.cos(rad(alt_deg)));
    ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 1.6;
    ctx.beginPath();
    [[half, -half], [half, half], [-half, half], [-half, -half]]
      .map(([da, daz]) => this._px(alt_deg + da, az_deg + daz / cosAlt))
      .forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py)));
    ctx.closePath(); ctx.stroke();
    ctx.beginPath(); ctx.arc(x, y, 3, 0, 7); ctx.fillStyle = '#58a6ff'; ctx.fill();
  }
}
