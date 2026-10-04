"""Universo de las alertas: top 150 por capitalización (CoinGecko) que tienen par spot USDT en Binance,
excluyendo stablecoins, oro, fondos tokenizados, tokens de otros exchanges y versiones envueltas.
Se guarda en data/alertas/universo.json con la fecha, para que todas las corridas del día usen la misma lista."""
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
             "BNSOL", "RETH", "LBTC", "SOLVBTC", "JITOSOL", "MSOL", "EZETH", "RSETH", "TBTC"}
RENOMBRES = {"BTT": "BTTC"}   # ticker CoinGecko -> ticker en Binance


def es_stable(c):
    n, i = c["name"].lower(), c["id"]
    precio = c.get("current_price") or 0
    return 0.97 < precio < 1.03 and ("usd" in i or "usd" in n or "dollar" in n or "stable" in n
                                     or c["symbol"].upper() in ("DAI", "GHO"))


def construir(top=150):
    cg = requests.get("https://api.coingecko.com/api/v3/coins/markets",
                      params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": top, "page": 1}, timeout=30).json()
    info = requests.get(SPOT + "/api/v3/exchangeInfo", timeout=60).json()
    spot = {s["baseAsset"]: s["symbol"] for s in info["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"}
    precios = {x["symbol"]: float(x["price"]) for x in requests.get(SPOT + "/api/v3/ticker/price", timeout=60).json()}
    monedas, fuera = [], []
    for k, c in enumerate(cg, 1):
        tk = c["symbol"].upper()
        base = RENOMBRES.get(tk, tk)
        if tk in NO_CRIPTO or es_stable(c):
            continue
        if base in spot and c.get("current_price") and abs(precios[spot[base]] / c["current_price"] - 1) > 0.05:
            fuera.append({"puesto": k, "ticker": tk, "nombre": c["name"], "motivo": "precio no coincide (¿otro token con el mismo ticker?)"})
        elif base in spot:
            monedas.append({"puesto": k, "ticker": tk, "nombre": c["name"], "simbolo": spot[base]})
        else:
            fuera.append({"puesto": k, "ticker": tk, "nombre": c["name"]})
    datos = {"fecha_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "monedas": monedas, "sin_spot_binance": fuera}
    ARCHIVO.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return datos


def cargar():
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if ARCHIVO.exists():
        d = json.loads(ARCHIVO.read_text(encoding="utf-8"))
        if d["fecha_utc"] == hoy:
            return d
    return construir()
