# backend/ml/scouting.py
# ============================================================
# Motor de Scouting ML — basado en tu notebook Futuras_estrellas
# K-Means clustering + scoring por posición + similitud
# Fuente: Understat xG data
# ============================================================

import numpy as np
import pandas as pd
import logging
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics.pairwise import cosine_similarity
from backend.config import METRICS_BY_POSITION

logger = logging.getLogger(__name__)

N_CLUSTERS = 4
CLUSTER_LABELS = {
    0: {"name": "🌟 Élite",          "color": "#e3b341"},
    1: {"name": "🔥 Alto rendimiento","color": "#f0883e"},
    2: {"name": "📈 Promedio",        "color": "#39c5cf"},
    3: {"name": "🌱 En desarrollo",   "color": "#3fb950"},
}


def score_player(player: dict, position: str) -> float:
    """
    Calcula score 0-99 basado en métricas ponderadas por posición.
    Lógica extraída y mejorada de tu notebook Futuras_estrellas.
    """
    metrics = METRICS_BY_POSITION.get(position, METRICS_BY_POSITION["MF"])
    keys    = metrics["keys"]
    weights = metrics["weights"]

    score = 0.0
    weight_sum = 0.0

    for key, weight in zip(keys, weights):
        val = player.get(key, 0) or 0
        if weight > 0:
            score += float(val) * abs(weight)
        else:
            score -= float(val) * abs(weight)  # penalización (ej: errores)
        weight_sum += abs(weight)

    # Normalizar
    score = score / max(weight_sum, 0.001) * 10

    # Bonus por edad (jugadores jóvenes con buen rendimiento son más valiosos)
    age = player.get("age", 25) or 25
    if age <= 20:   score *= 1.18
    elif age <= 22: score *= 1.12
    elif age <= 24: score *= 1.06
    elif age <= 26: score *= 1.02
    elif age > 30:  score *= 0.95
    elif age > 33:  score *= 0.88

    return round(min(99, max(40, score)), 1)


def run_kmeans_clustering(players: list, position: str) -> list:
    """
    K-Means real sobre los jugadores filtrados.
    Basado en tu notebook Futuras_estrellas — lógica exacta preservada.
    """
    if len(players) < N_CLUSTERS:
        for p in players:
            p["cluster"] = 0
            p["cluster_label"] = CLUSTER_LABELS[0]["name"]
            p["cluster_color"] = CLUSTER_LABELS[0]["color"]
        return players

    metrics = METRICS_BY_POSITION.get(position, METRICS_BY_POSITION["MF"])
    feature_keys = [k for k in metrics["keys"]
                    if k in players[0] and players[0].get(k) is not None]

    if len(feature_keys) < 2:
        for i, p in enumerate(players):
            p["cluster"] = i % N_CLUSTERS
            p["cluster_label"] = CLUSTER_LABELS[i % N_CLUSTERS]["name"]
            p["cluster_color"] = CLUSTER_LABELS[i % N_CLUSTERS]["color"]
        return players

    # Matriz de features
    X = np.array([[float(p.get(k, 0) or 0) for k in feature_keys] for p in players])

    # Normalizar (StandardScaler — igual que tu notebook)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # K-Means
    kmeans = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init=10)
    raw_labels = kmeans.fit_predict(X_scaled)

    # Ordenar clusters por score medio (0 = mejor)
    cluster_scores = {}
    for i, p in enumerate(players):
        c = raw_labels[i]
        cluster_scores.setdefault(c, []).append(p.get("score", 50))

    cluster_avg = {c: np.mean(scores) for c, scores in cluster_scores.items()}
    rank_map = {c: rank for rank, c in enumerate(sorted(cluster_avg, key=cluster_avg.get, reverse=True))}

    # PCA para visualización 2D
    pca = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(X_scaled)
    variance = round(sum(pca.explained_variance_ratio_) * 100, 1)

    # Asignar resultados
    for i, p in enumerate(players):
        c = rank_map[raw_labels[i]]
        p["cluster"]        = c
        p["cluster_label"]  = CLUSTER_LABELS[c]["name"]
        p["cluster_color"]  = CLUSTER_LABELS[c]["color"]
        p["pca_x"]          = round(float(coords[i, 0]), 3)
        p["pca_y"]          = round(float(coords[i, 1]), 3)
        p["pca_variance"]   = variance

    return players


def find_similar_players(target_player: dict, all_players: list, position: str, top_n: int = 5) -> list:
    """
    'Jugadores similares a X' — K-Means + Cosine Similarity.
    Feature principal de scouting que no tienen los competidores.
    """
    metrics = METRICS_BY_POSITION.get(position, METRICS_BY_POSITION["MF"])
    keys = metrics["keys"]

    # Vector del jugador objetivo
    target_vec = np.array([[float(target_player.get(k, 0) or 0) for k in keys]])

    # Vectores de todos los jugadores
    candidates = [p for p in all_players if p.get("id") != target_player.get("id")]
    if not candidates:
        return []

    matrix = np.array([[float(p.get(k, 0) or 0) for k in keys] for p in candidates])

    # Normalizar
    scaler = StandardScaler()
    all_vecs = np.vstack([target_vec, matrix])
    all_vecs_scaled = scaler.fit_transform(all_vecs)

    target_scaled = all_vecs_scaled[:1]
    candidates_scaled = all_vecs_scaled[1:]

    # Similitud coseno
    similarities = cosine_similarity(target_scaled, candidates_scaled)[0]

    # Top N similares
    top_indices = np.argsort(similarities)[::-1][:top_n]
    result = []
    for idx in top_indices:
        p = candidates[idx].copy()
        p["similarity"] = round(float(similarities[idx]) * 100, 1)
        result.append(p)

    return result


def run_scouting_pipeline(
    players: list,
    position: str,
    max_age: int = 25,
    min_minutes: int = 500,
    league: str = "all",
) -> dict:
    """
    Pipeline completo de scouting — exactamente lo que hace tu notebook.
    1. Filtrar por posición, edad, minutos
    2. Calcular score ML por jugador
    3. K-Means clustering
    4. Devolver resultados ordenados
    """
    # Filtrar
    filtered = [p for p in players
                if p.get("position", "") == position
                and (p.get("age", 99) or 99) <= max_age
                and (p.get("time", 0) or 0) >= min_minutes
                and (league == "all" or p.get("league", "") == league)]

    if not filtered:
        return {"players": [], "summary": {}, "top_prospects": []}

    # Calcular scores
    for p in filtered:
        p["score"] = score_player(p, position)

    # K-Means clustering
    filtered = run_kmeans_clustering(filtered, position)

    # Ordenar por score
    filtered.sort(key=lambda x: -x.get("score", 0))

    # Top prospects (Élite + Alto)
    top_prospects = [p for p in filtered
                     if p.get("cluster", 3) <= 1][:10]

    # Resumen estadístico
    scores = [p["score"] for p in filtered]
    summary = {
        "total_players":    len(filtered),
        "avg_score":        round(np.mean(scores), 1),
        "max_score":        round(max(scores), 1),
        "elite_count":      sum(1 for p in filtered if p.get("cluster") == 0),
        "high_count":       sum(1 for p in filtered if p.get("cluster") == 1),
        "cluster_dist":     {CLUSTER_LABELS[i]["name"]: sum(1 for p in filtered if p.get("cluster") == i)
                             for i in range(N_CLUSTERS)},
        "top_player":       filtered[0]["name"] if filtered else "",
        "position":         position,
    }

    return {
        "players":       filtered,
        "summary":       summary,
        "top_prospects": top_prospects,
    }
