import httpx

from app.core.config import get_settings

s = get_settings()
print(
    "telegram_enabled:",
    s.telegram_enabled,
    "| chat_id set:",
    bool(s.telegram_chat_id),
    "| token set:",
    bool(s.telegram_bot_token),
)
base = s.telegram_api_base_url.rstrip("/")
r = httpx.post(
    f"{base}/bot{s.telegram_bot_token}/sendMessage",
    json={
        "chat_id": s.telegram_chat_id,
        "text": "GerarAI: prueba de canal Telegram OK - stack completo operativo.",
    },
    timeout=15,
)
print("Telegram API:", r.status_code, r.json().get("ok"))