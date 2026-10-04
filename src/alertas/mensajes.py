"""Textos de los mensajes (HTML de Telegram). Datos, sin exageraciones: qué pasó, niveles y la estadística
comparada con un día cualquiera, en varios plazos."""
import html
import math

from src.alertas.estadistica import HORIZONTES


def fp(x):
    """Precio legible, con punto de miles y coma decimal."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    dec = 2 if abs(x) >= 1 else max(2, 3 - int(math.floor(math.log10(abs(x)))))
    return f"{x:,.{dec}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def fr(x):
    return f"{x:.1f}".replace(".", ",")


def fn(n):
    return f"{n:,}".replace(",", ".")


def pct(x, signo=False):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    return (f"{x:+.1%}" if signo else f"{x:.0%}").replace(".", ",")


def fecha(t):
    return f"{t:%d/%m}"


def _lectura(diff):
    if abs(diff) < 0.03:
        return "casi no se diferencia de un día cualquiera"
    if diff > 0:
        return f"algo mejor que un día cualquiera (+{diff * 100:.0f} puntos)"
    return f"PEOR que un día cualquiera ({diff * 100:.0f} puntos)"


def es_destacada(a):
    """Fibonacci + divergencia alcista: la combinación con mejor estadística (pedido de priorizarla)."""
    return a["tipo"].startswith("toque fibonacci") and bool(a.get("divergencias"))


def texto_estadistica(a, stats):
    """Estadística en texto, solo mercado alcista (sin comparación con un día cualquiera)."""
    clave = f"{a['tipo']}|{a.get('estado', '')}"
    al = stats["alcista"].get(clave)
    if not al:
        return ""
    palabra = "más arriba" if al["direccion"] == "sube" else "más abajo"
    toque = a["tipo"].startswith("toque")
    plazos = " · ".join(f"{h} día{'s' if h > 1 else ''} {pct(al[f'a_favor_{h}d'])}"
                        for h in al.get("horizontes", HORIZONTES))
    t = (f"📊 En mercado alcista ({fn(al['n'])} casos), el precio estuvo {palabra}"
         + (" (comprando en el nivel)" if toque else "") + f":\n{plazos}")
    if toque and "a_favor_cierre_5d" in al:
        t += (f"\nSi comprabas al cierre del día: {pct(al['a_favor_cierre_5d'])} a 5 días y "
              f"{pct(al['a_favor_cierre_10d'])} a 10 días.")
    if "maximo_primero" in al:
        t += (f"\nEn 20 días, llegó primero al máximo el {pct(al['maximo_primero'])} de las veces y primero "
              f"al 0,893 el {pct(al['stop_primero'])}.")
    if "se_confirmo" in al:
        t += f"\nDe las que empezaron a formarse así, se confirmaron el {pct(al['se_confirmo'])}."
    if a.get("divergencias"):
        d = a["divergencias"][0]
        estado = "en formación" if d["estado"] == "formación" else "confirmada"
        t += (f"\n\n➕ <b>Divergencia alcista {d['tipo'].replace('divergencia alcista ', '')} {estado}</b> "
              f"(precio {fp(d['precio_j'])} contra {fp(d['precio_p'])}, RSI {fr(d['rsi_j'])} contra {fr(d['rsi_p'])}).")
        cd, sd = al.get("con_div"), al.get("sin_div")
        if cd and sd and cd["n"] >= 30:
            t += (f"\nCON divergencia, el precio estuvo más arriba a 10 días el {pct(cd['a_favor_10d'])} de las veces "
                  f"({fn(cd['n'])} casos); SIN divergencia, el {pct(sd['a_favor_10d'])}.")
        elif cd:
            t += f"\nHubo solo {cd['n']} casos con esta combinación: muy pocos para sacar conclusiones."
    return t


def _min_precio(a):
    if "vela_4h_cerrada" in a:
        if a["vela_4h_cerrada"]:
            return f"Mínimo de la vela de 4h {fp(a['minimo'])}, cierre {fp(a['precio'])} (el toque fue antes del cierre de la vela)"
        return f"Mínimo de la vela de 4h hasta ahora {fp(a['minimo'])}, precio actual {fp(a['precio'])}"
    if a.get("dia_cerrado"):
        return f"Mínimo del día {fp(a['minimo'])}, cierre {fp(a['precio'])} (el toque fue antes del cierre diario)"
    return f"Mínimo de hoy hasta ahora {fp(a['minimo'])}, precio actual {fp(a['precio'])}"


def texto_alerta(m, a, stats):
    tk = html.escape(m["ticker"])
    tipo = a["tipo"]
    if tipo.startswith("toque fibonacci"):
        f = tipo.split()[-1].replace(".", ",")
        cuerpo = (f"🔷 <b>{tk} · tocó el {f} de Fibonacci</b> (impulso diario, tendencia alcista)\n\n"
                  f"Impulso: {fp(a['L'])} ({fecha(a['L_t'])}) a {fp(a['H'])} ({fecha(a['H_t'])})\n"
                  f"0 (máximo): {fp(a['H'])} · 0,618: {fp(a['n618'])} · 0,786: {fp(a['n786'])}\n"
                  f"0,893 (stop de referencia): {fp(a['n893'])} · 1: {fp(a['L'])}\n"
                  + _min_precio(a))
    elif tipo.startswith("toque EMA"):
        nombre = tipo.replace("toque ", "")
        cuerpo = (f"🟦 <b>{tk} · tocó la {nombre}</b> después de una suba\n\n"
                  f"{nombre}: {fp(a['nivel'])}\n" + _min_precio(a))
        if tipo.endswith("4h"):
            cuerpo += "\n⏱ Señal de corto plazo: históricamente el efecto dura de 1 a 5 días."
    elif tipo == "sobreventa":
        cuerpo = f"🟢 <b>{tk} · RSI entró en sobreventa</b> (diario, al cierre)\n\nRSI {fr(a['rsi'])} (cruzó 30). Cierre {fp(a['cierre'])}."
    else:
        alc = "alcista" in tipo
        emoji = "🟢" if alc else "🔴"
        estado = "EN FORMACIÓN" if a["estado"] == "formación" else "CONFIRMADA"
        extremo = "mínimo" if alc else "máximo"
        cuerpo = (f"{emoji} <b>{tk} · {tipo.capitalize()} {estado}</b> (diario, al cierre)\n\n"
                  f"Precio: {extremo} {fp(a['precio_j'])} ({fecha(a['j_t'])}) contra {fp(a['precio_p'])} ({fecha(a['p_t'])})\n"
                  f"RSI: {fr(a['rsi_j'])} contra {fr(a['rsi_p'])} · cierre {fp(a['cierre'])}")
        if a["estado"] == "formación":
            dist = a["invalidacion"] / a["cierre"] - 1
            cuerpo += (f"\nSe anula con {a['invalidacion_texto']} {fp(a['invalidacion'])} "
                       f"({pct(dist, True)} desde el cierre). Se confirma si aguanta 5 velas desde el pivote.")
    if es_destacada(a):
        cuerpo = "⭐⭐⭐ <b>ALERTA DESTACADA: FIBONACCI + DIVERGENCIA ALCISTA</b> ⭐⭐⭐\n\n" + cuerpo
    return cuerpo + "\n\n" + texto_estadistica(a, stats)


def texto_resumen(fecha_vela, n_monedas, alertas, seguimientos, errores, es_cierre):
    if es_cierre:
        t = f"📋 <b>Resumen del cierre diario</b> · vela del {fecha_vela} · {n_monedas} monedas\n"
    else:
        t = f"⏱ <b>Toques de hoy</b> · {n_monedas} monedas\n"
    if not alertas and not seguimientos:
        t += "\nSin alertas nuevas."
    destacadas = [(m, a) for m, a, _ in alertas if es_destacada(a)]
    if destacadas:
        t += "\n⭐⭐⭐ <b>DESTACADAS (Fibonacci + divergencia alcista):</b>\n" + "\n".join(
            f"⭐ <b>{html.escape(m['ticker'])}</b>: {a['tipo']}" for m, a in destacadas) + "\n"
    resto = [(m, a) for m, a, _ in alertas if not es_destacada(a)]
    if resto:
        t += f"\n{len(resto)} alerta(s){' más' if destacadas else ''}:\n" + "\n".join(
            f"• {html.escape(m['ticker'])}: {a['tipo']}" + (f" ({a['estado']})" if a.get("estado") else "")
            + (" ➕ divergencia alcista" if a.get("divergencias") else "") for m, a in resto)
    if seguimientos:
        t += "\n\nSeguimiento de divergencias:\n" + "\n".join(
            f"• {html.escape(m['ticker'])}: {ab['tipo']} → {res}" for m, ab, res in seguimientos)
    if errores:
        t += f"\n\n⚠️ No se pudo leer: {html.escape(', '.join(e.split(':')[0] for e in errores))}"
    return t


def texto_seguimiento(m, ab, res):
    tk = html.escape(m["ticker"])
    if res == "confirmada":
        return f"✅ {tk} · la {ab['tipo']} que se estaba formando (aviso del {ab['fecha']}) se CONFIRMÓ."
    if res == "anulada":
        return (f"❌ {tk} · la {ab['tipo']} que se estaba formando (aviso del {ab['fecha']}) se ANULÓ "
                f"(nivel de invalidación: {fp(ab.get('invalidacion'))}).")
    return f"⌛ {tk} · la {ab['tipo']} en formación (aviso del {ab['fecha']}) venció sin resolverse."
