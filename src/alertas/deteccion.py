"""Detección de situaciones en velas DIARIAS cerradas. Todo se evalúa sobre la última vela cerrada.

A) Fibonacci: en tendencia alcista (EMA50 > EMA200 y EMA200 subiendo vs 20 días), el precio entra por
   PRIMERA vez en la zona 0,618–0,786 del impulso (ZigZag 3 × ATR, como la estrategia v1).
B1) RSI(14): entra en sobreventa (<30) ese día. (Sobrecompra desactivada.)
B2) Divergencias del RSI (lógica de TradingView: pivotes 5/5, 5 a 60 velas entre pivotes):
   - "en formación": el candidato a pivote está en las últimas 5 velas (todavía no se puede confirmar);
   - "confirmada": se cumplieron las 5 velas a la derecha.
   Regular alcista: precio mínimo más bajo y RSI mínimo más alto. Oculta alcista: precio más alto y RSI más bajo.
   Regular bajista: precio máximo más alto y RSI máximo más bajo. Oculta bajista: precio más bajo y RSI más alto.
   Invalidación (para la próxima vela): en las regulares, el cierre que llevaría el RSI al valor del pivote
   anterior; en las ocultas, el precio del pivote anterior.
"""
import numpy as np
import pandas as pd

from src.indicadores.basicos import ema, precio_para_rsi, rsi, rsi_componentes
from src.indicadores.impulso import impulsos

IZQ, DER, RANGO_MIN, RANGO_MAX = 5, 5, 5, 60


def preparar(d: pd.DataFrame) -> pd.DataFrame:
    d = d.reset_index(drop=True).copy()
    d["ema50"], d["ema200"] = ema(d.close, 50), ema(d.close, 200)
    d["tendencia"] = (d.ema50 > d.ema200) & (d.ema200 > d.ema200.shift(20))
    d["rsi"] = rsi(d.close, 14)
    d["suba"], d["baja"] = rsi_componentes(d.close, 14)
    return pd.concat([d, impulsos(d, 3.0, 14)], axis=1)


# ---------- A) Fibonacci ----------
def alerta_fibonacci(d: pd.DataFrame, i: int | None = None):
    i = len(d) - 1 if i is None else i
    r = d.iloc[i]
    if not (r.tendencia and r.imp_valido) or pd.isna(r.imp_H_t):
        return None
    if pd.Timestamp(r.imp_H_t) >= r.open_time:
        return None                                   # máximo y retroceso en la misma vela: no se sabe el orden
    H, L = r.imp_H, r.imp_L
    n618, n786, n893 = H - 0.618 * (H - L), H - 0.786 * (H - L), H - 0.893 * (H - L)
    desde_H = d[(d.open_time > r.imp_H_t) & (d.index < i)]
    if r.low > n618 or (len(desde_H) and desde_H.low.min() <= n618):
        return None                                   # no tocó la zona hoy, o ya la había tocado antes
    return {"tipo": "fibonacci", "clave": f"fib|{pd.Timestamp(r.imp_L_t):%Y-%m-%d}", "L": L, "H": H,
            "L_t": r.imp_L_t, "H_t": r.imp_H_t, "n618": n618, "n786": n786, "n893": n893,
            "cierre": r.close, "minimo": r.low, "rsi": r.rsi,
            "rb_618": 0.618 / (0.893 - 0.618), "rb_786": 0.786 / (0.893 - 0.786)}


# ---------- B1) sobrecompra / sobreventa ----------
def alerta_rsi_extremo(d: pd.DataFrame, i: int | None = None):
    i = len(d) - 1 if i is None else i
    r, a = d.rsi.iloc[i], d.rsi.iloc[i - 1]
    # sobrecompra (>70) desactivada (2026-10-03): el foco son los longs y en la historia
    # no se diferencia de un día cualquiera
    if r < 30 <= a:
        return {"tipo": "sobreventa", "clave": f"sv|{d.open_time.iloc[i]:%Y-%m-%d}", "rsi": r, "cierre": d.close.iloc[i]}
    return None


# ---------- B2) divergencias ----------
def _pivotes_confirmados(o: np.ndarray, hasta: int, bajo: bool):
    """Índices j de pivotes del RSI confirmados con datos hasta `hasta` (j + DER <= hasta)."""
    piv = []
    for j in range(IZQ, hasta - DER + 1):
        v, izq, der = o[j], o[j - IZQ:j], o[j + 1:j + DER + 1]
        if np.isnan(v) or np.isnan(izq).any() or np.isnan(der).any():
            continue
        if (bajo and v < izq.min() and v <= der.min()) or (not bajo and v > izq.max() and v >= der.max()):
            piv.append(j)
    return piv


def divergencias(d: pd.DataFrame, i: int | None = None) -> list[dict]:
    """Divergencias en formación y confirmadas en la vela i (por defecto, la última)."""
    i = len(d) - 1 if i is None else i
    o = d.rsi.to_numpy()
    out = []
    for bajo in (True, False):
        precio = (d.low if bajo else d.high).to_numpy()
        piv = _pivotes_confirmados(o, i, bajo)
        # confirmada hoy: el pivote j = i - DER se acaba de confirmar
        if piv and piv[-1] == i - DER and len(piv) >= 2:
            j, p = piv[-1], piv[-2]
            out += _clasificar(d, p, j, bajo, "confirmada", i)
        # en formación: candidato j en las últimas DER velas (sin las 5 de la derecha todavía)
        previos = [p for p in piv if p <= i - DER]
        if not previos:
            continue
        for j in range(max(i - DER + 1, IZQ), i + 1):
            v, izq, der = o[j], o[j - IZQ:j], o[j + 1:i + 1]
            if np.isnan(v) or np.isnan(izq).any():
                continue
            es_piv = (v < izq.min() and (len(der) == 0 or v <= der.min())) if bajo else \
                     (v > izq.max() and (len(der) == 0 or v >= der.max()))
            if es_piv:
                p = previos[-1]
                out += _clasificar(d, p, j, bajo, "formación", i)
                break
    return out


def _clasificar(d, p, j, bajo, estado, i):
    if not (RANGO_MIN <= j - p <= RANGO_MAX):
        return []
    o = d.rsi.to_numpy()
    pr = (d.low if bajo else d.high).to_numpy()
    res = []
    if bajo:
        if pr[j] < pr[p] and o[j] > o[p]:
            res.append("alcista regular")
        if pr[j] > pr[p] and o[j] < o[p]:
            res.append("alcista oculta")
    else:
        if pr[j] > pr[p] and o[j] < o[p]:
            res.append("bajista regular")
        if pr[j] < pr[p] and o[j] > o[p]:
            res.append("bajista oculta")
    alertas = []
    for t in res:
        a = {"tipo": f"divergencia {t}", "estado": estado, "p": p, "j": j,
             "p_t": d.open_time.iloc[p], "j_t": d.open_time.iloc[j],
             "precio_p": pr[p], "precio_j": pr[j], "rsi_p": o[p], "rsi_j": o[j],
             "cierre": d.close.iloc[i], "rsi": o[i],
             "clave": f"div|{t}|{d.open_time.iloc[p]:%Y-%m-%d}"}
        if estado == "formación":
            if "regular" in t:
                a["invalidacion"] = precio_para_rsi(d.close.iloc[i], d.suba.iloc[i], d.baja.iloc[i], o[p])
                a["invalidacion_texto"] = ("cierre diario por debajo de" if bajo else "cierre diario por encima de")
            else:
                a["invalidacion"] = pr[p]
                a["invalidacion_texto"] = ("precio por debajo de" if bajo else "precio por encima de")
        alertas.append(a)
    return alertas


def escanear(d: pd.DataFrame) -> list[dict]:
    """Todas las alertas de la última vela cerrada."""
    d = preparar(d)
    alertas = []
    for f in (alerta_fibonacci, alerta_rsi_extremo):
        a = f(d)
        if a:
            alertas.append(a)
    alertas += divergencias(d)
    return alertas


# ---------- C) TOQUES durante el día (se revisan cada 30 minutos) ----------
# Los niveles salen de velas YA CERRADAS (hasta ayer, o la última semana cerrada). Lo único que se mira de hoy
# es el mínimo del día hasta el momento: en vivo, el de la vela en curso; en la historia, el del día completo.
# Así la estadística y el bot usan exactamente la misma regla.
NIVELES_FIB = (0.618, 0.786)
EMAS_DIARIAS = (200, 100)
DIAS_ARRIBA = 30          # "venía subiendo": los últimos 30 cierres por encima de la media
SEMANAS_ARRIBA = 6


def preparar_toques(d: pd.DataFrame) -> pd.DataFrame:
    """Agrega columnas para los toques. La última fila puede ser el día en curso (incompleto)."""
    d = preparar(d)
    for n in EMAS_DIARIAS:
        e = ema(d.close, n)
        d[f"ema{n}"] = e
        d[f"arriba{n}"] = (d.close > e).astype(int).rolling(DIAS_ARRIBA).sum()
    # EMA 20 semanal: semanas de lunes a domingo; para un día vale la de la última semana CERRADA
    sem = d.set_index("open_time")[["close"]].resample("W-MON", label="left", closed="left").last().dropna()
    ew = ema(sem.close, 20)
    ok = (ew > ew.shift(4)) & ((sem.close > ew).astype(int).rolling(SEMANAS_ARRIBA).sum() == SEMANAS_ARRIBA)
    tabla = pd.DataFrame({"semana": sem.index + pd.Timedelta(days=7), "ema20s": ew.to_numpy(), "ok20s": ok.to_numpy()})
    d["semana"] = d.open_time.dt.floor("D") - pd.to_timedelta(d.open_time.dt.dayofweek, unit="D")
    d = d.merge(tabla, on="semana", how="left")   # la semana actual toma la EMA de la semana anterior (cerrada)
    return d


def toques(d: pd.DataFrame, i: int | None = None) -> list[dict]:
    """Toques del día i usando niveles conocidos al cierre de i-1 y el mínimo del día i."""
    i = len(d) - 1 if i is None else i
    if i < 1:
        return []
    hoy, ayer = d.iloc[i], d.iloc[i - 1]
    out = []
    # Fibonacci: impulso y tendencia al cierre de ayer; primer toque del nivel desde el máximo
    if ayer.tendencia and ayer.imp_valido and not pd.isna(ayer.imp_H_t):
        H, L = ayer.imp_H, ayer.imp_L
        previos = d[(d.open_time > ayer.imp_H_t) & (d.index < i)]
        for f in NIVELES_FIB:
            nivel = H - f * (H - L)
            if hoy.low <= nivel and (previos.empty or previos.low.min() > nivel):
                out.append({"tipo": f"toque fibonacci {f}", "clave": f"fib{f}|{pd.Timestamp(ayer.imp_L_t):%Y-%m-%d}",
                            "nivel": nivel, "L": L, "H": H, "L_t": ayer.imp_L_t, "H_t": ayer.imp_H_t,
                            "n618": H - 0.618 * (H - L), "n786": H - 0.786 * (H - L), "n893": H - 0.893 * (H - L),
                            "minimo": hoy.low, "precio": hoy.close})
    # EMA 200 / 100 diaria: venía 30 cierres arriba, media subiendo, ayer no la tocó, hoy sí
    for n in EMAS_DIARIAS:
        e = ayer[f"ema{n}"]
        if (ayer[f"arriba{n}"] == DIAS_ARRIBA and e > d[f"ema{n}"].iloc[i - 21] and ayer.low > e and hoy.low <= e):
            out.append({"tipo": f"toque EMA {n} diaria", "clave": f"ema{n}|{hoy.open_time:%Y-%m-%d}",
                        "nivel": e, "minimo": hoy.low, "precio": hoy.close})
    # EMA 20 semanal: semanas previas arriba y media subiendo; primer toque de la semana
    if hoy.ok20s is True or hoy.ok20s == 1.0:
        e = hoy.ema20s
        esta_semana = d[(d.semana == hoy.semana) & (d.index < i)]
        if hoy.low <= e and (esta_semana.empty or esta_semana.low.min() > e):
            out.append({"tipo": "toque EMA 20 semanal", "clave": f"ema20s|{hoy.semana:%Y-%m-%d}",
                        "nivel": e, "minimo": hoy.low, "precio": hoy.close})
    return out


def divergencia_alcista_activa(d: pd.DataFrame, i: int, dias: int = 5) -> list[dict]:
    """Divergencias alcistas (regular u oculta) en formación al cierre de la vela i, o confirmadas en las
    últimas `dias` velas. Se usan como confirmación de otras alertas, no como alerta sola."""
    vistas, out = set(), []
    for k in range(i, max(i - dias, 0), -1):
        for a in divergencias(d, k):
            if "alcista" not in a["tipo"] or a["clave"] in vistas:
                continue
            if a["estado"] == "formación" and k != i:
                continue                      # una "en formación" solo cuenta si sigue formándose hoy
            vistas.add(a["clave"])
            out.append(a)
    return out


# ---------- D) Toque de la EMA 200 en velas de 4h (señal de corto plazo) ----------
def preparar_4h(d4: pd.DataFrame) -> pd.DataFrame:
    d4 = d4.reset_index(drop=True).copy()
    d4["ema200"] = ema(d4.close, 200)
    d4["arriba200"] = (d4.close > d4.ema200).astype(int).rolling(DIAS_ARRIBA).sum()
    return d4


def toque_ema200_4h(d4: pd.DataFrame, i: int | None = None):
    """Vela de 4h i (puede estar en curso): las 30 velas previas cerraron sobre la EMA 200 de 4h, la media sube
    respecto de 20 velas atrás, la vela anterior no la tocó y la actual sí (con el nivel de la vela anterior)."""
    i = len(d4) - 1 if i is None else i
    if i < 21:
        return None
    ayer, hoy = d4.iloc[i - 1], d4.iloc[i]
    e = ayer.ema200
    if ayer.arriba200 == DIAS_ARRIBA and e > d4.ema200.iloc[i - 21] and ayer.low > e and hoy.low <= e:
        return {"tipo": "toque EMA 200 4h", "clave": f"ema200_4h|{hoy.open_time:%Y-%m-%d %H}",
                "nivel": e, "minimo": hoy.low, "precio": hoy.close}
    return None
