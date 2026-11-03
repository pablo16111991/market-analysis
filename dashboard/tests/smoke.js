// Prueba de humo del dashboard con jsdom (sin navegador).
// Uso (desde la raiz del repo, tras `python3 dashboard/build.py`):
//   NODE_PATH=<carpeta con node_modules/jsdom> node dashboard/tests/smoke.js [carpeta_site]
// Sale con codigo 1 si algo falla. Se puede apuntar a una copia descargada del sitio publicado.
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const site = process.argv[2] || path.join(__dirname, '..', 'site');
const html = fs.readFileSync(path.join(site, 'index.html'), 'utf8')
  .replace(/<script src[^>]*><\/script>/g, '').replace(/<link[^>]*>/g, '');
const data = fs.readFileSync(path.join(site, 'data.json'), 'utf8');
const fails = [];
const check = (ok, msg) => { if (!ok) fails.push(msg); console.log((ok ? 'OK   ' : 'FAIL ') + msg); };

let parsed;
try { parsed = JSON.parse(data); check(true, 'data.json es JSON valido'); } catch (e) { check(false, 'data.json no parsea: ' + e.message); process.exit(1); }

const w = new JSDOM(html, { runScripts: 'outside-only', pretendToBeVisual: true }).window;
w.Chart = function () { this.destroy = () => {}; }; w.Chart.defaults = {};
const lg = { clearLayers() {}, addTo() { return this; } };
w.L = { map: () => ({ setView() { return this; }, invalidateSize() {} }), tileLayer: () => ({ addTo() {} }),
  layerGroup: () => lg, circleMarker: () => ({ addTo() { return { bindPopup() {} }; } }) };
w.fetch = () => Promise.resolve({ json: () => Promise.resolve(parsed) });
const errors = [];
w.addEventListener('error', e => errors.push(e.message));
process.on('unhandledRejection', e => errors.push(String(e.message || e)));
w.eval([...html.matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1]);

const d = w.document, q = x => d.querySelector(x), ev = (e, t) => e.dispatchEvent(new w.Event(t));
const T = x => (x ? x.textContent.replace(/\s+/g, ' ') : '');
const set = (id, v) => { q(id).value = v; ev(q(id), 'change'); ev(q(id), 'input'); };

setTimeout(() => {
  check(!/error/i.test(T(q('#gen'))) && T(q('#gen')).includes('Actualizado'), 'cabecera "Actualizado" sin errores: ' + T(q('#gen')).slice(0, 80));
  const total = d.querySelectorAll('#p-tab tr').length;
  check(total > 5, 'tabla de pisos con filas (' + total + ')');
  const cnt = () => parseInt(T(q('#f-count')).replace(/\./g, ''), 10);
  const base = cnt();
  const chip = q('.chip[data-k="terraza"]'); chip.click();
  check(cnt() > 0 && cnt() < base, `filtro terraza reduce (${base} -> ${cnt()})`);
  q('#f-reset').click();
  check(cnt() === base, 'Limpiar restaura filtros');
  // valorador
  const bar = q('#v-bar'); check(bar.options.length > 10, 'valorador tiene barrios (' + bar.options.length + ')');
  set('#v-m2', 70); set('#v-ask', 230000);
  check(/Estimo/.test(T(q('#v-out'))), 'valorador da una estimacion');
  // comparador de pisos
  const key = [...q('#c-bar').options].map(o => o.value)[5]; set('#c-bar', key); set('#c-m2', 70); set('#c-price', 230000);
  check(/De cada 10|Pocos datos/.test(T(q('#c-out'))), 'comparador de pisos responde');
  // tendencia
  check(T(q('#t-kpis')).length > 20, 'seccion de tendencia con KPIs');
  // second-hand: cada producto
  q('.tab[data-t="sh"]').click();
  const prods = [...d.querySelectorAll('.pc')];
  check(prods.length >= 1, 'second-hand tiene productos (' + prods.length + ')');
  prods.forEach(p => { p.click(); set('#s-mine', 1000);
    check(T(q('#s-verdict')).length > 20, 'veredicto second-hand para ' + p.dataset.n); });
  check(errors.length === 0, 'sin errores de JS (' + errors.slice(0, 2).join(' | ') + ')');
  console.log(fails.length ? `\n${fails.length} FALLOS` : '\nTODO OK');
  process.exit(fails.length ? 1 : 0);
}, 600);
