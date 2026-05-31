# main.py
# ============================================================
# SPORTALYZE — Servidor FastAPI principal
# Arranca con: python main.py
# Docs en:    http://localhost:8000/docs
# ============================================================

import asyncio
import logging
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
from backend.config import PORT, ENV, LEAGUES

# ── Logging ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO if ENV == "production" else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sportalyze")

# ── App ───────────────────────────────────────────────────
app = FastAPI(
    title="SPORTALYZE API",
    description="🏆 Plataforma profesional de análisis futbolístico",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Importar scrapers y ML ────────────────────────────────
from backend.scrapers.football_data import football_client
from backend.scrapers.understat import (
    get_league_players, get_player_shots,
    get_match_shots, get_league_teams_xg,
)
from backend.scrapers.transfermarkt import (
    get_player_injuries, build_injury_features,
)
from backend.ml.scouting import run_scouting_pipeline, find_similar_players
from backend.ml.injury_prediction import build_player_risk_features, calculate_injury_risk


# ════════════════════════════════════════════════════════
# RUTAS — COMPETICIONES
# ════════════════════════════════════════════════════════

@app.get("/api/competitions")
async def get_competitions():
    """Lista todas las competiciones con banderas y colores"""
    try:
        comps = await football_client.get_competitions()
        return {"competitions": comps, "total": len(comps)}
    except Exception as e:
        # Fallback: retornar las ligas que conocemos
        fallback = [
            {**{"id": i, "code": k, "name": v["name"],
                "country": v["country"], "flag": v["flag"],
                "color": v["color"], "emblem": None},
            } for i, (k, v) in enumerate(LEAGUES.items())
        ]
        return {"competitions": fallback, "total": len(fallback), "source": "local"}


# ════════════════════════════════════════════════════════
# RUTAS — CLASIFICACIONES
# ════════════════════════════════════════════════════════

@app.get("/api/standings/{competition_code}")
async def get_standings(competition_code: str):
    """
    Clasificación en tiempo real de una liga.
    Incluye xG de equipos desde Understat.
    """
    try:
        standings = await football_client.get_standings(competition_code.upper())
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Enriquecer con xG de Understat (async, no bloqueante)
    try:
        xg_data = await get_league_teams_xg(competition_code.upper())
        xg_map = {t["team"]: t for t in xg_data}
        for row in standings["table"]:
            team_key = next(
                (k for k in xg_map if k.lower() in row["team_name"].lower()
                 or row["team_name"].lower() in k.lower()), None
            )
            if team_key:
                row["xG"]  = xg_map[team_key].get("xG", None)
                row["xGA"] = xg_map[team_key].get("xGA", None)
    except Exception:
        pass  # xG es adicional, no crítico

    return standings


# ════════════════════════════════════════════════════════
# RUTAS — PARTIDOS
# ════════════════════════════════════════════════════════

@app.get("/api/matches/today")
async def get_today_matches():
    """Partidos de hoy con marcadores live"""
    try:
        matches = await football_client.get_matches_today()
        return {"matches": matches, "total": len(matches)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/matches/{competition_code}")
async def get_competition_matches(
    competition_code: str,
    status: str = Query(None, description="FINISHED | SCHEDULED | LIVE"),
    limit: int = Query(20, ge=1, le=50),
):
    """Partidos de una competición"""
    try:
        matches = await football_client.get_competition_matches(
            competition_code.upper(), status=status, limit=limit
        )
        return {"matches": matches, "total": len(matches)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ════════════════════════════════════════════════════════
# RUTAS — EQUIPOS
# ════════════════════════════════════════════════════════

@app.get("/api/teams/{team_id}")
async def get_team(team_id: int):
    """Perfil completo del equipo con plantilla"""
    try:
        team = await football_client.get_team(team_id)
        recent = await football_client.get_team_matches(team_id, limit=10)
        return {**team, "recent_matches": recent}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/teams/{team_id}/matches")
async def get_team_matches_route(
    team_id: int,
    limit: int = Query(10, ge=1, le=20)
):
    """Últimos partidos de un equipo"""
    try:
        matches = await football_client.get_team_matches(team_id, limit=limit)
        return {"matches": matches, "total": len(matches)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ════════════════════════════════════════════════════════
# RUTAS — GOLEADORES
# ════════════════════════════════════════════════════════

@app.get("/api/scorers/{competition_code}")
async def get_top_scorers(
    competition_code: str,
    limit: int = Query(20, ge=5, le=50),
):
    """Top goleadores de una competición"""
    try:
        scorers = await football_client.get_top_scorers(
            competition_code.upper(), limit=limit
        )
        return {"scorers": scorers, "total": len(scorers)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ════════════════════════════════════════════════════════
# RUTAS — JUGADORES (Understat)
# ════════════════════════════════════════════════════════

@app.get("/api/players/{competition_code}")
async def get_league_players_stats(
    competition_code: str,
    season: int = Query(2024, description="2024 = temporada 2024/25"),
    position: str = Query(None),
    min_minutes: int = Query(200, ge=0),
    max_age: int = Query(99, ge=15, le=50),
    limit: int = Query(100, ge=10, le=500),
):
    """
    Jugadores de una liga con estadísticas xG reales (Understat).
    Filtros: posición, minutos mínimos, edad máxima.
    """
    try:
        players = await get_league_players(competition_code.upper(), season)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Filtros
    if position:
        players = [p for p in players if p.get("position", "").upper() == position.upper()]
    players = [p for p in players if p.get("time", 0) >= min_minutes]

    # Score ML
    from backend.ml.scouting import score_player
    for p in players:
        pos = p.get("position", "FW")
        p["score"] = score_player(p, pos[:2])

    players.sort(key=lambda x: -x.get("score", 0))
    return {
        "players": players[:limit],
        "total": len(players),
        "competition": competition_code.upper(),
        "season": season,
    }


@app.get("/api/player/{player_id}/shots")
async def get_player_shot_map(player_id: str):
    """Disparos de un jugador con coordenadas para shot map"""
    try:
        shots = await get_player_shots(player_id)
        return {"shots": shots, "total": len(shots)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ════════════════════════════════════════════════════════
# RUTAS — LESIONES
# ════════════════════════════════════════════════════════

@app.get("/api/player/{player_id}/injuries")
async def get_player_injuries_route(
    player_id: str,
    player_slug: str = Query("player"),
    minutes_last_30: int = Query(0),
    matches_last_30: int = Query(0),
    age: int = Query(25),
    position: str = Query("MF"),
):
    """
    Historial de lesiones + predicción de riesgo ML.
    Combina Transfermarkt + nuestro modelo de predicción.
    """
    # Historial desde Transfermarkt
    injuries = get_player_injuries(player_id, player_slug)
    injury_features_raw = build_injury_features(injuries)

    # Calcular días desde última lesión
    days_since = 365
    if injuries:
        import datetime
        last = injuries[0].get("date_until", "") or injuries[0].get("date_from", "")
        if last and last != "Present":
            try:
                parts = last.split(".")
                if len(parts) == 3:
                    d = datetime.datetime(int(parts[2]), int(parts[1]), int(parts[0]))
                    days_since = (datetime.datetime.now() - d).days
            except:
                pass

    # Features para el modelo
    risk_features = build_player_risk_features(
        injury_history=injuries,
        minutes_last_30_days=minutes_last_30,
        matches_last_30_days=matches_last_30,
        age=age,
        position=position,
        days_since_last_injury=days_since,
    )

    # Predicción
    risk = calculate_injury_risk(risk_features)

    return {
        "player_id":     player_id,
        "injuries":      injuries,
        "injury_summary":injury_features_raw,
        "risk_prediction": risk,
        "features":      risk_features,
    }


# ════════════════════════════════════════════════════════
# RUTAS — SCOUTING ML
# ════════════════════════════════════════════════════════

@app.get("/api/scouting/{competition_code}")
async def run_scouting(
    competition_code: str,
    position: str = Query("FW", description="FW | MF | DF | GK"),
    max_age: int = Query(25, ge=15, le=35),
    min_minutes: int = Query(500, ge=0),
    season: int = Query(2024),
):
    """
    Scouting ML — K-Means clustering + scoring por posición.
    Basado en tu notebook Futuras_estrellas.
    """
    try:
        players = await get_league_players(competition_code.upper(), season)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    result = run_scouting_pipeline(
        players=players,
        position=position.upper()[:2],
        max_age=max_age,
        min_minutes=min_minutes,
    )
    return result


@app.get("/api/player/{player_id}/similar")
async def get_similar_players(
    player_id: str,
    competition_code: str = Query("PL"),
    top_n: int = Query(5, ge=3, le=10),
    season: int = Query(2024),
):
    """'Jugadores similares a X' — K-Means similarity"""
    players = await get_league_players(competition_code.upper(), season)
    target = next((p for p in players if str(p.get("player_id")) == str(player_id)), None)
    if not target:
        raise HTTPException(status_code=404, detail="Jugador no encontrado")

    similar = find_similar_players(
        target_player=target,
        all_players=players,
        position=target.get("position", "MF"),
        top_n=top_n,
    )
    return {"target": target, "similar": similar}


# ════════════════════════════════════════════════════════
# RUTAS — VISUALIZACIONES (PNG en base64)
# ════════════════════════════════════════════════════════

@app.get("/api/viz/radar/{competition_code}/{player_id}")
async def get_player_radar(
    competition_code: str,
    player_id: str,
    season: int = Query(2024),
    position: str = Query(None),
):
    """Radar PyPizza del jugador — imagen PNG en base64"""
    try:
        players = await get_league_players(competition_code.upper(), season)
        target = next((p for p in players if str(p.get("player_id")) == str(player_id)), None)
        if not target:
            raise HTTPException(status_code=404, detail="Jugador no encontrado")
        pos = position or target.get("position", "FW")
        from backend.viz.radar import generar_radar_pizza
        img = generar_radar_pizza(
            player_data=target,
            all_players=players,
            position=pos[:2].upper(),
        )
        if not img:
            raise HTTPException(status_code=500, detail="Error generando radar")
        return {"image": img, "player": target["name"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/viz/radar-custom")
async def get_custom_radar(
    name: str = Query(...),
    goals: float = Query(0),
    assists: float = Query(0),
    xG: float = Query(0),
    minutes: int = Query(0),
    rating: float = Query(80),
    position: str = Query("FW"),
    team: str = Query(""),
    competition_code: str = Query("PL"),
    season: int = Query(2024),
):
    """Radar PyPizza con datos directos — para jugadores locales del frontend"""
    try:
        player_data = {
            "name": name, "goals": goals, "assists": assists,
            "xG": xG, "xA": assists * 0.8, "npxG": xG * 0.95,
            "minutes": minutes, "rating": rating, "team": team,
            "shots": int(goals * 3.5), "key_passes": int(assists * 2),
            "xGChain": xG * 1.3, "xGBuildup": xG * 0.5,
            "position": position,
        }
        # Get league players for percentile comparison
        try:
            all_players = await get_league_players(competition_code.upper(), season)
        except:
            all_players = [player_data]

        from backend.viz.radar import generar_radar_pizza
        img = generar_radar_pizza(
            player_data=player_data,
            all_players=all_players,
            position=position[:2].upper(),
            titulo_principal=name,
            titulo_secundario=f"{team} · {position} · Temporada {season}/{str(season+1)[-2:]}",
        )
        if not img:
            raise HTTPException(status_code=500, detail="Error generando radar")
        return {"image": img, "player": name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/viz/shotmap/{player_id}")
async def get_shotmap(player_id: str, season_filter: str = Query(None)):
    """Shot map del jugador desde Understat — imagen PNG en base64"""
    try:
        shots = await get_player_shots(player_id)
        if season_filter:
            shots = [s for s in shots if s.get("season") == season_filter]
        if not shots:
            raise HTTPException(status_code=404, detail="Sin datos de disparos")
        player_name = shots[0].get("player", "Jugador") if shots else "Jugador"
        from backend.viz.shotmap import generar_shotmap
        img = generar_shotmap(shots, title=f"Shot Map — {player_name}")
        return {"image": img, "total_shots": len(shots)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/viz/shotmap-custom")
async def get_custom_shotmap(
    player_name: str = Query("Jugador"),
    goals: int = Query(10),
    shots: int = Query(50),
    xG: float = Query(8.5),
    team_color: str = Query("0ea5e9"),
):
    """Shot map simulado — cuando no hay datos de Understat"""
    try:
        import random
        random.seed(hash(player_name) % 1000)
        # Generate realistic shot positions
        simulated_shots = []
        for i in range(shots):
            is_goal = i < goals
            # Shots concentrated around penalty area
            x = random.gauss(88, 8)
            y = random.gauss(34, 12)
            x = max(60, min(100, x))
            y = max(15, min(85, y))
            simulated_shots.append({
                "x": x, "y": y,
                "xG": random.uniform(0.05, 0.6) if is_goal else random.uniform(0.02, 0.3),
                "result": "Goal" if is_goal else random.choice(["SavedShot","MissedShots","BlockedShot"]),
                "player": player_name,
                "situation": random.choice(["OpenPlay","SetPiece","FromCorner"]),
                "shot_type": random.choice(["RightFoot","LeftFoot","Head"]),
            })
        from backend.viz.shotmap import generar_shotmap
        img = generar_shotmap(
            simulated_shots,
            title=f"Shot Map — {player_name}",
            team_color=f"#{team_color}",
        )
        return {"image": img, "total_shots": shots, "simulated": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ════════════════════════════════════════════════════════
# FRONTEND — Servir el HTML
# ════════════════════════════════════════════════════════

frontend_path = Path(__file__).parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_frontend():
        index = frontend_path / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"message": "SPORTALYZE API corriendo. Frontend no encontrado."})
else:
    @app.get("/", include_in_schema=False)
    async def root():
        return {
            "app": "SPORTALYZE API",
            "version": "2.0.0",
            "docs": "/docs",
            "status": "running",
        }


# ════════════════════════════════════════════════════════
# HEALTH CHECK
# ════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    from backend.config import FOOTBALL_API_KEY
    return {
        "status": "ok",
        "api_key_configured": bool(FOOTBALL_API_KEY),
        "env": ENV,
    }


# ════════════════════════════════════════════════════════
# ARRANQUE
# ════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════╗
║        ⚽ SPORTALYZE v2.0            ║
║   Análisis Deportivo Profesional     ║
╠══════════════════════════════════════╣
║  API Docs: http://localhost:8000/docs║
║  Frontend: http://localhost:8000     ║
╚══════════════════════════════════════╝
    """)
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=(ENV == "development"),
        log_level="info",
    )
