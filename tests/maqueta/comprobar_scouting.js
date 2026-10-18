// ══════════════════════════════════════════════════════════════════
// COMPROBADOR DE SCOUTING, FICHA Y COMPARADOR
// ══════════════════════════════════════════════════════════════════
//   node comprobar_scouting.js <index.html> <scouting.json> <tiros.json>
//
// Carga el index.html de verdad en un DOM, le sirve la respuesta que
// da el motor de scouting y comprueba que lo dibujado ES el dato.
//
// LO QUE BUSCA, Y POR QUÉ CADA COSA
//
//   1. QUE NO HAYA RUIDO EN LAS COORDENADAS. La versión anterior del
//      mapa de talento hacía esto:
//
//          x: p.xG + (Math.random() - 0.5) * 0.4
//
//      o sea movía cada punto al azar para que no se solaparan. Dos
//      jugadores que caen encima es el dato —son parecidos— y
//      separarlos lo borra. Aquí se comprueba punto a punto que la
//      coordenada pintada es EXACTAMENTE la que calculó el PCA. Y se
//      ejecuta dos veces: con ruido aleatorio, dos pasadas dan
//      números distintos, así que eso también cae.
//
//   2. QUE LA TABLA SEA LA RESPUESTA. Mismo orden, mismos percentiles,
//      mismos minutos. Una tabla ordenada por otra cosa que la nota
//      cuenta otra historia sin que se note.
//
//   3. QUE LAS BARRAS DE LA FICHA MIDAN EL PERCENTIL. Una barra al
//      82 % de ancho con un 71 escrito al lado es un gráfico que
//      miente, y es el fallo más fácil de no ver.
//
//   4. QUE LOS TIROS ESTÉN DONDE SE TIRARON. Understat da x e y de 0 a
//      1; el campo va de 0 a 120 y de 0 a 80. Un factor de escala mal
//      puesto mueve todos los tiros a la vez, así que el mapa sigue
//      pareciendo un mapa.
//
//   5. QUE NO SE PINTE UN CERO DONDE FALTA EL DATO. Si npxG no viene,
//      tiene que salir «—», no «0.00».
const fs = require('fs');
const { JSDOM } = require('jsdom');

const [rutaHtml, rutaScouting, rutaTiros] = process.argv.slice(2);
const D = JSON.parse(fs.readFileSync(rutaScouting, 'utf8'));
const TIROS = JSON.parse(fs.readFileSync(rutaTiros, 'utf8'));
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

// ── el servidor, de mentira; los datos, del motor de verdad ──
const pedidas = [];
function montaFetch() {
  w.fetch = async (url) => {
    pedidas.push(String(url));
    const u = String(url);
    const cuerpo = u.includes('/api/scouting/') ? D
      : u.includes('/shots') ? TIROS
      : null;
    if (!cuerpo) return { ok: false, status: 404, json: async () => ({ detail: 'no previsto: ' + u }) };
    return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(cuerpo)) };
  };
}

// ── Chart.js no se carga en jsdom: se queda con lo que le pasan ──
const dibujados = {};
function montaChart() {
  w.Chart = function (ctx, cfg) {
    const id = ctx && ctx.__id;
    dibujados[id] = cfg;
    this.data = cfg.data;
    this.destroy = () => {};
    this.options = cfg.options;
  };
  // El canvas de jsdom no tiene getContext, así que se le pone uno que
  // sólo sirve para saber de qué canvas viene cada gráfico.
  w.HTMLCanvasElement.prototype.getContext = function () {
    return { __id: this.id };
  };
}

const esperar = ms => new Promise(r => setTimeout(r, ms));

w.addEventListener('load', async () => {
  montaFetch();
  montaChart();

  for (const f of ['runScouting', 'scPinta', 'abrirFicha', 'initCmp',
                   'runCompare', 'abrirFichaDesdeCarta', 'pintaTirosFicha']) {
    comprueba(typeof w[f] === 'function', `${f} existe`);
  }
  if (typeof w.runScouting !== 'function') return fin();

  const doc = w.document;
  const pl = D.players;

  // ════════════════════════════════════════════════════════════
  // 1. SCOUTING
  // ════════════════════════════════════════════════════════════
  console.log('\n── scouting ──');
  await w.runScouting();
  await esperar(30);

  comprueba(pedidas.some(u => u.includes('/api/scouting/')),
    'pide al servidor en vez de reutilizar la lista de las cartas',
    pedidas.join(' | ').slice(0, 120));
  const url = pedidas.find(u => u.includes('/api/scouting/')) || '';
  comprueba(url.includes('position=') && url.includes('min_minutes='),
    'manda el puesto y los minutos que están elegidos en pantalla', url);

  // ── el mapa: coordenada a coordenada ──
  const mapa = dibujados['scPCA'];
  comprueba(!!mapa, 'dibuja el mapa de talento');
  if (mapa) {
    const puntos = mapa.data.datasets.flatMap(ds => ds.data);
    comprueba(puntos.length === pl.length,
      `el mapa tiene los ${pl.length} jugadores`, `tiene ${puntos.length}`);
    const malos = [];
    pl.forEach(p => {
      const q = puntos.find(pt => pt.jug && pt.jug.player_id === p.player_id);
      if (!q) return malos.push(`${p.name}: no está en el mapa`);
      if (q.x !== p.pca_x || q.y !== p.pca_y)
        malos.push(`${p.name}: pintado en (${q.x}, ${q.y}) y el PCA dice (${p.pca_x}, ${p.pca_y})`);
    });
    comprueba(malos.length === 0,
      'cada punto está en su coordenada del PCA, sin ruido añadido',
      malos.slice(0, 3).join(' · '));

    const grupos = mapa.data.datasets.map(ds => ds.data.length);
    const delMotor = [0, 1, 2, 3].map(c => pl.filter(p => p.cluster === c).length);
    comprueba(JSON.stringify(grupos) === JSON.stringify(delMotor),
      'los grupos son los del servidor', `${grupos} contra ${delMotor}`);
    comprueba(typeof mapa.options.onClick === 'function',
      'pinchando un punto se abre la ficha');
    comprueba(!!(mapa.options.plugins.tooltip &&
                 mapa.options.plugins.tooltip.callbacks),
      'al pasar el ratón sale quién es y sus percentiles');
  }

  // ── dos pasadas: con ruido aleatorio, no coinciden ──
  const antes = (dibujados['scPCA'].data.datasets.flatMap(d => d.data)
    .map(p => `${p.x},${p.y}`).sort().join('|'));
  await w.runScouting();
  await esperar(30);
  const despues = (dibujados['scPCA'].data.datasets.flatMap(d => d.data)
    .map(p => `${p.x},${p.y}`).sort().join('|'));
  comprueba(antes === despues,
    'dos pasadas dan el mismo mapa (con Math.random esto no pasa)');

  // ── la tabla ──
  const filas = [...doc.querySelectorAll('#scTbl tbody tr')];
  comprueba(filas.length === pl.length,
    `la tabla tiene ${pl.length} filas`, `tiene ${filas.length}`);
  const etiquetas = Object.keys(pl[0].percentiles);
  const malTabla = [];
  filas.forEach((tr, i) => {
    const c = [...tr.querySelectorAll('td')].map(t => t.textContent.trim());
    const p = pl[i];
    if (c[1] !== p.name) malTabla.push(`fila ${i + 1}: «${c[1]}» en vez de «${p.name}»`);
    if (c[4] !== String(p.time)) malTabla.push(`${p.name}: ${c[4]} min y son ${p.time}`);
    if (c[5] !== String(p.goals)) malTabla.push(`${p.name}: ${c[5]} goles y son ${p.goals}`);
    etiquetas.forEach((e, k) => {
      const pintado = c[8 + k];
      if (pintado !== String(p.percentiles[e]))
        malTabla.push(`${p.name} ${e}: ${pintado} y es ${p.percentiles[e]}`);
    });
    const nota = c[8 + etiquetas.length];
    if (nota !== String(p.score)) malTabla.push(`${p.name}: nota ${nota} y es ${p.score}`);
  });
  comprueba(malTabla.length === 0,
    'cada celda de la tabla es el dato del servidor',
    malTabla.slice(0, 3).join(' · '));

  const nombres = filas.map(tr => tr.querySelectorAll('td')[1].textContent.trim());
  comprueba(JSON.stringify(nombres) === JSON.stringify(pl.map(p => p.name)),
    'la tabla va en el orden que manda el servidor (por nota)');

  // ════════════════════════════════════════════════════════════
  // 2. LA FICHA
  // ════════════════════════════════════════════════════════════
  console.log('\n── ficha de jugador ──');
  const p0 = JSON.parse(JSON.stringify(pl[0]));
  p0.shots = TIROS.shots.length;   // que la cabecera cuadre con el mapa
  await w.abrirFicha(p0);
  await esperar(40);

  const ficha = doc.getElementById('fichaJug');
  comprueba(!!ficha, 'la ficha se abre');
  if (ficha) {
    comprueba(ficha.textContent.includes(p0.name), 'lleva su nombre');
    comprueba(ficha.textContent.includes(String(p0.time)) &&
              ficha.textContent.includes(String(p0.games)),
      `dice los minutos (${p0.time}) y los partidos (${p0.games})`);

    // ── las barras miden el percentil ──
    const barras = [...ficha.querySelectorAll('div[title]')]
      .filter(e => /percentil \d/.test(e.getAttribute('title')));
    const malBarra = [];
    Object.entries(p0.percentiles).forEach(([e, v]) => {
      const caja = barras.find(b => b.getAttribute('title').startsWith(e + ':'));
      if (!caja) return malBarra.push(`${e}: no tiene barra`);
      const relleno = caja.lastElementChild && caja.lastElementChild.firstElementChild;
      const ancho = relleno && relleno.style.width;
      if (ancho !== `${v}%`) malBarra.push(`${e}: barra al ${ancho} y el percentil es ${v}`);
      if (!caja.getAttribute('title').includes(String(p0.por_90[e])))
        malBarra.push(`${e}: el ratón no enseña la tasa por 90 (${p0.por_90[e]})`);
    });
    comprueba(malBarra.length === 0,
      'cada barra mide su percentil y el ratón enseña la cifra por 90',
      malBarra.slice(0, 3).join(' · '));

    // ── los tiros, uno a uno ──
    comprueba(pedidas.some(u => u.includes(`/api/player/${p0.player_id}/shots`)),
      'pide sus tiros de verdad al servidor');
    const circulos = [...ficha.querySelectorAll('svg circle')]
      .filter(c => c.querySelector('title'));
    comprueba(circulos.length === TIROS.shots.length,
      `pinta los ${TIROS.shots.length} tiros`, `pinta ${circulos.length}`);
    const malTiro = [];
    TIROS.shots.forEach(t => {
      const cx = +(t.x * 120).toFixed(2), cy = +(t.y * 80).toFixed(2);
      const c = circulos.find(c =>
        Math.abs(+c.getAttribute('cx') - cx) < 0.005 &&
        Math.abs(+c.getAttribute('cy') - cy) < 0.005);
      if (!c) return malTiro.push(`min ${t.minute}: ningún círculo en (${cx}, ${cy})`);
      const tit = c.querySelector('title').textContent;
      if (!tit.includes(t.xG.toFixed(3)))
        malTiro.push(`min ${t.minute}: el ratón no dice su xG (${t.xG.toFixed(3)})`);
      const esGol = c.getAttribute('fill') !== 'none';
      if (esGol !== (t.result === 'Goal'))
        malTiro.push(`min ${t.minute}: relleno ${esGol} y result=${t.result}`);
    });
    comprueba(malTiro.length === 0,
      'cada tiro está en su sitio, con su xG al pasar el ratón y relleno si fue gol',
      malTiro.slice(0, 3).join(' · '));

    comprueba(!/No cuadra/i.test(ficha.textContent),
      'cuando el mapa y la cabecera cuadran, no avisa de nada');
    const u = pedidas.find(x => x.includes('/shots')) || '';
    comprueba(u.includes('season='),
      'pide los tiros DE ESTA TEMPORADA, no los de toda la carrera', u);

    const goles = TIROS.shots.filter(t => t.result === 'Goal').length;
    const xgTotal = TIROS.shots.reduce((a, t) => a + t.xG, 0);
    comprueba(ficha.textContent.includes(xgTotal.toFixed(2)),
      `suma el xG de los tiros (${xgTotal.toFixed(2)})`);
    const dif = (goles - xgTotal).toFixed(2);
    comprueba(ficha.textContent.includes(dif),
      `dice la diferencia con lo esperado (${dif})`);
    comprueba(/suerte/i.test(ficha.textContent.replace(/\s+/g, ' ')),
      'avisa de que esa diferencia es sobre todo suerte');
  }

  // ── un servidor viejo que se traga el filtro de temporada ──
  //
  // index.html se lee del disco en cada visita; main.py sólo al
  // arrancar. Así que durante un rato la pantalla es nueva y el
  // servidor es viejo, y ahí fue donde salió: Raphinha con 550 tiros
  // y 79 goles bajo una cabecera que decía 26 tiros.
  w.cerrarFicha();
  const otrasTemporadas = [];
  for (let i = 0; i < 40; i++) {
    const t = JSON.parse(JSON.stringify(TIROS.shots[i % TIROS.shots.length]));
    t.season = '2019';
    t.result = 'Goal';
    t.id = 'viejo' + i;
    otrasTemporadas.push(t);
  }
  const servidorViejo = { shots: TIROS.shots.concat(otrasTemporadas),
                          total: TIROS.shots.length + 40 };   // sin temporada ni total_carrera
  const antesFetch = w.fetch;
  // Un servidor viejo tampoco manda `season` en el scouting: sólo el
  // "2026/27". Esto reproduce eso, que es lo que de verdad pasó.
  const scoutingViejo = JSON.parse(JSON.stringify(D));
  delete scoutingViejo.season;
  w.fetch = async (url) => {
    pedidas.push(String(url));
    const u = String(url);
    if (u.includes('/shots'))
      return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(servidorViejo)) };
    if (u.includes('/api/scouting/'))
      return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(scoutingViejo)) };
    return antesFetch(url);
  };
  w.eval('window.SEASON_ANYO = undefined');
  await w.runScouting();
  await esperar(60);
  comprueba(w.SEASON_ANYO === 2026,
    'sin `season`, saca el año del texto «2026/27» en vez de rendirse',
    'SEASON_ANYO = ' + w.SEASON_ANYO);
  w.eval('FICHA.tiros = {}');
  const pViejo = JSON.parse(JSON.stringify(pl[0]));
  pViejo.shots = TIROS.shots.length;
  await w.abrirFicha(pViejo);
  await esperar(60);
  const fv = doc.getElementById('fichaJug');
  const circulosV = [...fv.querySelectorAll('svg circle')].filter(c => c.querySelector('title'));
  comprueba(circulosV.length === TIROS.shots.length,
    'con un servidor viejo, la pantalla recorta ella misma a esta temporada',
    `pinta ${circulosV.length} y esta temporada tiene ${TIROS.shots.length}`);
  comprueba(!/No cuadra/i.test(fv.textContent.replace(/\s+/g, ' ')),
    'y entonces ya no hace falta avisar de ningún descuadre');
  w.fetch = antesFetch;
  w.eval('FICHA.tiros = {}');
  w.cerrarFicha();

  // ── el mapa que no cuadra con la cabecera ──
  //
  // Esto es el fallo que apareció con datos reales: Understat devuelve
  // los tiros de toda la CARRERA, así que Raphinha salía con 550 tiros
  // debajo de una cabecera que decía 26.
  w.cerrarFicha();
  const descuadrado = JSON.parse(JSON.stringify(pl[0]));
  descuadrado.shots = TIROS.shots.length + 500;
  await w.abrirFicha(descuadrado);
  await esperar(40);
  comprueba(/No cuadra/i.test(doc.getElementById('fichaJug').textContent.replace(/\s+/g, ' ')),
    'si el mapa y la cabecera no cuadran, lo dice en pantalla');

  // ── el cero que no debe pintarse ──
  w.cerrarFicha();
  const sinNpxg = JSON.parse(JSON.stringify(p0));
  delete sinNpxg.npxG;
  await w.abrirFicha(sinNpxg);
  await esperar(20);
  const caja = [...doc.querySelectorAll('#fichaJug div')]
    .find(e => e.textContent.trim() === 'npxG');
  const valor = caja && caja.parentElement.querySelectorAll('div')[1].textContent.trim();
  comprueba(valor === '—',
    'sin npxG pinta «—» y no «0.00»', `pinta «${valor}»`);
  w.cerrarFicha();

  // ── un puesto sin percentiles no se queda en blanco ──
  const sinPct = JSON.parse(JSON.stringify(p0));
  sinPct.percentiles = {};
  await w.abrirFicha(sinPct);
  await esperar(20);
  // El texto se compara APLASTANDO los espacios. Si no, un salto de
  // línea entre dos palabras del HTML hace fallar una prueba que mira
  // algo que en pantalla está perfectamente bien.
  const sinPctTxt = ((doc.getElementById('fichaJug') || {}).textContent || '(no hay ficha)')
    .replace(/\s+/g, ' ').trim();
  comprueba(/no publica/i.test(sinPctTxt),
    'un jugador sin percentiles explica por qué no los tiene',
    sinPctTxt.replace(/\s+/g, ' ').trim().slice(0, 180));
  w.cerrarFicha();

  // ════════════════════════════════════════════════════════════
  // 3. EL COMPARADOR
  // ════════════════════════════════════════════════════════════
  console.log('\n── comparador ──');
  await w.initCmp();
  await esperar(60);

  const c1 = doc.getElementById('c1'), c2 = doc.getElementById('c2');
  comprueba(c1.options.length === pl.length,
    `carga los ${pl.length} jugadores sin pasar por Cartas FIFA`,
    `carga ${c1.options.length}`);
  comprueba(c1.value !== c2.value, 'empieza con dos jugadores distintos');

  const radar = dibujados['rC'];
  comprueba(!!radar, 'dibuja la rueda');
  if (radar) {
    const a = pl.find(p => String(p.player_id) === c1.value);
    const b = pl.find(p => String(p.player_id) === c2.value);
    const ejes = radar.data.labels;
    const malEje = [];
    [[a, 0], [b, 1]].forEach(([p, i]) => {
      ejes.forEach((e, k) => {
        const v = radar.data.datasets[i].data[k];
        if (v !== p.percentiles[e])
          malEje.push(`${p.name} ${e}: eje a ${v} y el percentil es ${p.percentiles[e]}`);
      });
    });
    comprueba(malEje.length === 0,
      'cada eje es el percentil contra la liga, no uno contra el otro',
      malEje.slice(0, 3).join(' · '));
    comprueba(radar.options.scales.r.min === 0 && radar.options.scales.r.max === 100,
      'la escala va de 0 a 100 fija (si no, dos malos salen al 100)');
    comprueba(!!(radar.options.plugins.tooltip &&
                 radar.options.plugins.tooltip.callbacks),
      'al pasar el ratón sale la cifra por 90 detrás del percentil');
  }

  // Dos iguales: tiene que decirlo, no dibujar una rueda de uno solo.
  c2.value = c1.value;
  w.runCompare();
  comprueba(/distintos/i.test(doc.getElementById('cOut').textContent.replace(/\s+/g, ' ')),
    'con el mismo jugador dos veces avisa en vez de dibujar');

  fin();
});

function fin() {
  console.log(fallos === 0
    ? '\nTODO BIEN: lo pintado es el dato'
    : `\n${fallos} FALLOS`);
  process.exit(fallos === 0 ? 0 : 1);
}
