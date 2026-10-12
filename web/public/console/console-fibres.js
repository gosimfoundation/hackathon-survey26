/* Fibre panel: grid_side x grid_side cells (layout: fibre 0 bottom-left, rows along
 * +alt, columns along +az — so row 0 renders at the BOTTOM of the grid).
 * Each cell has a dropdown of candidate targets from the last `field` query answer.
 */

export class FibrePanel {
  constructor(container, onChange) {
    this.container = container;
    this.onChange = onChange || (() => {});
    this.selects = new Map(); // fiberId -> <select>
    this.nFibers = 0;
  }

  setup(instrument) {
    this.nFibers = instrument.n_fibers;
    const side = instrument.grid_side;
    this.container.style.gridTemplateColumns = `repeat(${side}, 1fr)`;
    this.container.innerHTML = '';
    this.selects.clear();
    for (let row = side - 1; row >= 0; row--) {
      for (let col = 0; col < side; col++) {
        const fid = row * side + col;
        const cell = document.createElement('div');
        cell.className = 'fibre';
        const label = document.createElement('div');
        label.className = 'fid';
        label.textContent = `F${fid}`;
        const sel = document.createElement('select');
        sel.dataset.fid = String(fid);
        sel.add(new Option('—', ''));
        sel.addEventListener('change', () => {
          cell.classList.toggle('filled', sel.value !== '');
          this.onChange();
        });
        cell.append(label, sel);
        this.container.append(cell);
        this.selects.set(fid, sel);
      }
    }
  }

  /* fibresMap: { fiberIdStr: [candidate, ...] } from the field query answer. */
  setCandidates(fibresMap) {
    for (const [fid, sel] of this.selects) {
      const prev = sel.value;
      sel.innerHTML = '';
      sel.add(new Option('—', ''));
      for (const c of (fibresMap && fibresMap[String(fid)]) || []) {
        const req = c.required ? ' · 必需 req' : '';
        const ok = c.altitude_ok === false ? ' · ↓低于高度下限 below min-alt' : '';
        const opt = new Option(
          `${c.target_id} · ${c.class} · w${c.science_weight}${req}${ok}`, c.target_id);
        if (c.altitude_ok === false) opt.disabled = true;
        sel.add(opt);
      }
      sel.value = prev; // kept only if still present, else browser resets to ''
      sel.parentElement.classList.toggle('filled', sel.value !== '');
    }
    this.onChange();
  }

  getAssignments() {
    const out = {};
    for (const [fid, sel] of this.selects) {
      if (sel.value) out[String(fid)] = sel.value;
    }
    return out;
  }

  setAssignments(map) {
    for (const [fid, sel] of this.selects) {
      const tid = map && (map[String(fid)] !== undefined ? map[String(fid)] : map[fid]);
      const want = tid == null ? '' : String(tid);
      if (want && ![...sel.options].some((o) => o.value === want)) sel.add(new Option(want, want));
      sel.value = want;
      sel.parentElement.classList.toggle('filled', sel.value !== '');
    }
    this.onChange();
  }

  clear() {
    this.setAssignments({});
  }
}
