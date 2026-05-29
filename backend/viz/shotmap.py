# backend/viz/shotmap.py
# ============================================================
# Shot Maps con mplsoccer — basado en tu PostMatch notebook
# Datos: Understat (coordenadas reales de disparos)
# ============================================================

import io
import base64
import logging
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as path_effects
from matplotlib.colors import LinearSegmentedColormap
from backend.config import VIZ_COLORS

logger = logging.getLogger(__name__)


def generar_shotmap(
    shots: list,
    title: str = "Shot Map",
    team_color: str = "#0ea5e9",
    show_misses: bool = True,
) -> str:
    """
    Shot map individual o de equipo con mplsoccer.
    EXACTAMENTE tu lógica de PostMatch_actualizado.ipynb
    shots: lista de dicts con keys: x, y, xG, result, player, minute
    """
    try:
        from mplsoccer import VerticalPitch
    except ImportError:
        logger.error("mplsoccer no instalado")
        return ""

    if not shots:
        return ""

    fig, ax = plt.subplots(figsize=(7, 9), facecolor=VIZ_COLORS["bg"])
    ax.set_facecolor(VIZ_COLORS["bg"])

    # ── Campo vertical (igual que tu notebook) ─────────────
    pitch = VerticalPitch(
        pitch_type="statsbomb",
        pitch_color="none",
        line_color="#FFFFFF",
        linewidth=0.8,
        corner_arcs=True,
        half=True,              # Solo mitad atacante
    )
    pitch.draw(ax=ax)

    # Separar por resultado
    goals    = [s for s in shots if s.get("result") == "Goal"]
    on_target = [s for s in shots if s.get("result") in ["SavedShot"] ]
    off_target = [s for s in shots if s.get("result") in ["MissedShots", "ShotOnPost", "BlockedShot"]]

    path_eff = [path_effects.Stroke(linewidth=2.5, foreground=VIZ_COLORS["bg"]),
                path_effects.Normal()]

    # ── Disparos fuera/bloqueados ──────────────────────────
    if show_misses and off_target:
        x_off = [s["x"] for s in off_target]
        y_off = [s["y"] for s in off_target]
        xG_off = [max(float(s.get("xG", 0.05)), 0.01) for s in off_target]
        sizes_off = [xg * 1500 + 50 for xg in xG_off]
        ax.scatter(x_off, y_off, s=sizes_off, c="#484f58", alpha=0.6,
                   linewidths=1, edgecolors="#8b949e", zorder=3, marker="o")

    # ── Disparos a puerta ──────────────────────────────────
    if on_target:
        x_on = [s["x"] for s in on_target]
        y_on = [s["y"] for s in on_target]
        xG_on = [max(float(s.get("xG", 0.1)), 0.01) for s in on_target]
        sizes_on = [xg * 2000 + 100 for xg in xG_on]
        ax.scatter(x_on, y_on, s=sizes_on, c=team_color, alpha=0.7,
                   linewidths=1.5, edgecolors="white", zorder=4, marker="o")

    # ── Goles (con efecto especial) ────────────────────────
    if goals:
        x_g  = [s["x"] for s in goals]
        y_g  = [s["y"] for s in goals]
        xG_g = [max(float(s.get("xG", 0.2)), 0.01) for s in goals]
        sizes_g = [xg * 3000 + 200 for xg in xG_g]

        # Brillo externo (tu efecto de PostMatch)
        ax.scatter(x_g, y_g, s=[sz * 2 for sz in sizes_g],
                   c=VIZ_COLORS["gold"], alpha=0.2, linewidths=0, zorder=4)
        ax.scatter(x_g, y_g, s=sizes_g, c=VIZ_COLORS["gold"],
                   linewidths=2, edgecolors="white", zorder=5, marker="*")

    # ── Stats de xG ───────────────────────────────────────
    total_xG  = sum(float(s.get("xG", 0)) for s in shots)
    total_goals = len(goals)
    n_shots   = len(shots)

    fig.text(0.5, 0.97, title, size=15, ha="center", color="#FFFFFF",
             fontweight="bold", path_effects=path_eff)

    stats_text = f"{total_goals} Goles  |  {n_shots} Disparos  |  xG: {total_xG:.2f}"
    fig.text(0.5, 0.94, stats_text, size=10, ha="center", color=VIZ_COLORS["text_dim"])

    # Leyenda
    legend_elements = [
        plt.scatter([], [], s=100, c=VIZ_COLORS["gold"], marker="*", label="Gol"),
        plt.scatter([], [], s=80, c=team_color, label="A puerta"),
        plt.scatter([], [], s=60, c="#484f58", label="Fuera/Bloqueado"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", frameon=False,
              labelcolor="white", fontsize=9)

    fig.text(0.99, 0.01, "SPORTALYZE · Understat data", size=7,
             ha="right", color="#484f58")

    plt.tight_layout(pad=0.3)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=VIZ_COLORS["bg"], transparent=False)
    plt.close(fig)
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.read()).decode()}"


def generar_shotmap_partido(
    home_shots: list,
    away_shots: list,
    home_team: str,
    away_team: str,
    home_color: str = "#0ea5e9",
    away_color: str = "#f85149",
) -> str:
    """
    Shot map de partido completo con ambos equipos lado a lado.
    Basado en la sección de visualización de disparos de tu PostMatch notebook.
    """
    try:
        from mplsoccer import VerticalPitch
    except ImportError:
        return ""

    fig, axes = plt.subplots(1, 2, figsize=(14, 9), facecolor=VIZ_COLORS["bg"])
    fig.patch.set_facecolor(VIZ_COLORS["bg"])

    path_eff = [path_effects.Stroke(linewidth=2.5, foreground=VIZ_COLORS["bg"]),
                path_effects.Normal()]

    for ax, shots, team, color in [
        (axes[0], home_shots, home_team, home_color),
        (axes[1], away_shots, away_team, away_color),
    ]:
        ax.set_facecolor(VIZ_COLORS["bg"])
        pitch = VerticalPitch(
            pitch_type="statsbomb",
            pitch_color="none",
            line_color="#FFFFFF",
            linewidth=0.8,
            corner_arcs=True,
            half=True,
        )
        pitch.draw(ax=ax)

        goals     = [s for s in shots if s.get("result") == "Goal"]
        on_target = [s for s in shots if s.get("result") == "SavedShot"]
        off_target = [s for s in shots if s.get("result") not in ["Goal", "SavedShot"]]

        if off_target:
            xoffs = [s["x"] for s in off_target]
            yoffs = [s["y"] for s in off_target]
            sizes = [max(float(s.get("xG", 0.05)), 0.01) * 1500 + 50 for s in off_target]
            ax.scatter(xoffs, yoffs, s=sizes, c="#484f58", alpha=0.6,
                       edgecolors="#8b949e", linewidths=1, zorder=3)

        if on_target:
            xons = [s["x"] for s in on_target]
            yons = [s["y"] for s in on_target]
            sizes = [max(float(s.get("xG", 0.1)), 0.01) * 2000 + 100 for s in on_target]
            ax.scatter(xons, yons, s=sizes, c=color, alpha=0.75,
                       edgecolors="white", linewidths=1.5, zorder=4)

        if goals:
            xgs = [s["x"] for s in goals]
            ygs = [s["y"] for s in goals]
            sizes = [max(float(s.get("xG", 0.2)), 0.01) * 3000 + 200 for s in goals]
            ax.scatter(xgs, ygs, s=[sz * 2 for sz in sizes],
                       c=VIZ_COLORS["gold"], alpha=0.2, linewidths=0, zorder=4)
            ax.scatter(xgs, ygs, s=sizes, c=VIZ_COLORS["gold"],
                       edgecolors="white", linewidths=2, zorder=5, marker="*")

        total_xG = sum(float(s.get("xG", 0)) for s in shots)
        n_goals  = len(goals)
        ax.set_title(f"{team}\n{n_goals} Goles · xG: {total_xG:.2f}",
                     color="white", fontsize=12, fontweight="bold",
                     path_effects=path_eff, pad=10)

    fig.text(0.5, 0.98, "Shot Map del Partido", size=14,
             ha="center", color="white", fontweight="bold", path_effects=path_eff)
    fig.text(0.99, 0.01, "SPORTALYZE · Understat data",
             size=7, ha="right", color="#484f58")

    plt.tight_layout(pad=1.5)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=VIZ_COLORS["bg"])
    plt.close(fig)
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.read()).decode()}"
