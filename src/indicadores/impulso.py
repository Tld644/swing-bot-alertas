"""Impulso alcista para trazar el Fibonacci: ZigZag por múltiplo de ATR, solo con pivotes confirmados.

Se recorre vela a vela (causal: en la vela i solo se usa información hasta i inclusive).
- Mínimo de swing confirmado: después del mínimo candidato, un máximo posterior supera
  mínimo + k × ATR. Ese mínimo pasa a ser el nivel 1 del impulso (L).
- Máximo de swing confirmado: después del máximo candidato, un mínimo posterior perfora
  máximo − k × ATR. Solo sirve para que el ZigZag vuelva a buscar un mínimo nuevo.
- Máximo del impulso (H, nivel 0): el máximo más alto desde L hasta la vela actual.
- Impulso roto: alguna vela cerró por debajo de L. Queda roto hasta que se confirme un L nuevo.
"""
import numpy as np
import pandas as pd

from src.indicadores.basicos import atr as calc_atr


def impulsos(d: pd.DataFrame, k: float = 3.0, n_atr: int = 14) -> pd.DataFrame:
    hi, lo, cl = d["high"].to_numpy(), d["low"].to_numpy(), d["close"].to_numpy()
    a = calc_atr(d, n_atr).to_numpy()
    n = len(d)
    L = np.full(n, np.nan); H = np.full(n, np.nan)
    L_i = np.full(n, -1); H_i = np.full(n, -1)
    roto = np.zeros(n, dtype=bool)

    buscando = "minimo"
    cand, cand_i = np.inf, -1          # candidato a mínimo (o máximo, según lo que se busque)
    l_act, l_i = np.nan, -1            # último mínimo confirmado
    h_act, h_i = np.nan, -1            # máximo desde ese mínimo
    r = False
    for i in range(n):
        if not np.isnan(a[i]):
            if buscando == "minimo":
                if lo[i] < cand:
                    cand, cand_i = lo[i], i
                elif hi[i] >= cand + k * a[i]:
                    l_act, l_i, r = cand, cand_i, False
                    j = l_i + np.argmax(hi[l_i:i + 1])
                    h_act, h_i = hi[j], j
                    buscando = "maximo"
                    cand, cand_i = h_act, h_i
            else:
                if hi[i] > cand:
                    cand, cand_i = hi[i], i
                elif lo[i] <= cand - k * a[i]:
                    buscando = "minimo"
                    j = cand_i + 1 + np.argmin(lo[cand_i + 1:i + 1])
                    cand, cand_i = lo[j], j
        if l_i >= 0:
            if hi[i] > h_act:
                h_act, h_i = hi[i], i
            if cl[i] < l_act:
                r = True
        L[i], H[i], L_i[i], H_i[i], roto[i] = l_act, h_act, l_i, h_i, r

    t = d["open_time"].to_numpy()
    return pd.DataFrame({
        "imp_L": L, "imp_H": H,
        "imp_L_t": [t[x] if x >= 0 else pd.NaT for x in L_i],
        "imp_H_t": [t[x] if x >= 0 else pd.NaT for x in H_i],
        "imp_valido": (L_i >= 0) & ~roto & (H > L),
        "atr": a,
    }, index=d.index)
