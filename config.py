import os
from dotenv import load_dotenv

load_dotenv()

EXCHANGERATE_ACCESS_KEY = os.getenv("EXCHANGERATE_ACCESS_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not EXCHANGERATE_ACCESS_KEY:
    raise ValueError("EXCHANGERATE_ACCESS_KEY не задан в .env")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан в .env")
