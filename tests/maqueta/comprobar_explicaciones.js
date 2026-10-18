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
  ok(/Understat no publica/i.test(EX.players.metodo) || /SIN NOTA/.test(EX.players.metodo),
     'la de cartas avisa de los que salen sin nota');
  console.log('');
  if(fallos){ console.log(fallos+' comprobación(es) FALLAN'); process.exit(1); }
  console.log('Todas las pantallas explicadas.'); process.exit(0);
});
setTimeout(()=>{console.log('colgado');process.exit(2);},50000);
