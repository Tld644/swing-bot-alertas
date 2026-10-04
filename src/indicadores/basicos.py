"""Indicadores calculados como TradingView (Pine ta.*), para que coincidan con lo que se ve en el gráfico.

- EMA y RMA arrancan con la SMA de las primeras n velas (igual que ta.ema / ta.rma).
- RSI: suavizado de Wilder (RMA) sobre las subas y bajas del cierre.
- ATR: RMA del true range.
"""
import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def _recursiva(s: pd.Series, n: int, alpha: float) -> pd.Series:
    x = s.to_numpy(dtype=float)
    out = np.full(len(x), np.nan)
    validos = np.flatnonzero(~np.isnan(x))
    if len(validos) < n:
        return pd.Series(out, index=s.index)
    ini = validos[0]
    semilla = ini + n - 1
    out[semilla] = x[ini:semilla + 1].mean()
    for i in range(semilla + 1, len(x)):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return pd.Series(out, index=s.index)


def ema(s: pd.Series, n: int) -> pd.Series:
    return _recursiva(s, n, 2 / (n + 1))


def rma(s: pd.Series, n: int) -> pd.Series:
    return _recursiva(s, n, 1 / n)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    cambio = close.diff()
    suba = rma(cambio.clip(lower=0).where(cambio.notna()), n)
    baja = rma((-cambio).clip(lower=0).where(cambio.notna()), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = 100 - 100 / (1 + suba / baja)
    r = r.where(suba != 0, 0.0).where(baja != 0, 100.0)   # como Pine: baja 0 da 100 primero
    return r.where(suba.notna())


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    cierre_prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - cierre_prev).abs(),
                    (df["low"] - cierre_prev).abs()], axis=1).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return rma(tr, n)


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """ADX de Wilder (como ta.dmi de TradingView): fuerza de la tendencia, sin dirección."""
    up = df["high"].diff()
    down = -df["low"].diff()
    dm_mas = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    dm_menos = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    dm_mas[up.isna()] = np.nan
    dm_menos[up.isna()] = np.nan
    a = atr(df, n)
    di_mas = 100 * rma(dm_mas, n) / a
    di_menos = 100 * rma(dm_menos, n) / a
    dx = 100 * (di_mas - di_menos).abs() / (di_mas + di_menos)
    return rma(dx, n)


def rsi_componentes(close: pd.Series, n: int = 14) -> tuple[pd.Series, pd.Series]:
    """Promedios de Wilder de subas y bajas (lo que usa el RSI por dentro)."""
    cambio = close.diff()
    suba = rma(cambio.clip(lower=0).where(cambio.notna()), n)
    baja = rma((-cambio).clip(lower=0).where(cambio.notna()), n)
    return suba, baja


def precio_para_rsi(cierre: float, suba: float, baja: float, rsi_objetivo: float, n: int = 14) -> float:
    """Cierre de la PRÓXIMA vela que deja el RSI exactamente en rsi_objetivo.
    Si el objetivo es menor al RSI actual, el precio sale por debajo del cierre (y viceversa)."""
    rs = rsi_objetivo / (100 - rsi_objetivo)
    if baja > 0 and suba / baja > rs:           # hay que bajar: cierre X < C
        return cierre - (n - 1) * (suba / rs - baja)
    return cierre + (n - 1) * (rs * baja - suba)   # hay que subir: cierre X > C
