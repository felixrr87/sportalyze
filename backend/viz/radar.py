# backend/viz/radar.py
# ============================================================
# Radar de Pizza (PyPizza) — estilo Opta/Sofascore
# Basado EXACTAMENTE en tu notebook diferenciar_jugadores.ipynb
# Fuente de datos: Understat (reemplaza FBref)
# ============================================================

import io
import base64
import logging
import numpy as np
import matplotlib
matplotlib.use("Agg")  # Sin display — para servidor
import matplotlib.pyplot as plt
import matplotlib.patheffects as path_effects
from matplotlib import rcParams
from backend.config import VIZ_COLORS

logger = logging.getLogger(__name__)

# Configuración de fuentes (igual que tu notebook)
rcParams["font.family"] = "DejaVu Sans"


def calcular_percentiles(valor: float, todos_valores: list) -> float:
    """Calcula el percentil de un valor dentro de una lista."""
    if not todos_valores:
        return 50.0
    return round(sum(1 for v in todos_valores if v <= valor) / len(todos_valores) * 100, 1)


def generar_radar_pizza(
    player_data: dict,
    all_players: list,
    position: str = "FW",
    titulo_principal: str = None,
    titulo_secundario: str = None,
    colores_categorias: dict = None,
) -> str:
    """
    Genera radar de pizza con percentiles reales.
    EXACTAMENTE el código de tu notebook diferenciar_jugadores.

    Returns: imagen en base64 para enviar al frontend
    """
    try:
        from mplsoccer import PyPizza
    except ImportError:
        logger.error("mplsoccer no instalado. pip install mplsoccer")
        return ""

    # ── Configuración de métricas por posición ─────────────
    METRICS_CONFIG = {
        "FW": {
            "params": ["Goles",   "xG",     "npxG",   "Asist",  "xA",     "Disparos", "G/Sh", "xG Chain"],
            "keys":   ["goals",   "xG",     "npxG",   "assists","xA",     "shots",    "goals","xGChain"],
            "categorias": {"Ataque": [0,1,2,3], "Creación": [4,5,6], "Juego": [7]},
        },
        "MF": {
            "params": ["xA",      "Asist",  "Pases Clave","xGChain","xGBuildup","Goles","xG","G+A/90"],
            "keys":   ["xA",      "assists","key_passes", "xGChain","xGBuildup","goals","xG","goals"],
            "categorias": {"Creación": [0,1,2], "Juego": [3,4], "Ataque": [5,6,7]},
        },
        "DF": {
            "params": ["xGChain", "xGBuildup","Pases Clave","Asist","xA","Goles","xG","G+A/90"],
            "keys":   ["xGChain", "xGBuildup","key_passes","assists","xA","goals","xG","goals"],
            "categorias": {"Construcción": [0,1,2], "Creación": [3,4], "Ataque": [5,6,7]},
        },
        "GK": {
            "params": ["xG conc","Asist","xGChain","xGBuildup","Pases Clave","Goles","xA","G+A/90"],
            "keys":   ["xG",     "assists","xGChain","xGBuildup","key_passes","goals","xA","goals"],
            "categorias": {"Control": [0,1,2], "Construcción": [3,4], "Aportación": [5,6,7]},
        },
    }

    config = METRICS_CONFIG.get(position, METRICS_CONFIG["MF"])
    params = config["params"]
    keys   = config["keys"]
    categorias = config["categorias"]

    # ── Calcular percentiles reales ────────────────────────
    # Filtrar jugadores de la misma posición para comparar
    same_pos = [p for p in all_players if p.get("position", "") == position]
    if len(same_pos) < 5:
        same_pos = all_players  # fallback

    values = []
    for key in keys:
        player_val = float(player_data.get(key, 0) or 0)
        all_vals   = [float(p.get(key, 0) or 0) for p in same_pos]
        pct = calcular_percentiles(player_val, all_vals)
        values.append(pct)

    # ── Colores por categoría (tus colores originales) ─────
    if colores_categorias is None:
        colores_categorias = {
            "Ataque":       "#0ea5e9",   # Azul eléctrico Sportalyze
            "Creación":     "#3b82f6",
            "Posesión":     "#8b5cf6",
            "Defensa":      "#10b981",
            "Construcción": "#06b6d4",
            "Control":      "#6366f1",
            "Juego":        "#a855f7",
            "Aportación":   "#ec4899",
        }

    # Construir listas de colores slice/text por categoría
    slice_colors = []
    text_colors  = []
    for i in range(len(params)):
        color = "#0ea5e9"
        for cat_name, indices in categorias.items():
            if i in indices:
                color = colores_categorias.get(cat_name, "#0ea5e9")
                break
        slice_colors.append(color)
        text_colors.append("#FFFFFF")

    # ── Crear figura con PyPizza (TU CÓDIGO EXACTO) ────────
    fig, ax = plt.subplots(figsize=(8, 8), facecolor=VIZ_COLORS["bg"])
    ax.set_facecolor(VIZ_COLORS["bg"])

    baker = PyPizza(
        params=params,
        background_color=VIZ_COLORS["bg"],
        straight_line_color=VIZ_COLORS["bg"],
        straight_line_lw=1,
        last_circle_lw=0,
        other_circle_lw=0,
        inner_circle_size=20,
    )

    try:
        baker.make_pizza(
            values,
            ax=ax,
            color_blank_space="same",
            slice_colors=slice_colors,
            value_colors=text_colors,
            value_bck_colors=slice_colors,
            blank_alpha=0.4,
            kwargs_slices=dict(edgecolor=VIZ_COLORS["bg"], zorder=2, linewidth=1),
            kwargs_params=dict(color="#FFFFFF", fontsize=10, va="center",
                               path_effects=[path_effects.withStroke(linewidth=2, foreground=VIZ_COLORS["bg"])]),
            kwargs_values=dict(color="#FFFFFF", fontsize=9, zorder=3,
                               bbox=dict(edgecolor="none", facecolor="none",
                                         boxstyle="round,pad=0.2", lw=1)),
        )
    except AttributeError:
        # Fallback for newer matplotlib versions
        baker.make_pizza(
            values,
            ax=ax,
            color_blank_space="same",
            slice_colors=slice_colors,
            value_colors=text_colors,
            value_bck_colors=slice_colors,
            blank_alpha=0.4,
            kwargs_slices=dict(edgecolor=VIZ_COLORS["bg"], zorder=2, linewidth=1),
            kwargs_params=dict(color="#FFFFFF", fontsize=10, va="center"),
            kwargs_values=dict(color="#FFFFFF", fontsize=9, zorder=3),
        )

    # ── Títulos (igual que tu notebook) ───────────────────
    player_name = titulo_principal or player_data.get("name", "Jugador")
    subtitle    = titulo_secundario or f"{player_data.get('team', '')} · {position} · 2024/25"

    fig.text(0.515, 0.975, player_name, size=18, ha="center", color="#FFFFFF",
             fontweight="bold",
             path_effects=[path_effects.withStroke(linewidth=2, foreground=VIZ_COLORS["bg"])])
    fig.text(0.515, 0.953, subtitle, size=11, ha="center", color=VIZ_COLORS["text_dim"])

    # Leyenda de categorías
    handles = []
    for cat_name, indices in categorias.items():
        color = colores_categorias.get(cat_name, "#0ea5e9")
        handles.append(plt.Line2D([0], [0], color=color, linewidth=4,
                                  label=cat_name))
    ax.legend(handles=handles, loc="lower center", ncol=len(categorias),
              frameon=False, fontsize=8,
              labelcolor="white", bbox_to_anchor=(0.5, -0.08))

    # Créditos
    fig.text(0.99, 0.005, "SPORTALYZE", size=8, ha="right", color="#484f58")

    plt.tight_layout(pad=0.5)

    # ── Exportar a base64 ─────────────────────────────────
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=VIZ_COLORS["bg"], transparent=False)
    plt.close(fig)
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode("utf-8")
    return f"data:image/png;base64,{img_b64}"


def generar_radar_simple(
    player_data: dict,
    all_players: list,
    position: str = "FW",
) -> str:
    """
    Radar simple premium con matplotlib puro.
    Muestra percentiles como área coloreada + valor real como etiqueta.
    """
    import io, base64
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch

    metrics_cfg = {
        "FW": (["Goles","xG","Asist","npxG","G+A/90","Disparos"],
               ["goals","xG","assists","npxG","goals","shots"]),
        "MF": (["Goles","Asist","xGChain","Pases Clave","G+A/90","xG"],
               ["goals","assists","xGChain","key_passes","goals","xG"]),
        "DF": (["Goles","Asist","Minutos","xGChain","xGBuildup","G+A/90"],
               ["goals","assists","minutes","xGChain","xGBuildup","goals"]),
        "GK": (["Minutos","Rating","Goles","Asist","xG","G+A/90"],
               ["minutes","rating","goals","assists","xG","goals"]),
    }
    labels, keys = metrics_cfg.get(position, metrics_cfg["FW"])
    N = len(labels)

    # Jugadores misma posición para percentiles
    same_pos = [p for p in all_players if p.get("position","") == position]
    if len(same_pos) < 3:
        same_pos = all_players

    raw_vals = []
    percentiles = []
    for key in keys:
        pv = float(player_data.get(key, 0) or 0)
        all_vals = [float(p.get(key, 0) or 0) for p in same_pos]
        pct = sum(1 for v in all_vals if v <= pv) / max(len(all_vals), 1) * 100
        percentiles.append(round(pct, 1))
        raw_vals.append(round(pv, 1))

    # Ángulos
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]
    pcts_norm = [p / 100.0 for p in percentiles] + [percentiles[0] / 100.0]

    # Colores por posición
    colors = {
        "FW": ["#0ea5e9","#0ea5e9","#10b981","#10b981","#f59e0b","#f97316"],
        "MF": ["#0ea5e9","#10b981","#8b5cf6","#8b5cf6","#f59e0b","#0ea5e9"],
        "DF": ["#0ea5e9","#10b981","#0ea5e9","#8b5cf6","#8b5cf6","#f59e0b"],
        "GK": ["#0ea5e9","#f59e0b","#0ea5e9","#10b981","#8b5cf6","#f59e0b"],
    }
    seg_colors = colors.get(position, colors["FW"])

    bg = VIZ_COLORS["bg"]
    fig = plt.figure(figsize=(9, 9), facecolor=bg)
    ax = fig.add_subplot(111, polar=True, facecolor=bg)

    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_ylim(0, 1.15)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["25", "50", "75", "100"],
                       color="#4a5568", fontsize=8, fontweight="bold")
    ax.yaxis.set_tick_params(pad=30)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, color="#e2e8f0", fontsize=12, fontweight="bold")
    ax.tick_params(axis='x', pad=15)
    ax.grid(color="#1e3a4a", linewidth=0.8, linestyle="--", alpha=0.6)
    ax.spines["polar"].set_color("#1e3a4a")
    ax.spines["polar"].set_linewidth(1.5)

    # Fondo radial suave
    for r in [0.25, 0.5, 0.75, 1.0]:
        ax.plot(angles, [r] * len(angles), color="#1e3a4a",
                linewidth=0.5, alpha=0.4)

    # Área principal — relleno con gradiente simulado
    ax.fill(angles[:-1] + angles[:1], pcts_norm,
            color="#0ea5e9", alpha=0.15, zorder=2)

    # Líneas de segmento coloreadas
    for i in range(N):
        a1, a2 = angles[i], angles[(i+1) % N]
        r1, r2 = pcts_norm[i], pcts_norm[(i+1) % N]
        ax.plot([a1, a2], [r1, r2],
                color=seg_colors[i], linewidth=2.5,
                solid_capstyle='round', zorder=3)
        # Punto en el vértice
        ax.scatter([a1], [r1], s=60,
                   color=seg_colors[i], zorder=4,
                   edgecolors="white", linewidths=1.2)

    # Etiquetas de percentil (en el borde del área)
    for i, (angle, pct, raw) in enumerate(zip(angles[:-1], percentiles, raw_vals)):
        r_label = pcts_norm[i] + 0.12
        r_label = min(r_label, 1.12)
        # Etiqueta percentil
        ax.annotate(
            f"{int(pct)}",
            xy=(angle, r_label),
            ha="center", va="center",
            fontsize=9, fontweight="bold",
            color=seg_colors[i],
            bbox=dict(
                boxstyle="round,pad=0.25",
                facecolor=bg,
                edgecolor=seg_colors[i],
                linewidth=1.2,
                alpha=0.9
            ),
            zorder=5
        )

    # Título
    name = player_data.get("name", "Jugador")
    team = player_data.get("team", "")
    fig.text(0.5, 0.97, name, size=18, ha="center",
             color="#FFFFFF", fontweight="bold",
             fontfamily="DejaVu Sans")
    fig.text(0.5, 0.94,
             f"{team}  ·  {position}  ·  Percentiles vs {position} en la liga",
             size=10, ha="center", color="#7a9bbf")

    # Leyenda rápida abajo
    fig.text(0.5, 0.02,
             "Número = percentil (100 = mejor de la liga)  ·  SPORTALYZE",
             size=8, ha="center", color="#484f58")

    plt.tight_layout(pad=2.0)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=bg, transparent=False)
    plt.close(fig)
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.read()).decode()}"
