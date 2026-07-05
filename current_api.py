"""Модуль для работы с api.exchangerate.host.

Используется только endpoint /convert с параметром access_key.
"""

import time

import requests
from dotenv import load_dotenv
import os

load_dotenv()

ACCESS_KEY = os.getenv("EXCHANGERATE_ACCESS_KEY")
BASE_URL = "http://api.exchangerate.host/convert"

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


def _make_request(params: dict) -> dict:
    """Отправляет запрос к api.exchangerate.host и возвращает JSON.

    При получении 429 (превышен лимит запросов) делает несколько
    повторных попыток с задержкой, прежде чем сообщить об ошибке.
    """
    if not ACCESS_KEY:
        raise RuntimeError("EXCHANGERATE_ACCESS_KEY не задан")

    params = {**params, "access_key": ACCESS_KEY}

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(BASE_URL, params=params, timeout=15)

            if response.status_code == 429:
                last_error = RuntimeError(
                    "Сервис курсов валют временно перегружен (превышен лимит запросов)."
                )
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS * attempt)
                    continue
                raise last_error

            response.raise_for_status()
            data = response.json()

            if not data.get("success", True):
                error = data.get("error", {})
                raise RuntimeError(
                    f"Ошибка API {error.get('code')}: {error.get('info', error)}"
                )

            return data

        except requests.exceptions.Timeout as e:
            last_error = RuntimeError("Сервис курсов валют не отвечает (таймаут).")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS * attempt)
                continue
            raise last_error from e

        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                "Не удалось подключиться к сервису курсов валют. Проверьте интернет-соединение."
            ) from e

        except requests.exceptions.HTTPError as e:
            raise RuntimeError(f"Сервис курсов валют вернул ошибку: {e}") from e

    # Сюда доходим только если все попытки исчерпаны из-за 429/таймаута
    raise last_error or RuntimeError("Не удалось получить ответ от сервиса курсов валют.")


def convert_currency(amount: float, from_currency: str, to_currency: str) -> float:
    """Конвертирует amount из from_currency в to_currency через /convert.

    Возвращает сконвертированную сумму (result).
    """
    if amount <= 0:
        raise ValueError("Сумма должна быть положительным числом")

    data = _make_request(
        {
            "from": from_currency.upper(),
            "to": to_currency.upper(),
            "amount": amount,
        }
    )

    result = data.get("result")
    if result is None:
        raise RuntimeError("API не вернул результат конвертации")

    return float(result)


def get_rate(from_currency: str, to_currency: str) -> float:
    """Возвращает текущий курс: сколько to_currency за 1 from_currency."""
    result = convert_currency(1.0, from_currency, to_currency)
    return result


if __name__ == "__main__":
    print("Курс RUB -> USD:", get_rate("RUB", "USD"))
    print("100 RUB -> USD:", convert_currency(100, "RUB", "USD"))
