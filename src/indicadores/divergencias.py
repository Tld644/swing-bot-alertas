"""Divergencias alcistas del RSI, replicando la lógica del indicador RSI de TradingView
(opción "Calculate Divergence": lookback izquierdo 5, derecho 5, rango entre pivotes 5 a 60 velas).

- Pivote bajo del RSI en la vela j: el RSI de j es menor que el de las 5 velas anteriores y
  menor o igual que el de las 5 siguientes. Se CONFIRMA recién en la vela j + 5 (no antes).
- Divergencia regular: precio hace un mínimo más bajo (low[j] < low del pivote anterior) y el RSI
  un mínimo más alto.
- Divergencia oculta: precio hace un mínimo más alto y el RSI un mínimo más bajo.
- El pivote anterior tiene que estar entre 5 y 60 velas antes.
La señal queda marcada en la vela de confirmación (j + 5), junto con el mínimo de precio del pivote.
"""
import numpy as np
import pandas as pd


def divergencias_alcistas(low: pd.Series, osc: pd.Series, izq: int = 5, der: int = 5,
                          rango_min: int = 5, rango_max: int = 60) -> pd.DataFrame:
    lo, o = low.to_numpy(float), osc.to_numpy(float)
    n = len(o)
    regular = np.zeros(n, bool)
    oculta = np.zeros(n, bool)
    low_pivote = np.full(n, np.nan)
    prev_j = None
    for i in range(izq + der, n):
        j = i - der
        v = o[j]
        if np.isnan(v) or np.isnan(o[j - izq:i + 1]).any():
            continue
        if not (v < o[j - izq:j].min() and v <= o[j + 1:i + 1].min()):
            continue
        if prev_j is not None and rango_min <= j - prev_j <= rango_max:
            if lo[j] < lo[prev_j] and v > o[prev_j]:
                regular[i] = True
            if lo[j] > lo[prev_j] and v < o[prev_j]:
                oculta[i] = True
        if regular[i] or oculta[i]:
            low_pivote[i] = lo[j]
        prev_j = j
    return pd.DataFrame({"div_regular": regular, "div_oculta": oculta, "div_low": low_pivote}, index=low.index)
