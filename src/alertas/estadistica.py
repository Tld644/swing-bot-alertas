r"""Estadística histórica de cada tipo de alerta, sobre velas diarias de perpetuos de ~648 monedas
(las 637 del universo + las 11 de la investigación), 2019–2026. Usa EXACTAMENTE las mismas reglas que el escáner.

- Alertas de CIERRE (sobreventa, divergencias): retorno desde el cierre del día de la alerta.
- Alertas de TOQUE (Fibonacci 0,618/0,786, EMA 200/100 diaria, EMA 20 semanal): retorno desde el precio del
  nivel tocado ("si comprabas en el toque") y también desde el cierre de ese día (el peor caso realista).
- Referencia: un día cualquiera, cierre a cierre.

Uso:  .venv\Scripts\python.exe -m src.alertas.estadistica      (tarda varios minutos; se regenera cada tanto)
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.alertas.deteccion import (DER, _clasificar, _pivotes_confirmados, divergencia_alcista_activa,
                                   preparar_toques, toques)

RAIZ = Path(__file__).resolve().parents[2]
SALIDA = RAIZ / "data" / "alertas" / "estadisticas.json"
EVENTOS = RAIZ / "data" / "alertas" / "eventos.parquet"      # cada caso con su fecha (para filtrar por período)
BASE = RAIZ / "data" / "alertas" / "referencia.parquet"
HORIZONTES = (5, 10, 20, 30, 60)
# períodos alcistas definidos mirando hacia atrás
VENTANAS_ALCISTAS = (("2019-01-01", "2022-03-30"), ("2023-01-01", "2026-01-26"))


def en_alcista(t: pd.Series) -> pd.Series:
    m = pd.Series(False, index=t.index)
    for a, b in VENTANAS_ALCISTAS:
        m |= (t >= pd.Timestamp(a, tz="UTC")) & (t <= pd.Timestamp(b, tz="UTC") + pd.Timedelta(hours=23, minutes=59))
    return m


def archivos_diarios():
    u = sorted((RAIZ / "data" / "clean" / "universo").glob("velas_*_1d.parquet"))
    once = [RAIZ / "data" / "clean" / f"velas_{s}_1d.parquet" for s in
            json.loads((RAIZ / "config" / "datos.json").read_text(encoding="utf-8"))["universo_investigacion"]]
    return u + once


def eventos_divergencias(d):
    """Devuelve (eventos, activa_alcista): activa_alcista[i] es True si en la vela i hay una divergencia alcista
    en formación o confirmada en las últimas 5 velas (misma regla que divergencia_alcista_activa)."""
    o = d.rsi.to_numpy()
    n = len(d)
    ev = []
    formando, confirmada = np.zeros(n, bool), np.zeros(n, bool)
    for bajo in (True, False):
        piv = _pivotes_confirmados(o, n - 1, bajo)
        for k in range(1, len(piv)):                       # confirmadas (en j + 5)
            p, j = piv[k - 1], piv[k]
            cl = _clasificar(d, p, j, bajo, "confirmada", j + DER)
            ev += [(j + DER, a) for a in cl]
            if bajo and cl and j + DER < n:
                confirmada[j + DER] = True
        emitidas, ptr = set(), -1
        for i in range(n):                                  # en formación (primera vez por pivote previo)
            while ptr + 1 < len(piv) and piv[ptr + 1] <= i - DER:
                ptr += 1
            if ptr < 0:
                continue
            p = piv[ptr]
            for j in range(max(i - DER + 1, 5), i + 1):
                v, izq, der = o[j], o[j - 5:j], o[j + 1:i + 1]
                if np.isnan(v) or np.isnan(izq).any():
                    continue
                ok = (v < izq.min() and (len(der) == 0 or v <= der.min())) if bajo else \
                     (v > izq.max() and (len(der) == 0 or v >= der.max()))
                if ok:
                    cl = _clasificar(d, p, j, bajo, "formación", i)
                    if bajo and cl:
                        formando[i] = True
                    for a in cl:
                        if a["clave"] not in emitidas:
                            emitidas.add(a["clave"])
                            ev.append((i, a))
                    break
    conf5 = pd.Series(confirmada).rolling(5, min_periods=1).max().to_numpy().astype(bool)
    return ev, formando | conf5


def retornos(c, i, desde, prefijo):
    return {f"{prefijo}{h}": (c[i + h] / desde - 1) if i + h < len(c) else np.nan for h in HORIZONTES}


def resultado_fib(d, i, a):
    """Dentro de 20 días: ¿llegó primero al máximo del impulso o al 0,893? El mismo día del toque solo cuenta
    el 0,893 (conservador: no sabemos si el rebote vino antes)."""
    if d.low.iat[i] <= a["n893"]:
        return "stop"
    for j in range(i + 1, min(i + 21, len(d))):
        stop, tp = d.low.iat[j] <= a["n893"], d.high.iat[j] >= a["H"]
        if stop or tp:
            return "stop" if stop else "maximo"
    return "ninguno"


def agregar(ev: pd.DataFrame, base: pd.DataFrame) -> dict:
    """Resume eventos y referencia (ya filtrados por el período que se quiera)."""
    stats = {"referencia": {"n": len(base)}}
    for h in HORIZONTES:
        x = base[f"r{h}"].dropna()
        stats["referencia"] |= {f"sube_{h}d": float((x > 0).mean()), f"baja_{h}d": float((x < 0).mean()),
                                f"mediana_{h}d": float(x.median())}
    for (t, e), g in ev.groupby(["tipo", "estado"]):
        alc = "bajista" not in t
        st = {"n": len(g), "monedas": int(g.simbolo.nunique()), "direccion": "sube" if alc else "baja"}
        for h in HORIZONTES:
            x = g[f"r{h}"].dropna()
            st[f"a_favor_{h}d"] = float((x > 0).mean() if alc else (x < 0).mean())
            st[f"mediana_{h}d"] = float(x.median())
            if f"rc{h}" in g and g[f"rc{h}"].notna().any():
                y = g[f"rc{h}"].dropna()
                st[f"a_favor_cierre_{h}d"] = float((y > 0).mean())
                st[f"mediana_cierre_{h}d"] = float(y.median())
        if e == "formación":
            st["se_confirmo"] = float(g.se_confirmo.mean())
        if "fib" in g and g.fib.notna().any():
            st |= {"maximo_primero": float((g.fib == "maximo").mean()), "stop_primero": float((g.fib == "stop").mean()),
                   "ninguno_20d": float((g.fib == "ninguno").mean())}
        if "con_div" in g and g.con_div.notna().any():
            for etiqueta, sub in (("con_div", g[g.con_div == True]), ("sin_div", g[g.con_div == False])):  # noqa: E712
                st[etiqueta] = {"n": len(sub)} | {f"a_favor_{h}d": float((sub[f"r{h}"].dropna() > 0).mean())
                                                   if len(sub) else float("nan") for h in HORIZONTES}
        stats[f"{t}|{e}"] = st
    return stats


def main():
    filas, base = [], []
    for k, p in enumerate(archivos_diarios()):
        d = pd.read_parquet(p)
        vivo = d.index[d.volume > 0]                         # deslistadas: se recortan las velas "muertas"
        d = d.loc[:vivo.max()] if len(vivo) else d.iloc[:0]
        if len(d) < 260:
            continue
        d = preparar_toques(d.reset_index(drop=True))
        s = p.stem.split("_")[1]
        c = d.close.to_numpy()
        for i in range(250, len(d) - 1, 3):                  # referencia: un día cualquiera
            base.append({"t": d.open_time.iat[i]} | retornos(c, i, c[i], "r"))
        evs, div_activa = eventos_divergencias(d)
        r = d.rsi.to_numpy()
        for i in range(1, len(d)):
            if r[i] < 30 <= r[i - 1]:
                filas.append({"tipo": "sobreventa", "estado": "", "simbolo": s, "t": d.open_time.iat[i],
                              "con_div": bool(div_activa[i])} | retornos(c, i, c[i], "r"))
        confirmadas = {a["clave"] for _, a in evs if a["estado"] == "confirmada"}
        for i, a in evs:
            fila = {"tipo": a["tipo"], "estado": a["estado"], "simbolo": s, "t": d.open_time.iat[i]} | retornos(c, i, c[i], "r")
            if a["estado"] == "formación":
                fila["se_confirmo"] = a["clave"] in confirmadas
            filas.append(fila)
        for i in range(250, len(d)):
            for a in toques(d, i):
                fila = ({"tipo": a["tipo"], "estado": "", "simbolo": s, "t": d.open_time.iat[i]} | retornos(c, i, a["nivel"], "r")
                        | retornos(c, i, c[i], "rc"))
                if a["tipo"].startswith("toque fibonacci"):
                    fila["fib"] = resultado_fib(d, i, a)
                fila["con_div"] = bool(div_activa[i - 1])   # estado al cierre de ayer
                filas.append(fila)
        if k % 100 == 0:
            print(k, s, flush=True)

    base, ev = pd.DataFrame(base), pd.DataFrame(filas)
    base.to_parquet(BASE, index=False)
    ev.to_parquet(EVENTOS, index=False)
    stats = {"total": agregar(ev, base), "alcista": agregar(ev[en_alcista(ev.t)], base[en_alcista(base.t)])}
    SALIDA.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
