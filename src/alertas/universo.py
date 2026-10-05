"""Universo de las alertas: top 150 por capitalización (CoinGecko), excluyendo stablecoins, oro, fondos
tokenizados, tokens de otros exchanges y versiones envueltas.

Fuente de precios de cada moneda, en este orden:
  1. spot de Binance (par contra USDT);
  2. si no tiene spot en Binance: perpetuo USDT de Bitget;
  3. si tampoco está en Bitget: perpetuo USDT de BingX.
(Binance Futuros no se puede usar desde los servidores de GitHub en EE.UU.: responde 451.)
En todos los casos se controla que el precio coincida con CoinGecko (±5%), para no confundir dos tokens
distintos con el mismo ticker. Se guarda en data/alertas/universo.json con la fecha del día."""
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parents[2]
ARCHIVO = RAIZ / "data" / "alertas" / "universo.json"
SPOT = "https://data-api.binance.vision"

NO_CRIPTO = {"PAXG", "XAUT", "KAU", "FIGR_HELOC", "USDY", "EURSAFO", "BCAP", "EUTBL", "JAAA", "YLDS", "JTRSY",
             "OUSG", "BUIDL", "USTB", "USYC", "USDTB", "HASH", "WBT", "LEO", "OKB", "HTX", "BGB", "GT", "KCS", "CRO",
             "EURC", "A7A5", "USDGO", "USD0", "APXUSD", "SOFID", "WBTC", "WETH", "STETH", "WSTETH", "WEETH", "CBBTC",
             "BNSOL", "RETH", "LBTC", "SOLVBTC", "JITOSOL", "MSOL", "EZETH", "RSETH", "TBTC", "USDT", "USDC"}
RENOMBRES = {"BTT": "BTTC"}   # ticker CoinGecko -> ticker en Binance
TOLERANCIA = 0.05


def es_stable(c):
    n, i = c["name"].lower(), c["id"]
    precio = c.get("current_price") or 0
    return 0.97 < precio < 1.03 and ("usd" in i or "usd" in n or "dollar" in n or "stable" in n or "tether" in n
                                     or c["symbol"].upper() in ("DAI", "GHO"))


def _precios_binance():
    info = requests.get(SPOT + "/api/v3/exchangeInfo", timeout=60).json()
    spot = {s["baseAsset"]: s["symbol"] for s in info["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"}
    px = {x["symbol"]: float(x["price"]) for x in requests.get(SPOT + "/api/v3/ticker/price", timeout=60).json()}
    return {b: (s, px.get(s)) for b, s in spot.items()}


def _precios_bitget():
    d = requests.get("https://api.bitget.com/api/v2/mix/market/tickers",
                     params={"productType": "USDT-FUTURES"}, timeout=60).json().get("data") or []
    return {x["symbol"][:-4]: (x["symbol"], float(x["lastPr"])) for x in d if x["symbol"].endswith("USDT")}


def _precios_bingx():
    d = requests.get("https://open-api.bingx.com/openApi/swap/v2/quote/ticker", timeout=60).json().get("data") or []
    return {x["symbol"][:-5]: (x["symbol"], float(x["lastPrice"])) for x in d if x["symbol"].endswith("-USDT")}


def construir(top=150):
    cg = requests.get("https://api.coingecko.com/api/v3/coins/markets",
                      params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": top, "page": 1}, timeout=30).json()
    fuentes = []
    for nombre, f in (("binance", _precios_binance), ("bitget", _precios_bitget), ("bingx", _precios_bingx)):
        try:
            fuentes.append((nombre, f()))
        except Exception:     # si un exchange no responde, se sigue con los demás
            fuentes.append((nombre, {}))
    monedas, fuera = [], []
    for k, c in enumerate(cg, 1):
        tk = c["symbol"].upper()
        if tk in NO_CRIPTO or es_stable(c):
            continue
        elegido, motivo = None, "no está en Binance spot, Bitget ni BingX"
        for nombre, tabla in fuentes:
            base = RENOMBRES.get(tk, tk) if nombre == "binance" else tk
            if base not in tabla:
                continue
            simbolo, precio = tabla[base]
            if c.get("current_price") and precio and abs(precio / c["current_price"] - 1) > TOLERANCIA:
                motivo = f"precio no coincide en {nombre} (¿otro token con el mismo ticker?)"
                continue
            elegido = {"puesto": k, "ticker": tk, "nombre": c["name"], "simbolo": simbolo, "fuente": nombre}
            break
        if elegido:
            monedas.append(elegido)
        else:
            fuera.append({"puesto": k, "ticker": tk, "nombre": c["name"], "motivo": motivo})
    datos = {"fecha_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "monedas": monedas, "fuera": fuera}
    ARCHIVO.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return datos


def cargar():
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if ARCHIVO.exists():
        d = json.loads(ARCHIVO.read_text(encoding="utf-8"))
        if d["fecha_utc"] == hoy and "fuera" in d:     # "fuera" = formato nuevo con Bitget/BingX
            return d
    return construir()
