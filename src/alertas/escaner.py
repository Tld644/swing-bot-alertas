r"""Escáner de alertas. Corre cada 30 minutos.

- TOQUES (cada corrida): Fibonacci 0,618/0,786, EMA 200/100 diaria y EMA 20 semanal, con niveles de velas ya
  cerradas y el mínimo del día en curso.
- CIERRE (solo cuando cerró una vela diaria nueva): sobreventa, divergencias, seguimiento de divergencias en
  formación, y el resumen del día. También revisa los toques del día que acaba de cerrar (por si fueron en los
  últimos minutos antes del cierre).

- Baja las velas diarias SPOT de Binance (data-api.binance.vision: funciona también desde servidores de EE.UU.)
  de las monedas del universo (src/alertas/universo.py).
- Detecta las alertas (src/alertas/deteccion.py) sobre la última vela CERRADA.
- Arma un mensaje resumen + un gráfico por alerta con su estadística histórica (data/alertas/estadisticas.json).
- Recuerda lo que ya avisó (data/alertas/estado.json) para no repetir y para avisar si una divergencia
  en formación se confirma o se anula.
- Envía por Telegram si hay TELEGRAM_TOKEN y TELEGRAM_CHAT_ID (variables de entorno o archivo .env).
  Si no, deja todo en salida_alertas/<fecha>/ para revisar.

Uso:  .venv\Scripts\python.exe -m src.alertas.escaner
"""
import json
from concurrent.futures import ThreadPoolExecutor
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from src.alertas import fuentes, universo
from src.alertas.deteccion import (divergencia_alcista_activa, escanear, preparar, preparar_4h, preparar_toques,
                                   toque_ema200_4h, toques)
from src.alertas.grafico import graficar
from src.alertas.mensajes import es_destacada, texto_alerta, texto_resumen, texto_seguimiento

RAIZ = Path(__file__).resolve().parents[2]
ESTADO = RAIZ / "data" / "alertas" / "estado.json"
STATS = RAIZ / "data" / "alertas" / "estadisticas.json"
SPOT = "https://data-api.binance.vision/api/v3/klines"
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"]
DIAS_FORMACION = 6   # una divergencia en formación que no se resolvió en 6 velas se da por vencida


def velas_diarias(simbolo: str, incluir_en_curso: bool = False, intervalo: str = "1d", limite: int = 1000) -> pd.DataFrame:
    for intento in range(4):
        r = requests.get(SPOT, params={"symbol": simbolo, "interval": intervalo, "limit": limite}, timeout=30)
        if r.status_code == 200:
            break
        time.sleep(2 ** intento)
    r.raise_for_status()
    d = pd.DataFrame(r.json(), columns=COLS).drop(columns="ignore")
    for c in ["open", "high", "low", "close", "volume", "quote_volume"]:
        d[c] = d[c].astype(float)
    d["open_time"] = pd.to_datetime(d.open_time, unit="ms", utc=True)
    d["close_time"] = pd.to_datetime(d.close_time, unit="ms", utc=True)
    if incluir_en_curso:
        return d.reset_index(drop=True)
    ahora = pd.Timestamp.now(tz="UTC")
    return d[d.close_time < ahora].reset_index(drop=True)   # solo velas cerradas


def credenciales():
    env = RAIZ / ".env"
    if env.exists():
        for linea in env.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.strip().startswith("#"):
                k, v = linea.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    return os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")


class Salida:
    """Envía a Telegram o, sin credenciales, guarda en una carpeta local."""

    def __init__(self, fecha):
        self.token, self.chat = credenciales()
        self.carpeta = RAIZ / "salida_alertas" / fecha
        self.log = []

    def texto(self, t):
        self.log.append(t)
        if self.token:
            requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                          data={"chat_id": self.chat, "text": t, "parse_mode": "HTML"}, timeout=30).raise_for_status()

    def foto(self, ruta, t):
        self.log.append(f"[{ruta.name}]\n{t}")
        if self.token:
            # el pie de foto admite 1024 caracteres: si no entra, la foto va con el título y el texto aparte
            pie = t if len(t) <= 1024 else t.split("\n")[0]
            with open(ruta, "rb") as f:
                requests.post(f"https://api.telegram.org/bot{self.token}/sendPhoto",
                              data={"chat_id": self.chat, "caption": pie, "parse_mode": "HTML"}, files={"photo": f},
                              timeout=60).raise_for_status()
            if pie != t:
                requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                              data={"chat_id": self.chat, "text": t, "parse_mode": "HTML"}, timeout=30).raise_for_status()

    def cerrar(self):
        if self.log:
            self.carpeta.mkdir(parents=True, exist_ok=True)
            (self.carpeta / "mensajes.txt").write_text("\n\n----------\n\n".join(self.log), encoding="utf-8")


def main():
    token, chat = credenciales()
    if os.environ.get("GITHUB_ACTIONS") == "true" and not (token and chat):
        # sin secretos cargados no se corre: si no, el estado marcaría alertas como enviadas sin haberlas mandado
        raise SystemExit("Faltan los secretos TELEGRAM_TOKEN / TELEGRAM_CHAT_ID en GitHub: no se corre el escáner.")
    uni = universo.cargar()
    stats = json.loads(STATS.read_text(encoding="utf-8"))
    estado = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}
    for k in ("enviadas", "abiertas", "cierres"):
        estado.setdefault(k, {})
    ahora = pd.Timestamp.now(tz="UTC")
    alertas, seguimientos, errores = [], [], []
    hubo_cierre, fecha_cierre = False, None

    def nueva(m, a, d):
        k = f"{m['simbolo']}|{a['clave']}|{a.get('estado', '')}"
        ya_en_formacion = a.get("estado") == "confirmada" and f"{m['simbolo']}|{a['clave']}|formación" in estado["enviadas"]
        if k in estado["enviadas"] or ya_en_formacion:
            return
        estado["enviadas"][k] = ahora.strftime("%Y-%m-%d %H:%M")
        alertas.append((m, a, d))
        if a.get("estado") == "formación":
            estado["abiertas"][k] = {"simbolo": m["simbolo"], "ticker": m["ticker"], "clave": a["clave"], "tipo": a["tipo"],
                                     "fecha": d.open_time.iloc[-1].strftime("%Y-%m-%d"), "invalidacion": a.get("invalidacion")}

    # descarga en paralelo (cada pedido tarda ~2 s; de a uno serían ~5 minutos por corrida)
    def bajar(m):
        out = {}
        for clave, limite in (("1d", 1000), ("4h", 500)):
            try:
                out[clave] = fuentes.velas(m, clave, limite)    # Binance spot, Bitget o BingX según la moneda
            except Exception as e:   # una moneda con problemas no frena al resto
                out[clave] = e
        return m["simbolo"], out

    with ThreadPoolExecutor(8) as ex:
        descargas = dict(ex.map(bajar, uni["monedas"]))

    for m in uni["monedas"]:
        todo = descargas[m["simbolo"]]["1d"]
        if isinstance(todo, Exception):
            errores.append(f"{m['ticker']}: {todo}")
            continue
        cerradas = todo[todo.close_time < ahora].reset_index(drop=True)
        if len(cerradas) < 260:
            continue
        ult = cerradas.open_time.iloc[-1].strftime("%Y-%m-%d")
        # divergencias alcistas activas: se calculan solo si hay una alerta a la que sumarlas (son lentas)
        cache = {}

        def divs(atras, _c=cerradas, _cache=cache):
            if atras not in _cache:
                if "dc" not in _cache:
                    _cache["dc"] = preparar(_c)
                dc = _cache["dc"]
                _cache[atras] = divergencia_alcista_activa(dc, len(dc) - 1 - atras)
            return _cache[atras]
        # ---- alertas de CIERRE: una vez por vela diaria nueva ----
        if estado["cierres"].get(m["simbolo"]) != ult:
            estado["cierres"][m["simbolo"]] = ult
            hubo_cierre, fecha_cierre = True, ult
            hoy = escanear(cerradas)
            claves_hoy = {(a["clave"], a.get("estado", "")) for a in hoy}
            for k, ab in list(estado["abiertas"].items()):
                if ab["simbolo"] != m["simbolo"]:
                    continue
                if (ab["clave"], "confirmada") in claves_hoy:
                    seguimientos.append((m, ab, "confirmada"))
                    del estado["abiertas"][k]
                elif (ab["clave"], "formación") not in claves_hoy:
                    vencida = (pd.Timestamp(ult) - pd.Timestamp(ab["fecha"])).days > DIAS_FORMACION
                    seguimientos.append((m, ab, "vencida" if vencida else "anulada"))
                    del estado["abiertas"][k]
            for a in hoy:
                if a["tipo"] == "fibonacci":           # Fibonacci va por toques durante el día
                    continue
                if a["tipo"].startswith("divergencia alcista"):
                    continue                           # las alcistas no avisan solas: acompañan a otras alertas
                if a["tipo"] == "sobreventa":
                    a["divergencias"] = divs(0)   # estado al último cierre
                nueva(m, a, cerradas)
            for a in toques(preparar_toques(cerradas)):   # toques del día que acaba de cerrar
                a["dia_cerrado"] = True
                a["divergencias"] = divs(1)   # para toques del día que acaba de cerrar
                nueva(m, a, cerradas)
        # ---- TOQUES de hoy (vela en curso) ----
        if len(todo) > len(cerradas):
            for a in toques(preparar_toques(todo)):
                a["divergencias"] = divs(0)   # estado al último cierre
                nueva(m, a, todo)
        # ---- TOQUE de la EMA 200 de 4h (vela en curso y la recién cerrada) ----
        crudo4 = descargas[m["simbolo"]]["4h"]
        if isinstance(crudo4, Exception):
            errores.append(f"{m['ticker']} 4h: {crudo4}")
            continue
        d4 = preparar_4h(crudo4)
        # se revisan todas las velas de 4h de las últimas 24 h: si GitHub atrasa corridas (pasó: huecos de 6-7 h),
        # ningún toque se pierde; los ya enviados no se repiten por el estado
        recientes = [i for i in range(len(d4)) if d4.open_time.iloc[i] >= ahora - pd.Timedelta(hours=24)]
        for i in recientes:
            cerrada = d4.close_time.iloc[i] < ahora
            a = toque_ema200_4h(d4, i)
            if a:
                a["vela_4h_cerrada"] = cerrada
                a["divergencias"] = divs(0)   # estado al último cierre
                nueva(m, a, d4.iloc[:i + 1])

    fecha = fecha_cierre or ahora.strftime("%Y-%m-%d")
    out = Salida(ahora.strftime("%Y-%m-%d_%H%M"))
    if hubo_cierre or alertas or seguimientos:
        out.texto(texto_resumen(fecha, len(uni["monedas"]), alertas, seguimientos, errores, hubo_cierre))
    for m, ab, res in seguimientos:
        out.texto(texto_seguimiento(m, ab, res))
    alertas.sort(key=lambda x: not es_destacada(x[1]))   # las destacadas primero
    for n, (m, a, d) in enumerate(alertas):
        out.carpeta.mkdir(parents=True, exist_ok=True)
        ruta = out.carpeta / f"{n:02d}_{m['ticker']}_{a['tipo'].replace(' ', '_')}.png"
        graficar(d, a, m, ruta)
        out.foto(ruta, texto_alerta(m, a, stats))
    out.cerrar()
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"{ahora:%Y-%m-%d %H:%M} UTC: cierre procesado={hubo_cierre}, {len(alertas)} alertas, "
          f"{len(seguimientos)} seguimientos, {len(errores)} errores. "
          f"{'Enviado a Telegram' if out.token else 'Guardado en ' + str(out.carpeta)}")


if __name__ == "__main__":
    main()
