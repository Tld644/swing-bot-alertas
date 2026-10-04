r"""Estadística del toque de la EMA 200 en 4h (misma regla que el escáner: toque_ema200_4h).
Se suma a data/alertas/estadisticas.json bajo "toque EMA 200 4h|", con plazos cortos (1, 3, 5, 10 y 20 días).

Uso:  .venv\Scripts\python.exe -m src.alertas.estadistica_4h
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.alertas.deteccion import DIAS_ARRIBA, preparar_4h
from src.alertas.estadistica import SALIDA, en_alcista

RAIZ = Path(__file__).resolve().parents[2]
HORIZONTES_4H = (1, 3, 5, 10, 20)   # en días (6 velas de 4h por día)
CLAVE = "toque EMA 200 4h|"


def archivos_4h():
    u = sorted((RAIZ / "data" / "clean" / "universo").glob("velas_*_4h.parquet"))
    once = [RAIZ / "data" / "clean" / f"velas_{s}_4h.parquet" for s in
            json.loads((RAIZ / "config" / "datos.json").read_text(encoding="utf-8"))["universo_investigacion"]]
    return u + once


def eventos():
    filas = []
    for p in archivos_4h():
        d = pd.read_parquet(p, columns=["open_time", "open", "high", "low", "close", "volume"])
        vivo = d.index[d.volume > 0]                    # deslistadas: fuera las velas "muertas"
        d = d.loc[:vivo.max()] if len(vivo) else d.iloc[:0]
        if len(d) < 400:
            continue
        d = preparar_4h(d)
        c, lo, e, ar = d.close.to_numpy(), d.low.to_numpy(), d.ema200.to_numpy(), d.arriba200.to_numpy()
        # misma condición que toque_ema200_4h, vectorizada
        i = np.arange(250, len(d))
        ok = (ar[i - 1] == DIAS_ARRIBA) & (e[i - 1] > e[i - 21]) & (lo[i - 1] > e[i - 1]) & (lo[i] <= e[i - 1])
        for k in i[ok]:
            fila = {"simbolo": p.stem.split("_")[1], "t": d.open_time.iat[k]}
            for h in HORIZONTES_4H:
                j = k + 6 * h
                fila[f"r{h}"] = c[j] / e[k - 1] - 1 if j < len(c) else np.nan
                fila[f"rc{h}"] = c[j] / c[k] - 1 if j < len(c) else np.nan
            filas.append(fila)
    return pd.DataFrame(filas)


def resumir(g):
    st = {"n": len(g), "monedas": int(g.simbolo.nunique()), "direccion": "sube", "horizontes": list(HORIZONTES_4H)}
    for h in HORIZONTES_4H:
        x, y = g[f"r{h}"].dropna(), g[f"rc{h}"].dropna()
        st |= {f"a_favor_{h}d": float((x > 0).mean()), f"mediana_{h}d": float(x.median()),
               f"a_favor_cierre_{h}d": float((y > 0).mean()), f"mediana_cierre_{h}d": float(y.median())}
    return st


def main():
    ev = eventos()
    stats = json.loads(SALIDA.read_text(encoding="utf-8"))
    stats["total"][CLAVE] = resumir(ev)
    stats["alcista"][CLAVE] = resumir(ev[en_alcista(ev.t)])
    SALIDA.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats["alcista"][CLAVE], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
