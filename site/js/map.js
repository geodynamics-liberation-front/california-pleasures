// The front page: the United States as flat lines inside faint state outlines, and the state
// under the pointer rising.
//
// decodeMap(buffer)                            parse site/data/map.bin (see build_map in tools/build_data.py)
// new LinesMap(svg, map, states, outlines)     draw the map into an <svg>; .raise(i) lifts state i (-1 = none),
//                                              .stateAt(clientX, clientY) tells which state a pointer is over

export function decodeMap(buffer) {
  const v = new DataView(buffer);
  if (buffer.byteLength < 32 || String.fromCharCode(v.getUint8(0), v.getUint8(1), v.getUint8(2), v.getUint8(3)) !== 'PLSM') {
    throw new Error('not a PLSM map file');
  }
  if (v.getUint16(4, true) !== 1) throw new Error('unsupported map version');
  const samples = v.getUint16(6, true), lines = v.getUint16(8, true);
  const n = samples * lines;
  if (buffer.byteLength !== 32 + 3 * n) throw new Error('map file is truncated');
  return {
    samples, lines, width: v.getFloat64(12, true), height: v.getFloat64(20, true),
    elev: new Int16Array(buffer, 32, n), owner: new Uint8Array(buffer, 32 + 2 * n, n),
  };
}

const RELIEF = 5;          // line spacings for the highest state; lower states rise as the square root
const RELIEF_FLOOR = 1.2;  // so the flattest states still visibly rise
const SVG = 'http://www.w3.org/2000/svg';
const f1 = (v) => (Math.round(v * 10) / 10).toString();

export class LinesMap {
  constructor(svg, map, states, outlines = {}) {
    this.svg = svg;
    this.map = map;
    this.states = states;
    this.active = -1;
    this.spacing = map.height / map.lines;
    this.step = map.width / map.samples;
    const highest = Math.max(...states.map((s) => s.elev[1]));
    this.peak = states.map((s) => this.spacing * Math.max(RELIEF_FLOOR, RELIEF * Math.sqrt(s.elev[1] / highest)));

    // per line: the runs of samples that belong to any state (the lines are only drawn there),
    // and per state: the lines it touches, so raising one only rewrites its lines
    this.runs = [];
    this.linesOf = states.map(() => []);
    const seen = new Uint8Array(states.length);
    for (let i = 0; i < map.lines; i++) {
      seen.fill(0);
      const row = map.owner.subarray(i * map.samples, (i + 1) * map.samples);
      const runs = [];
      let start = -1;
      for (let j = 0; j <= row.length; j++) {
        const o = j < row.length ? row[j] : 0;
        if (o && start < 0) start = j;
        if (!o && start >= 0) { runs.push([start, j - 1]); start = -1; }
        if (o && !seen[o - 1]) { seen[o - 1] = 1; this.linesOf[o - 1].push(i); }
      }
      this.runs.push(runs);
    }

    svg.setAttribute('viewBox', `0 0 ${map.width} ${map.height}`);
    svg.replaceChildren();
    const bg = document.createElementNS(SVG, 'rect');
    bg.setAttribute('width', map.width); bg.setAttribute('height', map.height); bg.setAttribute('class', 'paper');
    svg.append(bg);
    const og = document.createElementNS(SVG, 'g');
    og.setAttribute('class', 'outlines');
    this.outlines = states.map((s) => {
      const p = document.createElementNS(SVG, 'path');
      p.setAttribute('d', outlines[s.id] || '');
      og.append(p);
      return p;
    });
    svg.append(og);
    const g = document.createElementNS(SVG, 'g');
    g.setAttribute('class', 'lines');
    this.paths = [];
    for (let i = 0; i < map.lines; i++) {
      const p = document.createElementNS(SVG, 'path');
      p.setAttribute('d', this.line(i, -1));
      g.append(p);
      this.paths.push(p);
    }
    svg.append(g);
  }

  // line i with state s lifted (s = -1: everything flat): one subpath per run of state samples,
  // flat stretches as H, the lifted state's samples as points
  line(i, s) {
    const { samples, elev, owner } = this.map;
    const base = i * samples, step = this.step;
    const y0 = (i + 0.5) * this.spacing;
    const k = s >= 0 ? this.peak[s] / Math.max(1, this.states[s].elev[1]) : 0;
    const mine = (j) => s >= 0 && owner[base + j] === s + 1;
    let d = '';
    for (const [a, b] of this.runs[i]) {
      d += `M${f1(a * step)},${f1(y0)}`;
      let j = a;
      while (j <= b) {
        if (mine(j)) {
          // the lifted state's samples, entered and left at the baseline on the sample edges
          const a1 = j;
          while (j <= b && mine(j)) j++;
          d += `L${f1(a1 * step)},${f1(y0)}`;
          for (let m = a1; m < j; m++) d += `L${f1((m + 0.5) * step)},${f1(y0 - elev[base + m] * k)}`;
          d += `L${f1(j * step)},${f1(y0)}`;
        } else {
          while (j <= b && !mine(j)) j++;
          d += `H${f1(j * step)}`;
        }
      }
    }
    return d;
  }

  raise(s) {
    if (s === this.active) return;
    if (this.active >= 0) {
      for (const i of this.linesOf[this.active]) this.paths[i].setAttribute('d', this.line(i, -1));
      this.outlines[this.active].classList.remove('raised');
    }
    this.active = s;
    if (s >= 0) {
      for (const i of this.linesOf[s]) this.paths[i].setAttribute('d', this.line(i, s));
      this.outlines[s].classList.add('raised');
    }
  }

  // the state under a pointer, looking one line and one sample around it, or -1
  stateAt(clientX, clientY) {
    const r = this.svg.getBoundingClientRect();
    const x = (clientX - r.left) / r.width * this.map.width;
    const y = (clientY - r.top) / r.height * this.map.height;
    const j = Math.floor(x / this.step), i = Math.floor(y / this.spacing);
    const { samples, lines, owner } = this.map;
    for (const [di, dj] of [[0, 0], [-1, 0], [1, 0], [0, -1], [0, 1], [-1, -1], [-1, 1], [1, -1], [1, 1]]) {
      const ii = i + di, jj = j + dj;
      if (ii < 0 || ii >= lines || jj < 0 || jj >= samples) continue;
      const o = owner[ii * samples + jj];
      if (o) return o - 1;
    }
    return -1;
  }
}
