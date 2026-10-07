"""Universo de las alertas: top 200 por capitalización (CoinGecko), excluyendo stablecoins, oro, fondos
tokenizados, tokens de otros exchanges y versiones envueltas, y con liquidez mínima: volumen PROMEDIO de los
últimos 30 días de al menos 5 millones de USD por día (decisión de 2026-10-05; el promedio evita que una moneda
entre y salga por un día puntual de mucho o poco movimiento). El volumen de cada día se guarda en
data/alertas/volumen_historial.json (carga inicial: src/alertas/semilla_volumen.py).

Fuente de precios de cada moneda, en este orden:
  1. spot de Binance (par contra USDT);
  2. si no tiene spot en Binance: perpetuo USDT de Bitget;
  3. si tampoco está en Bitget: perpetuo USDT de BingX.
(Binance Futuros no se puede usar desde los servidores de GitHub en EE.UU.: responde 451.)
En todos los casos se controla que el precio coincida con CoinGecko (±5%), para no confundir dos tokens
distintos con el mismo ticker. Se guarda en data/alertas/universo.json con la fecha del día."""
import json
from datetime import datetime, timedelta, timezone
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
TOP = 200
VOLUMEN_MINIMO = 5_000_000     # USD por día, promedio de DIAS_VOLUMEN días (volumen total de CoinGecko)
DIAS_VOLUMEN = 30
HISTORIAL = RAIZ / "data" / "alertas" / "volumen_historial.json"
CRITERIO = {"top": TOP, "volumen_minimo": VOLUMEN_MINIMO, "dias_promedio": DIAS_VOLUMEN,
            "fuentes": ["binance", "bitget", "bingx"]}


def volumen_promedio(cg: list) -> dict:
    """Agrega el volumen de hoy al historial, borra lo de más de 40 días y devuelve {id: promedio 30 días}.
    Una moneda sin historial (recién entrada al ranking) usa los días que haya, como mínimo el de hoy."""
    hist = json.loads(HISTORIAL.read_text(encoding="utf-8")) if HISTORIAL.exists() else {}
    hoy = datetime.now(timezone.utc)
    for c in cg:
        if c.get("total_volume") is not None:
            hist.setdefault(c["id"], {})[hoy.strftime("%Y-%m-%d")] = c["total_volume"]
    corte_borrar = (hoy - timedelta(days=40)).strftime("%Y-%m-%d")
    corte_prom = (hoy - timedelta(days=DIAS_VOLUMEN)).strftime("%Y-%m-%d")
    prom = {}
    for i, dias in list(hist.items()):
        dias = {d: v for d, v in dias.items() if d > corte_borrar}
        if not dias:
            del hist[i]
            continue
        hist[i] = dias
        ult = [v for d, v in dias.items() if d > corte_prom and v is not None]
        if ult:
            prom[i] = sum(ult) / len(ult)
    HISTORIAL.write_text(json.dumps(hist), encoding="utf-8")
    return prom


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


def construir(top=TOP):
    cg = requests.get("https://api.coingecko.com/api/v3/coins/markets",
                      params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": top, "page": 1}, timeout=30).json()
    fuentes = []
    for nombre, f in (("binance", _precios_binance), ("bitget", _precios_bitget), ("bingx", _precios_bingx)):
        try:
            fuentes.append((nombre, f()))
        except Exception:     # si un exchange no responde, se sigue con los demás
            fuentes.append((nombre, {}))
    prom = volumen_promedio(cg)
    monedas, fuera = [], []
    for k, c in enumerate(cg, 1):
        tk = c["symbol"].upper()
        if tk in NO_CRIPTO or es_stable(c):
            continue
        vol = prom.get(c["id"], c.get("total_volume") or 0)
        if vol < VOLUMEN_MINIMO:
            fuera.append({"puesto": k, "ticker": tk, "nombre": c["name"],
                          "motivo": f"volumen promedio {DIAS_VOLUMEN} días de {vol / 1e6:.1f} M USD (mínimo 5 M)"})
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
            elegido = {"puesto": k, "ticker": tk, "nombre": c["name"], "simbolo": simbolo, "fuente": nombre,
                       "volumen_30d": round(vol)}
            break
        if elegido:
            monedas.append(elegido)
        else:
            fuera.append({"puesto": k, "ticker": tk, "nombre": c["name"], "motivo": motivo})
    datos = {"fecha_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "criterio": CRITERIO,
             "monedas": monedas, "fuera": fuera}
    ARCHIVO.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return datos


def cargar():
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if ARCHIVO.exists():
        d = json.loads(ARCHIVO.read_text(encoding="utf-8"))
        if d["fecha_utc"] == hoy and d.get("criterio") == CRITERIO:   # si cambia el criterio, se rearma ya
            return d
    return construir()
