# Escáner de alertas cripto

Revisa cada 15 minutos las principales criptomonedas (top 150 por capitalización; precios de Binance spot, o de los perpetuos de Bitget/BingX si no hay spot) y avisa
por Telegram cuando el precio toca niveles de Fibonacci o medias móviles después de una suba, y al cierre diario
cuando hay sobreventa o divergencias del RSI. Cada alerta trae un gráfico y la estadística histórica de esa situación.

No opera ni recomienda operar: es un radar. Las decisiones son de quien lo usa.

- Datos: Binance spot (`data-api.binance.vision`), perpetuos de Bitget y BingX, y CoinGecko.
- Credenciales: secretos `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` del repositorio (nunca en el código).
- Correr a mano: `python -m src.alertas.escaner`
