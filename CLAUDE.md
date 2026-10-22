# Sportalyze

Analítica de fútbol en español. FastAPI + un solo HTML. De Félix Ramírez
(@felixrr87). Empezó como TFM del máster en UCAM + Sport Data Campus y
sigue creciendo. Es su portfolio: lo que lo hace valer es que cada cifra
se puede comprobar.

## Las tres reglas que no se negocian

1. **Cada número se puede verificar.** Si no se puede, el código se
   niega: lanza, devuelve 503 con el motivo escrito, o pinta «—».
   Nunca un cero, nunca una media inventada, nunca un dato por defecto.
   Un hueco explicado vale más que un número inventado.
2. **La clave de football-data NO se sube.** Vive en
   `~/Desktop/clave_football_data.txt`, fuera de todo repositorio.
   `.env` está en `.gitignore`. (Sigue en el historial público de git de
   antes: anularla en football-data.org es lo único que cierra eso.)
3. **Nada de datos de Opta.** Eso incluye FBref y WhoScored: mirarlos es
   gratis, reproducirlos en una página propia no. Las fuentes son
   **Understat** (tiros) y **football-data.org** (calendario, plantillas,
   clasificaciones). StatsBomb Open Data sólo para los análisis sueltos.

## Cómo se trabaja aquí

Escribir la prueba → **romper el código a propósito** → confirmar que se
pone roja → restaurar. Una prueba que no puede fallar no protege nada.
Los sabotajes y lo que falló con cada uno van escritos en el mensaje del
commit.

Los mensajes de commit son largos y en español: qué se fue, por qué, qué
entra, qué fallo se llevó por delante y qué sabotajes se probaron.

Los comentarios del código cuentan **qué había antes y por qué se fue**.
No se borran al refactorizar: son la memoria del proyecto.

## El mapa

```
main.py                 1.400 líneas. TODAS las rutas /api/*.
backend/scrapers/       understat.py, football_data.py
backend/ml/
  puntuar.py            percentiles por 90 + encogido (K_MINUTOS = 540)
  scouting.py           percentiles + K-Means + PCA (lo hace el SERVIDOR)
  minutos.py            reconstruye quién estaba en el campo cada minuto
  onoff.py              xG encajado con él / sin él (K_ENCOGIDO = 450)
  emparejar.py          cruza partidos entre fuentes; se niega si duda
  emparejar_jugadores.py cruza plantilla football-data ↔ Understat
  informe_liga.py       informe post-partido
  simulador.py          simulación de liga
  hallazgos.py          quién no cuadra con su xG, con Benjamini-Hochberg
                        (FDR = 0,10) para no publicar sesenta falsos
frontend/index.html     4.700 líneas. TODA la interfaz, un solo fichero.
tests/                  389 pruebas
tests/maqueta/*.js      comprobadores jsdom: cargan el index.html de
                        verdad y comprueban que lo PINTADO es el dato
```

## Comandos

```bash
python3 -m pytest tests/ -q          # las 347, ~20 s
python3 -m pytest tests/test_maqueta.py -q   # sólo los comprobadores jsdom
```

Los comprobadores jsdom necesitan node + `cd tests/maqueta && npm install`.
Si falta node, se **saltan**, no fallan.

## Trampas que ya han costado tiempo

**El servidor no recarga solo.** `ENV=production` → uvicorn sin reload.
`frontend/index.html` se lee del disco **en cada visita**, pero `main.py`
sólo **al arrancar**. Después de tocar main.py hay que reiniciar, y en
ese rato la pantalla es nueva y el servidor el de antes. Por eso el
frontend se defiende solo en algunos sitios (ver `recuerdaTemporada`).

**jsdom:** un `const` o `let` de nivel superior NO está en `window`. Para
leerlo desde el comprobador: `w.eval('TITULOS')`, no `w.TITULOS`.

**La carpeta montada** (`/sessions/.../mnt/`) lanza a veces
`[Errno 35] Resource deadlock avoided`. Reintentar. Borrar ficheros ahí
necesita permiso aparte.

**La consola del navegador corta la salida** sobre ~1.500 caracteres.
Devolver objetos pequeños o por trozos.

**Understat:**
- `season` = el año en que EMPIEZA la temporada (2026 = 2026/27)
- `get_player_shots` devuelve **toda la carrera**, no una temporada.
  Esto causó el fallo de Raphinha: 550 tiros y 79 goles bajo una
  cabecera que decía 26 en 8 partidos.
- `roster_in` / `roster_out` son identificadores internos de cambio,
  **no minutos**
- `position == "Sub"` marca suplente, y no es un puesto: hay que contar
  el puesto a lo largo de varios partidos
- los minutos vienen redondeados, así que las cuentas se van de uno
- ligas válidas, con mayúsculas exactas:
  `EPL La_Liga Bundesliga Serie_A Ligue_1 RFPL`

**football-data.org:** 10 peticiones por minuto. Hay caché y se calienta
al arrancar.

## Cómo editar `frontend/index.html`

4.400 líneas: **no se lee entero**. Se busca con grep, se lee el trozo, y
los cambios grandes van en un script de Python con `assert` en cada
sustitución, que **escribe sólo si todas encajan** (ejemplo del 21 de
octubre: 27 sustituciones, 0 escrituras hasta que las 27 cuadraron).

Al quitar una pantalla hay que mirar **siete** sitios: el menú `.ni`, el
botón de la portada, el bloque `<div class="page" id="page-…">`, las
acciones de `nav()`, `TITULOS`, la entrada de `EXPLICA` y los
comprobadores de `tests/maqueta/`.

## Lo que la app se niega a hacer, a propósito

- Puntuar defensas y porteros con datos de tiro (`/api/scouting` devuelve
  503 con el motivo escrito). Para defensas está «con él y sin él».
- Enseñar el informe de un partido que no ha identificado con seguridad.
- Repartir el xG de un partido cuando los minutos admiten dos lecturas
  que no dan lo mismo.
- Ordenar en el navegador lo que recorta el servidor.

Esto **no son bugs**. Son la razón de existir del proyecto. Si una
pantalla deja de negarse, se ha roto algo.

## Para quién es

Para quien tiene que defender un número delante de alguien y no tiene
presupuesto para Wyscout: periodistas, entrenadores de cantera, analistas
junior, creadores de contenido. No para un club con Opta en plantilla.

Si una pantalla no le sirve a esa persona, sobra. (Así se fueron las
Cartas FIFA y la Watchlist.)

## La pantalla de Método se escribe sola, y tiene que seguir así

`/api/metodo` **lee** las constantes de los módulos y cuenta las
funciones de prueba abriendo `tests/*.py`. Nada de eso está tecleado.
Al añadir una constante que se pueda discutir, se añade a esa ruta con
su fichero y su explicación — no a la pantalla.

## Pendiente

- Desplegar en Render (`render.yaml` listo; falta la cuenta de Félix)
- Anular la clave de football-data del historial público
- Edad real cruzando Understat con football-data en toda la liga
- Dejar los hallazgos en una tarea semanal que avise los lunes
