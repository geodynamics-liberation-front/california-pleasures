#!/usr/bin/env node
// Render every state in site/data/ with the same code the browser uses:
//
//   site/downloads/<xx>.svg    the state at the default settings
//   site/downloads/<xx>.pdf
//
//   node tools/render.mjs            all states
//   node tools/render.mjs ca ri      only these

import { mkdirSync, readFileSync, writeFileSync, renameSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { decodeGrid, draw, toSVG, toPDF, DEFAULTS } from '../site/js/pleasures.js';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SITE = join(ROOT, 'site');
const fail = (m) => { console.error(`render.mjs: ${m}`); process.exit(1); };

let index;
try {
  index = JSON.parse(readFileSync(join(SITE, 'data', 'states.json'), 'utf8'));
} catch (e) {
  fail(`cannot read site/data/states.json (${e.message}); run make build first`);
}
const only = new Set(process.argv.slice(2).map((s) => s.toLowerCase()));
const states = index.states.filter((s) => only.size === 0 || only.has(s.id));
if (states.length === 0) fail('no matching states');

mkdirSync(join(SITE, 'downloads'), { recursive: true });

const write = (path, text) => { writeFileSync(path + '.part', text); renameSync(path + '.part', path); };
let bytes = 0;
for (const s of states) {
  let grid;
  try {
    const buf = readFileSync(join(SITE, 'data', s.file));
    grid = decodeGrid(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));
  } catch (e) {
    fail(`${s.file}: ${e.message}`);
  }
  const title = `${s.name} – Topographic Pleasures`;
  const full = draw(grid, DEFAULTS);
  const svg = toSVG(full, { title });
  const pdf = toPDF(full, { title: `${s.name} - Topographic Pleasures` });
  write(join(SITE, 'downloads', `${s.id}.svg`), svg);
  write(join(SITE, 'downloads', `${s.id}.pdf`), pdf);
  bytes += svg.length + pdf.length;
  console.log(`${s.abbr} ${s.name}: svg ${(svg.length / 1e3).toFixed(0)} kB, pdf ${(pdf.length / 1e3).toFixed(0)} kB`);
}
console.log(`rendered ${states.length} states, ${(bytes / 1e6).toFixed(1)} MB`);
