// ══════════════════════════════════════════════════════════════════
// COMPROBADOR DE HALLAZGOS Y DE MÉTODO
// ══════════════════════════════════════════════════════════════════
//   node comprobar_hallazgos.js <index.html> <hallazgos.json> <metodo.json>
//
// LO QUE BUSCA, Y POR QUÉ CADA COSA
//
//   1. QUE EL DENOMINADOR ESTÉ EN PANTALLA. Una lista de «jugadores
//      que superan su xG» sin decir a cuántos se ha mirado no se
//      puede juzgar. Si se prueban 242 y se publican 2, hay que ver
//      los 242 y los 12 que habrían salido por azar. Aquí se
//      comprueba que esas cifras están, y que son las del servidor.
//
//   2. QUE EL AVISO VAYA SIEMPRE. También cuando la lista está llena
//      de nombres jugosos. Un aviso que sólo sale cuando no hay nada
//      que contar no es un aviso.
//
//   3. QUE LA TABLA SEA LA RESPUESTA, EN SU ORDEN. El orden es por lo
//      raro que es cada uno, y lo decide el servidor.
//
//   4. QUE UN p PEQUEÑO NO SE PINTE COMO CERO. Con dos decimales,
//      0,000002 y 0,004 salen los dos «0,00» y no se distingue un
//      jugador raro de uno rarísimo.
//
//   5. QUE EL MÉTODO ENSEÑE DÓNDE VIVE CADA NÚMERO. Una constante sin
//      su fichero es un número que hay que creerse.
const fs = require('fs');
const { JSDOM } = require('jsdom');

const [rutaHtml, rutaHZ, rutaMT] = process.argv.slice(2);
const HZ = JSON.parse(fs.readFileSync(rutaHZ, 'utf8'));
const MT = JSON.parse(fs.readFileSync(rutaMT, 'utf8'));
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

let QUE_DEVUELVE_HZ = HZ;
function montaFetch() {
  w.fetch = async (url) => {
    const u = String(url);
    if (u.includes('/api/hallazgos')) {
      return { ok: true, status: 200,
               json: async () => JSON.parse(JSON.stringify(QUE_DEVUELVE_HZ)) };
    }
    if (u.includes('/api/metodo')) {
      return { ok: true, status: 200,
               json: async () => JSON.parse(JSON.stringify(MT)) };
    }
    return { ok: false, status: 404, text: async () => 'no previsto: ' + u };
  };
}

function montaChart() {
  w.Chart = function (ctx, cfg) { this.data = cfg.data; this.destroy = () => {}; };
  w.HTMLCanvasElement.prototype.getContext = function () { return { __id: this.id }; };
}

const esperar = ms => new Promise(r => setTimeout(r, ms));
const txt = n => (n ? n.textContent.replace(/\s+/g, ' ').trim() : '');
const coma = v => Number(v).toFixed(2).replace('.', ',');

w.addEventListener('load', async () => {
  montaFetch();
  montaChart();
  const doc = w.document;

  // ════════════════════════════════════════════════════════════
  // 0. QUE EXISTA TODO
  // ════════════════════════════════════════════════════════════
  console.log('\n── que existe ──');
  for (const f of ['renderHallazgos', 'renderMetodo', 'abrirFichaDesdeHZ',
                   'expHZ', 'd4c']) {
    comprueba(typeof w[f] === 'function', `${f} existe`);
  }
  comprueba(!!doc.getElementById('page-hallazgos'), 'está la pantalla de hallazgos');
  comprueba(!!doc.getElementById('page-metodo'), 'está la pantalla de método');

  let titulos = {}, ex = {};
  try { titulos = w.eval('TITULOS'); } catch (e) {}
  try { ex = w.eval('EXPLICA'); } catch (e) {}
  comprueba(titulos.hallazgos && titulos.metodo,
            'las dos tienen nombre en la barra del móvil');
  comprueba(!!ex.hallazgos && !!ex.metodo, 'las dos están explicadas');
  if (ex.hallazgos) {
    comprueba(/Benjamini/i.test(ex.hallazgos.metodo),
              'la explicación nombra la corrección que usa');
    comprueba(/sin penaltis/i.test(ex.hallazgos.metodo),
              'la explicación dice que no cuenta penaltis');
    comprueba(/NO dice|no dice/.test(ex.hallazgos.cristiano),
              'la explicación dice lo que esto NO demuestra');
  }

  if (typeof w.renderHallazgos !== 'function') return fin();

  // ════════════════════════════════════════════════════════════
  // 1. EL DENOMINADOR EN PANTALLA
  // ════════════════════════════════════════════════════════════
  console.log('\n── el denominador ──');
  w.nav('hallazgos');
  await esperar(60);

  const kpis = txt(doc.getElementById('hzKPIs'));
  comprueba(kpis.includes(String(HZ.cuantos_probados)),
            `dice a cuántos ha mirado (${HZ.cuantos_probados})`, kpis);
  comprueba(kpis.includes(String(HZ.esperados_por_puro_azar)),
            `dice cuántos saldrían por azar (${HZ.esperados_por_puro_azar})`, kpis);
  comprueba(kpis.includes(String(HZ.pasarian_sin_corregir)),
            `dice cuántos pasarían sin corregir (${HZ.pasarian_sin_corregir})`, kpis);
  comprueba(kpis.includes(String(HZ.hallazgos.length)),
            'dice cuántos hallazgos publica');

  const tabla = txt(doc.getElementById('hzTbl'));
  comprueba(/NO dice/.test(tabla), 'el aviso de lo que esto no demuestra está');
  comprueba(tabla.includes(String(HZ.esperados_por_puro_azar)),
            'y lleva dentro la cifra del azar');
  comprueba(/Benjamini/i.test(tabla), 'y nombra la corrección');

  // ════════════════════════════════════════════════════════════
  // 2. LA TABLA ES LA RESPUESTA
  // ════════════════════════════════════════════════════════════
  console.log('\n── la tabla ──');
  const filas = Array.from(doc.querySelectorAll('#hzTbl table tbody tr'));
  comprueba(filas.length === HZ.hallazgos.length,
            `una fila por hallazgo (${HZ.hallazgos.length})`,
            `pintadas ${filas.length}`);

  let mal = [];
  filas.forEach((f, i) => {
    const c = Array.from(f.querySelectorAll('td')).map(txt);
    const p = HZ.hallazgos[i];
    if (!p) return;
    if (c[1].indexOf(p.name) !== 0) mal.push(`${i}: «${c[1]}» ≠ ${p.name}`);
    if (c[2] !== p.team) mal.push(`${i}: equipo «${c[2]}»`);
    if (c[4] !== String(p.tiros)) mal.push(`${i}: tiros «${c[4]}»`);
    if (c[5] !== String(p.goles_sin_penalti)) mal.push(`${i}: goles «${c[5]}»`);
    if (c[6] !== coma(p.npxg)) mal.push(`${i}: npxG «${c[6]}» ≠ ${coma(p.npxg)}`);
    if (c[9] !== p.direccion) mal.push(`${i}: dirección «${c[9]}»`);
  });
  comprueba(!mal.length, 'cada celda es su dato', mal[0]);

  // El p: un 0,000002 no puede salir como «0,00».
  let pes = filas.map(f => txt(f.querySelectorAll('td')[8]));
  comprueba(!pes.some(x => x === '0,00' || x === '0,0000'),
            'un p pequeñísimo no se pinta como cero', pes.join(' | '));
  comprueba(pes.every(x => /^(<0,0001|0,\d{4})$/.test(x.replace(/\s/g, ''))),
            'el p va con cuatro decimales o con «menor que»', pes.join(' | '));

  // Los goles publicados son los de SIN penaltis: si alguien cambiara
  // la ruta a los totales, estos números no cuadrarían con el fixture.
  const conPenaltis = HZ.hallazgos.some(p => p.goles_sin_penalti !== undefined);
  comprueba(conPenaltis && HZ.sin_penaltis === true,
            'la respuesta dice que va sin penaltis');

  // ════════════════════════════════════════════════════════════
  // 3. CUANDO NO HAY NADA, SE DICE QUE ES UN RESULTADO
  // ════════════════════════════════════════════════════════════
  console.log('\n── una semana sin nada ──');
  QUE_DEVUELVE_HZ = JSON.parse(JSON.stringify(HZ));
  QUE_DEVUELVE_HZ.hallazgos = [];
  QUE_DEVUELVE_HZ.falsos_esperados_entre_los_publicados = 0.0;
  await w.renderHallazgos();
  await esperar(40);
  const vacio = txt(doc.getElementById('hzTbl'));
  comprueba(/no hay nada que contar/i.test(vacio),
            'dice que no hay nada, en vez de dejar la tabla en blanco');
  comprueba(/no un fallo|es un resultado/i.test(vacio),
            'y explica que eso es un resultado, no un fallo', vacio.slice(0, 80));
  comprueba(/NO dice/.test(vacio),
            'el aviso sigue estando aunque no haya hallazgos');

  // Y si la ruta se cae, se dice con el código.
  w.fetch = async () => ({ ok: false, status: 503,
                           text: async () => 'Understat no contesta' });
  await w.renderHallazgos();
  await esperar(40);
  const caido = txt(doc.getElementById('hzTbl'));
  comprueba(/503/.test(caido) && /no he podido/i.test(caido),
            'si la fuente se cae, lo dice con el código', caido.slice(0, 70));
  montaFetch();
  QUE_DEVUELVE_HZ = HZ;

  // ════════════════════════════════════════════════════════════
  // 4. EL MÉTODO
  // ════════════════════════════════════════════════════════════
  console.log('\n── el método ──');
  w.nav('metodo');
  await esperar(60);
  const mt = doc.getElementById('mtCont');
  const texto = txt(mt);

  let faltan = [];
  for (const n of MT.numeros_que_se_pueden_discutir) {
    if (!texto.includes(n.nombre)) faltan.push(`falta ${n.nombre}`);
    if (!texto.includes(String(n.valor))) faltan.push(`falta el valor de ${n.nombre}`);
    if (!texto.includes(n.donde)) faltan.push(`falta el fichero de ${n.nombre}`);
  }
  comprueba(!faltan.length,
            `las ${MT.numeros_que_se_pueden_discutir.length} constantes salen con su valor y su fichero`,
            faltan[0]);

  let sinNoDa = MT.fuentes.filter(f => !texto.includes(f.no_da));
  comprueba(!sinNoDa.length, 'de cada fuente se dice lo que NO publica',
            sinNoDa.map(f => f.nombre).join(', '));

  comprueba(/FBref/.test(texto) && /Opta/.test(texto),
            'la fuente descartada y su motivo salen');

  let sinAlternativa = MT.cuando_se_niega.filter(
    n => !texto.includes(n.que_hace_en_su_lugar));
  comprueba(!sinAlternativa.length,
            'cada negativa dice qué hace en su lugar',
            sinAlternativa.map(n => n.que).join(' | '));

  const total = MT.como_se_prueba.pruebas.total;
  comprueba(texto.includes(String(total)),
            `sale el número de pruebas (${total})`);
  const ficheros = Object.keys(MT.como_se_prueba.pruebas.por_fichero);
  comprueba(ficheros.every(f => texto.includes(f)),
            `salen los ${ficheros.length} ficheros de pruebas`);

  // Lo que hace que esta pantalla valga: que si cambia el código,
  // cambia ella. Se le sirve otro valor y tiene que pintarlo.
  const otro = JSON.parse(JSON.stringify(MT));
  otro.numeros_que_se_pueden_discutir[0].valor = 12345;
  w.fetch = async (url) => (String(url).includes('/api/metodo')
    ? { ok: true, status: 200, json: async () => otro }
    : { ok: false, status: 404, text: async () => 'no' });
  await w.renderMetodo();
  await esperar(40);
  comprueba(txt(mt).includes('12345'),
            'si el servidor manda otro valor, la pantalla lo pinta');

  fin();
});

function fin() {
  if (fallos) {
    console.log(`\n${fallos} comprobación(es) FALLAN`);
    process.exit(1);
  }
  console.log('\nTodo el método y los hallazgos pintados son el dato');
  process.exit(0);
}
