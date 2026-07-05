"""Telegram-бот «миникошелёк для путешественника».

Использует pyTelegramBotAPI (telebot), SQLite для хранения данных
и api.exchangerate.host/convert для курсов валют.
"""

import re
from typing import Optional

import telebot
from telebot import types
from telebot import ExceptionHandler

from config import TELEGRAM_TOKEN
from current_api import convert_currency, get_rate
from database import TravelDB


class BotExceptionHandler(ExceptionHandler):
    """Логирует необработанные исключения, но не даёт боту упасть."""

    def handle(self, exception: Exception) -> bool:
        print(f"[Необработанная ошибка] {exception}")
        return True  # исключение считается обработанным, polling продолжается


bot = telebot.TeleBot(TELEGRAM_TOKEN, exception_handler=BotExceptionHandler())
db = TravelDB()

# ---------- Состояния пользователей ----------
STATE_MAIN = "main"
STATE_WAIT_DEPARTURE = "wait_departure"
STATE_WAIT_DESTINATION = "wait_destination"
STATE_WAIT_RATE_CONFIRM = "wait_rate_confirm"
STATE_WAIT_MANUAL_RATE = "wait_manual_rate"
STATE_WAIT_HOME_AMOUNT = "wait_home_amount"
STATE_WAIT_EXPENSE_CONFIRM = "wait_expense_confirm"
STATE_WAIT_NEW_RATE = "wait_new_rate"

user_states: dict[int, str] = {}
# Временные данные для создаваемого путешествия / расхода
user_data: dict[int, dict] = {}

# ---------- Карта страна -> валюта ----------
COUNTRY_CURRENCIES = {
    "россия": "RUB",
    "русская": "RUB",
    "рус": "RUB",
    "сша": "USD",
    "америка": "USD",
    "штаты": "USD",
    "китай": "CNY",
    "кнр": "CNY",
    "германия": "EUR",
    "франция": "EUR",
    "италия": "EUR",
    "испания": "EUR",
    "европа": "EUR",
    "великобритания": "GBP",
    "англия": "GBP",
    "британия": "GBP",
    "япония": "JPY",
    "турция": "TRY",
    "тайланд": "THB",
    "таиланд": "THB",
    "индия": "INR",
    "узбекистан": "UZS",
    "казахстан": "KZT",
    "беларусь": "BYN",
    "белоруссия": "BYN",
    "армения": "AMD",
    "грузия": "GEL",
    "египет": "EGP",
    "оаэ": "AED",
    "дубай": "AED",
    "абу-даби": "AED",
    "украина": "UAH",
    "молдова": "MDL",
    "азербайджан": "AZN",
    "киргизия": "KGS",
    "кыргызстан": "KGS",
    "таджикистан": "TJS",
    "вьетнам": "VND",
    "корея": "KRW",
    "австралия": "AUD",
    "канада": "CAD",
    "швейцария": "CHF",
    "швеция": "SEK",
    "норвегия": "NOK",
    "дания": "DKK",
    "польша": "PLN",
    "чехия": "CZK",
    "венгрия": "HUF",
    "румыния": "RON",
    "болгария": "BGN",
    "хорватия": "HRK",
    "сербия": "RSD",
    "израиль": "ILS",
    "марокко": "MAD",
    "тунис": "TND",
    "мексика": "MXN",
    "бразилия": "BRL",
    "аргентина": "ARS",
    "чили": "CLP",
    "перу": "PEN",
    "колумбия": "COP",
    "юар": "ZAR",
    "сингапур": "SGD",
    "гонконг": "HKD",
    "индонезия": "IDR",
    "малайзия": "MYR",
    "филиппины": "PHP",
    "шри-ланка": "LKR",
    "пакистан": "PKR",
    "бангладеш": "BDT",
    "непал": "NPR",
    "камбоджа": "KHR",
    "лаос": "LAK",
    "мьянма": "MMK",
    "монголия": "MNT",
}


# ---------- Вспомогательные функции ----------

def get_currency_by_country(text: str) -> Optional[str]:
    """Определяет валюту по названию страны."""
    text = text.strip().lower()
    return COUNTRY_CURRENCIES.get(text)


def _to_float(text: str) -> Optional[float]:
    """Парсит положительное число из строки."""
    text = text.replace(" ", "").replace(",", ".").strip()
    try:
        value = float(text)
        return value if value > 0 else None
    except ValueError:
        return None


def format_money(amount: float, currency: str = "") -> str:
    """Форматирует сумму с разделителем тысяч."""
    formatted = f"{amount:,.2f}".replace(",", " ")
    return f"{formatted} {currency}".strip()


def format_balance(trip: dict) -> str:
    return (
        f"💰 Остаток: {format_money(trip['dest_balance'], trip['dest_currency'])} "
        f"= {format_money(trip['home_balance'], trip['home_currency'])}"
    )


def convert_dest_to_home(amount_dest: float, trip: dict) -> float:
    """Конвертирует сумму из валюты пребывания в домашнюю."""
    try:
        return convert_currency(
            amount_dest,
            trip["dest_currency"],
            trip["home_currency"],
        )
    except Exception:
        # rate = сколько dest за 1 home → home = dest / rate
        return amount_dest / trip["rate"]


def main_menu_markup() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✈️ Создать новое путешествие", callback_data="menu_new_trip"),
        types.InlineKeyboardButton("🗺️ Мои путешествия", callback_data="menu_my_trips"),
        types.InlineKeyboardButton("💰 Баланс", callback_data="menu_balance"),
        types.InlineKeyboardButton("📋 История расходов", callback_data="menu_history"),
        types.InlineKeyboardButton("💱 Изменить курс", callback_data="menu_set_rate"),
    )
    return markup


def send_main_menu(chat_id: int, text: str = "📋 Главное меню") -> None:
    bot.send_message(chat_id, text, reply_markup=main_menu_markup())


# ---------- Команды ----------

@bot.message_handler(commands=["start"])
def cmd_start(message: types.Message) -> None:
    user_id = message.from_user.id
    user_states[user_id] = STATE_MAIN
    user_data[user_id] = {}
    bot.send_message(
        message.chat.id,
        "👋 Привет! Я твой миникошелёк для путешествий.\n\n"
        "Создай новое путешествие — и я буду конвертировать расходы "
        "в твою домашнюю валюту.\n\n"
        "💡 Отправляйте суммы расходов числом — я предложу учесть их.",
        reply_markup=main_menu_markup(),
    )


@bot.message_handler(commands=["newtrip"])
def cmd_newtrip(message: types.Message) -> None:
    start_new_trip(message.chat.id, message.from_user.id)


@bot.message_handler(commands=["switch"])
def cmd_switch(message: types.Message) -> None:
    show_trips(message.chat.id, message.from_user.id)


@bot.message_handler(commands=["balance"])
def cmd_balance(message: types.Message) -> None:
    show_balance(message.chat.id, message.from_user.id)


@bot.message_handler(commands=["history"])
def cmd_history(message: types.Message) -> None:
    show_history(message.chat.id, message.from_user.id)


@bot.message_handler(commands=["setrate"])
def cmd_setrate(message: types.Message) -> None:
    start_set_rate(message.chat.id, message.from_user.id)


# ---------- Обработка текста ----------

@bot.message_handler(
    content_types=[
        "photo", "video", "sticker", "document", "voice",
        "audio", "location", "contact", "video_note", "animation",
    ]
)
def handle_non_text(message: types.Message) -> None:
    bot.send_message(
        message.chat.id,
        "📎 Я понимаю только текст и числа.\n"
        "Введите сумму расхода или выберите действие в меню.",
        reply_markup=main_menu_markup(),
    )


@bot.message_handler(content_types=["text"])
def handle_text(message: types.Message) -> None:
    user_id = message.from_user.id
    state = user_states.get(user_id, STATE_MAIN)
    text = message.text.strip()

    if state == STATE_WAIT_DEPARTURE:
        handle_departure(message)
    elif state == STATE_WAIT_DESTINATION:
        handle_destination(message)
    elif state == STATE_WAIT_MANUAL_RATE:
        handle_manual_rate(message)
    elif state == STATE_WAIT_HOME_AMOUNT:
        handle_home_amount(message)
    elif state == STATE_WAIT_NEW_RATE:
        handle_new_rate(message)
    elif state == STATE_WAIT_EXPENSE_CONFIRM:
        if re.match(r"^\d+([.,]\d+)?$", text.replace(" ", "")):
            handle_expense(message)
        else:
            bot.send_message(
                message.chat.id,
                "⏳ Ожидаю подтверждение расхода — нажмите ✅ Да или ❌ Нет.\n"
                "Или введите новую сумму, чтобы пересчитать.",
            )
    elif state == STATE_MAIN:
        # В главном меню любое число — расход
        if re.match(r"^\d+([.,]\d+)?$", text.replace(" ", "")):
            handle_expense(message)
        else:
            bot.send_message(
                message.chat.id,
                "🤔 Не понял. Введите сумму расхода числом или выберите действие в меню.",
                reply_markup=main_menu_markup(),
            )
    else:
        bot.send_message(
            message.chat.id,
            "Давайте завершим текущее действие. Используйте меню, если запутались.",
            reply_markup=main_menu_markup(),
        )


# ---------- Логика создания путешествия ----------

def start_new_trip(chat_id: int, user_id: int) -> None:
    user_states[user_id] = STATE_WAIT_DEPARTURE
    user_data[user_id] = {}
    bot.send_message(
        chat_id,
        "✈️ Создание нового путешествия\n\n"
        "🌍 Введите страну отправления (например, Россия):",
    )


def handle_departure(message: types.Message) -> None:
    user_id = message.from_user.id
    country = message.text.strip()
    currency = get_currency_by_country(country)

    if not currency:
        bot.send_message(
            message.chat.id,
            "❌ Не удалось определить валюту для этой страны.\n"
            "Попробуйте другое название (например: Россия, Китай, Турция).",
        )
        return

    user_data[user_id]["home_country"] = country
    user_data[user_id]["home_currency"] = currency
    user_states[user_id] = STATE_WAIT_DESTINATION
    bot.send_message(
        message.chat.id,
        f"✅ Валюта отправления: {currency}\n\n"
        f"🌍 Теперь введите страну назначения:",
    )


def handle_destination(message: types.Message) -> None:
    user_id = message.from_user.id
    country = message.text.strip()
    currency = get_currency_by_country(country)

    if not currency:
        bot.send_message(
            message.chat.id,
            "❌ Не удалось определить валюту для этой страны.\n"
            "Попробуйте другое название (например: Китай, Турция, Япония).",
        )
        return

    home_currency = user_data[user_id]["home_currency"]
    if currency == home_currency:
        bot.send_message(
            message.chat.id,
            "⚠️ Валюты отправления и назначения совпадают.\n"
            "Введите другую страну назначения.",
        )
        return

    bot.send_message(message.chat.id, "⏳ Запрашиваю текущий курс...")
    try:
        rate = get_rate(home_currency, currency)
    except RuntimeError as e:
        bot.send_message(
            message.chat.id,
            f"⚠️ Не удалось получить курс: {e}\n\n"
            "Введите курс вручную на следующем шаге.",
        )
        rate = None
    except Exception as e:
        bot.send_message(
            message.chat.id,
            f"❌ Ошибка при обращении к API: {e}",
            reply_markup=main_menu_markup(),
        )
        user_states[user_id] = STATE_MAIN
        return

    user_data[user_id]["dest_country"] = country
    user_data[user_id]["dest_currency"] = currency
    user_data[user_id]["rate"] = rate

    if rate is None:
        # Если API не ответил — сразу просим ввести курс вручную
        user_states[user_id] = STATE_WAIT_MANUAL_RATE
        bot.send_message(
            message.chat.id,
            "💱 Введите курс обмена вручную\n"
            f"(сколько {currency} за 1 {home_currency}, например 0.088):",
        )
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Да", callback_data="rate_yes"),
        types.InlineKeyboardButton("❌ Нет", callback_data="rate_no"),
    )
    bot.send_message(
        message.chat.id,
        f"💱 Текущий курс:\n"
        f"1 {home_currency} = {rate:.4f} {currency}\n\n"
        f"Подходит?",
        reply_markup=markup,
    )
    user_states[user_id] = STATE_WAIT_RATE_CONFIRM


@bot.callback_query_handler(func=lambda call: call.data == "rate_yes")
def callback_rate_yes(call: types.CallbackQuery) -> None:
    user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    user_states[user_id] = STATE_WAIT_HOME_AMOUNT
    bot.send_message(
        call.message.chat.id,
        f"💰 Введите начальную сумму в {user_data[user_id].get('home_currency', 'домашней валюте')}:",
    )


@bot.callback_query_handler(func=lambda call: call.data == "rate_no")
def callback_rate_no(call: types.CallbackQuery) -> None:
    user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    user_states[user_id] = STATE_WAIT_MANUAL_RATE
    bot.send_message(
        call.message.chat.id,
        "💱 Введите курс обмена вручную\n"
        "(сколько единиц валюты назначения за 1 единицу домашней):",
    )


def handle_manual_rate(message: types.Message) -> None:
    user_id = message.from_user.id
    rate = _to_float(message.text)
    if rate is None:
        bot.send_message(message.chat.id, "Введите положительное число, например 13.5.")
        return

    data = user_data.get(user_id)
    if not data or "home_currency" not in data or "dest_currency" not in data:
        bot.send_message(
            message.chat.id,
            "Сессия создания путешествия была потеряна. Начните заново.",
            reply_markup=main_menu_markup(),
        )
        user_states[user_id] = STATE_MAIN
        return

    data["rate"] = rate
    user_states[user_id] = STATE_WAIT_HOME_AMOUNT
    bot.send_message(
        message.chat.id,
        f"💰 Введите начальную сумму в {data['home_currency']}:",
    )


def handle_home_amount(message: types.Message) -> None:
    user_id = message.from_user.id
    amount = _to_float(message.text)
    if amount is None:
        bot.send_message(message.chat.id, "Введите положительное число.")
        return

    data = user_data.get(user_id) or {}
    if "home_currency" not in data or "dest_currency" not in data:
        bot.send_message(
            message.chat.id,
            "Сессия создания путешествия была потеряна. Начните заново.",
            reply_markup=main_menu_markup(),
        )
        user_states[user_id] = STATE_MAIN
        return

    home_currency = data["home_currency"]
    dest_currency = data["dest_currency"]
    rate = data["rate"]

    if rate is None:
        bot.send_message(
            message.chat.id,
            "Не удалось определить курс. Создание путешествия отменено.",
            reply_markup=main_menu_markup(),
        )
        user_states[user_id] = STATE_MAIN
        return

    # Конвертируем начальную сумму через API или по сохранённому курсу
    try:
        dest_amount = convert_currency(amount, home_currency, dest_currency)
    except Exception as e:
        # Если API не отвечает, используем сохранённый курс
        dest_amount = amount * rate
        bot.send_message(
            message.chat.id,
            f"Не удалось уточнить сумму через API ({e}), использую сохранённый курс.",
        )

    trip_name = data["dest_country"]
    trip_id = db.create_trip(
        user_id=user_id,
        name=trip_name,
        home_currency=home_currency,
        dest_currency=dest_currency,
        rate=rate,
        home_balance=amount,
        dest_balance=dest_amount,
    )

    user_states[user_id] = STATE_MAIN
    bot.send_message(
        message.chat.id,
        f"🎉 Путешествие создано!\n\n"
        f"📍 Валютная пара: {home_currency} → {dest_currency}\n"
        f"💱 Курс: 1 {home_currency} = {rate:.4f} {dest_currency}\n"
        f"💰 Стартовый баланс: {format_money(amount, home_currency)} "
        f"= {format_money(dest_amount, dest_currency)}\n\n"
        f"Отправляйте суммы расходов числом — я буду конвертировать и предлагать учесть их.",
        reply_markup=main_menu_markup(),
    )


# ---------- Расходы ----------

def handle_expense(message: types.Message) -> None:
    user_id = message.from_user.id
    trip = db.get_active_trip(user_id)

    if not trip:
        bot.send_message(
            message.chat.id,
            "⚠️ Нет активного путешествия.\n"
            "Создайте новое или выберите существующее в меню.",
            reply_markup=main_menu_markup(),
        )
        return

    amount_dest = _to_float(message.text)
    if amount_dest is None:
        bot.send_message(message.chat.id, "❌ Введите сумму расхода числом, больше нуля.")
        return

    amount_home = convert_dest_to_home(amount_dest, trip)

    user_data[user_id] = {
        "pending_expense": {
            "trip_id": trip["id"],
            "amount_dest": amount_dest,
            "amount_home": amount_home,
        }
    }
    user_states[user_id] = STATE_WAIT_EXPENSE_CONFIRM

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Да", callback_data="expense_yes"),
        types.InlineKeyboardButton("❌ Нет", callback_data="expense_no"),
    )
    bot.send_message(
        message.chat.id,
        f"💸 {format_money(amount_dest, trip['dest_currency'])} "
        f"= {format_money(amount_home, trip['home_currency'])}\n\n"
        f"Учесть как расход?",
        reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda call: call.data == "expense_yes")
def callback_expense_yes(call: types.CallbackQuery) -> None:
    user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    pending = user_data.get(user_id, {}).get("pending_expense")

    if not pending:
        bot.send_message(call.message.chat.id, "Что-то пошло не так. Попробуйте снова.")
        return

    db.add_expense(
        trip_id=pending["trip_id"],
        amount_dest=pending["amount_dest"],
        amount_home=pending["amount_home"],
        description="",
    )
    trip = db.get_trip(pending["trip_id"])
    user_states[user_id] = STATE_MAIN

    bot.send_message(
        call.message.chat.id,
        f"✅ Расход записан:\n"
        f"{format_money(pending['amount_dest'], trip['dest_currency'])} "
        f"= {format_money(pending['amount_home'], trip['home_currency'])}\n\n"
        f"{format_balance(trip)}",
        reply_markup=main_menu_markup(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "expense_no")
def callback_expense_no(call: types.CallbackQuery) -> None:
    user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    user_states[user_id] = STATE_MAIN
    bot.send_message(
        call.message.chat.id,
        "↩️ Расход не записан.\n"
        "Можете ввести другую сумму или открыть меню.",
        reply_markup=main_menu_markup(),
    )


# ---------- Inline-меню ----------

@bot.callback_query_handler(func=lambda call: call.data == "menu_new_trip")
def menu_new_trip(call: types.CallbackQuery) -> None:
    bot.answer_callback_query(call.id)
    start_new_trip(call.message.chat.id, call.from_user.id)


@bot.callback_query_handler(func=lambda call: call.data == "menu_my_trips")
def menu_my_trips(call: types.CallbackQuery) -> None:
    bot.answer_callback_query(call.id)
    show_trips(call.message.chat.id, call.from_user.id)


@bot.callback_query_handler(func=lambda call: call.data == "menu_balance")
def menu_balance(call: types.CallbackQuery) -> None:
    bot.answer_callback_query(call.id)
    show_balance(call.message.chat.id, call.from_user.id)


@bot.callback_query_handler(func=lambda call: call.data == "menu_history")
def menu_history(call: types.CallbackQuery) -> None:
    bot.answer_callback_query(call.id)
    show_history(call.message.chat.id, call.from_user.id)


@bot.callback_query_handler(func=lambda call: call.data == "menu_set_rate")
def menu_set_rate(call: types.CallbackQuery) -> None:
    bot.answer_callback_query(call.id)
    start_set_rate(call.message.chat.id, call.from_user.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("switch_trip:"))
def switch_trip(call: types.CallbackQuery) -> None:
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    trip_id = int(call.data.split(":")[1])

    if db.set_active_trip(user_id, trip_id):
        trip = db.get_trip(trip_id)
        bot.send_message(
            call.message.chat.id,
            f"🗺️ Активно путешествие «{trip['name']}»\n\n{format_balance(trip)}",
            reply_markup=main_menu_markup(),
        )
    else:
        bot.send_message(
            call.message.chat.id,
            "Не удалось переключиться. Попробуйте снова.",
            reply_markup=main_menu_markup(),
        )
    user_states[user_id] = STATE_MAIN


# ---------- Разделы меню ----------

def show_trips(chat_id: int, user_id: int) -> None:
    trips = db.get_trips(user_id)
    if not trips:
        bot.send_message(
            chat_id,
            "🗺️ У вас пока нет путешествий.\nСоздайте первое!",
            reply_markup=main_menu_markup(),
        )
        return

    markup = types.InlineKeyboardMarkup()
    for trip in trips:
        active = " ✅" if trip["is_active"] else ""
        markup.add(
            types.InlineKeyboardButton(
                f"📍 {trip['name']}{active}",
                callback_data=f"switch_trip:{trip['id']}",
            )
        )
    markup.add(types.InlineKeyboardButton("◀️ Главное меню", callback_data="menu_back"))
    bot.send_message(chat_id, "🗺️ Выберите путешествие:", reply_markup=markup)


def show_balance(chat_id: int, user_id: int) -> None:
    trip = db.get_active_trip(user_id)
    if not trip:
        bot.send_message(
            chat_id,
            "Нет активного путешествия. Создайте или выберите существующее.",
            reply_markup=main_menu_markup(),
        )
        return

    bot.send_message(
        chat_id,
        f"💰 Баланс — {trip['name']}\n\n"
        f"💱 Курс: 1 {trip['home_currency']} = {trip['rate']:.4f} {trip['dest_currency']}\n\n"
        f"{format_balance(trip)}",
        reply_markup=main_menu_markup(),
    )


def show_history(chat_id: int, user_id: int) -> None:
    trip = db.get_active_trip(user_id)
    if not trip:
        bot.send_message(
            chat_id,
            "Нет активного путешествия. Создайте или выберите существующее.",
            reply_markup=main_menu_markup(),
        )
        return

    expenses = db.get_expenses(trip["id"], limit=20)
    if not expenses:
        bot.send_message(
            chat_id,
            "📋 История расходов пока пуста.",
            reply_markup=main_menu_markup(),
        )
        return

    lines = [f"📋 Расходы — «{trip['name']}»:", ""]
    for i, exp in enumerate(reversed(expenses), start=1):
        lines.append(
            f"{i}. {format_money(exp['amount_dest'], trip['dest_currency'])} "
            f"= {format_money(exp['amount_home'], trip['home_currency'])}"
        )
    lines.append("")
    lines.append(format_balance(trip))

    bot.send_message(chat_id, "\n".join(lines), reply_markup=main_menu_markup())


def start_set_rate(chat_id: int, user_id: int) -> None:
    trip = db.get_active_trip(user_id)
    if not trip:
        bot.send_message(
            chat_id,
            "Нет активного путешествия. Создайте или выберите существующее.",
            reply_markup=main_menu_markup(),
        )
        return

    user_states[user_id] = STATE_WAIT_NEW_RATE
    user_data[user_id] = {"edit_trip_id": trip["id"]}
    bot.send_message(
        chat_id,
        f"💱 Текущий курс:\n"
        f"1 {trip['home_currency']} = {trip['rate']:.4f} {trip['dest_currency']}\n\n"
        f"Введите новый курс:",
    )


def handle_new_rate(message: types.Message) -> None:
    user_id = message.from_user.id
    rate = _to_float(message.text)
    if rate is None:
        bot.send_message(message.chat.id, "Введите положительное число, например 13.5.")
        return

    trip_id = user_data.get(user_id, {}).get("edit_trip_id")
    if not trip_id:
        bot.send_message(
            message.chat.id,
            "Ошибка: не найдено путешествие для изменения курса.",
            reply_markup=main_menu_markup(),
        )
        user_states[user_id] = STATE_MAIN
        return

    try:
        db.update_rate(trip_id, rate)
        trip = db.get_trip(trip_id)
        user_states[user_id] = STATE_MAIN
        bot.send_message(
            message.chat.id,
            f"✅ Курс обновлён:\n"
            f"1 {trip['home_currency']} = {trip['rate']:.4f} {trip['dest_currency']}\n\n"
            f"{format_balance(trip)}",
            reply_markup=main_menu_markup(),
        )
    except Exception as e:
        bot.send_message(
            message.chat.id,
            f"Не удалось обновить курс: {e}",
            reply_markup=main_menu_markup(),
        )
        user_states[user_id] = STATE_MAIN


@bot.callback_query_handler(func=lambda call: call.data == "menu_back")
def menu_back(call: types.CallbackQuery) -> None:
    bot.answer_callback_query(call.id)
    send_main_menu(call.message.chat.id)


# ---------- Запуск ----------

if __name__ == "__main__":
    bot.infinity_polling()
