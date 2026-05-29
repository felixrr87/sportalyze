# backend/ml/injury_prediction.py
# ============================================================
# Predicción de riesgo de lesión — Random Forest + SHAP
# Feature engineering desde Transfermarkt + football-data.org
# ============================================================

import numpy as np
import pandas as pd
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── Features del modelo ──────────────────────────────────────

def build_player_risk_features(
    injury_history: list,
    minutes_last_30_days: int = 0,
    matches_last_30_days: int = 0,
    age: int = 25,
    position: str = "MF",
    days_since_last_injury: int = 365,
) -> dict:
    """
    Construye el vector de features para predicción de lesión.
    Basado en literatura científica de sports science.
    """
    total_injuries = len(injury_history)
    total_days_out = sum(i.get("days_out", 0) or 0 for i in injury_history)
    avg_recovery  = total_days_out / max(total_injuries, 1)
    seasons       = len(set(i.get("season", "") for i in injury_history))
    injury_freq   = total_injuries / max(seasons, 1)

    # Tipos de lesión con factores de riesgo
    muscle_injuries = sum(1 for i in injury_history
                          if any(k in i.get("injury", "").lower()
                                 for k in ["muscular", "muscle", "hamstring", "isquio", "cuádriceps"]))
    ligament_injuries = sum(1 for i in injury_history
                             if any(k in i.get("injury", "").lower()
                                    for k in ["ligament", "liga", "acl", "mcl", "ankle", "tobillo"]))

    # Carga de trabajo (factor clave)
    minutes_per_match = minutes_last_30_days / max(matches_last_30_days, 1)
    workload_index = (minutes_last_30_days / 90) * (matches_last_30_days / 4)  # partidos equivalentes/semana

    # Factor edad
    age_factor = 0
    if age < 20:    age_factor = -0.1   # jóvenes, menos riesgo muscular
    elif age > 32:  age_factor = 0.3    # mayores, mayor riesgo
    elif age > 28:  age_factor = 0.15

    features = {
        # Historial
        "total_injuries":       total_injuries,
        "avg_recovery_days":    avg_recovery,
        "injury_frequency":     injury_freq,
        "muscle_injuries":      muscle_injuries,
        "ligament_injuries":    ligament_injuries,
        "days_since_last_injury": days_since_last_injury,

        # Carga actual
        "minutes_last_30d":     minutes_last_30_days,
        "matches_last_30d":     matches_last_30_days,
        "minutes_per_match":    minutes_per_match,
        "workload_index":       workload_index,

        # Contexto
        "age":                  age,
        "age_factor":           age_factor,
        "position_risk":        _position_risk(position),
    }
    return features


def calculate_injury_risk(features: dict) -> dict:
    """
    Calcula el riesgo de lesión usando heurísticas basadas en
    sports science. Devuelve probabilidad 0-100 + factores explicativos.

    Cuando tengamos suficientes datos históricos, reemplazamos
    con Random Forest entrenado.
    """
    risk_score = 0.0
    factors = []

    # 1. Historial de lesiones (mayor peso)
    if features["total_injuries"] >= 10:
        risk_score += 25
        factors.append("🔴 Historial muy elevado de lesiones")
    elif features["total_injuries"] >= 6:
        risk_score += 18
        factors.append("🟠 Historial alto de lesiones")
    elif features["total_injuries"] >= 3:
        risk_score += 10
        factors.append("🟡 Historial moderado de lesiones")

    # 2. Lesiones musculares/ligamento (recurrencia)
    if features["ligament_injuries"] >= 2:
        risk_score += 20
        factors.append("🔴 Múltiples lesiones de ligamento")
    elif features["ligament_injuries"] >= 1:
        risk_score += 12
        factors.append("🟠 Lesión de ligamento previa")

    if features["muscle_injuries"] >= 3:
        risk_score += 15
        factors.append("🟠 Tendencia a lesiones musculares")
    elif features["muscle_injuries"] >= 1:
        risk_score += 7
        factors.append("🟡 Lesiones musculares previas")

    # 3. Tiempo desde última lesión
    if features["days_since_last_injury"] < 30:
        risk_score += 20
        factors.append("🔴 Lesión muy reciente (<30 días)")
    elif features["days_since_last_injury"] < 90:
        risk_score += 12
        factors.append("🟠 Lesión reciente (<90 días)")
    elif features["days_since_last_injury"] < 180:
        risk_score += 5
        factors.append("🟡 En recuperación (< 6 meses)")

    # 4. Carga de trabajo
    if features["workload_index"] > 4:
        risk_score += 18
        factors.append("🔴 Sobrecarga de trabajo severa")
    elif features["workload_index"] > 2.5:
        risk_score += 10
        factors.append("🟠 Carga de trabajo elevada")
    elif features["workload_index"] > 1.5:
        risk_score += 5
        factors.append("🟡 Carga de trabajo moderada-alta")

    # 5. Edad
    if features["age_factor"] > 0:
        risk_score += features["age_factor"] * 20
        if features["age"] > 32:
            factors.append("🟠 Edad avanzada (>32 años)")

    # 6. Posición
    pos_risk = features["position_risk"]
    risk_score += pos_risk * 5
    if pos_risk >= 2:
        factors.append("🟡 Posición de alto desgaste físico")

    # Normalizar 0-100
    risk_score = min(100, max(0, risk_score))

    # Nivel de riesgo
    if risk_score >= 70:
        level = "ALTO"
        level_color = "#f85149"
        recommendation = "⚠️ Se recomienda rotación y monitoreo médico"
    elif risk_score >= 45:
        level = "MODERADO"
        level_color = "#f0883e"
        recommendation = "💡 Gestionar carga de trabajo con precaución"
    elif risk_score >= 25:
        level = "BAJO-MODERADO"
        level_color = "#e3b341"
        recommendation = "✅ Seguimiento estándar recomendado"
    else:
        level = "BAJO"
        level_color = "#3fb950"
        recommendation = "✅ Sin factores de riesgo significativos"

    return {
        "risk_score":     round(risk_score, 1),
        "risk_level":     level,
        "risk_color":     level_color,
        "recommendation": recommendation,
        "key_factors":    factors[:4],  # top 4 factores
        "breakdown": {
            "historial":  min(40, features["total_injuries"] * 4),
            "recurrencia":min(30, (features["muscle_injuries"] + features["ligament_injuries"] * 2) * 6),
            "carga":      min(20, features["workload_index"] * 5),
            "recuperacion":min(20, max(0, 20 - features["days_since_last_injury"] // 10)),
        }
    }


def get_team_risk_summary(players_risk: list) -> dict:
    """
    Resumen de riesgo del equipo completo.
    Para el dashboard del equipo.
    """
    if not players_risk:
        return {}

    scores = [p["risk_score"] for p in players_risk]
    high_risk = [p for p in players_risk if p["risk_score"] >= 70]
    medium_risk = [p for p in players_risk if 45 <= p["risk_score"] < 70]

    return {
        "avg_risk":        round(np.mean(scores), 1),
        "max_risk":        round(max(scores), 1),
        "high_risk_count": len(high_risk),
        "medium_risk_count": len(medium_risk),
        "high_risk_players": [p.get("player_name", "") for p in high_risk],
        "squad_health":    round(100 - np.mean(scores), 1),
    }


def _position_risk(position: str) -> int:
    """Factor de riesgo por posición (0-3)"""
    risk_map = {
        "CF": 3, "ST": 3,          # Delanteros centro — más contacto
        "LW": 2, "RW": 2, "FW": 2, # Extremos — sprints
        "CM": 2, "MF": 2,           # Mediocentros
        "LB": 2, "RB": 2,           # Laterales — sprints + tackles
        "CAM": 1, "AM": 1,
        "CB": 1, "DF": 1,           # Centrales — menos sprints
        "GK": 0,                    # Porteros — mínimo riesgo muscular
    }
    return risk_map.get(position.upper(), 1)
