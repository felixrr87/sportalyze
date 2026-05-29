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
# Edita .env — ya tiene tu API key de football-data.org
```

### Paso 3 — Arrancar

```bash
python main.py
```

Abre: **http://localhost:8000**  
API Docs: **http://localhost:8000/docs**

---

## 🌐 Deploy en Railway (gratis, 24/7)

1. Sube el proyecto a GitHub
2. Ve a [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub**
3. Selecciona tu repositorio
4. En **Variables** añade: `FOOTBALL_API_KEY=18f8f363554247f69bba9b7a9d049da8`
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
