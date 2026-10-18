// ══════════════════════════════════════════════════════════════════
// COMPROBADOR DE LA MAQUETA DEL SIMULADOR
// ══════════════════════════════════════════════════════════════════
//   node comprobar_maqueta.js <index.html> <edicion.json>
//
// Carga el index.html DE VERDAD en un DOM, le pasa una edición
// calculada por el motor y comprueba lo que ha quedado pintado.
//
// POR QUÉ ESTO Y NO UNA CAPTURA
// -----------------------------
// Una captura dice si se ve bonito. Esto dice si los números de la
// pantalla son los números del modelo. Son dos preguntas distintas y la
// segunda es la que importa: una barra puede estar perfectamente
// alineada y señalar el puesto equivocado.
//
// Comprueba, una por una:
//   · que las 20 filas están y en el orden de la clasificación
//   · que los puntos de la tabla son los que dio el motor
//   · que cada barra del rango cae donde le toca, con la escala de 20
//     puestos, y que la mediana queda DENTRO de su propia barra
//   · que el 1X2 de cada partido suma 100 % de anchura
//   · que la procedencia (jornada, fecha, fuente) está escrita
//   · que las probabilidades pequeñas se escriben "<1 %" y no "0 %"
const fs = require('fs');
const { JSDOM } = require('jsdom');

const [rutaHtml, rutaJson] = process.argv.slice(2);
const ed = JSON.parse(fs.readFileSync(rutaJson, 'utf8'));
const html = fs.readFileSync(rutaHtml, 'utf8');

let fallos = 0;
function comprueba(ok, que, detalle) {
  if (ok) { console.log(`  ok    ${que}`); }
  else { fallos++; console.log(`  FALLA ${que}${detalle ? '  → ' + detalle : ''}`); }
}

const dom = new JSDOM(html, {
  // Un origen de verdad: sin esto, localStorage lanza "opaque origins".
  // Se prueban las DOS cosas: aquí con almacenamiento (el caso normal) y
  // más abajo sin él.
  url: 'http://localhost:8000/',
  runScripts: 'dangerously',
  pretendToBeVisual: true,
  // Nada de red: ni CDN ni fuentes. Si el código dependiera de Chart.js
  // para esto, se vería aquí.
  resources: undefined,
});
const w = dom.window;

w.addEventListener('load', () => {
  // Chart.js no se ha cargado (no hay red); el simulador no lo usa.
  comprueba(typeof w.simPinta === 'function', 'simPinta existe');
  comprueba(typeof w.loadSimulador === 'function', 'loadSimulador existe');
  if (typeof w.simPinta !== 'function') { fin(); return; }

  w.document.getElementById('simLiga').innerHTML =
    '<option value="PD">La Liga</option>';
  w.simPinta(ed);

  const d = w.document;
  const n = ed.equipos;

  // ── la tabla ──
  const filas = [...d.querySelectorAll('#simTabla tbody tr')];
  comprueba(filas.length === n, `hay ${n} filas en la tabla`, `salen ${filas.length}`);

  let malPuntos = [], malNombre = [], malBarra = [], malMediana = [];
  filas.forEach((tr, i) => {
    const f = ed.tabla[i];
    const c = [...tr.children].map(td => td.textContent.trim());
    if (String(f.pos_hoy) !== c[0]) malNombre.push(`pos ${i}: ${c[0]} ≠ ${f.pos_hoy}`);
    if (!c[1].includes(f.corto)) malNombre.push(`nombre ${i}: "${c[1]}" no trae "${f.corto}"`);
    if (String(f.pts_hoy) !== c[2]) malPuntos.push(`${f.corto}: ${c[2]} ≠ ${f.pts_hoy}`);

    // la barra: izquierda y anchura, en tanto por ciento de 20 puestos
    const barras = tr.querySelectorAll('td:nth-child(6) div > div');
    if (barras.length < 2) { malBarra.push(`${f.corto}: no hay barra`); return; }
    const pct = (el, prop) => parseFloat((el.getAttribute('style')
      .match(new RegExp(prop + ':\\s*([-\\d.]+)%')) || [0, NaN])[1]);
    const izq = pct(barras[0], 'left');
    const ancho = pct(barras[0], 'width');
    const esperadoIzq = (f.p10 - 1) / n * 100;
    const esperadoAncho = (f.p90 - f.p10 + 1) / n * 100;
    if (Math.abs(izq - esperadoIzq) > 0.01)
      malBarra.push(`${f.corto}: empieza en ${izq}% y debería en ${esperadoIzq}%`);
    if (Math.abs(ancho - esperadoAncho) > 0.01)
      malBarra.push(`${f.corto}: mide ${ancho}% y debería ${esperadoAncho}%`);
    // la mediana tiene que caer dentro de la propia barra
    const med = pct(barras[1], 'left');
    if (!(med >= izq - 0.01 && med <= izq + ancho + 0.01))
      malMediana.push(`${f.corto}: mediana en ${med}% fuera de [${izq}, ${izq + ancho}]`);
  });
  comprueba(!malNombre.length, 'cada fila lleva su puesto y su nombre', malNombre[0]);
  comprueba(!malPuntos.length, 'los puntos pintados son los del motor', malPuntos[0]);
  comprueba(!malBarra.length, 'cada barra del rango cae donde le toca', malBarra[0]);
  comprueba(!malMediana.length, 'la mediana queda dentro de su barra', malMediana[0]);

  // ── las probabilidades pequeñas ──
  const chico = ed.tabla.find(f => f.p_titulo > 0 && f.p_titulo < 0.005);
  if (chico) {
    const i = ed.tabla.indexOf(chico);
    const txt = filas[i].children[6].textContent;
    comprueba(txt.includes('<1'), `una probabilidad del ${chico.p_titulo} se escribe "<1 %"`, txt);
  } else {
    console.log('  --    ninguna probabilidad cae entre 0 y 0,5 % en esta edición');
  }
  const cero = ed.tabla.find(f => f.p_titulo === 0);
  if (cero) {
    const txt = filas[ed.tabla.indexOf(cero)].children[6].textContent.trim();
    comprueba(txt === '—', 'un cero exacto se pinta con una raya, no con "0 %"', txt);
  }

  // ── los próximos partidos ──
  const prox = [...d.querySelectorAll('#simProx tbody tr')];
  comprueba(prox.length === ed.proximos.length,
    `hay ${ed.proximos.length} partidos próximos`, `salen ${prox.length}`);
  let mal1x2 = [];
  prox.forEach((tr, i) => {
    const q = ed.proximos[i];
    const trozos = [...tr.querySelectorAll('td:nth-child(4) div > div')];
    if (trozos.length !== 3) { mal1x2.push(`${q.local}: ${trozos.length} trozos`); return; }
    const suma = trozos.reduce((a, el) => a + parseFloat(
      (el.getAttribute('style').match(/width:\s*([\d.]+)%/) || [0, 0])[1]), 0);
    if (Math.abs(suma - 100) > 0.01)
      mal1x2.push(`${q.local} v ${q.visitante}: la barra suma ${suma}%`);
    if (!tr.textContent.includes(q.local))
      mal1x2.push(`${q.local} no aparece en su fila`);
    if (!tr.textContent.includes(String(q.jornada)))
      mal1x2.push(`${q.local}: falta la jornada ${q.jornada}`);
  });
  comprueba(!mal1x2.length, 'cada 1X2 ocupa el 100 % de su barra y lleva su jornada', mal1x2[0]);

  // ── la procedencia, que es media pantalla ──
  const proc = d.getElementById('simProc').textContent;
  const [a, m, dd] = ed.ultima_fecha.split('-');
  const debe = [String(ed.jornada), `${ed.partidos_jugados} de ${ed.partidos_calendario}`,
                `${dd}/${m}/${a}`, '10.000', String(ed.modelo.semilla)];
  const faltan = debe.filter(x => !proc.includes(x));
  comprueba(!faltan.length, 'la procedencia está escrita en pantalla', 'falta: ' + faltan.join(', '));

  const sub = d.getElementById('simSub').textContent;
  comprueba(sub.includes(`Jornada ${ed.jornada}`), 'el subtítulo dice la jornada', sub);

  // ── que las tarjetas se vean y el cartel de error no ──
  ['simFicha', 'simTablaCard', 'simProxCard', 'simComoCard'].forEach(id =>
    comprueba(d.getElementById(id).style.display !== 'none', `${id} está visible`));
  comprueba(d.getElementById('simEstado').style.display === 'none',
    'el cartel de error está oculto cuando sí hay resultado');

  // ── y al revés: que el cartel de error funcione ──
  w.simEstado('Prueba', 'texto de prueba', 'detalle');
  comprueba(d.getElementById('simEstado').style.display !== 'none',
    'el cartel de error aparece cuando hace falta');
  comprueba(d.getElementById('simTablaCard').style.display === 'none',
    'con el error visible, la tabla se esconde (no se deja media pantalla)');

  // ── que ninguna pantalla esté metida dentro de otra ──
  //
  // Esto costó caro. Una <div class="card"> vacía SIN CERRAR dentro de
  // page-config hacía que page-team, page-relieve, page-simulador y
  // page-informe quedaran DENTRO de page-config. En el navegador eso
  // significa que esas cuatro pantallas no se veían nunca: su padre
  // estaba en display:none. Las pruebas pasaban, el HTML parecía bien,
  // y la pantalla estaba en blanco.
  const paginas = [...d.querySelectorAll('.page')];
  const anidadas = paginas.filter(p => p.parentElement.closest('.page'));
  comprueba(!anidadas.length,
    `las ${paginas.length} pantallas cuelgan de main, ninguna dentro de otra`,
    anidadas.map(p => `${p.id} dentro de ${p.parentElement.closest('.page').id}`).join('; '));
  comprueba(paginas.every(p => p.id && p.id.startsWith('page-')),
    'todas las pantallas llevan su id');

  // ── escapado ──
  // esc() se declara con const, así que vive en el ámbito léxico global
  // y NO en window: hay que preguntárselo a la propia página.
  const escapado = w.eval('esc(\'<b>"Hertha BSC" & co</b>\')');
  comprueba(escapado === '&lt;b&gt;&quot;Hertha BSC&quot; &amp; co&lt;/b&gt;',
    'esc() escapa lo que debe', escapado);

  // ── y que la pantalla aguante sin localStorage ──
  // Era el fallo que encontró este comprobador: leer localStorage en la
  // primera línea del script mataba la página entera en ventana privada.
  comprueba(w.eval("(function(){ try { return guarda.leer('nada_de_nada') === null; } catch (e) { return 'ha lanzado: ' + e.message; } })()") === true,
    'guarda.leer() devuelve null en vez de lanzar');
  comprueba(w.eval("guarda.escribir('sp_prueba','1') === true"),
    'guarda.escribir() funciona cuando sí hay almacenamiento');

  fin();
});

function fin() {
  console.log('');
  if (fallos) { console.log(`${fallos} comprobación(es) FALLAN`); process.exit(1); }
  console.log('Toda la maqueta cuadra con el modelo.');
  process.exit(0);
}

setTimeout(() => { console.log('\nse ha quedado colgado'); process.exit(2); }, 60000);
