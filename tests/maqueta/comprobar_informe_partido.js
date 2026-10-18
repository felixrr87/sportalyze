// ══════════════════════════════════════════════════════════════════
// COMPROBADOR DEL INFORME DE UN PARTIDO DE ESTA TEMPORADA
// ══════════════════════════════════════════════════════════════════
//   node comprobar_informe_partido.js <index.html> <informe.json>
//
// Carga el index.html de verdad en un DOM, le sirve un informe salido
// del motor —no un JSON escrito a mano— y comprueba que lo dibujado
// ES el dato.
//
// LO QUE BUSCA
//
//   1. QUE CADA EQUIPO ATAQUE HACIA SU LADO. Es el fallo que no canta:
//      el mapa sigue pareciendo un mapa y cuenta otra historia. Se
//      comprueba tiro a tiro contra las coordenadas del motor.
//
//   2. QUE LA LÍNEA DE xG ACABE DONDE DICE EL RESUMEN. El gráfico y el
//      número grande de arriba salen de sitios distintos del código;
//      si no coinciden, el visitante ve dos cifras que se contradicen.
//
//   3. QUE LOS GOLES ESTÉN EN SU MINUTO en la carrera.
//
//   4. QUE LA TABLA DE JUGADORES SEA LA DEL EQUIPO QUE DICE. Poner los
//      jugadores del visitante bajo el nombre del local es trivial de
//      hacer e imposible de ver.
//
//   5. QUE DIGA DE DÓNDE SALE Y QUÉ NO TIENE. Si alguien quita ese
//      aviso, esta pantalla pasa a parecer un informe completo.
const fs = require('fs');
const { JSDOM } = require('jsdom');

const [rutaHtml, rutaJson] = process.argv.slice(2);
const D = JSON.parse(fs.readFileSync(rutaJson, 'utf8'));
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
const dibujados = {};

w.addEventListener('load', async () => {
  w.fetch = async (url) => ({
    ok: true, status: 200,
    json: async () => JSON.parse(JSON.stringify(D)),
  });
  w.Chart = function (ctx, cfg) {
    dibujados[ctx && ctx.__id] = cfg;
    this.data = cfg.data; this.options = cfg.options; this.destroy = () => {};
  };
  w.HTMLCanvasElement.prototype.getContext = function () { return { __id: this.id }; };

  const doc = w.document;
  const L = D.local, V = D.visitante;
  const el = D.equipos[L], ev = D.equipos[V];

  comprueba(typeof w.abrirInformePartido === 'function', 'abrirInformePartido existe');
  if (typeof w.abrirInformePartido !== 'function') return fin();

  await w.abrirInformePartido('PD', L, V, D.fecha);
  await new Promise(r => setTimeout(r, 80));

  const caja = doc.getElementById('infPartido');
  comprueba(!!caja, 'el informe se abre');
  if (!caja) return fin();
  const txt = caja.textContent.replace(/\s+/g, ' ').trim();

  // ── 1. el marcador y el xG ──
  comprueba(txt.includes(`${D.goles_local}–${D.goles_visitante}`),
    `pinta el marcador ${D.goles_local}–${D.goles_visitante}`,
    txt.slice(0, 120));
  comprueba(txt.includes(el.xg.toFixed(2)) && txt.includes(ev.xg.toFixed(2)),
    `pinta el xG de los dos (${el.xg} y ${ev.xg})`);

  // ── 2. el mapa, tiro a tiro ──
  const circulos = [...caja.querySelectorAll('svg circle')].filter(c => c.querySelector('title'));
  comprueba(circulos.length === D.tiros.length,
    `pinta los ${D.tiros.length} tiros`, `pinta ${circulos.length}`);

  const malos = [];
  D.tiros.forEach(t => {
    const c = circulos.find(x =>
      Math.abs(+x.getAttribute('cx') - t.x) < 0.01 &&
      Math.abs(+x.getAttribute('cy') - t.y) < 0.01);
    if (!c) return malos.push(`${t.jugador} min ${t.minuto}: nada en (${t.x}, ${t.y})`);
    const relleno = c.getAttribute('fill') !== 'none';
    if (relleno !== t.gol) malos.push(`${t.jugador} min ${t.minuto}: relleno ${relleno}, gol ${t.gol}`);
    const tit = c.querySelector('title').textContent;
    if (!tit.includes(t.xg.toFixed(3))) malos.push(`${t.jugador}: el ratón no dice su xG`);
  });
  comprueba(malos.length === 0,
    'cada tiro está en su coordenada, con su xG al pasar el ratón',
    malos.slice(0, 3).join(' · '));

  // ── el fallo que no canta: los dos equipos a la misma portería ──
  const xl = D.tiros.filter(t => !t.visitante).map(t => t.x);
  const xv = D.tiros.filter(t => t.visitante).map(t => t.x);
  comprueba(xl.length && xv.length && Math.min(...xl) > Math.max(...xv),
    'los dos equipos atacan a porterías distintas',
    `local ${Math.min(...xl)}–${Math.max(...xl)}, visitante ${Math.min(...xv)}–${Math.max(...xv)}`);

  // ── 3. la carrera de xG ──
  const g = dibujados['ipCarrera'];
  comprueba(!!g, 'dibuja la carrera de xG');
  if (g) {
    const dl = g.data.datasets[0].data, dv = g.data.datasets[1].data;
    comprueba(g.data.datasets[0].label === L && g.data.datasets[1].label === V,
      'cada línea lleva el nombre de su equipo');
    comprueba(JSON.stringify(dl) === JSON.stringify(D.carrera.map(p => p.local)) &&
              JSON.stringify(dv) === JSON.stringify(D.carrera.map(p => p.visitante)),
      'la línea es exactamente la carrera que calculó el motor');
    comprueba(Math.abs(dl[dl.length - 1] - el.xg) < 0.005 &&
              Math.abs(dv[dv.length - 1] - ev.xg) < 0.005,
      'la línea acaba en el xG que dice el resumen',
      `acaba en ${dl[dl.length - 1]} / ${dv[dv.length - 1]}, el resumen dice ${el.xg} / ${ev.xg}`);
    comprueba(g.data.datasets.every(ds => ds.stepped),
      'la línea va a escalones (el xG salta con cada tiro, no sube en diagonal)');

    const goles = D.carrera.map((p, i) => [p, i]).filter(([p]) => p.gol);
    const malGol = goles.filter(([p, i]) => {
      const ds = p.gol === L ? 0 : 1;
      return g.data.datasets[ds].pointRadius[i] === 0;
    });
    comprueba(malGol.length === 0,
      `los ${goles.length} goles salen marcados en su minuto`,
      malGol.map(([p]) => `${p.gol} min ${p.minuto}`).join(' · '));
    comprueba(g.options.scales.y.beginAtZero === true,
      'el eje de xG empieza en cero (si no, exagera la diferencia)');
  }

  // ── 4. la tabla de cada equipo ──
  if (el.jugadores.length) {
    const tablas = [...caja.querySelectorAll('table')];
    comprueba(tablas.length >= 2, `hay una tabla por equipo`, `hay ${tablas.length}`);
    const nombresLocal = el.jugadores.filter(j => j.minutos > 0).map(j => j.nombre);
    const filas = tablas.length ? [...tablas[tablas.length - 2].querySelectorAll('tbody tr')] : [];
    const pintados = filas.map(tr =>
      tr.querySelector('td').textContent.replace(/[🟥🟨]/g, '').trim());
    comprueba(JSON.stringify(pintados) === JSON.stringify(nombresLocal),
      'la tabla del local lleva a los jugadores del local',
      `pinta ${pintados.slice(0, 3)} y son ${nombresLocal.slice(0, 3)}`);

    // ── y no se inventa el minuto del cambio ──
    //
    // roster_in / roster_out de Understat parecen minutos y son
    // identificadores internos. Con ellos en pantalla salió
    // "Gerard Martín ▲806581".
    const conNumeros = filas.map(tr => tr.textContent)
      .filter(t => /[▲▼]\s*\d{3,}/.test(t));
    comprueba(conNumeros.length === 0,
      'no pinta identificadores internos haciéndolos pasar por minutos',
      conNumeros[0]);
  }

  // ── 5. honestidad ──
  comprueba(/Understat/.test(txt), 'dice que los datos son de Understat');
  comprueba(/red de pases/i.test(txt),
    'dice que NO tiene red de pases (si se quita, parece un informe completo)');
  comprueba(/StatsBomb/i.test(txt),
    'y manda al informe que sí la tiene');

  // ── y cuando el servidor se niega ──
  w.cerrarInformePartido();
  w.fetch = async () => ({
    ok: false, status: 404,
    json: async () => ({ detail: {
      motivo: 'nombres_no_encajan',
      detalle: 'He encontrado partidos de ese día pero ninguno es éste.',
      partidos_ese_dia: ['Sevilla - Betis', 'Valencia - Levante'] } }),
  });
  await w.abrirInformePartido('PD', 'Equipo A', 'Equipo B', '2026-10-18');
  await new Promise(r => setTimeout(r, 60));
  const t2 = doc.getElementById('infPartido').textContent.replace(/\s+/g, ' ');
  comprueba(/ninguno es éste/.test(t2), 'cuando se niega, explica por qué');
  comprueba(/Sevilla - Betis/.test(t2),
    'y enseña qué partidos SÍ había ese día');
  comprueba(!doc.querySelector('#infPartido svg circle'),
    'y no dibuja ningún mapa vacío');

  fin();
});

function fin() {
  console.log(fallos === 0
    ? '\nTodo el informe del partido cuadra con el dato.'
    : `\n${fallos} FALLOS`);
  process.exit(fallos === 0 ? 0 : 1);
}
