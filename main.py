import logging
import asyncio
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.dispatcher.filters import Command
from aiogram.dispatcher.filters.state import State, StatesGroup

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO)

# --- Токен бота ---
BOT_TOKEN = '7750147455:AAH5kY4fUeJ8Rqwrcyl3reTBG0jjK1SBRNg'

# --- Инициализация бота и диспетчера ---
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# --- Клавиатура главного меню ---
main_menu_kb = ReplyKeyboardMarkup(resize_keyboard=True)
main_menu_kb.add(
    KeyboardButton("➕ Добавить"),
    KeyboardButton("📋 Посмотреть список"),
    KeyboardButton("⏰ Проверить сроки"),
    KeyboardButton("💰 Прибыль")
)

# --- Подключение к Google Sheets ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
client = gspread.authorize(creds)
SPREADSHEET_NAME = 'Школа бокса Фарид'
sheet = client.open(SPREADSHEET_NAME).sheet1

# --- Асинхронные обертки для работы с таблицей ---
async def get_all_records_async():
    return await asyncio.to_thread(sheet.get_all_records)

async def append_row_async(row):
    await asyncio.to_thread(sheet.append_row, row)

# --- Команда /start ---
@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    await message.answer(
        "Привет! Я CRM-бот для школы бокса Локально111.\n"
        "Используй команды:\n"
        "/add_student - добавить ученика\n"
        "/list_students - список учеников\n"
        "/check - проверить кто скоро заканчивается",
        reply_markup=main_menu_kb
    )

# --- Список учеников ---
@dp.message_handler(commands=['list_students'])
@dp.message_handler(text="📋 Посмотреть список")
async def list_students(message: types.Message):
    records = await get_all_records_async()
    response = "Ученики и дни осталось:\n"
    for rec in records:
        response += f"{rec['ФИО']} - {rec['Дней осталось']} дней\n"
    await message.answer(response)

# --- Проверка абонементов, заканчивающихся скоро ---
@dp.message_handler(commands=['check'])
@dp.message_handler(text="⏰ Проверить сроки")
async def check_expiring(message: types.Message):
    records = await get_all_records_async()
    today = datetime.now().date()
    notify_list = []
    for rec in records:
        try:
            end_date = datetime.strptime(rec['Дата окончания'], "%d.%m.%Y").date()
            days_left = (end_date - today).days
        except Exception as e:
            logging.warning(f"Ошибка парсинга даты у {rec.get('ФИО', 'неизвестно')}: {e}")
            continue

        if 0 <= days_left <= 3:
            notify_list.append(f"{rec['ФИО']} - заканчивается через {days_left} дней")
            if rec.get('Telegram ID'):
                try:
                    await bot.send_message(rec['Telegram ID'], f"Ваш абонемент заканчивается через {days_left} дней.")
                except Exception as e:
                    logging.warning(f"Не удалось отправить сообщение {rec['ФИО']}: {e}")
    if notify_list:
        await message.answer("Скоро заканчиваются абонементы:\n" + "\n".join(notify_list))
    else:
        await message.answer("Нет абонементов, которые заканчиваются в ближайшие 3 дня.")

# --- Прибыль ---
@dp.message_handler(text="💰 Прибыль")
async def show_profit(message: types.Message):
    records = await get_all_records_async()
    today = datetime.today().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    day_total = 0
    week_total = 0
    month_total = 0

    for rec in records:
        try:
            start_date = datetime.strptime(rec['Дата начала'], "%d.%m.%Y").date()
            payment = int(rec['Сумма оплаты (в рублях)'])
            if start_date == today:
                day_total += payment
            if week_ago <= start_date <= today:
                week_total += payment
            if month_ago <= start_date <= today:
                month_total += payment
        except Exception as e:
            logging.warning(f"Ошибка при обработке записи: {e}")
            continue

    await message.answer(
        f"💰 *Прибыль:*\n"
        f"Сегодня: {day_total} ₽\n"
        f"За неделю: {week_total} ₽\n"
        f"За месяц: {month_total} ₽",
        parse_mode="Markdown"
    )

# --- FSM для добавления ученика ---
class AddStudentState(StatesGroup):
    fio = State()
    phone = State()
    telegram_id = State()
    abon_type = State()
    start_date = State()
    end_date = State()
    payment = State()

@dp.message_handler(Command("cancel"), state="*")
async def cancel_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    logging.info(f"Текущая стадия FSM: {current_state}")

    if current_state is None:
        await message.reply("Нет активного действия для отмены.")
        return

    await state.finish()
    await message.reply("❌ Добавление отменено.", reply_markup=main_menu_kb)

@dp.message_handler(commands=['add_student'])
@dp.message_handler(text="➕ Добавить")
async def cmd_add_student(message: types.Message):
    logging.info(f"Команда /add_student вызвана от {message.from_user.id}")
    await AddStudentState.fio.set()
    await message.reply("Введите ФИО ученика:\n\nℹ️ В любой момент вы можете ввести /cancel, чтобы отменить.")

@dp.message_handler(state=AddStudentState.fio)
async def process_fio(message: types.Message, state: FSMContext):
    await state.update_data(fio=message.text)
    await AddStudentState.phone.set()
    await message.reply("Введите телефон:")

@dp.message_handler(state=AddStudentState.phone)
async def process_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await AddStudentState.telegram_id.set()
    await message.reply("Введите Telegram ID:")

@dp.message_handler(state=AddStudentState.telegram_id)
async def process_tid(message: types.Message, state: FSMContext):
    await state.update_data(telegram_id=message.text)
    await AddStudentState.abon_type.set()
    await message.reply("Введите тип абонемента (Групповой, Малая группа, Индивидуально):")

@dp.message_handler(state=AddStudentState.abon_type)
async def process_abon(message: types.Message, state: FSMContext):
    await state.update_data(abon_type=message.text)
    await AddStudentState.start_date.set()
    await message.reply("Введите дату начала (ДД.ММ.ГГГГ):")

@dp.message_handler(state=AddStudentState.start_date)
async def process_start(message: types.Message, state: FSMContext):
    # Проверяем формат даты
    try:
        datetime.strptime(message.text, "%d.%m.%Y")
    except ValueError:
        await message.reply("Неверный формат даты. Введите дату начала в формате ДД.ММ.ГГГГ:")
        return
    await state.update_data(start_date=message.text)
    await AddStudentState.end_date.set()
    await message.reply("Введите дату окончания (ДД.ММ.ГГГГ):")

@dp.message_handler(state=AddStudentState.end_date)
async def process_end(message: types.Message, state: FSMContext):
    # Проверяем формат даты
    try:
        datetime.strptime(message.text, "%d.%m.%Y")
    except ValueError:
        await message.reply("Неверный формат даты. Введите дату окончания в формате ДД.ММ.ГГГГ:")
        return
    await state.update_data(end_date=message.text)
    await AddStudentState.payment.set()
    await message.reply("Введите сумму оплаты (в рублях):")

@dp.message_handler(state=AddStudentState.payment)
async def process_payment(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    payment = message.text
    try:
        start = datetime.strptime(user_data["start_date"], "%d.%m.%Y")
        end = datetime.strptime(user_data["end_date"], "%d.%m.%Y")
        days_left = (end - datetime.today()).days
        int(payment)  # Проверка, что сумма — число
    except ValueError:
        await message.reply("Ошибка в данных. Убедитесь, что даты и сумма оплаты введены корректно.")
        return

    new_row = [
        user_data["fio"],
        user_data["phone"],
        user_data["telegram_id"],
        days_left,
        user_data["abon_type"],
        user_data["start_date"],
        user_data["end_date"],
        payment
    ]

    try:
        await append_row_async(new_row)
        await message.reply("✅ Ученик добавлен!", reply_markup=main_menu_kb)
    except Exception as e:
        await message.reply(f"Ошибка при добавлении в таблицу: {e}")

    await state.finish()

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
