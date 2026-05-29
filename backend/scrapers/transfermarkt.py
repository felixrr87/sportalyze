# backend/scrapers/transfermarkt.py
# ============================================================
# Transfermarkt — historial de lesiones y valores de mercado
# Sin API key. Scraping con requests + BeautifulSoup
# ============================================================

import requests
import logging
from bs4 import BeautifulSoup
from cachetools import TTLCache
from backend.config import CACHE_TTL

logger = logging.getLogger(__name__)
_cache = TTLCache(maxsize=200, ttl=CACHE_TTL * 2)  # 2h para lesiones

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
    "Referer": "https://www.transfermarkt.es/",
}

BASE = "https://www.transfermarkt.es"


def get_player_injuries(player_id: str, player_slug: str = "player") -> list:
    """
    Historial completo de lesiones de un jugador.
    player_id: ID de Transfermarkt (ej: '28003' para Messi)
    player_slug: slug del nombre (ej: 'lionel-messi')
    """
    cache_key = f"tm_injuries_{player_id}"
    if cache_key in _cache:
        return _cache[cache_key]

    url = f"{BASE}/{player_slug}/verletzungen/spieler/{player_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        injuries = []
        table = soup.find("table", {"class": "items"})
        if not table:
            return []

        rows = table.find("tbody").find_all("tr") if table.find("tbody") else []
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 6:
                continue
            injuries.append({
                "season":       cols[0].get_text(strip=True),
                "injury":       cols[1].get_text(strip=True),
                "date_from":    cols[2].get_text(strip=True),
                "date_until":   cols[3].get_text(strip=True),
                "days_out":     _parse_int(cols[4].get_text(strip=True)),
                "games_missed": _parse_int(cols[5].get_text(strip=True)),
            })

        _cache[cache_key] = injuries
        return injuries

    except Exception as e:
        logger.error(f"Transfermarkt injuries error for {player_id}: {e}")
        return []


def get_player_market_value_history(player_id: str, player_slug: str = "player") -> list:
    """
    Evolución del valor de mercado de un jugador por fecha.
    Para el gráfico de valor histórico.
    """
    cache_key = f"tm_market_{player_id}"
    if cache_key in _cache:
        return _cache[cache_key]

    url = f"{BASE}/{player_slug}/marktwertverlauf/spieler/{player_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        # El valor está en JSON embebido en la página
        import re
        import json
        script_tags = soup.find_all("script")
        for script in script_tags:
            if "Highcharts.Chart" in str(script) and "data" in str(script):
                matches = re.findall(r'\{\"datum\":\"([^\"]+)\",\"mw\":\"([^\"]+)\"', str(script))
                result = []
                for date, value in matches:
                    # value viene como "10 Mio. €" o "500.000 €"
                    value_clean = _parse_market_value(value)
                    result.append({
                        "date":  date,
                        "value": value_clean,
                        "value_display": value,
                    })
                _cache[cache_key] = result
                return result
        return []

    except Exception as e:
        logger.error(f"Transfermarkt market value error for {player_id}: {e}")
        return []


def get_team_injuries(team_id: str, team_slug: str = "team") -> list:
    """
    Lesiones actuales del equipo — para el dashboard del equipo.
    """
    cache_key = f"tm_team_injuries_{team_id}"
    if cache_key in _cache:
        return _cache[cache_key]

    url = f"{BASE}/{team_slug}/sperrenundverletzungen/verein/{team_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        injuries = []
        tables = soup.find_all("table", {"class": "items"})
        for table in tables:
            rows = table.find("tbody").find_all("tr") if table.find("tbody") else []
            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 4:
                    continue
                player_link = row.find("a", {"class": "spielprofil_tooltip"})
                injuries.append({
                    "player":     player_link.get_text(strip=True) if player_link else cols[1].get_text(strip=True),
                    "player_id":  player_link["id"] if player_link and "id" in player_link.attrs else "",
                    "injury":     cols[2].get_text(strip=True) if len(cols) > 2 else "",
                    "since":      cols[3].get_text(strip=True) if len(cols) > 3 else "",
                    "until":      cols[4].get_text(strip=True) if len(cols) > 4 else "",
                })

        _cache[cache_key] = injuries
        return injuries

    except Exception as e:
        logger.error(f"Transfermarkt team injuries error {team_id}: {e}")
        return []


def build_injury_features(injuries: list) -> dict:
    """
    Extrae features para el modelo de predicción de lesiones.
    Usado por el módulo ML.
    """
    if not injuries:
        return {
            "total_injuries": 0,
            "total_days_out": 0,
            "avg_recovery_days": 0,
            "injury_types": {},
            "recent_injury_days": 0,
            "injury_frequency": 0,
            "recurrent_zones": [],
        }

    total_injuries = len(injuries)
    total_days = sum(i.get("days_out", 0) or 0 for i in injuries)
    avg_days = round(total_days / total_injuries, 1) if total_injuries > 0 else 0

    # Tipos de lesión
    injury_types = {}
    for inj in injuries:
        t = inj.get("injury", "Unknown")
        injury_types[t] = injury_types.get(t, 0) + 1

    # Lesiones recurrentes (misma zona 2+ veces)
    recurrent = [k for k, v in injury_types.items() if v >= 2]

    # Días fuera en la última temporada
    recent = injuries[:5]  # las 5 más recientes
    recent_days = sum(i.get("days_out", 0) or 0 for i in recent)

    return {
        "total_injuries":     total_injuries,
        "total_days_out":     total_days,
        "avg_recovery_days":  avg_days,
        "injury_types":       injury_types,
        "recent_injury_days": recent_days,
        "injury_frequency":   round(total_injuries / max(len(set(i.get("season", "") for i in injuries)), 1), 2),
        "recurrent_zones":    recurrent,
    }


def _parse_int(text: str) -> int:
    try:
        return int("".join(c for c in text if c.isdigit()))
    except:
        return 0


def _parse_market_value(text: str) -> int:
    """Convierte '10 Mio. €' → 10000000, '500.000 €' → 500000"""
    try:
        text = text.replace("€", "").replace("Mio.", "M").replace("Tsd.", "K").strip()
        if "M" in text:
            return int(float(text.replace("M", "").strip()) * 1_000_000)
        elif "K" in text:
            return int(float(text.replace("K", "").strip()) * 1_000)
        else:
            return int("".join(c for c in text if c.isdigit()))
    except:
        return 0
