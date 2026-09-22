// The drawing: elevation grid in, "Unknown Pleasures" lines out, as SVG or PDF.
//
// Runs in the browser (site/js/app.js) and in Node (tools/render.mjs) with no dependencies.
//
//   decodeGrid(arrayBuffer)      -> grid           parse a site/data/<xx>.bin file
//   draw(grid, options)          -> picture        the lines in image units (1000 wide)
//   toSVG(picture, options)      -> string
//   toPDF(picture, options)      -> string         a one-page vector PDF, pure ASCII
//
// A picture is drawn north to south. Every line is a filled shape (fill = background colour)
// with a white stroke, so a line hides whatever lies behind it: that is the whole trick.

export const DEFAULTS = {
  lines: 60,          // number of latitude lines
  relief: 5,          // height of the state's highest point, in line spacings
  detail: 400,        // points per line, roughly (the grid is block averaged down to this)
  stroke: 1.4,        // line width in image units (the image is 1000 wide)
  tails: 0.08,        // flat extension on each side, as a fraction of the state's width
  margin: 0.04,       // blank frame on every side, as a fraction of the state's width
  projection: 'mercator',   // or 'equirectangular'
  line: '#ffffff',
  background: '#000000',
};

export const LIMITS = {
  lines: [8, 200], relief: [0.5, 20], detail: [40, 4000], stroke: [0.2, 6], tails: [0, 0.5], margin: [0, 0.3],
};

export const NODATA = -32768;

export function decodeGrid(buffer) {
  const v = new DataView(buffer);
  if (buffer.byteLength < 64 || String.fromCharCode(v.getUint8(0), v.getUint8(1), v.getUint8(2), v.getUint8(3)) !== 'PLSR') {
    throw new Error('not a PLSR grid file');
  }
  const version = v.getUint16(4, true);
  if (version !== 1) throw new Error(`unsupported grid version ${version}`);
  const cols = v.getUint16(6, true), rows = v.getUint16(8, true);
  if (buffer.byteLength !== 64 + 2 * rows * cols) throw new Error('grid file is truncated');
  return {
    cols, rows,
    lon0: v.getFloat64(12, true), lat0: v.getFloat64(20, true), cell: v.getFloat64(28, true),
    nodata: v.getInt16(36, true), elevMin: v.getInt16(38, true), elevMax: v.getInt16(40, true),
    data: new Int16Array(buffer, 64, rows * cols),
  };
}

const RAD = Math.PI / 180;
const projections = {
  mercator: {
    x: (lon) => lon * RAD,
    y: (lat) => Math.log(Math.tan(Math.PI / 4 + lat * RAD / 2)),
    lat: (y) => (2 * Math.atan(Math.exp(y)) - Math.PI / 2) / RAD,
  },
  equirectangular: {
    x: (lon, k) => lon * RAD * k,
    y: (lat) => lat * RAD,
    lat: (y) => y / RAD,
  },
};

export function clampOptions(o) {
  const out = { ...DEFAULTS, ...o };
  for (const k in LIMITS) {
    const n = Number(out[k]);
    out[k] = Number.isFinite(n) ? Math.min(LIMITS[k][1], Math.max(LIMITS[k][0], n)) : DEFAULTS[k];
  }
  out.lines = Math.round(out.lines);
  out.detail = Math.round(out.detail);
  if (!projections[out.projection]) out.projection = DEFAULTS.projection;
  for (const k of ['line', 'background']) if (!/^#[0-9a-fA-F]{6}$/.test(out[k])) out[k] = DEFAULTS[k];
  return out;
}

// Sample the grid along `lines` latitudes and lay the lines out in a 1000-unit-wide image.
export function draw(grid, options = {}) {
  const o = clampOptions(options);
  const P = projections[o.projection];
  const { cols, rows, lon0, lat0, cell, data } = grid;
  const lonW = lon0, lonE = lon0 + cols * cell;
  const latN = lat0, latS = lat0 - rows * cell;
  const k = Math.cos((latN + latS) / 2 * RAD);       // horizontal squeeze for equirectangular

  const yN = P.y(latN), yS = P.y(latS);
  const spacing = (yN - yS) / o.lines;
  const xW = P.x(lonW, k), xE = P.x(lonE, k);
  const width = xE - xW;
  const scaleZ = o.relief * spacing / Math.max(1, grid.elevMax);   // projected units per metre

  const factor = Math.max(1, Math.round(cols / o.detail));   // about `detail` points per line
  const tailW = xW - o.tails * width, tailE = xE + o.tails * width;

  // Each line: the flat tail, then for every run of in-state cells a baseline point at the run's
  // west edge, the block averages of the run (blocks start at the run, so nothing outside it is
  // averaged in), a baseline point at its east edge, and the flat tail again. So the line always
  // drops to the baseline exactly at the state's border, whatever the detail.
  const lines = [];
  let top = -Infinity;
  for (let i = 0; i < o.lines; i++) {
    const y0 = yN - (i + 0.5) * spacing;
    const lat = P.lat(y0);
    const r = Math.min(rows - 1, Math.max(0, Math.floor((lat0 - lat) / cell)));
    const row = data.subarray(r * cols, (r + 1) * cols);
    const xs = [tailW], ys = [y0];
    let j = 0;
    while (j < cols) {
      if (row[j] === NODATA) { j++; continue; }
      const a = j;
      while (j < cols && row[j] !== NODATA) j++;
      const b = j;
      xs.push(P.x(lon0 + a * cell, k)); ys.push(y0);
      for (let c = a; c < b; c += factor) {
        const c1 = Math.min(b, c + factor);
        let sum = 0;
        for (let m = c; m < c1; m++) sum += row[m];
        const y = y0 + (sum / (c1 - c)) * scaleZ;
        xs.push(P.x(lon0 + (c + c1) / 2 * cell, k)); ys.push(y);
        if (y > top) top = y;
      }
      xs.push(P.x(lon0 + b * cell, k)); ys.push(y0);
    }
    xs.push(tailE); ys.push(y0);
    lines.push({ y0, xs, ys, lat });
  }

  // frame: state width plus tails and margins; vertically from the lowest baseline to the highest peak
  const pad = o.margin * width;
  const x0 = tailW - pad, x1 = tailE + pad;
  const y1 = Math.max(top, yN) + pad, y0 = yS - pad;
  const s = 1000 / (x1 - x0);
  const height = (y1 - y0) * s;
  const paths = lines.map((L) => ({
    x: L.xs.map((x) => (x - x0) * s),
    y: L.ys.map((y) => (y1 - y) * s),
    lat: L.lat,
  }));
  return { width: 1000, height, paths, options: o };
}

const fmt = (v, p) => {
  const s = v.toFixed(p);
  return p > 0 ? s.replace(/\.?0+$/, '') : s;
};

// SVG text. `precision` = decimals (0.1 of an image unit is 0.1 mm on a metre-wide print); `scale`
// shrinks the coordinate space (thumbnails use 0.5 with 0 decimals).
export function toSVG(pic, { title = "", precision = 1, scale = 1 } = {}) {
  const o = pic.options;
  const W = fmt(pic.width * scale, precision), H = fmt(pic.height * scale, precision);
  const out = [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">`,
  ];
  if (title) out.push(`<title>${escapeXML(title)}</title>`);
  out.push(`<rect width="${W}" height="${H}" fill="${o.background}"/>`);
  out.push(`<g fill="${o.background}" stroke="${o.line}" stroke-width="${fmt(o.stroke * scale, 3)}" stroke-linejoin="round" stroke-linecap="round">`);
  for (const p of pic.paths) {
    const pts = [];
    for (let i = 0; i < p.x.length; i++) pts.push(`${fmt(p.x[i] * scale, precision)},${fmt(p.y[i] * scale, precision)}`);
    out.push(`<path d="M${pts.join(' ')}"/>`);
  }
  out.push('</g>', '</svg>', '');
  return out.join('\n');
}

function escapeXML(s) {
  return String(s).replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
}

// A single-page PDF, one point per image unit (1000 pt = 35.3 cm wide). ASCII only, so byte
// offsets are string offsets. The fill of an open path closes it along the baseline; the stroke
// does not, which is exactly the behaviour the drawing needs.
export function toPDF(pic, { title = '' } = {}) {
  const o = pic.options;
  const rgb = (hex) => [1, 3, 5].map((i) => fmt(parseInt(hex.slice(i, i + 2), 16) / 255, 3)).join(' ');
  const H = pic.height;
  const c = [
    `${rgb(o.background)} rg 0 0 ${fmt(pic.width, 2)} ${fmt(H, 2)} re f`,
    `${rgb(o.line)} RG ${rgb(o.background)} rg ${fmt(o.stroke, 3)} w 1 J 1 j`,
  ];
  for (const p of pic.paths) {
    const seg = [`${fmt(p.x[0], 1)} ${fmt(H - p.y[0], 1)} m`];
    for (let i = 1; i < p.x.length; i++) seg.push(`${fmt(p.x[i], 1)} ${fmt(H - p.y[i], 1)} l`);
    seg.push('B');
    c.push(seg.join(' '));
  }
  const content = c.join('\n') + '\n';
  const info = title ? `/Title (${title.replace(/[\\()]/g, '\\$&').replace(/[^\x20-\x7e]/g, '?')}) ` : '';
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${fmt(pic.width, 2)} ${fmt(H, 2)}] /Contents 4 0 R /Resources << >> >>`,
    `<< /Length ${content.length} >>\nstream\n${content}endstream`,
    `<< ${info}/Producer (Topographic Pleasures) >>`,
  ];
  let pdf = '%PDF-1.4\n';
  const offsets = [];
  objects.forEach((body, i) => {
    offsets.push(pdf.length);
    pdf += `${i + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xref = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const off of offsets) pdf += `${String(off).padStart(10, '0')} 00000 n \n`;
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R /Info 5 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return pdf;
}
