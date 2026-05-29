# backend/config.py
# ============================================================
# Configuración central de SPORTALYZE
# Toda la app lee de aquí — nunca hardcodear valores
# ============================================================

import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ─────────────────────────────────────────────────
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY", "")
FOOTBALL_API_BASE = "https://api.football-data.org/v4"

# ── App ──────────────────────────────────────────────────────
PORT = int(os.getenv("PORT", 8000))
ENV = os.getenv("ENV", "development")
CACHE_TTL = int(os.getenv("CACHE_TTL", 3600))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sportalyze.db")

# ── Ligas disponibles con metadata completa ──────────────────
LEAGUES = {
    "PL":  {"name": "Premier League",    "country": "England",     "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "color": "#3D195B", "bg": "#29003e"},
    "PD":  {"name": "La Liga",           "country": "Spain",       "flag": "🇪🇸", "color": "#EE3524", "bg": "#8B0000"},
    "BL1": {"name": "Bundesliga",        "country": "Germany",     "flag": "🇩🇪", "color": "#D20515", "bg": "#7a0000"},
    "SA":  {"name": "Serie A",           "country": "Italy",       "flag": "🇮🇹", "color": "#024494", "bg": "#012060"},
    "FL1": {"name": "Ligue 1",           "country": "France",      "flag": "🇫🇷", "color": "#132257", "bg": "#0a1530"},
    "DED": {"name": "Eredivisie",        "country": "Netherlands", "flag": "🇳🇱", "color": "#FF6600", "bg": "#8B3A00"},
    "PPL": {"name": "Primeira Liga",     "country": "Portugal",    "flag": "🇵🇹", "color": "#006600", "bg": "#003300"},
    "BSA": {"name": "Brasileirão",       "country": "Brazil",      "flag": "🇧🇷", "color": "#009C3B", "bg": "#005520"},
    "CL":  {"name": "Champions League", "country": "Europe",      "flag": "🏆", "color": "#1B3A6B", "bg": "#0d1f3c"},
    "EL":  {"name": "Europa League",    "country": "Europe",      "flag": "🟠", "color": "#F47921", "bg": "#7a3a00"},
    "EC":  {"name": "Euros",            "country": "Europe",      "flag": "🇪🇺", "color": "#003399", "bg": "#001a66"},
    "WC":  {"name": "World Cup",        "country": "World",       "flag": "🌍", "color": "#6CABDD", "bg": "#2a5a7a"},
}

# ── Posiciones ───────────────────────────────────────────────
POSITIONS = {
    "GK":  {"name": "Portero",          "color": "#f59e0b"},
    "DF":  {"name": "Defensa",          "color": "#3b82f6"},
    "MF":  {"name": "Centrocampista",   "color": "#10b981"},
    "FW":  {"name": "Delantero",        "color": "#ef4444"},
}

# ── Métricas por posición (para ML y radar) ──────────────────
METRICS_BY_POSITION = {
    "FW": {
        "labels":  ["Goles", "Asist", "xG", "npxG", "Disparos", "SoT%", "Regates", "G+A/90"],
        "keys":    ["goals", "assists", "xG", "npxG", "shots", "sot_pct", "dribbles", "ga_p90"],
        "weights": [0.30, 0.12, 0.22, 0.15, 0.07, 0.05, 0.05, 0.04],
    },
    "MF": {
        "labels":  ["Goles", "Asist", "xAG", "Pases%", "Pases Prog", "Presiones", "Regates", "Duelos"],
        "keys":    ["goals", "assists", "xAG", "pass_pct", "prog_passes", "pressures", "dribbles", "duels_won"],
        "weights": [0.15, 0.20, 0.15, 0.15, 0.12, 0.10, 0.08, 0.05],
    },
    "DF": {
        "labels":  ["Tackles", "Interc", "Despejes", "Aéreos%", "Pases%", "Bloques", "Presiones", "Errores"],
        "keys":    ["tackles", "interceptions", "clearances", "aerial_pct", "pass_pct", "blocks", "pressures", "errors"],
        "weights": [0.22, 0.20, 0.15, 0.12, 0.12, 0.08, 0.08, -0.03],
    },
    "GK": {
        "labels":  ["Paradas%", "xGA", "PSxG", "Paradas", "Salidas", "Pases%", "Penaltis", "Goles Conc"],
        "keys":    ["save_pct", "xGA", "PSxG", "saves", "sweeper_actions", "pass_pct", "pk_saves", "goals_against"],
        "weights": [0.28, 0.22, 0.18, 0.12, 0.08, 0.06, 0.04, -0.02],
    },
}

# ── Colores de visualizaciones (tus notebooks) ───────────────
VIZ_COLORS = {
    "bg":           "#0a0a0a",
    "bg_secondary": "#111111",
    "pitch":        "none",
    "lines":        "#FFFFFF",
    "green":        "#69f900",
    "red":          "#ff4b44",
    "blue":         "#56CEE0",
    "violet":       "#a369ff",
    "electric":     "#0ea5e9",    # Azul eléctrico Sportalyze
    "gold":         "#e3b341",
    "text":         "#FFFFFF",
    "text_dim":     "#8b949e",
}

# ── Sportalyze brand colors ───────────────────────────────────
BRAND = {
    "primary":   "#0ea5e9",   # Azul eléctrico
    "secondary": "#0284c7",
    "dark":      "#030712",   # Negro profundo
    "surface":   "#0d1117",
    "surface2":  "#161b22",
    "border":    "rgba(255,255,255,0.07)",
    "gold":      "#e3b341",
}
