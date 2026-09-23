// Topographic Pleasures: the map of fifty states and the workbench for one of them.
//
// Routes live in the hash: ""  the gallery,  "#ca"  California,  "#ca?lines=80&relief=4"  with settings.

import { decodeGrid, draw, toSVG, toPDF, DEFAULTS, LIMITS, clampOptions } from './pleasures.js';
import { decodeMap, LinesMap } from './map.js';

// Bump when the files in data/ change, so browsers and the site's cache refetch them.
const DATA_VERSION = 1;

const $ = (sel) => document.querySelector(sel);
const gallery = $('#gallery');
const mapSvg = $('#map');
const caption = $('#caption');
const stateView = $('#state');
let linesMap = null;
const art = $('#art');
const form = $('#controls');
const grids = new Map();
let index = null;
let current = null;        // { state, grid, picture }
let pending = 0;

async function main() {
  try {
    const r = await fetch(`data/states.json?v=${DATA_VERSION}`);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    index = await r.json();
  } catch (e) {
    gallery.innerHTML = `<p class="error">The list of states did not load (${escapeHTML(e.message)}). <a href="">Try again</a>.</p>`;
    return;
  }
  buildGallery();
  wireControls();
  buildMap();
  window.addEventListener('hashchange', route);
  route();
}

function buildGallery() {
  $('#states').innerHTML = index.states.map((s, i) => `<a href="#${s.id}" data-index="${i}">${escapeHTML(s.name)}</a>`).join('');
}

const HINT = 'Move across the map to raise a state, and click it to open it.';

// raise state s on the map (-1: none) and say which it is
function highlight(s) {
  if (!linesMap) return;
  linesMap.raise(s);
  mapSvg.classList.toggle('over', s >= 0);
  caption.textContent = s >= 0 ? index.states[s].name : HINT;
}

async function buildMap() {
  if (!index.map) { caption.textContent = 'The map is not part of this build.'; return; }
  try {
    const [m, o] = await Promise.all([
      fetch(`data/${index.map.file}?v=${DATA_VERSION}`),
      fetch(`data/${index.map.outlines}?v=${DATA_VERSION}`),
    ]);
    if (!m.ok) throw new Error(`${index.map.file}: ${m.status} ${m.statusText}`);
    if (!o.ok) throw new Error(`${index.map.outlines}: ${o.status} ${o.statusText}`);
    linesMap = new LinesMap(mapSvg, decodeMap(await m.arrayBuffer()), index.states, (await o.json()).outlines);
  } catch (e) {
    caption.innerHTML = `The map did not load (${escapeHTML(e.message)}). <a href="">Try again</a>, or pick a state from the list below.`;
    return;
  }
  caption.textContent = HINT;
  const point = (e) => {
    const s = linesMap.stateAt(e.clientX, e.clientY);
    highlight(s);
    return s;
  };
  // Which kind of pointer last touched the map. The click event carries no pointerType in Safari,
  // and on a touch screen the browser fires pointerleave between the finger lifting and the click,
  // so neither the click nor the map's raised state can be trusted to tell a tap from a mouse click.
  let pointer = 'mouse';
  let tapped = -1;           // the state raised by the last tap on a touch screen
  mapSvg.addEventListener('pointerdown', (e) => { pointer = e.pointerType || 'mouse'; });
  mapSvg.addEventListener('pointermove', (e) => { if (e.pointerType === 'mouse') point(e); });
  mapSvg.addEventListener('pointerleave', (e) => { if (e.pointerType === 'mouse') highlight(-1); });
  mapSvg.addEventListener('click', (e) => {
    const s = point(e);
    if (s < 0) { tapped = -1; return; }
    // with a mouse the state is already raised; on a touch screen the first tap raises, the second opens
    if (pointer === 'mouse' || s === tapped) {
      tapped = -1;
      location.hash = `#${index.states[s].id}`;
    } else {
      tapped = s;
      caption.textContent = `${index.states[s].name} – tap again to open it`;
    }
  });
  // the list under the map raises states too, for hover and for keyboard focus
  const list = $('#states');
  const fromLink = (e) => { const a = e.target.closest('a[data-index]'); return a ? Number(a.dataset.index) : -1; };
  list.addEventListener('pointerover', (e) => { const s = fromLink(e); if (s >= 0) highlight(s); });
  list.addEventListener('pointerout', (e) => { if (fromLink(e) >= 0) highlight(-1); });
  list.addEventListener('focusin', (e) => { const s = fromLink(e); if (s >= 0) highlight(s); });
  list.addEventListener('focusout', (e) => { if (fromLink(e) >= 0) highlight(-1); });
}

function parseHash() {
  const h = location.hash.replace(/^#/, '');
  if (!h) return { id: null, params: new URLSearchParams() };
  const [id, query = ''] = h.split('?');
  return { id: id.toLowerCase(), params: new URLSearchParams(query) };
}

function optionsFromParams(params) {
  const o = {};
  for (const k of [...Object.keys(LIMITS), 'projection', 'line', 'background']) {
    if (params.has(k)) o[k] = params.get(k);
  }
  return clampOptions(o);
}

async function route() {
  const { id, params } = parseHash();
  const state = id && index.states.find((s) => s.id === id);
  if (!state) {
    if (!stateView.hidden) window.scrollTo(0, 0);
    stateView.hidden = true;
    gallery.hidden = false;
    document.title = 'Topographic Pleasures';
    current = null;
    if (id) history.replaceState(null, '', location.pathname);
    return;
  }
  if (stateView.hidden || current?.state !== state) window.scrollTo(0, 0);
  gallery.hidden = true;
  stateView.hidden = false;
  document.title = `${state.name} – Topographic Pleasures`;
  const i = index.states.indexOf(state);
  const prev = index.states[(i + index.states.length - 1) % index.states.length];
  const next = index.states[(i + 1) % index.states.length];
  $('#prev').href = `#${prev.id}`; $('#prev').textContent = prev.name;
  $('#next').href = `#${next.id}`; $('#next').textContent = next.name;
  $('#state-name').textContent = state.name;
  const km = (state.cell * 111.2).toFixed(1);
  $('#state-facts').textContent =
    `Highest cell ${state.elev[1].toLocaleString()} m. ${state.cols.toLocaleString()} × ${state.rows.toLocaleString()} cells of ${km} km.`;

  const options = optionsFromParams(params);
  setForm(options, state);
  if (current?.state !== state) {
    current = { state, grid: null, picture: null };
    art.innerHTML = '<p class="loading">Loading elevation data…</p>';
    try {
      const grid = await loadGrid(state);
      if (current.state !== state) return;          // the reader moved on
      current.grid = grid;
    } catch (e) {
      art.innerHTML = `<p class="error">${escapeHTML(state.name)}'s elevation data did not load (${escapeHTML(e.message)}). <a href="#${state.id}">Try again</a>.</p>`;
      return;
    }
  }
  render();
}

async function loadGrid(state) {
  if (grids.has(state.id)) return grids.get(state.id);
  const r = await fetch(`data/${state.file}?v=${DATA_VERSION}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  const grid = decodeGrid(await r.arrayBuffer());
  grids.set(state.id, grid);
  return grid;
}

function readForm() {
  const o = {};
  for (const el of form.elements) if (el.name) o[el.name] = el.value;
  return clampOptions(o);
}

function setForm(o, state) {
  form.elements.detail.max = Math.max(LIMITS.detail[0], state.cols);
  for (const el of form.elements) if (el.name && o[el.name] !== undefined) el.value = o[el.name];
  showValues();
}

function showValues() {
  for (const k of ['lines', 'relief', 'detail', 'stroke', 'tails']) {
    $(`#${k}-out`).value = form.elements[k].value;
  }
}

function render() {
  if (!current?.grid) return;
  clearTimeout(pending);                 // coalesce a burst of slider events into one drawing
  pending = setTimeout(() => {
    const o = readForm();
    current.picture = draw(current.grid, o);
    art.innerHTML = toSVG(current.picture, { title: `${current.state.name} – Topographic Pleasures` });
    updateHash(o);
  }, 0);
}

function updateHash(o) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (String(v) !== String(DEFAULTS[k])) q.set(k, v);
  const query = q.toString();
  const hash = `#${current.state.id}${query ? '?' + query : ''}`;
  if (location.hash !== hash) history.replaceState(null, '', hash);
}

function download(name, type, text) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function wireControls() {
  form.addEventListener('input', () => { showValues(); render(); });
  form.addEventListener('submit', (e) => e.preventDefault());
  $('#reset').addEventListener('click', () => { setForm(DEFAULTS, current.state); render(); });
  $('#dl-svg').addEventListener('click', () => {
    if (!current?.picture) return;
    download(`${current.state.id}-pleasures.svg`, 'image/svg+xml', toSVG(current.picture, { title: `${current.state.name} – Topographic Pleasures` }));
  });
  $('#dl-pdf').addEventListener('click', () => {
    if (!current?.picture) return;
    download(`${current.state.id}-pleasures.pdf`, 'application/pdf', toPDF(current.picture, { title: `${current.state.name} - Topographic Pleasures` }));
  });
  $('#copy-link').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    try {
      await navigator.clipboard.writeText(location.href);
      btn.textContent = 'Link copied'; btn.classList.add('done');
    } catch {
      btn.textContent = 'Copy the address bar to share these settings';
    }
    setTimeout(() => { btn.textContent = 'Copy link to these settings'; btn.classList.remove('done'); }, 2500);
  });
  document.addEventListener('keydown', (e) => {
    if (!current || e.target.closest('input, select, textarea')) return;
    if (e.key === 'ArrowLeft') $('#prev').click();
    if (e.key === 'ArrowRight') $('#next').click();
  });
}

function escapeHTML(s) {
  return String(s).replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
}

main();
