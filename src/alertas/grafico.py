"""Gráfico diario de una alerta (estilo TradingView): velas, EMA 50/100/200, EMA 20 semanal, niveles y RSI."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from src.alertas.deteccion import preparar_toques
from src.alertas.mensajes import fp

FONDO, TEXTO, GRILLA = "#131722", "#d1d4dc", "#2a2e39"
VERDE, ROJO, AZUL, NARANJA, VIOLETA = "#26a69a", "#ef5350", "#2962ff", "#ff9800", "#b388ff"
VELAS = 150


def graficar(d_crudo: pd.DataFrame, a: dict, m: dict, ruta):
    d = preparar_toques(d_crudo)
    ini = max(0, len(d) - VELAS)
    v = d.iloc[ini:].reset_index(drop=True)
    x = np.arange(len(v))
    idx = lambda t: int(np.argmin(np.abs((v.open_time - pd.Timestamp(t)).dt.total_seconds().to_numpy())))

    fig, (ax, ar) = plt.subplots(2, 1, figsize=(13, 8), facecolor=FONDO, sharex=True,
                                 gridspec_kw={"height_ratios": [3, 1]})
    for e in (ax, ar):
        e.set_facecolor(FONDO)
        e.tick_params(colors=TEXTO)
        e.grid(color=GRILLA, lw=0.5)
        e.yaxis.tick_right()
        for sp in e.spines.values():
            sp.set_color(GRILLA)
    for i, r in v.iterrows():
        c = VERDE if r.close >= r.open else ROJO
        ax.plot([i, i], [r.low, r.high], color=c, lw=0.8)
        ax.add_patch(Rectangle((i - 0.35, min(r.open, r.close)), 0.7, max(abs(r.close - r.open), 1e-12), color=c))
    ax.plot(x, v.ema50, color=AZUL, lw=1, label="EMA 50")
    ax.plot(x, v.ema100, color="#e040fb", lw=1, ls="--", label="EMA 100")
    ax.plot(x, v.ema200, color=NARANJA, lw=1.2, label="EMA 200")
    ax.step(x, v.ema20s, where="post", color="#ffeb3b", lw=1, label="EMA 20 semanal")
    ar.plot(x, v.rsi, color=VIOLETA, lw=1.2)
    for nivel, col in ((70, ROJO), (50, GRILLA), (30, VERDE)):
        ar.axhline(nivel, color=col, lw=0.8, ls="--")
    ar.set_ylim(0, 100)

    if a["tipo"].startswith("toque EMA"):
        ax.axhline(a["nivel"], color="white", lw=1, ls=":")
        ax.text(len(v) + 0.5, a["nivel"], f"{a['tipo'].replace('toque ', '')} ({fp(a['nivel'])})",
                color="white", va="center", fontsize=8)
    elif a["tipo"].startswith("toque fibonacci"):
        xh = idx(a["H_t"]) if pd.Timestamp(a["H_t"]) >= v.open_time.iloc[0] else 0
        for nombre, y, col in (("0", a["H"], VERDE), ("0,618", a["n618"], NARANJA), ("0,786", a["n786"], NARANJA),
                               ("0,893", a["n893"], ROJO), ("1", a["L"], AZUL)):
            ax.hlines(y, xh, len(v) - 1, colors=col, lw=1)
            ax.text(len(v) + 0.5, y, f"{nombre} ({fp(y)})", color=col, va="center", fontsize=8)
        ax.axhspan(a["n786"], a["n618"], xmin=xh / (len(v) + 12), color=NARANJA, alpha=0.08)
    elif a["tipo"].startswith("divergencia"):
        col = VERDE if "alcista" in a["tipo"] else ROJO
        if pd.Timestamp(a["p_t"]) >= v.open_time.iloc[0]:
            xp, xj = idx(a["p_t"]), idx(a["j_t"])
            ax.plot([xp, xj], [a["precio_p"], a["precio_j"]], color=col, lw=2)
            ar.plot([xp, xj], [a["rsi_p"], a["rsi_j"]], color=col, lw=2)
        if a.get("invalidacion"):
            ax.axhline(a["invalidacion"], color="white", lw=1, ls=":")
            ax.text(len(v) + 0.5, a["invalidacion"], f"anula: {fp(a['invalidacion'])}", color="white", va="center", fontsize=8)
    else:
        ar.scatter([len(v) - 1], [v.rsi.iloc[-1]], color=VERDE, s=60, zorder=5)

    ticks = list(range(0, len(v), max(1, len(v) // 8)))
    ar.set_xticks(ticks, [v.open_time[i].strftime("%d/%m/%y") for i in ticks])
    ax.set_xlim(-1, len(v) + 12)
    ax.legend(loc="upper left", facecolor="#1e222d", edgecolor=GRILLA, labelcolor=TEXTO, fontsize=8)
    estado = f" ({a['estado']})" if a.get("estado") else ""
    en_curso = " (en curso)" if a["tipo"].startswith("toque") else ""
    tf = "4h" if a["tipo"].endswith("4h") else "diario"
    fmt_vela = "%d/%m/%Y %H:%M UTC" if tf == "4h" else "%d/%m/%Y"
    ax.set_title(f"{m['ticker']} · {a['tipo']}{estado} · {tf} · vela del {v.open_time.iloc[-1]:{fmt_vela}}{en_curso}",
                 color=TEXTO, fontsize=12, loc="left")
    ar.set_ylabel("RSI 14", color=TEXTO)
    fig.tight_layout()
    fig.savefig(ruta, dpi=100, facecolor=FONDO)
    plt.close(fig)
