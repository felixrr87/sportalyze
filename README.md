# ⚽ SPORTALYZE v2.0

> Plataforma profesional de análisis futbolístico con ML real, datos en tiempo real y visualizaciones estilo Opta.

---

## 🚀 Instalación en 5 minutos

### Requisitos
- Python 3.11+
- Git

### Paso 1 — Clonar y preparar

```bash
git clone https://github.com/TU_USUARIO/sportalyze.git
cd sportalyze
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Paso 2 — Configurar variables de entorno

```bash
cp .env.example .env
# Edita .env y pon tu clave de football-data.org
# (saca una gratis en football-data.org/client/register)
```

### Paso 3 — Arrancar

```bash
python main.py
```

Abre: **http://localhost:8000**  
API Docs: **http://localhost:8000/docs**

---

## 🌐 Subirlo a internet

El repositorio trae `render.yaml` y `railway.json`, así que en los dos
sitios es conectar el repositorio y poner una variable:

    FOOTBALL_API_KEY = tu clave de football-data.org

Y nada más. `ENV=production` ya va en los dos ficheros.

**Un solo worker, a propósito.** La caché y el turnero de football-data
viven en la memoria del proceso. Con dos workers habría dos cachés y
dos turneros, y entre los dos se pasarían del límite de la API —
exactamente el problema que el turnero está para evitar.

**Lo que consume**, medido:

| | Memoria |
|---|---|
| Arrancado, sin hacer nada | 67 MB |
| Después de simular 10.000 ligas | 175 MB |

Cabe en los 512 MB de los planes pequeños. Antes eran 169 y 368: se
bajó quitando `pandas` (se importaba en tres ficheros y no se usaba en
ninguno), cargando `scipy` y `sklearn` sólo cuando hacen falta, y
troceando la simulación.

**Sin clave** la página funciona igual: el informe post-partido y el
relieve van sobre StatsBomb, que no pide clave. Las pantallas que
necesitan football-data dicen «falta la clave» en vez de un 403 pelado.

## 🌐 Deploy en Railway (histórico)

1. Sube el proyecto a GitHub
2. Ve a [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub**
3. Selecciona tu repositorio
4. En **Variables** añade: `FOOTBALL_API_KEY=tu_clave_de_football-data.org`
   5. Railway despliega automáticamente — en 2 minutos tienes URL pública

---

## 📡 API Endpoints

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/competitions` | Ligas con banderas y colores |
| `GET /api/standings/PL` | Clasificación Premier League live |
| `GET /api/matches/today` | Partidos de hoy |
| `GET /api/matches/PL` | Partidos de una liga |
| `GET /api/teams/57` | Perfil de equipo (Arsenal = 57) |
| `GET /api/scorers/PL` | Top goleadores |
| `GET /api/players/PL` | Jugadores con xG (Understat) |
| `GET /api/player/123/shots` | Disparos con coordenadas |
| `GET /api/player/123/injuries` | Lesiones + predicción ML |
| `GET /api/scouting/PL?position=FW` | Scouting ML |
| `GET /api/viz/radar/PL/123` | Radar PyPizza (PNG) |
| `GET /api/viz/shotmap/123` | Shot Map (PNG) |
| `GET /api/simulador/PD` | El Simulador: rangos de posición final |

### Abierto a la gente: el límite de football-data

Las **10 peticiones por minuto** del plan gratuito son del plan, no de
cada visitante. Con una persona no se nota; con un enlace compartido,
cinco personas pinchando equipos a la vez se las comen y todas ven un
error.

Por eso el cliente hace dos cosas:

- **Un turno.** Nunca salen más de nueve peticiones en sesenta
  segundos. Quien llega de más espera un par de segundos en lugar de
  recibir un 429.
- **Un viaje por petición.** Si cinco visitantes piden lo mismo a la
  vez, sale **una** y las cinco esperan a esa. Ahorra más que el turno,
  porque todo el mundo mira las mismas ligas.

Y al arrancar se calientan las clasificaciones de las cinco grandes,
despacio y cediendo el paso: si hay cola, deja de calentar. Un
visitante de verdad vale más que una liga que a lo mejor nadie mira.

`GET /health` dice cuántos segundos de cola hay ahora mismo.

El informe post-partido y el relieve **no gastan de aquí**: van sobre
StatsBomb Open Data, que no pide clave ni tiene límite.

### Scouting: lo que esta fuente permite puntuar

| Puesto | Nota | Por qué |
|---|---|---|
| Delanteros | sí | npxG, goles, xA, asistencias, pases clave, tiros y xGChain, por 90 minutos |
| Centrocampistas | sí | xA, pases clave, xGBuildup, xGChain, asistencias, npxG y goles, por 90 |
| Defensas | **no** | Understat no publica entradas, intercepciones, despejes ni duelos |
| Porteros | **no** | Understat no publica paradas, xG evitado ni salidas |

La nota es el **percentil medio dentro de su puesto en esa misma
comparación**, no una suma de métricas con unidades distintas. Un 86
quiere decir «mejor que el 86 % de los delanteros de esta comparación»,
y cada jugador lleva su desglose métrica a métrica.

**Lo que había antes, medido:** la tabla pedía métricas que Understat
no publica y las daba por cero cuando faltaban. Llegaban 5 de 8 para
delanteros, 2 de 8 para centrocampistas y **0 de 8** para defensas y
porteros — o sea que todos los defensas y todos los porteros tenían
exactamente 40,0 y la pantalla los ordenaba como si significara algo.
Encima multiplicaba por un bonus de edad calculado sobre una edad por
defecto de 25 años, porque Understat tampoco da la edad.

### El informe post-partido

| Ruta | Qué hace |
|---|---|
| `GET /api/informe/competiciones` | Qué hay con datos abiertos |
| `GET /api/informe/partidos/43/106` | Los partidos de una temporada |
| `GET /api/informe/3869685` | El informe entero de un partido |

Red de pases, mapa de tiros con su xG, la carrera de xG minuto a
minuto, las dos alineaciones cifra a cifra y quién hizo qué. Todo
calculado de los eventos y dibujado en SVG en el navegador: ni una
imagen generada en el servidor.

**La fuente es StatsBomb Open Data, y no es un detalle.** El cuaderno
del que viene este informe lee los eventos del HTML de WhoScored, que
por dentro son de Opta. Eso vale para mirar un partido en tu ordenador
y no vale para publicarlo: es licencia comercial, y las condiciones de
WhoScored prohíben extraerlo y redistribuirlo. StatsBomb Open Data es
gratis, está publicado justo para esto y sólo pide atribución — por eso
«StatsBomb Open Data» sale en la pantalla y no en letra pequeña.

La tanda de penaltis **no entra en ninguna cifra**. Viene como eventos
normales en el periodo 5, y contarla deja la final del Mundial 2022 en
7-5 y le regala 1,57 de xG a Francia sin haber tirado a puerta.

Y antes de publicar nada, el informe comprueba que los goles que salen
de los eventos cuadran con el marcador oficial. Si no cuadran, no hay
informe.

### El Simulador

Una sola llamada trae el calendario entero de la liga —jugado y por
jugar—, ajusta la fuerza de ataque y defensa de cada equipo y simula
10.000 veces lo que queda. Devuelve, por equipo, el rango de posiciones
en el que acaba en 8 de cada 10 simulaciones, más el 1X2 de los
próximos partidos.

Se **niega** a contestar cuando los datos no permiten simular
honestamente, y dice por qué en `motivo`:

| `motivo` | Qué ha pasado |
|---|---|
| `datos_desfasados` | Hay partidos jugados y la fuente aún no da su resultado |
| `calendario_incompleto` | No ha llegado la temporada entera |
| `demasiado_pronto` | Tan poco jugado que el resultado no diría nada |
| `limite_alcanzado` | Gastadas las 10 peticiones del minuto (HTTP 429) |
| `fuente_caida` | football-data no ha contestado |

Devolver un número en cualquiera de esos casos sería peor que no
devolver ninguno: parecería de hoy sin serlo.

---

## 🏗️ Estructura del proyecto

```
sportalyze/
├── main.py                 # Servidor FastAPI
├── requirements.txt        # Dependencias
├── .env.example            # Variables de entorno
├── railway.json            # Config deploy Railway
├── Procfile                # Config Heroku/Railway
│
├── backend/
│   ├── config.py           # Configuración central
│   ├── scrapers/
│   │   ├── football_data.py  # API football-data.org
│   │   ├── understat.py      # xG real
│   │   └── transfermarkt.py  # Lesiones + valores
│   ├── ml/
│   │   ├── scouting.py       # K-Means + scoring (Futuras_estrellas)
│   │   └── injury_prediction.py # Predicción lesiones
│   └── viz/
│       ├── radar.py          # PyPizza (diferenciar_jugadores)
│       └── shotmap.py        # Shot maps (PostMatch)
│
├── frontend/               # App web (próximo paso)
│
└── .github/workflows/
    └── daily_update.yml    # Scraping automático diario
```

---

## 📊 Fuentes de datos

| Fuente | Datos | Coste |
|--------|-------|-------|
| football-data.org | Clasificaciones, partidos, equipos | Gratis (10 req/min) |
| Understat | xG, xA, shots con coordenadas | Gratis |
| Transfermarkt | Lesiones, valores de mercado | Gratis (scraping) |
| StatsBomb Open | Eventos de partido detallados | Gratis |
| TheSportsDB | Escudos, fotos | Gratis |

---

## 🤖 Machine Learning incluido

- **Scouting** — K-Means clustering + scoring ponderado por posición
- **Jugadores similares** — Cosine Similarity sobre métricas normalizadas
- **Predicción de lesiones** — Random Forest features desde Transfermarkt
- **Radar PyPizza** — Percentiles reales vs media de la liga

---

## 💰 Monetización (próximo paso)

Ver `docs/MONETIZACION.md` para el plan completo freemium.

---

## 📬 Contacto

¿Quieres colaborar o monetizar Sportalyze?
Abre un issue o contacta directamente.

---

*SPORTALYZE v2.0 — De los datos al gol.*
