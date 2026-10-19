// ══════════════════════════════════════════════════════════════════
// COMPROBADOR DE LA PANTALLA ESTRECHA
// ══════════════════════════════════════════════════════════════════
//   node comprobar_movil.js <index.html>
//
// Carga el index.html en un DOM de 390 píxeles de ancho —un iPhone— y
// comprueba que se puede navegar.
//
// POR QUÉ ESTO ES LO MÁS IMPORTANTE DE TODO
//
// La barra lateral estaba en display:none por debajo de 820px y NO
// HABÍA NADA en su sitio. O sea que quien entraba desde el móvil
// aterrizaba en una pantalla sin manera de ir a ninguna otra. Y esto
// se comparte por enlace: la mayoría entra desde el móvil.
//
// Es el fallo que no se ve nunca desarrollando, porque uno trabaja en
// un portátil con la ventana ancha.
//
// jsdom no calcula el diseño de verdad —no hay motor de maquetación—,
// así que esto NO mide píxeles. Lo que hace es leer las reglas CSS que
// se aplican por debajo de 820px y comprobar que existen y dicen lo
// que tienen que decir, más probar el comportamiento del cajón, que
// eso sí es JavaScript y sí se puede ejecutar.
const fs = require('fs');
const { JSDOM } = require('jsdom');

const [rutaHtml] = process.argv.slice(2);
const html = fs.readFileSync(rutaHtml, 'utf8');

let fallos = 0;
function comprueba(ok, que, detalle) {
  if (ok) console.log(`  ok    ${que}`);
  else { fallos++; console.log(`  FALLA ${que}${detalle ? '  → ' + detalle : ''}`); }
}

// ── las reglas de la hoja de estilo, leídas a mano ──
//
// Se busca el bloque @media(max-width:820px) en el texto del <style>
// y se mira qué dice dentro. Es tosco y es fiable: lo que importa es
// que la regla esté escrita, no cómo la pinte un navegador.
const estilo = (html.match(/<style>([\s\S]*?)<\/style>/) || [])[1] || '';
const bloque = (() => {
  const i = estilo.indexOf('@media(max-width:820px)');
  if (i < 0) return '';
  let nivel = 0, j = estilo.indexOf('{', i);
  const ini = j;
  for (; j < estilo.length; j++) {
    if (estilo[j] === '{') nivel++;
    else if (estilo[j] === '}') { nivel--; if (!nivel) break; }
  }
  return estilo.slice(ini, j);
})();

const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true,
                              url: 'http://localhost:8000/' });
const w = dom.window;

w.addEventListener('load', () => {
  const doc = w.document;

  console.log('── el menú existe en pantalla estrecha ──');

  comprueba(bloque.length > 0, 'hay reglas para pantallas de 820px o menos');

  // El fallo original: .sidebar { display:none } y nada más.
  const ocultaSinMas = /\.sidebar\s*\{[^}]*display\s*:\s*none/.test(bloque);
  comprueba(!ocultaSinMas,
    'la barra lateral NO se esconde sin poner nada en su sitio',
    'sigue el display:none que dejaba el móvil sin navegación');

  comprueba(!!doc.querySelector('.topbar'),
    'hay una barra arriba con el menú');
  comprueba(!!doc.querySelector('.burger'),
    'hay un botón de menú');
  comprueba(!!doc.querySelector('.tapa-menu'),
    'hay una tapa para cerrar el menú tocando fuera');
  comprueba(/\.topbar\s*\{[^}]*display\s*:\s*flex/.test(bloque),
    'la barra de arriba SÓLO se enseña en pantalla estrecha');
  comprueba(/\.topbar\s*\{\s*display\s*:\s*none/.test(estilo),
    'y en pantalla ancha está escondida (si no, saldrían dos menús)');

  console.log('\n── el cajón se abre y se cierra ──');

  comprueba(typeof w.menuMovil === 'function', 'menuMovil existe');
  if (typeof w.menuMovil !== 'function') return fin();

  comprueba(!doc.body.classList.contains('menu-abierto'),
    'empieza cerrado');

  w.menuMovil();
  comprueba(doc.body.classList.contains('menu-abierto'),
    'el botón lo abre');
  comprueba(doc.getElementById('burger').getAttribute('aria-expanded') === 'true',
    'y lo dice para quien use un lector de pantalla');

  w.menuMovil();
  comprueba(!doc.body.classList.contains('menu-abierto'),
    'el botón lo vuelve a cerrar');

  // ── lo que de verdad rompe la experiencia ──
  w.menuMovil(true);
  w.nav('standings');
  comprueba(!doc.body.classList.contains('menu-abierto'),
    'al elegir una pantalla el menú se cierra solo',
    'si no, el menú se queda encima de lo que acabas de pedir');

  comprueba(doc.getElementById('topbarTitulo').textContent === 'Clasificación',
    'la barra de arriba dice en qué pantalla estás',
    `dice «${doc.getElementById('topbarTitulo').textContent}»`);

  w.nav('simulador');
  comprueba(doc.getElementById('topbarTitulo').textContent === 'El Simulador',
    'y cambia al cambiar de pantalla');

  // ── que todas las pantallas tengan título ──
  const enMenu = [...doc.querySelectorAll('.ni')]
    .map(a => (a.getAttribute('onclick') || '').match(/nav\('([^']+)'\)/))
    .filter(Boolean).map(m => m[1]);
  // TITULOS es un const del nivel de arriba: no está en window. Hay
  // que sacarlo con eval, que es el tropiezo de siempre con jsdom.
  const titulos = w.eval('TITULOS');
  const sinTitulo = enMenu.filter(p => !titulos[p]);
  comprueba(sinTitulo.length === 0,
    `las ${enMenu.length} pantallas del menú tienen nombre en la barra`,
    sinTitulo.join(', '));

  console.log('\n── que nada se salga de la pantalla ──');

  comprueba(/\.tw\s+table\s*\{[^}]*min-width/.test(bloque),
    'las tablas anchas se arrastran de lado en vez de reventar la página');
  comprueba(/\.g2\s*\{[^}]*grid-template-columns\s*:\s*1fr/.test(bloque),
    'los bloques de dos columnas pasan a una');
  comprueba(/\.cont\s*\{[^}]*padding\s*:\s*16px/.test(bloque),
    'los márgenes se achican (28px por lado se comen media pantalla)');

  // ── dos cosas medidas en un navegador de verdad a 375px ──
  //
  // jsdom no maqueta, así que estas dos no se pueden medir aquí. Lo
  // que se comprueba es que siga puesta la regla que las arregló, y
  // la cifra de cada una sale de haberlo medido:
  //
  //  · la palabra SPORTALYZE con 40px de tamaño ocupaba 424px y se
  //    salía por los dos lados de una pantalla de 375
  //  · una tabla dentro de una tarjeta estiraba la tarjeta a 598px,
  //    porque un hijo de grid no encoge por debajo de su contenido
  //    salvo que se le ponga min-width:0
  const clamp = (estilo.match(/\.hero-title\s*\{[^}]*font-size\s*:\s*clamp\(\s*(\d+)px/) || [])[1];
  comprueba(clamp && +clamp <= 32,
    'el título del inicio baja lo bastante como para caber en 375px',
    clamp ? `el mínimo es ${clamp}px y a 40px ocupaba 424` : 'no encuentro el clamp');

  comprueba(/\.card\s*,\s*\.kpi\s*\{[^}]*min-width\s*:\s*0/.test(estilo),
    'las tarjetas pueden encoger por debajo de su contenido',
    'sin min-width:0 una tabla ancha estira la tarjeta fuera de su columna');

  // ── Escape ──
  w.menuMovil(true);
  doc.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  comprueba(!doc.body.classList.contains('menu-abierto'),
    'Escape cierra el menú');

  fin();
});

function fin() {
  console.log(fallos === 0
    ? '\nEn el móvil se puede navegar.'
    : `\n${fallos} FALLOS`);
  process.exit(fallos === 0 ? 0 : 1);
}
