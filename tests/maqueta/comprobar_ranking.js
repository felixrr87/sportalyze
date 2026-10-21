// ══════════════════════════════════════════════════════════════════
// COMPROBADOR DEL RANKING DE GOLES Y ASISTENCIAS
// ══════════════════════════════════════════════════════════════════
//   node comprobar_ranking.js <index.html> <ranking.json> <ranking_dif.json>
//
// Carga el index.html de verdad en un DOM, le sirve la respuesta que
// da la ruta /api/goles-asistencias y comprueba que lo dibujado ES el
// dato.
//
// LO QUE BUSCA, Y POR QUÉ CADA COSA
//
//   1. QUE LA PANTALLA NO REORDENE. El orden lo decide el servidor
//      porque el recorte de `limit` tiene que caer DESPUÉS de
//      ordenar. Si la pantalla reordenara por su cuenta, la lista
//      saldría ordenada pero recortada por otro criterio, y el que se
//      busca —el que lleva poco pero mucho más de lo que le tocaba—
//      se habría quedado fuera sin que se viera. Aquí se comprueba
//      fila a fila que el orden pintado es el de la respuesta.
//
//   2. QUE LA DIFERENCIA SEA LA DEL SERVIDOR. La columna que importa
//      es G+A menos xG+xA. Si la pantalla la recalculara, dos
//      redondeos distintos darían dos números distintos para la misma
//      cosa. Se comprueba que lo pintado es `diferencia`, tal cual.
//
//   3. QUE EL QUE LLEVA POCO PERO MUCHA DIFERENCIA APAREZCA. Con la
//      lista ordenada por diferencia, el primero tiene que ser el que
//      la tiene más alta, aunque lleve 5 de G+A y el de arriba 18.
//
//   4. QUE NO SE PINTE UN CERO DONDE FALTA EL DATO. Esta ruta no da
//      tiros ni pases clave, así que la ficha que se abre al pinchar
//      una fila tiene que poner «—», no «0».
//
//   5. QUE LOS FILTROS VIAJEN. Lo que pone en los selectores tiene que
//      ser lo que se le pide al servidor. Un selector que no se lee es
//      una pantalla que enseña otra cosa de la que dice enseñar.
//
//   6. QUE NO QUEDE NADA DE LAS CARTAS FIFA. Ni la pantalla, ni la
//      Watchlist, ni sus funciones.
const fs = require('fs');
const { JSDOM } = require('jsdom');

const [rutaHtml, rutaGA, rutaDif] = process.argv.slice(2);
const D = JSON.parse(fs.readFileSync(rutaGA, 'utf8'));
const DIF = JSON.parse(fs.readFileSync(rutaDif, 'utf8'));
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

// ── el servidor, de mentira; la respuesta, de la ruta de verdad ──
let pedidas = [];
let QUE_DEVUELVE = D;
function montaFetch() {
  w.fetch = async (url) => {
    const u = String(url);
    pedidas.push(u);
    if (u.includes('/api/goles-asistencias')) {
      return { ok: true, status: 200,
               json: async () => JSON.parse(JSON.stringify(QUE_DEVUELVE)) };
    }
    // Lo demás no se pide en esta pantalla. Si se pide, se entera.
    return { ok: false, status: 404, text: async () => 'no previsto: ' + u,
             json: async () => ({ detail: 'no previsto: ' + u }) };
  };
}

function montaChart() {
  w.Chart = function (ctx, cfg) { this.data = cfg.data; this.destroy = () => {}; };
  w.HTMLCanvasElement.prototype.getContext = function () { return { __id: this.id }; };
}

const esperar = ms => new Promise(r => setTimeout(r, ms));
const coma = v => Number(v).toFixed(2).replace('.', ',');
const txt = n => (n ? n.textContent.replace(/\s+/g, ' ').trim() : '');

// Las filas del ranking, saltándose la cabecera.
function filas() {
  const t = w.document.querySelector('#gaTbl table tbody');
  return t ? Array.from(t.querySelectorAll('tr')) : [];
}

w.addEventListener('load', async () => {
  montaFetch();
  montaChart();

  // ════════════════════════════════════════════════════════════
  // 0. LO QUE TIENE QUE EXISTIR Y LO QUE NO
  // ════════════════════════════════════════════════════════════
  console.log('\n── que existe lo nuevo y no lo viejo ──');
  for (const f of ['renderGA', 'expGA', 'abrirFichaDesdeGA', 'd2c', 'abrirFicha']) {
    comprueba(typeof w[f] === 'function', `${f} existe`);
  }
  for (const f of ['renderCards', 'renderWL', 'toggleWL', 'expCSV',
                   'abrirFichaDesdeCarta', 'cargarJugadores']) {
    comprueba(typeof w[f] === 'undefined', `${f} ya no existe`);
  }
  const doc = w.document;
  comprueba(!doc.getElementById('page-watchlist'), 'no queda la pantalla de Watchlist');
  comprueba(!doc.getElementById('pGrid'), 'no queda la rejilla de cartas');
  comprueba(!!doc.getElementById('page-players'), 'está la pantalla del ranking');
  // El rótulo, en lo que se LEE: menú, títulos de pantalla y botones.
  // No en el <script>, donde los comentarios cuentan a propósito qué
  // había antes y por qué se fue.
  const rotulos = Array.from(
    doc.querySelectorAll('.ni, .ptitle, .psub, button, .nav-sec, h1, h2, h3'))
    .map(txt);
  comprueba(!rotulos.some(t => /Cartas FIFA|Watchlist|Ultimate Team/i.test(t)),
            'no queda ningún rótulo de las Cartas ni de la Watchlist',
            rotulos.filter(t => /Cartas|Watchlist/i.test(t)).join(' | '));
  comprueba(rotulos.some(t => t === 'Goles y asistencias'),
            'el menú lleva a «Goles y asistencias»');

  // El nombre que sale en la barra del móvil.
  let titulos = {};
  try { titulos = w.eval('TITULOS'); } catch (e) {}
  comprueba(titulos.players === 'Goles y asistencias',
            'en el móvil la pantalla se llama «Goles y asistencias»',
            String(titulos.players));
  comprueba(!('watchlist' in titulos), 'ya no hay título de Watchlist');

  // La explicación de la pantalla, que va siempre visible.
  let ex = {};
  try { ex = w.eval('EXPLICA'); } catch (e) {}
  comprueba(!!ex.players, 'la pantalla tiene explicación');
  comprueba(!ex.watchlist, 'ya no hay explicación de Watchlist');
  if (ex.players) {
    comprueba(/xG\+xA/.test(ex.players.metodo),
              'la explicación dice contra qué se compara');
    comprueba(/recort/i.test(ex.players.metodo),
              'la explicación dice que el recorte va después de ordenar');
    comprueba(/no mide lo bueno que es nadie|no hay nota/i.test(ex.players.metodo),
              'la explicación avisa de que esto no es una nota');
  }

  if (typeof w.renderGA !== 'function') return fin();

  // ════════════════════════════════════════════════════════════
  // 1. LO PINTADO ES EL DATO, EN EL ORDEN DEL SERVIDOR
  // ════════════════════════════════════════════════════════════
  console.log('\n── la tabla es la respuesta ──');
  w.nav('players');
  await esperar(40);

  const j = D.jugadores;
  const fs1 = filas();
  comprueba(fs1.length === j.length,
            `hay una fila por jugador (${j.length})`, `pintadas ${fs1.length}`);

  let ordenMal = [], celdaMal = [], difMal = [];
  for (let i = 0; i < Math.min(fs1.length, j.length); i++) {
    const c = Array.from(fs1[i].querySelectorAll('td')).map(txt);
    const p = j[i];
    if (c[1].indexOf(p.name) !== 0) ordenMal.push(`${i}: «${c[1]}» ≠ ${p.name}`);
    if (c[0] !== String(i + 1)) celdaMal.push(`${i}: puesto «${c[0]}»`);
    if (c[2] !== p.team) celdaMal.push(`${i}: equipo «${c[2]}» ≠ ${p.team}`);
    if (c[3] !== p.league) celdaMal.push(`${i}: liga «${c[3]}» ≠ ${p.league}`);
    if (c[4] !== String(p.minutos)) celdaMal.push(`${i}: min «${c[4]}» ≠ ${p.minutos}`);
    if (c[5] !== String(p.goles)) celdaMal.push(`${i}: goles «${c[5]}» ≠ ${p.goles}`);
    if (c[6] !== String(p.asistencias)) celdaMal.push(`${i}: asis «${c[6]}» ≠ ${p.asistencias}`);
    if (c[7] !== String(p.ga)) celdaMal.push(`${i}: G+A «${c[7]}» ≠ ${p.ga}`);
    if (c[8] !== coma(p.xga)) celdaMal.push(`${i}: xG+xA «${c[8]}» ≠ ${coma(p.xga)}`);
    // La diferencia: lo pintado tiene que ser `diferencia` tal cual,
    // no una resta hecha aquí con otro redondeo.
    const esperada = (p.diferencia > 0 ? '+' : '') + coma(p.diferencia);
    if (c[9] !== esperada) difMal.push(`${i}: dif «${c[9]}» ≠ ${esperada}`);
    if (c[10] !== coma(p.ga_90)) celdaMal.push(`${i}: G+A/90 «${c[10]}» ≠ ${coma(p.ga_90)}`);
  }
  comprueba(!ordenMal.length, 'el orden pintado es el del servidor', ordenMal[0]);
  comprueba(!celdaMal.length, 'cada celda es su dato', celdaMal[0]);
  comprueba(!difMal.length, 'la diferencia pintada es la del servidor', difMal[0]);

  // El color de la diferencia tiene que decir lo mismo que el signo.
  let colorMal = [];
  for (let i = 0; i < Math.min(fs1.length, j.length); i++) {
    const td = fs1[i].querySelectorAll('td')[9];
    const estilo = td.getAttribute('style') || '';
    const verde = /var\(--green\)/.test(estilo);
    const rojo = /#f43f5e/.test(estilo);
    const p = j[i];
    if (p.diferencia > 0.05 && !verde) colorMal.push(`${p.name}: +${p.diferencia} sin verde`);
    if (p.diferencia < -0.05 && !rojo) colorMal.push(`${p.name}: ${p.diferencia} sin rojo`);
    if (Math.abs(p.diferencia) <= 0.05 && (verde || rojo))
      colorMal.push(`${p.name}: ${p.diferencia} pintado de color`);
  }
  comprueba(!colorMal.length, 'el color dice lo mismo que el signo', colorMal[0]);

  // ════════════════════════════════════════════════════════════
  // 2. EL CONTADOR DICE CUÁNTOS HAY Y CUÁNTOS SE VEN
  // ════════════════════════════════════════════════════════════
  console.log('\n── el contador ──');
  const cnt = txt(doc.getElementById('gaCnt'));
  comprueba(cnt.includes(String(j.length)), 'dice cuántos se enseñan', cnt);
  comprueba(cnt.includes(String(D.cuantos_cumplen)),
            'dice cuántos cumplen el filtro', cnt);
  comprueba(cnt.includes(String(D.minutos_minimos)),
            'dice el mínimo de minutos', cnt);
  comprueba(cnt.includes(D.temporada), 'dice la temporada', cnt);

  // ════════════════════════════════════════════════════════════
  // 3. LOS FILTROS VIAJAN AL SERVIDOR
  // ════════════════════════════════════════════════════════════
  console.log('\n── lo que pone en los selectores es lo que se pide ──');
  pedidas = [];
  doc.getElementById('gaLg').value = 'PD';
  doc.getElementById('gaOrd').value = 'diferencia';
  doc.getElementById('gaMin').value = '450';
  QUE_DEVUELVE = DIF;
  await w.renderGA();
  await esperar(30);
  const u = pedidas.find(x => x.includes('/api/goles-asistencias')) || '';
  comprueba(/liga=PD/.test(u), 'la liga viaja', u);
  comprueba(/orden=diferencia/.test(u), 'el orden viaja', u);
  comprueba(/min_minutes=450/.test(u), 'el mínimo de minutos viaja', u);
  comprueba(/limit=\d+/.test(u), 'el límite viaja escrito', u);

  // ════════════════════════════════════════════════════════════
  // 4. ORDENADA POR DIFERENCIA, EL QUE LLEVA POCO SALE ARRIBA
  // ════════════════════════════════════════════════════════════
  console.log('\n── el recorte va después de ordenar ──');
  const fs2 = filas();
  const primero = DIF.jugadores[0];
  const mejorGA = DIF.jugadores.reduce((a, b) => (b.ga > a.ga ? b : a));
  comprueba(fs2.length > 0 && txt(fs2[0].querySelectorAll('td')[1]).indexOf(primero.name) === 0,
            `arriba va el de más diferencia (${primero.name}, ${primero.diferencia})`,
            fs2.length ? txt(fs2[0].querySelectorAll('td')[1]) : 'sin filas');
  comprueba(primero.ga < mejorGA.ga,
            'y no es el que más G+A lleva, que es de lo que va esta prueba',
            `${primero.name} ${primero.ga} vs ${mejorGA.name} ${mejorGA.ga}`);

  // ════════════════════════════════════════════════════════════
  // 5. LOS AVISOS SE VEN
  // ════════════════════════════════════════════════════════════
  console.log('\n── los avisos ──');
  QUE_DEVUELVE = JSON.parse(JSON.stringify(D));
  QUE_DEVUELVE.avisos = ['No he podido traer PL: Understat no contesta.'];
  await w.renderGA();
  await esperar(30);
  comprueba(/No he podido traer PL/.test(txt(doc.getElementById('gaTbl'))),
            'un aviso del servidor se pinta en la pantalla');

  // Y cuando la ruta se cae del todo, se dice, no se enseña una lista
  // vacía como si no hubiera jugadores.
  QUE_DEVUELVE = null;
  w.fetch = async (url) => {
    pedidas.push(String(url));
    return { ok: false, status: 503, text: async () => 'Understat no contesta' };
  };
  await w.renderGA();
  await esperar(30);
  const caido = txt(doc.getElementById('gaTbl'));
  comprueba(/503/.test(caido) && /no he podido/i.test(caido),
            'si la fuente se cae, lo dice con el código', caido.slice(0, 90));
  comprueba(!filas().length, 'y no deja una tabla vacía puesta');
  montaFetch();

  // ════════════════════════════════════════════════════════════
  // 6. LA FILA ABRE LA FICHA, Y SIN CEROS INVENTADOS
  // ════════════════════════════════════════════════════════════
  console.log('\n── pinchar una fila ──');
  QUE_DEVUELVE = D;
  await w.renderGA();
  await esperar(30);
  const p0 = D.jugadores[0];
  filas()[0].dispatchEvent(new w.Event('click', { bubbles: true }));
  await esperar(40);
  const ficha = doc.getElementById('fichaJug');
  comprueba(!!ficha, 'se abre la ficha');
  if (ficha) {
    const t = txt(ficha);
    comprueba(t.includes(p0.name), 'es la ficha de ese jugador', t.slice(0, 70));
    comprueba(t.includes(String(p0.minutos)), 'con sus minutos');
    // Esta ruta no da tiros ni pases clave. Un 0 ahí sería un dato
    // inventado; tiene que salir una raya.
    const celdas = Array.from(ficha.querySelectorAll('div'))
      .map(txt).filter(x => /^(Tiros|Pases clave)/.test(x));
    comprueba(celdas.length === 0 || !celdas.some(x => /\b0\b/.test(x)),
              'los tiros y los pases clave salen con raya, no con cero',
              celdas.join(' | '));
    comprueba(!/\b0,00\b/.test(t) || /—/.test(t),
              'no hay un 0,00 donde falta el dato');
  }

  // ════════════════════════════════════════════════════════════
  // 7. NADA DE AZAR EN EL CÓDIGO DE ESTA PANTALLA
  // ════════════════════════════════════════════════════════════
  console.log('\n── sin azar ──');
  const fuente = String(w.renderGA) + String(w.abrirFichaDesdeGA) + String(w.d2c);
  comprueba(!/Math\.random/.test(fuente),
            'renderGA no mueve ningún número al azar');
  comprueba(!/\.sort\(/.test(String(w.renderGA)),
            'renderGA no reordena por su cuenta');

  fin();
});

function fin() {
  if (fallos) {
    console.log(`\n${fallos} comprobación(es) FALLAN`);
    process.exit(1);
  }
  console.log('\nTodo el ranking pintado es el dato');
  process.exit(0);
}
