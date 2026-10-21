// Recorre todas las pantallas y comprueba que cada una tiene su
// explicación, con las dos partes y en el orden correcto: el método
// primero y la versión en cristiano debajo.
const fs=require('fs'); const {JSDOM}=require('jsdom');
const dom=new JSDOM(fs.readFileSync(process.argv[2],'utf8'),
  {url:'http://localhost/',runScripts:'dangerously',pretendToBeVisual:true});
const w=dom.window;
let fallos=0;
const ok=(c,q,d)=>{ if(c) console.log('  ok    '+q); else {fallos++; console.log('  FALLA '+q+(d?'  → '+d:''));} };
w.addEventListener('load', async ()=>{
  const d=w.document;
  // EXPLICA se declara con const: vive en el ámbito léxico global y
  // NO en window. Hay que preguntárselo a la propia página.
  const EX=w.eval('EXPLICA');
  const conExpl=Object.keys(EX);
  console.log(`pantallas con explicación: ${conExpl.length}\n`);
  for(const p of conExpl){
    try{ w.nav(p); }catch(e){ ok(false,p,'nav ha reventado: '+e.message); continue; }
    await new Promise(r=>setTimeout(r,120));
    const pag=d.getElementById('page-'+p);
    const ex=pag && pag.querySelector('.expl');
    if(!ex){ ok(false,`${p}: tiene explicación`); continue; }
    const partes=[...ex.children];
    const t=partes.map(x=>x.querySelector('.expl-t').textContent.trim());
    const textos=partes.map(x=>x.querySelector('p').textContent.trim());
    const bien = partes.length===2 && t[0].startsWith('El método') && t[1]==='En cristiano'
      && textos[0].length>80 && textos[1].length>60;
    ok(bien, `${p}: método arriba y cristiano debajo`,
       bien?'':`partes=${partes.length} t=${JSON.stringify(t)} largos=${textos.map(x=>x.length)}`);
  }
  // que no se duplique al volver a entrar
  w.nav('scouting'); w.nav('players'); w.nav('scouting');
  await new Promise(r=>setTimeout(r,150));
  ok(d.getElementById('page-scouting').querySelectorAll('.expl').length===1,
     'no se duplica al volver a entrar');
  // que ninguna explicación prometa lo que el código no hace
  const prohibidas=[/inteligencia artificial/i,/próximamente/i,/machine learning avanzad/i];
  let mal=[];
  for(const [k,v] of Object.entries(EX))
    for(const re of prohibidas)
      if(re.test(v.metodo+' '+v.cristiano)) mal.push(k+': '+re);
  ok(!mal.length,'ninguna explicación promete humo',mal[0]);
  // la de scouting TIENE que decir lo de defensas y porteros
  ok(/defensa/i.test(EX.scouting.metodo) && /portero/i.test(EX.scouting.metodo),
     'la de scouting avisa de que no puntúa defensas ni porteros');
  // Ésta decía «la de cartas avisa de los que salen sin nota» y
  // buscaba «Understat no publica». La pantalla ya no son las Cartas
  // FIFA: es el ranking de goles y asistencias, que no pone nota a
  // nadie. Lo que tiene que decir ahora es otra cosa.
  ok(/xG\+xA/.test(EX.players.metodo),
     'la del ranking dice contra qué se compara');
  ok(/recort/i.test(EX.players.metodo),
     'la del ranking dice que el recorte va después de ordenar');
  ok(/no mide lo bueno que es nadie|no hay nota/i.test(EX.players.metodo),
     'la del ranking avisa de que no es una nota');
  // ── frases que el código ya no cumple ──
  //
  // Una explicación que describe cómo se hacía antes es peor que no
  // tener explicación: el visitante comprueba lo que dice y no cuadra.
  // Estas dos estuvieron puestas describiendo exactamente lo contrario
  // de lo que hace el código ahora.
  const aplasta = t => String(t).replace(/\s+/g, ' ');
  const caducadas = [
    ['compare', /cada eje est[áa] escalado al mayor de los dos/i,
     'la rueda ya NO se escala al mayor de los dos: va de 0 a 100 fija'],
    ['scouting', /filtro de edad|edad m[áa]xima/i,
     'ya no hay selector de edad: Understat no publica la edad'],
  ];
  let viejas = [];
  for (const [k, re, por] of caducadas) {
    const t = aplasta(EX[k].metodo + ' ' + EX[k].cristiano);
    // «la edad no se filtra porque...» sí vale: explica la ausencia.
    if (re.test(t) && !/no se filtra|no la publica|no hac[íi]a nada/i.test(t))
      viejas.push(`${k}: ${por}`);
  }
  ok(!viejas.length, 'ninguna explicación describe cómo se hacía antes', viejas[0]);
  ok(/percentil/i.test(EX.compare.metodo) && /mismo puesto/i.test(EX.compare.metodo),
     'la del comparador dice que los ejes son percentiles del mismo puesto');
  console.log('');
  if(fallos){ console.log(fallos+' comprobación(es) FALLAN'); process.exit(1); }
  console.log('Todas las pantallas explicadas.'); process.exit(0);
});
setTimeout(()=>{console.log('colgado');process.exit(2);},50000);
