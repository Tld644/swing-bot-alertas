"""Velas de cada fuente, todas en el mismo formato (open_time, open, high, low, close, volume, close_time,
quote_volume; tiempos en UTC; orden de la más vieja a la más nueva; la última puede ser la vela en curso).

- binance: spot de Binance (data-api.binance.vision, accesible desde los servidores de GitHub en EE.UU.).
- bitget:  perpetuos USDT de Bitget (para monedas sin spot en Binance). Velas diarias con corte 00:00 UTC.
- bingx:   perpetuos USDT de BingX (para las que tampoco están en Bitget).
Binance Futuros y Bybit bloquean las conexiones desde EE.UU. (probado desde GitHub el 05/10/2026).
"""
import time

import pandas as pd
import requests

BINANCE = "https://data-api.binance.vision/api/v3/klines"
BITGET = "https://api.bitget.com/api/v2/mix/market/"
BINGX = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
PASO = {"1d": pd.Timedelta(days=1), "4h": pd.Timedelta(hours=4)}
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume"]


def _get(url, params, intentos=4):
    for k in range(intentos):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(2 ** k)
    raise RuntimeError(f"No se pudo leer {url} {params}")


def _armar(filas, intervalo):
    """filas: lista de (open_ms, open, high, low, close, volume, quote_volume)."""
    d = pd.DataFrame(filas, columns=["open_time", "open", "high", "low", "close", "volume", "quote_volume"])
    for c in ["open", "high", "low", "close", "volume", "quote_volume"]:
        d[c] = d[c].astype(float)
    d["open_time"] = pd.to_datetime(d.open_time.astype("int64"), unit="ms", utc=True)
    d = d.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    d["close_time"] = d.open_time + PASO[intervalo] - pd.Timedelta(milliseconds=1)
    return d[COLS]


def _binance(simbolo, intervalo, limite):
    data = _get(BINANCE, {"symbol": simbolo, "interval": intervalo, "limit": limite})
    return _armar([(x[0], x[1], x[2], x[3], x[4], x[5], x[7]) for x in data], intervalo)


def _bitget(simbolo, intervalo, limite):
    base = {"symbol": simbolo, "productType": "USDT-FUTURES", "granularity": "1Dutc" if intervalo == "1d" else "4H"}
    filas = _get(BITGET + "candles", base | {"limit": 1000}).get("data") or []   # últimos ~90 días, con la vela en curso
    while filas and len(filas) < limite:                                       # más historia, de a tramos hacia atrás
        fin = min(int(x[0]) for x in filas)
        previas = [x for x in (_get(BITGET + "history-candles", base | {"limit": 200, "endTime": fin}).get("data") or [])
                   if int(x[0]) < fin]
        if not previas:
            break
        filas += previas
        time.sleep(0.15)
    return _armar([(x[0], x[1], x[2], x[3], x[4], x[5], x[6]) for x in filas], intervalo).tail(limite)


def _bingx(simbolo, intervalo, limite):
    data = _get(BINGX, {"symbol": simbolo, "interval": intervalo, "limit": min(limite, 1000)}).get("data") or []
    return _armar([(x["time"], x["open"], x["high"], x["low"], x["close"], x["volume"], float("nan")) for x in data],
                  intervalo)


def velas(moneda: dict, intervalo: str = "1d", limite: int = 1000) -> pd.DataFrame:
    fuente = moneda.get("fuente", "binance")
    f = {"binance": _binance, "bitget": _bitget, "bingx": _bingx}[fuente]
    return f(moneda["simbolo"], intervalo, limite).reset_index(drop=True)
