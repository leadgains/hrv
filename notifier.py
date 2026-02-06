"""Telegram notifications for the penny bot."""

import logging
try:
    import httpx
except ImportError:
    httpx = None

log = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)
        if not self.enabled:
            log.warning("Telegram notifications disabled (no token/chat_id)")

    async def send(self, message: str):
        if not self.enabled:
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient() as http:
                await http.post(url, json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                })
        except Exception as e:
            log.error(f"Telegram send failed: {e}")

    def send_sync(self, message: str):
        if not self.enabled:
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            with httpx.Client() as http:
                http.post(url, json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                })
        except Exception as e:
            log.error(f"Telegram send failed: {e}")
