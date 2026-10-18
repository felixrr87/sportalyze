// ══════════════════════════════════════════════════════════════════
// COMPROBADOR DE LA MAQUETA DEL INFORME POST-PARTIDO
// ══════════════════════════════════════════════════════════════════
//   node comprobar_informe.js <index.html> <informe.json>
//
// Carga el index.html de verdad en un DOM, le pasa un informe
// calculado por el motor y comprueba que lo dibujado ES el dato.
//
// Lo que de verdad busca aquí son los dos fallos que no se ven mirando:
//
//   1. Que un tiro se pinte en el sitio equivocado. StatsBomb da las
//      coordenadas SIEMPRE con el atacante yendo hacia x=120, así que
//      al visitante hay que darle la vuelta para que ataque hacia su
//      lado. Si no se hace —o se hace dos veces, o sólo en x— los dos
//      equipos disparan a la misma portería y el mapa parece correcto.
//      Aquí se comprueba tiro a tiro.
//
//   2. Que un nodo de la red de pases no esté en su posición media.
//      Un círculo mal puesto no canta: simplemente cuenta una historia
//      distinta de la que pasó.
const fs = require('fs');
const { JSDOM } = require('jsdom');

const [rutaHtml, rutaJson] = process.argv.slice(2);
const d = JSON.parse(fs.readFileSync(rutaJson, 'utf8'));
const html = fs.readFileSync(rutaHtml, 'utf8');

let fallos = 0;
function comprueba(ok, que, detalle) {
  if (ok) console.log(`  ok    ${que}`);
  else { fallos++; console.log(`  FALLA ${que}${detalle ? '  → ' + detalle : ''}`); }
}

const dom = new JSDOM(html, {
  url: 'http://localhost:8000/',
  runScripts: 'dangerously',
  pretendToBeVisual: true,
});
const w = dom.window;

w.addEventListener('load', () => {
  comprueba(typeof w.infPinta === 'function', 'infPinta existe');
  if (typeof w.infPinta !== 'function') return fin();
  w.infPinta(d);

  const doc = w.document;
  const L = d.local, V = d.visitante;
  const num = (el, a) => parseFloat(el.getAttribute(a));

  // ── marcador ──
  const cab = doc.getElementById('infMarcador').textContent;
  comprueba(cab.includes(L) && cab.includes(V), 'los dos equipos están en la cabecera');
  comprueba(cab.replace(/\s/g, '').includes(`${d.goles_local}–${d.goles_visitante}`),
    `el marcador pintado es ${d.goles_local}–${d.goles_visitante}`,
    cab.replace(/\s+/g, ' ').trim().slice(0, 70));

  // ── red de pases ──
  let malNodo = [], malEnlace = [];
  [L, V].forEach(e => {
    const r = d.red[e];
    // el bloque de cada equipo es el que lleva su nombre en el título
    const bloque = [...doc.querySelectorAll('#infRedes > div')]
      .find(b => b.querySelector('b') && b.querySelector('b').textContent.trim() === e);
    if (!bloque) { malNodo.push(`no encuentro el bloque de ${e}`); return; }
    const circulos = [...bloque.querySelectorAll('g > circle')];
    if (circulos.length !== r.nodos.length)
      malNodo.push(`${e}: ${circulos.length} círculos y ${r.nodos.length} nodos`);
    r.nodos.forEach(n => {
      const c = circulos.find(c =>
        Math.abs(num(c, 'cx') - n.x) < 0.01 && Math.abs(num(c, 'cy') - n.y) < 0.01);
      if (!c) malNodo.push(`${e}: ${n.corto} debería estar en (${n.x}, ${n.y}) y no hay círculo ahí`);
    });
    // Sólo las líneas CON título son enlaces de pases: el campo
    // también dibuja una línea, la del medio, y la primera versión de
    // esta comprobación la contaba y daba 35 de 34.
    const lineas = [...bloque.querySelectorAll('line')]
      .filter(l => l.querySelector('title'));
    if (lineas.length !== r.enlaces.length)
      malEnlace.push(`${e}: ${lineas.length} líneas y ${r.enlaces.length} enlaces`);
  });
  comprueba(!malNodo.length, 'cada jugador está en su posición media', malNodo[0]);
  comprueba(!malEnlace.length, 'hay una línea por pareja de pases', malEnlace[0]);

  // ── mapa de tiros: lo del espejo ──
  const tiros = [...doc.querySelectorAll('#infTiros svg circle')]
    .filter(c => c.querySelector('title'));     // los puntos del campo no llevan title
  comprueba(tiros.length === d.tiros.length,
    `hay un círculo por tiro (${d.tiros.length})`, `salen ${tiros.length}`);

  let malEspejo = [], malRelleno = [];
  d.tiros.forEach(t => {
    const esperadoX = t.equipo === L ? t.x : 120 - t.x;
    const esperadoY = t.equipo === L ? t.y : 80 - t.y;
    const c = tiros.find(c =>
      Math.abs(num(c, 'cx') - esperadoX) < 0.01 && Math.abs(num(c, 'cy') - esperadoY) < 0.01);
    if (!c) {
      malEspejo.push(`${t.corto} (${t.equipo}) min ${t.minuto}: debería estar en ` +
        `(${esperadoX.toFixed(1)}, ${esperadoY.toFixed(1)})`);
      return;
    }
    const relleno = c.getAttribute('fill') !== 'none';
    if (relleno !== t.gol)
      malRelleno.push(`${t.corto} min ${t.minuto}: gol=${t.gol} y relleno=${relleno}`);
  });
  comprueba(!malEspejo.length,
    'cada equipo dispara hacia su portería (el visitante va espejado)', malEspejo[0]);
  comprueba(!malRelleno.length, 'sólo los goles salen rellenos', malRelleno[0]);

  // Y que el espejo sea de verdad un espejo: si el visitante NO se
  // girara, sus tiros caerían todos en el mismo lado que los del local.
  const xLocal = d.tiros.filter(t => t.equipo === L).map(t => t.x);
  const xVisit = tiros.filter((c, i) => d.tiros[i] && d.tiros[i].equipo === V)
    .map(c => num(c, 'cx'));
  if (xLocal.length && xVisit.length) {
    const medL = xLocal.reduce((a, b) => a + b, 0) / xLocal.length;
    const medV = xVisit.reduce((a, b) => a + b, 0) / xVisit.length;
    comprueba(medL > 60 && medV < 60,
      'los dos equipos atacan a porterías distintas',
      `media de x: ${L} ${medL.toFixed(1)}, ${V} ${medV.toFixed(1)}`);
  }

  // ── carrera de xG ──
  const xgTxt = doc.getElementById('infXg').textContent;
  [L, V].forEach(e => {
    const fin = d.carrera_xg[e][d.carrera_xg[e].length - 1].xg.toFixed(2);
    comprueba(xgTxt.includes(fin), `el xG final de ${e} (${fin}) está escrito`, xgTxt.slice(0, 80));
  });
  const golesPintados = doc.querySelectorAll('#infXg circle').length;
  const golesDato = d.tiros.filter(t => t.gol).length;
  comprueba(golesPintados === golesDato,
    `la carrera marca los ${golesDato} goles`, `marca ${golesPintados}`);

  // ── comparativa ──
  const barras = [...doc.querySelectorAll('#infStats > div')];
  comprueba(barras.length > 10, `hay ${barras.length} filas de comparativa`);
  let malBarra = [];
  barras.forEach(b => {
    const tr = [...b.querySelectorAll('div > div')];
    if (tr.length < 2) return;
    const suma = tr.slice(-2).reduce((a, el) => a + parseFloat(
      (el.getAttribute('style').match(/width:\s*([\d.]+)%/) || [0, 0])[1]), 0);
    if (Math.abs(suma - 100) > 0.01) malBarra.push(`una barra suma ${suma}%`);
  });
  comprueba(!malBarra.length, 'cada barra de comparativa ocupa el 100 %', malBarra[0]);

  // El xG de la comparativa tiene que ser el mismo que el de la carrera
  const comp = doc.getElementById('infStats').textContent;
  comprueba(comp.includes(d.estadisticas[L].xg.toFixed(2)) &&
            comp.includes(d.estadisticas[V].xg.toFixed(2)),
    'el xG de la comparativa coincide con el del resto de la pantalla');

  // ── jugadores ──
  const filas = [...doc.querySelectorAll('#infJug tbody tr')];
  comprueba(filas.length === Math.min(24, d.jugadores.length),
    'la tabla de jugadores tiene las filas que toca', `salen ${filas.length}`);
  const mejor = [...d.jugadores].sort((a, b) => b.xg - a.xg)[0];
  comprueba(filas[0] && filas[0].textContent.includes(mejor.corto),
    `el primero de la tabla es el de más xG (${mejor.corto})`,
    filas[0] && filas[0].textContent.trim().slice(0, 50));

  // ── la atribución, que es condición de uso ──
  const todo = doc.getElementById('page-informe').textContent;
  comprueba(/StatsBomb/i.test(todo), 'StatsBomb aparece en la pantalla');

  // ── y el cartel de error ──
  w.infEstado('Prueba', 'texto', 'detalle');
  comprueba(doc.getElementById('infEstado').style.display !== 'none',
    'el cartel de error aparece cuando hace falta');
  comprueba(doc.getElementById('infTirosCard').style.display === 'none',
    'con el error visible, el informe se esconde entero');

  fin();
});

function fin() {
  console.log('');
  if (fallos) { console.log(`${fallos} comprobación(es) FALLAN`); process.exit(1); }
  console.log('Todo el informe pintado cuadra con el dato.');
  process.exit(0);
}

setTimeout(() => { console.log('\nse ha quedado colgado'); process.exit(2); }, 60000);
