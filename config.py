import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # Polymarket
    private_key: str = os.getenv("POLYMARKET_PRIVATE_KEY", "")
    funder: str = os.getenv("POLYMARKET_FUNDER", "")
    clob_url: str = "https://clob.polymarket.com"
    chain_id: int = 137

    # Telegram
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Penny strategy
    max_price_cents: int = int(os.getenv("MAX_PRICE_CENTS", "9"))
    min_price_cents: int = int(os.getenv("MIN_PRICE_CENTS", "1"))
    max_spend_per_trade: float = float(os.getenv("MAX_SPEND_PER_TRADE", "2.0"))
    total_budget: float = float(os.getenv("TOTAL_BUDGET", "10.0"))
    daily_loss_limit: float = float(os.getenv("DAILY_LOSS_LIMIT", "5.0"))
    check_interval: int = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))
    min_volume: int = int(os.getenv("MIN_VOLUME", "100"))
    min_liquidity: float = float(os.getenv("MIN_LIQUIDITY", "50"))
