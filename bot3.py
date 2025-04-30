import asyncio
import aiohttp
import logging
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton

API_TOKEN = '7671796047:AAFOybMQyfljpXOeQ2yP1V7pHRoXuW-O__o'
ADMIN_ID = 299423088  # Your Telegram ID

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot=bot, storage=storage)

# Set up logging
logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    encoding='utf-8'
)
logger = logging.getLogger(__name__)

# Initialize SQLite database
conn = sqlite3.connect('evacuator.db', check_same_thread=False)
cursor = conn.cursor()

# Define the expected schema for each table
EXPECTED_ORDERS_COLUMNS = {
    'order_id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
    'client_id': 'INTEGER',
    'car': 'TEXT',
    'location': 'TEXT',
    'location_coords': 'TEXT',
    'destination': 'TEXT',
    'destination_coords': 'TEXT',
    'distance': 'TEXT',
    'wheels_locked': 'TEXT',
    'timing': 'TEXT',
    'comment': 'TEXT',
    'photo_id': 'TEXT',
    'status': 'TEXT',
    'timestamp': 'TEXT',
    'accepted_timestamp': 'TEXT',
    'client_phone_number': 'TEXT'
}

EXPECTED_EVACUATORS_COLUMNS = {
    'evacuator_id': 'INTEGER PRIMARY KEY',
    'username': 'TEXT',
    'name': 'TEXT',
    'full_name': 'TEXT',
    'status': 'TEXT',
    'timestamp': 'TEXT'
}

EXPECTED_RESPONSES_COLUMNS = {
    'response_id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
    'order_id': 'INTEGER',
    'evacuator_id': 'INTEGER',
    'price_time': 'TEXT',
    'evacuator_comment': 'TEXT',
    'evacuator_username': 'TEXT',
    'client_decision': 'TEXT',
    'timestamp': 'TEXT'
}

EXPECTED_CLIENTS_COLUMNS = {
    'client_id': 'INTEGER PRIMARY KEY',
    'username': 'TEXT',
    'name': 'TEXT',
    'timestamp': 'TEXT'
}

EXPECTED_FEEDBACK_COLUMNS = {
    'feedback_id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
    'order_id': 'INTEGER',
    'client_id': 'INTEGER',
    'rating': 'INTEGER',
    'comment': 'TEXT',
    'timestamp': 'TEXT'
}

# Create database tables
cursor.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        car TEXT,
        photo_id TEXT,
        location TEXT,
        location_coords TEXT,
        destination TEXT,
        destination_coords TEXT,
        distance TEXT,
        wheels_locked TEXT,
        timing TEXT,
        comment TEXT,
        status TEXT,  -- 'pending', 'accepted', 'completed', 'canceled'
        timestamp TEXT
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS responses (
        response_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        evacuator_id INTEGER,
        price_time TEXT,
        evacuator_comment TEXT,
        evacuator_username TEXT,
        client_decision TEXT,
        timestamp TEXT,
        FOREIGN KEY (order_id) REFERENCES orders (order_id)
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS evacuators (
        evacuator_id INTEGER PRIMARY KEY,
        username TEXT,
        name TEXT,
        full_name TEXT,
        status TEXT,  -- 'approved', 'active', 'removed'
        timestamp TEXT
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS clients (
        client_id INTEGER PRIMARY KEY,
        username TEXT,
        name TEXT,
        timestamp TEXT
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS feedback (
        feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        client_id INTEGER,
        rating INTEGER,
        pros TEXT,
        cons TEXT,
        timestamp TEXT,
        FOREIGN KEY (order_id) REFERENCES orders (order_id)
    )
''')

# Schema migration: Add missing columns if they don't exist
def migrate_database():
# Migration for responses table
    cursor.execute("PRAGMA table_info(responses)")
    existing_columns = [col[1] for col in cursor.fetchall()]
    if 'evacuator_name' in existing_columns:
        cursor.execute('''
            CREATE TABLE responses_temp (
                response_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                evacuator_id INTEGER,
                price_time TEXT,
                evacuator_comment TEXT,
                evacuator_username TEXT,
                client_decision TEXT,
                timestamp TEXT,
                FOREIGN KEY (order_id) REFERENCES orders (order_id)
            )
        ''')
        cursor.execute('''
            INSERT INTO responses_temp (
                response_id, order_id, evacuator_id, price_time, 
                evacuator_comment, evacuator_username, client_decision, timestamp
            )
            SELECT 
                response_id, order_id, evacuator_id, price_time, 
                evacuator_comment, evacuator_username, client_decision, timestamp
            FROM responses
        ''')
        cursor.execute("DROP TABLE responses")
        cursor.execute("ALTER TABLE responses_temp RENAME TO responses")
        logger.info("Migrated responses table: removed 'evacuator_name'")

    cursor.execute("PRAGMA table_info(feedback)")
    columns = [col[1] for col in cursor.fetchall()]
    
    # Если таблица имеет старую структуру с pros и cons
    if 'pros' in columns or 'cons' in columns:
        # Создаем новую временную таблицу с правильной структурой
        cursor.execute('''
            CREATE TABLE feedback_new (
                feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                client_id INTEGER,
                rating INTEGER,
                comment TEXT,
                timestamp TEXT,
                FOREIGN KEY (order_id) REFERENCES orders(order_id),
                FOREIGN KEY (client_id) REFERENCES users(user_id)
            )
        ''')
        
        # Переносим данные, объединяя pros и cons в comment
        cursor.execute('''
            INSERT INTO feedback_new (feedback_id, order_id, client_id, rating, comment, timestamp)
            SELECT feedback_id, order_id, client_id, rating,
                   CASE
                       WHEN pros IS NOT NULL AND cons IS NOT NULL THEN pros || ' | ' || cons
                       WHEN pros IS NOT NULL THEN pros
                       WHEN cons IS NOT NULL THEN cons
                       ELSE NULL
                   END AS comment,
                   timestamp
            FROM feedback
        ''')
        
        # Удаляем старую таблицу
        cursor.execute("DROP TABLE feedback")
        
        # Переименовываем новую таблицу
        cursor.execute("ALTER TABLE feedback_new RENAME TO feedback")
        
        conn.commit()
        logger.info("Migrated 'feedback' table: replaced 'pros' and 'cons' with 'comment'")
    
    # Проверяем актуальную структуру таблицы feedback
    expected_columns = ['feedback_id', 'order_id', 'client_id', 'rating', 'comment', 'timestamp']
    cursor.execute("PRAGMA table_info(feedback)")
    actual_columns = [col[1] for col in cursor.fetchall()]
    if set(expected_columns) != set(actual_columns):
        logger.error(f"Schema mismatch in 'feedback' table! Expected: {expected_columns}, Found: {actual_columns}")
    else:
        logger.info("Schema for 'feedback' table is correct")

    # Проверяем структуру таблицы orders
    expected_columns_orders = [
        'order_id', 'client_id', 'car', 'location', 'location_coords', 'destination',
        'destination_coords', 'distance', 'wheels_locked', 'timing', 'comment',
        'photo_id', 'status', 'timestamp', 'accepted_timestamp', 'client_phone_number'
    ]
    cursor.execute("PRAGMA table_info(orders)")
    actual_columns_orders = [col[1] for col in cursor.fetchall()]
    if set(expected_columns_orders) != set(actual_columns_orders):
        logger.error(f"Schema mismatch in 'orders' table! Expected: {expected_columns_orders}, Found: {actual_columns_orders}")
    else:
        logger.info("Schema for 'orders' table is correct")

    def add_missing_columns(table_name: str, expected_columns: dict):
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = [col[1] for col in cursor.fetchall()]
        
        for column_name, column_type in expected_columns.items():
            if column_name not in existing_columns:
                base_type = column_type.split()[0]
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {base_type}")
                logger.info(f"Added '{column_name}' column to '{table_name}' table")

    # Обновляем EXPECTED_EVACUATORS_COLUMNS
    global EXPECTED_EVACUATORS_COLUMNS
    EXPECTED_EVACUATORS_COLUMNS = {
        'evacuator_id': 'INTEGER PRIMARY KEY',
        'username': 'TEXT',
        'phone_number': 'TEXT',
        'status': 'TEXT',
        'timestamp': 'TEXT'
    }

    # Проверяем наличие старых столбцов и пересоздаем таблицу, если нужно
    cursor.execute("PRAGMA table_info(evacuators)")
    existing_columns = [col[1] for col in cursor.fetchall()]
    if 'name' in existing_columns or 'full_name' in existing_columns:
        # Создаем временную таблицу с новой структурой
        cursor.execute('''
            CREATE TABLE evacuators_temp (
                evacuator_id INTEGER PRIMARY KEY,
                username TEXT,
                phone_number TEXT,
                status TEXT,
                timestamp TEXT
            )
        ''')
        # Копируем данные, игнорируя старые столбцы
        cursor.execute('''
            INSERT INTO evacuators_temp (evacuator_id, username, status, timestamp)
            SELECT evacuator_id, username, status, timestamp
            FROM evacuators
        ''')
        # Удаляем старую таблицу и переименовываем новую
        cursor.execute("DROP TABLE evacuators")
        cursor.execute("ALTER TABLE evacuators_temp RENAME TO evacuators")
        logger.info("Migrated evacuators table: removed 'name' and 'full_name', added 'phone_number'")
    
    # Добавляем новые столбцы, если нужно
    add_missing_columns('evacuators', EXPECTED_EVACUATORS_COLUMNS)
    add_missing_columns('orders', EXPECTED_ORDERS_COLUMNS)
    add_missing_columns('responses', EXPECTED_RESPONSES_COLUMNS)
    add_missing_columns('clients', EXPECTED_CLIENTS_COLUMNS)
    add_missing_columns('feedback', EXPECTED_FEEDBACK_COLUMNS)

migrate_database()
conn.commit()

# Проверка схемы таблицы orders
cursor.execute("PRAGMA table_info(orders)")
columns = [col[1] for col in cursor.fetchall()]
expected_columns = list(EXPECTED_ORDERS_COLUMNS.keys())
if columns != expected_columns:
    logger.error(f"Schema mismatch in 'orders' table! Expected: {expected_columns}, Found: {columns}")
else:
    logger.info(f"Schema of 'orders' table is correct: {columns}")

cursor.execute("PRAGMA table_info(orders)")
existing_columns = [col[1] for col in cursor.fetchall()]
if 'client_phone_number' not in existing_columns:
    cursor.execute("ALTER TABLE orders ADD COLUMN client_phone_number TEXT")
    logger.info("Added 'client_phone_number' column to 'orders' table")
    

# Function to get approved evacuators
def get_approved_evacuators():
    cursor.execute("SELECT evacuator_id FROM evacuators WHERE status = 'approved'")
    evacuators = [row[0] for row in cursor.fetchall()]
    logger.info(f"Approved evacuators: {evacuators}")
    return evacuators

# States for client order process, evacuator response, feedback, editing, and admin actions
class OrderForm(StatesGroup):
    car = State()
    location = State()
    confirm_location = State()
    destination = State()
    destination_confirm = State()
    wheels_locked = State()
    timing = State()
    comment = State()
    phone_number = State()  # Добавлено
    photo = State()
    confirm_order = State()
    evacuator_response = State()
    evacuator_price = State()  # Новое состояние для цены
    evacuator_time = State()   # Новое состояние для времени
    edit_car = State()
    edit_photo = State()
    edit_location = State()
    edit_destination = State()
    edit_wheels_locked = State()
    edit_timing = State()
    edit_comment = State()

class FeedbackForm(StatesGroup):
    rating = State()
    comment = State()  # Новый шаг для общего комментария

class AdminForm(StatesGroup):
    register_evacuator = State()
    enter_id = State()
    enter_name = State()
    enter_start_date = State()  # Для ввода начальной даты
    enter_end_date = State()    # Для ввода конечной даты

# Keyboards
location_button = KeyboardButton(text="Отправить текущую геолокацию", request_location=True)
location_markup = ReplyKeyboardMarkup(
    keyboard=[[location_button]],
    resize_keyboard=True,
    one_time_keyboard=True
)

confirm_location_buttons = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Да")],
        [KeyboardButton(text="Нет")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

confirm_button = KeyboardButton(text="Подтвердить")
confirm_markup = ReplyKeyboardMarkup(
    keyboard=[[confirm_button]],
    resize_keyboard=True,
    one_time_keyboard=True
)

wheels_locked_buttons = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="1 колесо"), KeyboardButton(text="2 колеса")],
        [KeyboardButton(text="3 колеса"), KeyboardButton(text="4 колеса")],
        [KeyboardButton(text="Не заблокированы"), KeyboardButton(text="Не знаю")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

timing_buttons = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Сейчас")]],
    resize_keyboard=True,
    one_time_keyboard=True
)

order_confirm_buttons = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Подтвердить заказ")],
        [KeyboardButton(text="Изменить автомобиль")],
        [KeyboardButton(text="Добавить/изменить фото")],
        [KeyboardButton(text="Изменить местоположение")],
        [KeyboardButton(text="Изменить конечный пункт")],
        [KeyboardButton(text="Изменить статус колес")],
        [KeyboardButton(text="Изменить время")],
        [KeyboardButton(text="Изменить комментарий")],
        [KeyboardButton(text="Отменить заказ")]  # Added Cancel Order button
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

new_order_button = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Создать новый заказ")]],
    resize_keyboard=True,
    one_time_keyboard=True
)

cancel_order_after_confirmation_buttons = ReplyKeyboardMarkup(
    keyboard=[
        # [KeyboardButton(text="Отменить заказ")],
        [KeyboardButton(text="Создать новый заказ")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)


rating_buttons = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="1"), KeyboardButton(text="2"), KeyboardButton(text="3")],
        [KeyboardButton(text="4"), KeyboardButton(text="5")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

remove_markup = ReplyKeyboardRemove()

evacuator_response_button = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Указать цену и время", callback_data="respond_to_order")]
])

admin_buttons = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Register Evacuator", callback_data="register_evacuator")],
    [InlineKeyboardButton(text="Remove Evacuator", callback_data="remove_evacuator")],
    [InlineKeyboardButton(text="View Statistics", callback_data="view_statistics")],
    [InlineKeyboardButton(text="View Orders by Period", callback_data="view_orders_by_period")]
])

# Helper functions
async def get_address_from_coordinates(lat: float, lon: float) -> str:
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"
    headers = {"User-Agent": "EvacuatorBot/1.0"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return f"Геолокация: ({lat}, {lon}) (не удалось определить адрес)"
                data = await response.json()
                address = data.get("display_name", "Адрес не найден")
                return address
        except Exception as e:
            logger.error(f"Error in geocoding: {e}")
            return f"Геолокация: ({lat}, {lon}) (не удалось определить адрес)"
        finally:
            await asyncio.sleep(1)

async def calculate_route_distance(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> str:
    url = f"http://router.project-osrm.org/route/v1/driving/{start_lon},{start_lat};{end_lon},{end_lat}?overview=false"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    return "Не удалось рассчитать маршрут"
                data = await response.json()
                if "routes" in data and data["routes"]:
                    distance_meters = data["routes"][0]["distance"]
                    distance_km = distance_meters / 1000
                    return f"{distance_km:.1f} км"
                return "Маршрут не найден"
        except Exception as e:
            logger.error(f"Error in route calculation: {e}")
            return "Не удалось рассчитать маршрут"

async def display_order_details(message: types.Message, state: FSMContext):
    data = await state.get_data()
    order_details = (
        "📋 *Ваш заказ:*\n"
        f"🚗 *Марка автомобиля:* {data.get('car', 'Не указано')}\n"
        f"📍 *Местоположение:* {data.get('location', 'Не указано')}\n"
        f"🏁 *Конечный пункт:* {data.get('destination', 'Не указано')}\n"
    )

    location_coords = data.get('location_coords')
    destination_coords = data.get('destination_coords')
    distance = data.get('distance')
    if location_coords and destination_coords and not distance:
        start_lat, start_lon = location_coords
        end_lat, end_lon = destination_coords
        distance = await calculate_route_distance(start_lat, start_lon, end_lat, end_lon)
        await state.update_data(distance=distance)
    if distance:
        order_details += f"📏 *Расстояние:* {distance}\n"
    else:
        order_details += "📏 *Расстояние:* (не удалось рассчитать)\n"

    order_details += (
        f"🔧 *Заблокированные колеса:* {data.get('wheels_locked', 'Не указано')}\n"
        f"⏰ *Когда нужен эвакуатор:* {data.get('timing', 'Не указано')}\n"
        f"💬 *Комментарий:* {data.get('comment', 'Не указано')}\n"
    )

    photo_id = data.get('photo_id')
    if photo_id:
        await bot.send_photo(
            chat_id=message.chat.id,
            photo=photo_id,
            caption=order_details,
            parse_mode="Markdown",
            reply_markup=order_confirm_buttons
        )
    else:
        await message.reply(
            order_details + "📸 *Фото:* Не прикреплено\n",
            parse_mode="Markdown",
            reply_markup=order_confirm_buttons
        )

# Function to notify evacuators and offer new order creation
async def notify_and_offer_new_order(client_id: int, order_id: int, message_text: str, is_canceled: bool = False, show_cancel_button: bool = False):
    # Notify evacuators if the order was sent to them
    if is_canceled and order_id:
        evacuators = get_approved_evacuators()
        for evacuator_id in evacuators:
            try:
                await bot.send_message(
                    chat_id=evacuator_id,
                    text=f"Заказ #{order_id} был отменен клиентом."
                )
                logger.info(f"Notified evacuator {evacuator_id} that order #{order_id} was canceled")
            except Exception as e:
                logger.error(f"Failed to notify evacuator {evacuator_id} about order #{order_id} cancellation: {e}")

    # Notify client and offer to create a new order
    try:
        # Используем разные клавиатуры в зависимости от ситуации
        markup = cancel_order_after_confirmation_buttons if show_cancel_button else new_order_button
        await bot.send_message(
            chat_id=client_id,
            text=message_text,
            reply_markup=markup
        )
        logger.info(f"Notified client {client_id} with message: {message_text}")
    except Exception as e:
        logger.error(f"Failed to notify client {client_id}: {e}")

# Admin command to show admin panel
@dp.message(Command(commands=['admin']))
async def admin_panel(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.reply("У вас нет прав для выполнения этой команды.")
        logger.warning(f"User {user_id} attempted to access admin panel but is not admin")
        return
    
    await message.reply(
        "Добро пожаловать в панель администратора! Выберите действие:",
        reply_markup=admin_buttons
    )
    logger.info(f"Admin {user_id} accessed admin panel")

phone_button = KeyboardButton(text="Отправить номер телефона", request_contact=True)
skip_button = KeyboardButton(text="Пропустить")
phone_markup = ReplyKeyboardMarkup(
    keyboard=[[phone_button], [skip_button]],
    resize_keyboard=True,
    one_time_keyboard=True
)

phone_button_client = KeyboardButton(text="Отправить номер телефона", request_contact=True)
skip_button = KeyboardButton(text="Пропустить")
phone_markup_client = ReplyKeyboardMarkup(
    keyboard=[[phone_button_client], [skip_button]],
    resize_keyboard=True,
    one_time_keyboard=True
)

# Handle "Register Evacuator" button
@dp.callback_query(lambda c: c.data == "register_evacuator")
async def start_register_evacuator(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    if user_id != ADMIN_ID:
        await callback_query.message.reply("У вас нет прав для выполнения этой команды.")
        await callback_query.answer()
        logger.warning(f"User {user_id} attempted to register evacuator but is not admin")
        return
    
    await callback_query.message.reply(
        "Перешлите сообщение от пользователя, которого хотите зарегистрировать как эвакуаторщика, "
        "или отправьте его Telegram ID (только цифры):",
        reply_markup=remove_markup
    )
    await state.set_state(AdminForm.enter_id)
    await callback_query.answer()
    logger.info(f"Admin {user_id} started evacuator registration process")

@dp.message(StateFilter(AdminForm.enter_id))
async def process_evacuator_id(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.reply("У вас нет прав для выполнения этой команды.")
        await state.clear()
        logger.warning(f"User {user_id} attempted to register/remove evacuator but is not admin")
        return
    
    data = await state.get_data()
    action = data.get('action', 'register')
    
    evacuator_id = None
    username = None
    
    if message.forward_from:
        evacuator_id = message.forward_from.id
        username = message.forward_from.username
        if not username:
            await message.reply(
                "У пользователя отсутствует Telegram-ник (@username). "
                "Попросите пользователя установить ник в настройках Telegram или отправьте его Telegram ID вручную."
            )
            logger.warning(f"Forwarded user {evacuator_id} has no username")
            return
        logger.info(f"Admin {user_id} forwarded message from evacuator {evacuator_id} with username {username}")
    elif message.text and message.text.isdigit():
        evacuator_id = int(message.text)
        # Попробуем получить username через Telegram API
        try:
            chat = await bot.get_chat(evacuator_id)
            username = chat.username
            if not username:
                await message.reply(
                    f"Пользователь с ID {evacuator_id} не имеет Telegram-ник (@username). "
                    "Попросите пользователя установить ник в настройках Telegram или отправьте его ID снова, "
                    "чтобы запросить номер телефона."
                )
                logger.warning(f"User {evacuator_id} has no username")
                return
            logger.info(f"Admin {user_id} manually entered evacuator ID {evacuator_id} with username {username}")
        except Exception as e:
            await message.reply(f"Не удалось получить информацию о пользователе с ID {evacuator_id}: {str(e)}")
            logger.error(f"Failed to get chat info for {evacuator_id}: {e}")
            return
    else:
        await message.reply(
            "Пожалуйста, перешлите сообщение от пользователя или отправьте его Telegram ID (только цифры)."
        )
        logger.warning(f"Admin {user_id} sent invalid input for evacuator ID")
        return
    
    if action == "remove":
        cursor.execute("SELECT * FROM evacuators WHERE evacuator_id = ?", (evacuator_id,))
        evacuator = cursor.fetchone()
        if not evacuator:
            await message.reply("Эвакуаторщик с таким ID не найден.")
            logger.info(f"Admin {user_id} attempted to remove evacuator {evacuator_id} but not found")
            await state.clear()
            return
        
        cursor.execute("DELETE FROM evacuators WHERE evacuator_id = ?", (evacuator_id,))
        conn.commit()
        
        await message.reply(f"Эвакуаторщик с ID {evacuator_id} удален из базы.")
        try:
            await bot.send_message(
                chat_id=evacuator_id,
                text="Вы были удалены из базы эвакуаторщиков."
            )
            logger.info(f"Notified evacuator {evacuator_id} about removal")
        except Exception as e:
            logger.error(f"Failed to notify evacuator {evacuator_id} about removal: {e}")
        
        logger.info(f"Admin {user_id} removed evacuator {evacuator_id}")
        await state.clear()
        return
    
    await state.update_data(
        evacuator_id=evacuator_id,
        username=username
    )
    await message.reply(
        "Отправьте номер телефона эвакуаторщика (например, +79991234567) или нажмите кнопку, чтобы запросить контакт:",
        reply_markup=phone_markup
    )
    await state.set_state(AdminForm.enter_name)  # Переименуем состояние для единообразия
    logger.info(f"Admin {user_id} moved to enter phone number for evacuator {evacuator_id}")

@dp.message(StateFilter(AdminForm.enter_name))
async def process_phone_number(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.reply("У вас нет прав для выполнения этой команды.")
        await state.clear()
        logger.warning(f"User {user_id} attempted to register evacuator but is not admin")
        return
    
    data = await state.get_data()
    evacuator_id = data.get('evacuator_id')
    username = data.get('username')
    
    phone_number = None
    if message.contact:
        phone_number = message.contact.phone_number
        logger.info(f"Admin {user_id} provided phone number {phone_number} via contact for evacuator {evacuator_id}")
    elif message.text:
        if message.text == "-" or message.text.lower() == "пропустить":
            phone_number = None
            logger.info(f"Admin {user_id} skipped phone number for evacuator {evacuator_id}")
        elif message.text.startswith('+') and message.text[1:].isdigit():
            phone_number = message.text
            logger.info(f"Admin {user_id} manually entered phone number {phone_number} for evacuator {evacuator_id}")
        else:
            await message.reply(
                "Пожалуйста, отправьте номер телефона в формате +79991234567, нажмите 'Пропустить' или отправьте '-'.",
                reply_markup=phone_markup
            )
            logger.warning(f"Admin {user_id} sent invalid phone number for evacuator {evacuator_id}: {message.text}")
            return
    else:
        await message.reply(
            "Пожалуйста, отправьте номер телефона в формате +79991234567, нажмите 'Пропустить' или отправьте '-'.",
            reply_markup=phone_markup
        )
        logger.warning(f"Admin {user_id} sent invalid input for phone number for evacuator {evacuator_id}")
        return
    
    cursor.execute("INSERT OR REPLACE INTO evacuators (evacuator_id, username, phone_number, status, timestamp) VALUES (?, ?, ?, ?, ?)",
                   (evacuator_id, username, phone_number, "approved", datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    
    phone_display = phone_number if phone_number else "Не указан"
    await message.reply(
        f"Эвакуаторщик добавлен:\n"
        f"ID: {evacuator_id}\n"
        f"Username: @{username}\n"
        f"Номер телефона: {phone_display}\n"
        f"Статус: approved\n\n"
        "Эвакуаторщик готов принимать заказы. Пусть нажмет /start в боте.",
        reply_markup=remove_markup
    )
    
    try:
        await bot.send_message(
            chat_id=evacuator_id,
            text="Вы добавлены как эвакуатор! Нажмите /start, чтобы начать принимать заказы."
        )
        logger.info(f"Notified evacuator {evacuator_id} about approval")
    except Exception as e:
        logger.error(f"Failed to notify evacuator {evacuator_id} about approval: {e}")
        await message.reply(f"Не удалось уведомить эвакуаторщика {evacuator_id}: {str(e)}")
    
    logger.info(f"Admin {user_id} registered evacuator {evacuator_id} (Username: {username}, Phone: {phone_display}) with status approved")
    await state.clear()

@dp.callback_query(lambda c: c.data == "remove_evacuator")
async def start_remove_evacuator(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    if user_id != ADMIN_ID:
        await callback_query.message.reply("У вас нет прав для выполнения этой команды.")
        await callback_query.answer()
        logger.warning(f"User {user_id} attempted to remove evacuator but is not admin")
        return
    
    await callback_query.message.reply(
        "Отправьте Telegram ID эвакуаторщика, которого хотите удалить (только цифры):",
        reply_markup=remove_markup
    )
    await state.set_state(AdminForm.enter_id)  # Используем то же состояние, что и для добавления
    await state.update_data(action="remove")  # Укажем, что действие — удаление
    await callback_query.answer()
    logger.info(f"Admin {user_id} started evacuator removal process")

@dp.callback_query(lambda c: c.data == "view_statistics")
async def view_statistics(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id != ADMIN_ID:
        await callback_query.message.reply("У вас нет прав для выполнения этой команды.")
        await callback_query.answer()
        logger.warning(f"User {user_id} attempted to view statistics but is not admin")
        return
    
    # Подсчитываем статистику
    cursor.execute("SELECT COUNT(*) FROM orders")
    total_orders = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM clients")
    total_clients = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM evacuators WHERE status = 'approved'")
    total_evacuators = cursor.fetchone()[0]
    
    stats_message = (
        "📊 *Статистика:*\n"
        f"Всего заказов: {total_orders}\n"
        f"Всего клиентов: {total_clients}\n"
        f"Всего эвакуаторщиков: {total_evacuators}"
    )
    
    await callback_query.message.reply(stats_message, parse_mode="Markdown")
    await callback_query.answer()
    logger.info(f"Admin {user_id} viewed statistics")

@dp.callback_query(lambda c: c.data == "view_orders_by_period")
async def start_view_orders_by_period(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    if user_id != ADMIN_ID:
        await callback_query.message.reply("У вас нет прав для выполнения этой команды.")
        await callback_query.answer()
        logger.warning(f"User {user_id} attempted to view orders but is not admin")
        return
    
    await callback_query.message.reply(
        "Введите начальную дату в формате ГГГГ-ММ-ДД (например, 2025-04-01):",
        reply_markup=remove_markup
    )
    await state.set_state(AdminForm.enter_start_date)
    await callback_query.answer()
    logger.info(f"Admin {user_id} started viewing orders by period")

@dp.message(StateFilter(AdminForm.enter_start_date))
async def process_start_date(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.reply("У вас нет прав для выполнения этой команды.")
        await state.clear()
        return
    
    try:
        start_date = datetime.strptime(message.text, '%Y-%m-%d')
        await state.update_data(start_date=start_date.strftime('%Y-%m-%d'))
        await message.reply("Введите конечную дату в формате ГГГГ-ММ-ДД (например, 2025-04-30):")
        await state.set_state(AdminForm.enter_end_date)
    except ValueError:
        await message.reply("Пожалуйста, введите дату в формате ГГГГ-ММ-ДД (например, 2025-04-01).")

@dp.message(StateFilter(AdminForm.enter_end_date))
async def process_end_date(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.reply("У вас нет прав для выполнения этой команды.")
        await state.clear()
        return
    
    try:
        end_date = datetime.strptime(message.text, '%Y-%m-%d')
        data = await state.get_data()
        start_date = data.get('start_date')
        
        cursor.execute("SELECT * FROM orders WHERE timestamp BETWEEN ? AND ? || ' 23:59:59'", (start_date, end_date.strftime('%Y-%m-%d')))
        orders = cursor.fetchall()
        
        if not orders:
            await message.reply("За указанный период заказов не найдено.")
            await state.clear()
            return
        
        orders_message = f"📋 *Заказы с {start_date} по {end_date.strftime('%Y-%m-%d')}:*\n\n"
        for order in orders:
            order_id = order[0]
            client_id = order[1]
            car = order[2]
            status = order[12]
            timestamp = order[13]
            orders_message += f"Заказ #{order_id}\nКлиент ID: {client_id}\nАвтомобиль: {car}\nСтатус: {status}\nДата: {timestamp}\n\n"
        
        await message.reply(orders_message, parse_mode="Markdown")
        await state.clear()
    except ValueError:
        await message.reply("Пожалуйста, введите дату в формате ГГГГ-ММ-ДД (например, 2025-04-30).")

# Handle evacuator ID input (forwarded message or manual ID)
@dp.message(StateFilter(AdminForm.enter_id))
async def process_evacuator_id(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.reply("У вас нет прав для выполнения этой команды.")
        await state.clear()
        logger.warning(f"User {user_id} attempted to register/remove evacuator but is not admin")
        return
    
    data = await state.get_data()
    action = data.get('action', 'register')  # По умолчанию — регистрация
    
    evacuator_id = None
    username = None
    name = None
    
    if message.forward_from:
        evacuator_id = message.forward_from.id
        username = message.forward_from.username
        if not username:
            username = f"user_{evacuator_id}"
        name = message.forward_from.first_name or ""
        if message.forward_from.last_name:
            name += f" {message.forward_from.last_name}"
        logger.info(f"Admin {user_id} forwarded message from evacuator {evacuator_id}")
    elif message.text and message.text.isdigit():
        evacuator_id = int(message.text)
        username = f"user_{evacuator_id}"
        name = "Неизвестно"
        logger.info(f"Admin {user_id} manually entered evacuator ID {evacuator_id}")
    else:
        await message.reply(
            "Пожалуйста, перешлите сообщение от пользователя или отправьте его Telegram ID (только цифры)."
        )
        logger.warning(f"Admin {user_id} sent invalid input for evacuator ID")
        return
    
    if action == "remove":
        cursor.execute("SELECT * FROM evacuators WHERE evacuator_id = ?", (evacuator_id,))
        evacuator = cursor.fetchone()
        if not evacuator:
            await message.reply("Эвакуаторщик с таким ID не найден.")
            logger.info(f"Admin {user_id} attempted to remove evacuator {evacuator_id} but not found")
            await state.clear()
            return
        
        # Полностью удаляем запись из базы
        cursor.execute("DELETE FROM evacuators WHERE evacuator_id = ?", (evacuator_id,))
        conn.commit()
        
        await message.reply(f"Эвакуаторщик с ID {evacuator_id} удален из базы.")
        try:
            await bot.send_message(
                chat_id=evacuator_id,
                text="Вы были удалены из базы эвакуаторщиков."
            )
            logger.info(f"Notified evacuator {evacuator_id} about removal")
        except Exception as e:
            logger.error(f"Failed to notify evacuator {evacuator_id} about removal: {e}")
        
        logger.info(f"Admin {user_id} removed evacuator {evacuator_id}")
        await state.clear()
        return
    
    # Логика для регистрации (без изменений)
    await state.update_data(
        evacuator_id=evacuator_id,
        username=username,
        name=name
    )
    await message.reply(
        "Укажите имя эвакуаторщика (или отправьте '-' для пропуска):"
    )
    await state.set_state(AdminForm.enter_name)
    logger.info(f"Admin {user_id} moved to enter name for evacuator {evacuator_id}")

# Handle evacuator name input
@dp.message(StateFilter(AdminForm.enter_name))
async def process_name(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.reply("У вас нет прав для выполнения этой команды.")
        await state.clear()
        logger.warning(f"User {user_id} attempted to register evacuator but is not admin")
        return
    
    data = await state.get_data()
    evacuator_id = data.get('evacuator_id')
    username = data.get('username')
    name = message.text.strip() if message.text else "Не указано"
    
    if name == "-":
        name = "Не указано"
    elif len(name) > 50:
        await message.reply(f"Имя эвакуаторщика не должно превышать 50 символов.")
        logger.warning(f"Admin {user_id} entered too long name for evacuator {evacuator_id}: {name}")
        return
    
    # Устанавливаем статус сразу как approved, так как админ добавляет вручную
    cursor.execute("INSERT OR REPLACE INTO evacuators (evacuator_id, username, full_name, status) VALUES (?, ?, ?, ?)",
                   (evacuator_id, username, name, "approved"))
    conn.commit()
    
    await message.reply(
        f"Эвакуаторщик добавлен:\nID: {evacuator_id}\nUsername: @{username}\nИмя: {name}\nСтатус: approved\n\n"
        "Эвакуаторщик готов принимать заказы. Пусть нажмет /start в боте."
    )
    
    # Уведомляем эвакуаторщика
    try:
        await bot.send_message(
            chat_id=evacuator_id,
            text="Вы добавлены как эвакуаторщик! Нажмите /start, чтобы начать принимать заказы."
        )
        logger.info(f"Notified evacuator {evacuator_id} about approval")
    except Exception as e:
        logger.error(f"Failed to notify evacuator {evacuator_id} about approval: {e}")
        await message.reply(f"Не удалось уведомить эвакуаторщика {evacuator_id}: {str(e)}")
    
    cursor.execute("SELECT status FROM evacuators WHERE evacuator_id = ?", (evacuator_id,))
    status = cursor.fetchone()[0]
    logger.info(f"Admin {user_id} registered evacuator {evacuator_id} (Username: {username}, Full Name: {name}) with status {status}")
    
    await state.clear()
    

@dp.callback_query(lambda c: c.data.startswith("approve_evacuator_"))
async def approve_evacuator_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id != ADMIN_ID:
        await callback_query.message.reply("У вас нет прав для выполнения этой команды.")
        await callback_query.answer()
        logger.warning(f"User {user_id} attempted to approve evacuator but is not admin")
        return
    
    evacuator_id = int(callback_query.data.split("approve_evacuator_")[1])
    
    cursor.execute("SELECT username FROM evacuators WHERE evacuator_id = ?", (evacuator_id,))
    evacuator = cursor.fetchone()
    if not evacuator:
        await callback_query.message.reply("Эвакуаторщик не найден.")
        await callback_query.answer()
        logger.warning(f"Admin {user_id} tried to approve evacuator {evacuator_id} but not found")
        return
    
    username = evacuator[0]
    
    cursor.execute("UPDATE evacuators SET status = ? WHERE evacuator_id = ?", ("approved", evacuator_id))
    conn.commit()
    
    await callback_query.message.reply(f"Эвакуаторщик @{username} (ID: {evacuator_id}) одобрен.")
    try:
        await bot.send_message(
            chat_id=evacuator_id,
            text="Вы одобрены как эвакуатор! Нажмите /start, чтобы начать принимать заказы."
        )
        logger.info(f"Notified evacuator {evacuator_id} about approval")
    except Exception as e:
        logger.error(f"Failed to notify evacuator {evacuator_id} about approval: {e}")
        await callback_query.message.reply(f"Не удалось уведомить эвакуаторщика {evacuator_id} об одобрении: {str(e)}")
    
    await callback_query.answer()
    logger.info(f"Admin {user_id} approved evacuator {evacuator_id}")

# Command to remove an evacuator (admin only)
@dp.message(Command(commands=['remove_evacuator']))
async def remove_evacuator(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.reply("У вас нет прав для выполнения этой команды.")
        logger.warning(f"User {user_id} attempted to remove evacuator but is not admin")
        return
    
    if not message.text.startswith('/remove_evacuator '):
        await message.reply("Пожалуйста, укажите Telegram ID эвакуаторщика (например, /remove_evacuator 123456789).")
        return
    
    try:
        evacuator_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.reply("Пожалуйста, укажите корректный Telegram ID (только цифры).")
        return
    
    cursor.execute("SELECT * FROM evacuators WHERE evacuator_id = ?", (evacuator_id,))
    evacuator = cursor.fetchone()
    if not evacuator:
        await message.reply("Эвакуаторщик с таким ID не найден.")
        logger.info(f"Admin {user_id} attempted to remove evacuator {evacuator_id} but not found")
        return
    
    cursor.execute("UPDATE evacuators SET status = ? WHERE evacuator_id = ?", ("removed", evacuator_id))
    conn.commit()
    
    await message.reply(f"Эвакуаторщик с ID {evacuator_id} удален из базы.")
    try:
        await bot.send_message(
            chat_id=evacuator_id,
            text="Вы были удалены из базы эвакуаторщиков."
        )
        logger.info(f"Notified evacuator {evacuator_id} about removal")
    except Exception as e:
        logger.error(f"Failed to notify evacuator {evacuator_id} about removal: {e}")
    
    logger.info(f"Admin {user_id} removed evacuator {evacuator_id}")

# Start command
@dp.message(Command(commands=['start']))
async def send_welcome(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    cursor.execute("SELECT * FROM evacuators WHERE evacuator_id = ?", (user_id,))
    evacuator = cursor.fetchone()
    
    cursor.execute("SELECT * FROM clients WHERE client_id = ?", (user_id,))
    if not cursor.fetchone():
        username = message.from_user.username or "Нет ника"
        name = message.from_user.first_name or ""
        if message.from_user.last_name:
            name += f" {message.from_user.last_name}"
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            INSERT INTO clients (client_id, username, name, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, name, timestamp))
        conn.commit()
        logger.info(f"Added client to database:\n"
                    f"  Client ID: {user_id}\n"
                    f"  Username: {username}\n"
                    f"  Name: {name}\n"
                    f"  Timestamp: {timestamp}")
    
    if evacuator:
        await message.reply("Вы зарегистрированы как эвакуатор. Ожидайте заказы.")
        logger.info(f"User {user_id} identified as evacuator")
    else:
        await message.reply(
            "Здравствуйте! Чтобы заказать эвакуатор, укажите марку и модель автомобиля (например, Toyota Camry).\n"
            "Вы также можете прикрепить фото автомобиля (по желанию):"
        )
        await state.set_state(OrderForm.car)
        await state.update_data(user_id=user_id)
        logger.info(f"User {user_id} started order creation as client")

# Step 1: Collect car make/model and optional photo
@dp.message(StateFilter(OrderForm.car))
async def process_car(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    evacuators = get_approved_evacuators()
    if user_id in evacuators:
        await message.reply("Вы зарегистрированы как эвакуатор. Клиентам: используйте другой аккаунт для создания заказа.")
        await state.clear()
        logger.info(f"User {user_id} attempted to create order but is an evacuator")
        return
    
    if message.photo:
        car = message.caption or "Не указана марка/модель"
        photo_id = message.photo[-1].file_id
        await state.update_data(car=car, photo_id=photo_id)
        logger.info(f"User {user_id} entered car: {car} with photo (file_id: {photo_id})")
    elif message.text:
        car = message.text
        await state.update_data(car=car, photo_id=None)
        logger.info(f"User {user_id} entered car: {car} without photo")
    else:
        await message.reply(
            "Пожалуйста, укажите марку и модель автомобиля (текстом) или прикрепите фото автомобиля (с подписью, если хотите).",
            reply_markup=remove_markup
        )
        logger.warning(f"User {user_id} sent invalid input for car")
        return
    
    await message.reply(
        "Давайте определим местоположение автомобиля. Отправьте вашу текущую геолокацию или введите адрес вручную:",
        reply_markup=location_markup
    )
    await state.set_state(OrderForm.location)

# Step 2: Collect location
@dp.message(StateFilter(OrderForm.location))
async def process_location(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.location:
        lat, lon = message.location.latitude, message.location.longitude
        address = await get_address_from_coordinates(lat, lon)
        location = f"{address} (координаты: {lat}, {lon})"
        await state.update_data(location=location, location_coords=(lat, lon))
        
        await message.reply(
            f"Это местоположение автомобиля?\n{location}",
            reply_markup=confirm_location_buttons
        )
        await state.set_state(OrderForm.confirm_location)
        logger.info(f"User {user_id} sent location: {location}, asking for confirmation")
    elif message.text:
        location = message.text
        await state.update_data(location=location, location_coords=None)
        await message.reply(f"Местоположение сохранено: {location}", reply_markup=remove_markup)
        await message.reply(
            "Укажите конечный пункт (например, автосервис). Отправьте геолокацию или введите адрес вручную.\n\n"
            "Чтобы отправить геолокацию:\n"
            "1. Нажмите на значок скрепки 📎.\n"
            "2. Выберите 'Местоположение'.\n"
            "3. Найдите нужное место или выберите точку на карте.\n"
            "4. Нажмите 'Отправить выбранное местоположение'."
        )
        await state.set_state(OrderForm.destination)
        logger.info(f"User {user_id} entered location as text: {location}")
    else:
        await message.reply(
            "Пожалуйста, отправьте геолокацию или введите адрес вручную.",
            reply_markup=location_markup
        )
        logger.warning(f"User {user_id} sent invalid input for location")
        return

# Step 3: Confirm location
@dp.message(StateFilter(OrderForm.confirm_location))
async def confirm_location(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    location = data.get('location')
    
    if message.text and message.text.lower() == "да":
        await message.reply(f"Местоположение подтверждено: {location}", reply_markup=remove_markup)
        await message.reply(
            "Укажите конечный пункт (например, автосервис). Отправьте геолокацию или введите адрес вручную.\n\n"
            "Чтобы отправить геолокацию:\n"
            "1. Нажмите на значок скрепки 📎.\n"
            "2. Выберите 'Местоположение'.\n"
            "3. Найдите нужное место или выберите точку на карте.\n"
            "4. Нажмите 'Отправить выбранное местоположение'."
        )
        await state.set_state(OrderForm.destination)
        logger.info(f"User {user_id} confirmed location: {location}")
    elif message.text and message.text.lower() == "нет":
        await message.reply(
            "Укажите местоположение автомобиля (геолокацию или текст):",
            reply_markup=location_markup
        )
        await state.set_state(OrderForm.location)
        await state.update_data(location=None, location_coords=None)
        logger.info(f"User {user_id} rejected location: {location}")
    else:
        await message.reply(
            "Пожалуйста, выберите 'Да' или 'Нет'.",
            reply_markup=confirm_location_buttons
        )
        logger.warning(f"User {user_id} sent invalid input during location confirmation")

# Step 4: Collect destination
@dp.message(StateFilter(OrderForm.destination))
async def process_destination(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.location:
        lat, lon = message.location.latitude, message.location.longitude
        address = await get_address_from_coordinates(lat, lon)
        destination = f"{address} (координаты: {lat}, {lon})"
        await state.update_data(destination=destination, destination_coords=(lat, lon))
        logger.info(f"User {user_id} sent destination: {destination}")
    elif message.text:
        destination = message.text
        await state.update_data(destination=destination, destination_coords=None)
        logger.info(f"User {user_id} entered destination as text: {destination}")
    else:
        await message.reply(
            "Пожалуйста, отправьте конечный пункт (геолокацию или текст).\n\n"
            "Чтобы отправить геолокацию:\n"
            "1. Нажмите на значок скрепки 📎.\n"
            "2. Выберите 'Местоположение'.\n"
            "3. Найдите нужное место или выберите точку на карте.\n"
            "4. Нажмите 'Отправить выбранное местоположение'."
        )
        logger.warning(f"User {user_id} sent invalid destination")
        return
    await message.reply(
        f"Конечный пункт: {destination}.",
        reply_markup=confirm_markup
    )
    await state.set_state(OrderForm.destination_confirm)

# Step 5: Confirm destination
@dp.message(StateFilter(OrderForm.destination_confirm))
async def confirm_destination(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    destination = data.get('destination')
    if message.text and message.text.lower() == "подтвердить":
        await message.reply(f"Конечный пункт подтвержден: {destination}.", reply_markup=remove_markup)
        await message.reply(
            "Сколько колес заблокировано у автомобиля?",
            reply_markup=wheels_locked_buttons
        )
        await state.set_state(OrderForm.wheels_locked)
        logger.info(f"User {user_id} confirmed destination: {destination}")
    elif message.location or message.text:
        if message.location:
            lat, lon = message.location.latitude, message.location.longitude
            address = await get_address_from_coordinates(lat, lon)
            destination = f"{address} (координаты: {lat}, {lon})"
            await state.update_data(destination=destination, destination_coords=(lat, lon))
            logger.info(f"User {user_id} updated destination: {destination}")
        else:
            destination = message.text
            await state.update_data(destination=destination, destination_coords=None)
            logger.info(f"User {user_id} updated destination as text: {destination}")
        await message.reply(
            f"Конечный пункт обновлен: {destination}.",
            reply_markup=confirm_markup
        )
    else:
        await message.reply(
            "Пожалуйста, нажмите 'Подтвердить' или введите другой адрес.",
            reply_markup=confirm_markup
        )
        logger.warning(f"User {user_id} sent invalid input during destination confirmation")

# Step 6: Collect wheels locked info
@dp.message(StateFilter(OrderForm.wheels_locked))
async def process_wheels_locked(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    valid_options = ["1 колесо", "2 колеса", "3 колеса", "4 колеса", "Не заблокированы", "Не знаю"]
    if message.text in valid_options:
        wheels_locked = message.text
        await state.update_data(wheels_locked=wheels_locked)
        await message.reply(
            "Когда нужен эвакуатор? Нажмите 'Сейчас' или укажите время (например, '14:30 27.04.2025'):",
            reply_markup=timing_buttons
        )
        await state.set_state(OrderForm.timing)
        logger.info(f"User {user_id} entered wheels locked: {wheels_locked}")
    else:
        await message.reply(
            "Пожалуйста, выберите один из вариантов.",
            reply_markup=wheels_locked_buttons
        )
        logger.warning(f"User {user_id} sent invalid input for wheels locked")

# Step 7: Collect timing
@dp.message(StateFilter(OrderForm.timing))
async def process_timing(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    timing = message.text
    await state.update_data(timing=timing)
    await message.reply(
        "Напишите комментарий к заказу (например, 'машина на обочине') или оставьте пустым, отправив '-':",
        reply_markup=remove_markup
    )
    await state.set_state(OrderForm.comment)
    logger.info(f"User {user_id} entered timing: {timing}")

# Step 8: Collect comment
# Обработчик комментария
# Обработчик комментария
@dp.message(StateFilter(OrderForm.comment))
async def process_comment(message: types.Message, state: FSMContext):
    comment = message.text.strip() if message.text else "Без комментария"
    await state.update_data(comment=comment)
    await state.set_state(OrderForm.phone_number)
    
    await message.reply(
        "Пожалуйста, отправьте ваш номер телефона в формате +79991234567, нажмите 'Отправить номер телефона' или 'Пропустить' (можно отправить '-').",
        reply_markup=phone_markup_client
    )
    logger.info(f"Client {message.from_user.id} entered comment: {comment}")

# Обработчик номера телефона
@dp.message(StateFilter(OrderForm.phone_number))
async def process_phone_number(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    phone_number = None
    if message.contact:
        phone_number = message.contact.phone_number
        logger.info(f"Client {user_id} provided phone number {phone_number} via contact")
    elif message.text:
        if message.text == "-" or message.text.lower() == "пропустить":
            phone_number = None
            logger.info(f"Client {user_id} skipped phone number")
        elif message.text.startswith('+') and message.text[1:].isdigit():
            phone_number = message.text
            logger.info(f"Client {user_id} manually entered phone number {phone_number}")
        else:
            await message.reply(
                "Пожалуйста, отправьте номер телефона в формате +79991234567, нажмите 'Отправить номер телефона' или 'Пропустить' (можно отправить '-').",
                reply_markup=phone_markup_client
            )
            logger.warning(f"Client {user_id} sent invalid phone number: {message.text}")
            return
    else:
        await message.reply(
            "Пожалуйста, отправьте номер телефона в формате +79991234567, нажмите 'Отправить номер телефона' или 'Пропустить' (можно отправить '-').",
            reply_markup=phone_markup_client
        )
        logger.warning(f"Client {user_id} sent invalid input for phone number")
        return
    
    await state.update_data(client_phone_number=phone_number)
    await state.set_state(OrderForm.confirm_order)
    
    # Показываем детали заказа сразу после ввода номера
    await display_order_details(message, state)
    logger.info(f"Client {user_id} provided phone number: {phone_number or 'None'} and moved to order confirmation")

# Step 9: Confirm order, edit fields, or cancel
@dp.message(StateFilter(OrderForm.confirm_order))
async def confirm_order(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    
    if message.text and message.text.lower() == "подтвердить заказ":
        user_id = data.get('user_id')
        location_coords_str = f"{data['location_coords'][0]},{data['location_coords'][1]}" if data.get('location_coords') else None
        destination_coords_str = f"{data['destination_coords'][0]},{data['destination_coords'][1]}" if data.get('destination_coords') else None
        distance = data.get('distance')
        photo_id = data.get('photo_id')
        client_phone_number = data.get('client_phone_number')  # Получаем номер телефона
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            INSERT INTO orders (client_id, car, photo_id, location, location_coords, destination, destination_coords, distance, wheels_locked, timing, comment, status, timestamp, client_phone_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            data['car'],
            photo_id,
            data['location'],
            location_coords_str,
            data['destination'],
            destination_coords_str,
            distance,
            data['wheels_locked'],
            data['timing'],
            data['comment'],
            "pending",
            timestamp,
            client_phone_number  # Добавляем номер телефона
        ))
        conn.commit()
        order_id = cursor.lastrowid
        
        logger.info(f"New order created:\n"
                    f"  Order ID: {order_id}\n"
                    f"  Client ID: {user_id}\n"
                    f"  Car: {data['car']}\n"
                    f"  Photo ID: {photo_id if photo_id else 'None'}\n"
                    f"  Location: {data['location']}\n"
                    f"  Destination: {data['destination']}\n"
                    f"  Distance: {distance if distance else 'Not calculated'}\n"
                    f"  Wheels Locked: {data['wheels_locked']}\n"
                    f"  Timing: {data['timing']}\n"
                    f"  Comment: {data['comment']}\n"
                    f"  Status: pending\n"
                    f"  Timestamp: {timestamp}")
        
        # Убрали уведомление админа о новом заказе
        
        order_details = (
            "📋 *Новый заказ на эвакуатор* #{}\n"
            "🚗 *Марка автомобиля:* {}\n"
            "📍 *Местоположение:* {}\n"
            "🏁 *Конечный пункт:* {}\n"
        ).format(order_id, data['car'], data['location'], data['destination'])
        
        if distance:
            order_details += f"📏 *Расстояние:* {distance}\n"
        order_details += (
            f"🔧 *Заблокированные колеса:* {data['wheels_locked']}\n"
            f"⏰ *Когда нужен эвакуатор:* {data['timing']}\n"
            f"💬 *Комментарий:* {data['comment']}"
        )
        
        evacuators = get_approved_evacuators()
        logger.info(f"Approved evacuators: {evacuators}")
        if not evacuators:
            message_text = (
                "Заказ сохранен, но в данный момент нет доступных эвакуаторов. "
                "Мы уведомим вас, когда появятся новые эвакуаторы.\n"
                # "Хотите создать новый заказ?"
            )
            await notify_and_offer_new_order(user_id, order_id, message_text)
            logger.warning(f"No approved evacuators available to send order #{order_id}")
            try:
                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"⚠️ Заказ #{order_id} не отправлен: нет доступных эвакуаторов."
                )
            except Exception as e:
                logger.error(f"Failed to notify admin about no evacuators for order #{order_id}: {e}")
        else:
            successful_sends = 0
            for evacuator_id in evacuators:
                cursor.execute("SELECT status FROM evacuators WHERE evacuator_id = ?", (evacuator_id,))
                evacuator_status = cursor.fetchone()
                if not evacuator_status or evacuator_status[0] != "approved":
                    logger.warning(f"Evacuator {evacuator_id} is not in 'approved' status, skipping order #{order_id}")
                    continue
                
                try:
                    await bot.send_chat_action(chat_id=evacuator_id, action="typing")
                except Exception as e:
                    logger.error(f"Cannot send message to evacuator {evacuator_id} (possibly blocked or unavailable): {e}")
                    try:
                        await bot.send_message(
                            chat_id=ADMIN_ID,
                            text=f"⚠️ Не удалось отправить заказ #{order_id} эвакуаторщику {evacuator_id}: пользователь недоступен или заблокировал бота."
                        )
                    except Exception as admin_e:
                        logger.error(f"Failed to notify admin about error for evacuator {evacuator_id}: {admin_e}")
                    continue
                
                try:
                    if photo_id:
                        await bot.send_photo(
                            chat_id=evacuator_id,
                            photo=photo_id,
                            caption=order_details,
                            parse_mode="Markdown",
                            reply_markup=evacuator_response_button
                        )
                    else:
                        await bot.send_message(
                            chat_id=evacuator_id,
                            text=order_details,
                            parse_mode="Markdown",
                            reply_markup=evacuator_response_button
                        )
                    successful_sends += 1
                    logger.info(f"Order #{order_id} sent to evacuator {evacuator_id}")
                except Exception as e:
                    logger.error(f"Failed to send order #{order_id} to evacuator {evacuator_id}: {e}")
                    try:
                        await bot.send_message(
                            chat_id=ADMIN_ID,
                            text=f"⚠️ Не удалось отправить заказ #{order_id} эвакуаторщику {evacuator_id}: {str(e)}"
                        )
                    except Exception as admin_e:
                        logger.error(f"Failed to notify admin about error for evacuator {evacuator_id}: {admin_e}")
            
            if successful_sends > 0:
                message_text = (
                    f"Заказ отправлен {successful_sends} эвакуаторам! Ожидайте предложений.\n"
                    "Если хотите отменить заказ или создать новый, выберите действие:"
                )
                await notify_and_offer_new_order(user_id, order_id, message_text, show_cancel_button=True)
                logger.info(f"User {user_id} confirmed order #{order_id} and sent to {successful_sends}/{len(evacuators)} evacuators")
            else:
                message_text = (
                    "Заказ сохранен, но не удалось отправить эвакуаторам. "
                    "Администратор уведомлен.\n"
                    "Хотите создать новый заказ?"
                )
                await notify_and_offer_new_order(user_id, order_id, message_text)
                logger.warning(f"Order #{order_id} could not be sent to any evacuators")
        await state.clear()
    elif message.text and message.text.lower() == "отменить заказ":
        user_id = data.get('user_id')
        await state.clear()
        message_text = "Заказ отменен, так как он еще не был отправлен эвакуаторам.\nХотите создать новый заказ?"
        await notify_and_offer_new_order(user_id, None, message_text, is_canceled=False)
        logger.info(f"User {user_id} canceled order before confirmation")
    elif message.text and message.text.lower() == "изменить автомобиль":
        await message.reply("Укажите новую марку и модель автомобиля (например, Toyota Camry):")
        await state.set_state(OrderForm.edit_car)
        logger.info(f"User {user_id} chose to edit car")
    elif message.text and message.text.lower() == "добавить/изменить фото":
        await message.reply("Прикрепите новое фото автомобиля (с подписью, если хотите):")
        await state.set_state(OrderForm.edit_photo)
        logger.info(f"User {user_id} chose to add/change photo")
    elif message.text and message.text.lower() == "изменить местоположение":
        await message.reply("Укажите новое местоположение автомобиля:", reply_markup=location_markup)
        await state.set_state(OrderForm.edit_location)
        logger.info(f"User {user_id} chose to edit location")
    elif message.text and message.text.lower() == "изменить конечный пункт":
        await message.reply("Укажите новый конечный пункт (геолокацию или текст):")
        await state.set_state(OrderForm.edit_destination)
        logger.info(f"User {user_id} chose to edit destination")
    elif message.text and message.text.lower() == "изменить статус колес":
        await message.reply("Сколько колес заблокировано у автомобиля?", reply_markup=wheels_locked_buttons)
        await state.set_state(OrderForm.edit_wheels_locked)
        logger.info(f"User {user_id} chose to edit wheels locked")
    elif message.text and message.text.lower() == "изменить время":
        await message.reply("Когда нужен эвакуатор? Нажмите 'Сейчас' или укажите время:", reply_markup=timing_buttons)
        await state.set_state(OrderForm.edit_timing)
        logger.info(f"User {user_id} chose to edit timing")
    elif message.text and message.text.lower() == "изменить комментарий":
        await message.reply("Введите новый комментарий к заказу или отправьте '-' для пропуска:")
        await state.set_state(OrderForm.edit_comment)
        logger.info(f"User {user_id} chose to edit comment")
    else:
        await message.reply("Пожалуйста, выберите одну из опций.", reply_markup=order_confirm_buttons)
        logger.warning(f"User {user_id} sent invalid input during order confirmation")
        
# Edit handlers
@dp.message(StateFilter(OrderForm.edit_car))
async def edit_car(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.text:
        car = message.text
        await state.update_data(car=car)
        logger.info(f"User {user_id} edited car to: {car}")
    else:
        await message.reply("Пожалуйста, укажите марку и модель автомобиля (текстом).")
        logger.warning(f"User {user_id} sent invalid input for editing car")
        return
    await state.set_state(OrderForm.confirm_order)
    await display_order_details(message, state)

@dp.message(StateFilter(OrderForm.edit_photo))
async def edit_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.photo:
        photo_id = message.photo[-1].file_id
        data = await state.get_data()
        car = message.caption if message.caption else data.get('car', "Не указана марка/модель")
        await state.update_data(photo_id=photo_id, car=car)
        logger.info(f"User {user_id} edited photo (file_id: {photo_id}) and car to: {car}")
    else:
        await message.reply("Пожалуйста, прикрепите фото автомобиля.")
        logger.warning(f"User {user_id} sent invalid input for editing photo")
        return
    await state.set_state(OrderForm.confirm_order)
    await display_order_details(message, state)

@dp.message(StateFilter(OrderForm.edit_location))
async def edit_location(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.location:
        lat, lon = message.location.latitude, message.location.longitude
        address = await get_address_from_coordinates(lat, lon)
        location = f"{address} (координаты: {lat}, {lon})"
        await state.update_data(location=location, location_coords=(lat, lon), distance=None)
        logger.info(f"User {user_id} edited location to: {location}")
    elif message.text:
        location = message.text
        await state.update_data(location=location, location_coords=None, distance=None)
        logger.info(f"User {user_id} edited location to (text): {location}")
    else:
        await message.reply("Пожалуйста, отправьте геолокацию или введите адрес вручную.", reply_markup=location_markup)
        logger.warning(f"User {user_id} sent invalid input for editing location")
        return
    await state.set_state(OrderForm.confirm_order)
    await display_order_details(message, state)

@dp.message(StateFilter(OrderForm.edit_destination))
async def edit_destination(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.location:
        lat, lon = message.location.latitude, message.location.longitude
        address = await get_address_from_coordinates(lat, lon)
        destination = f"{address} (координаты: {lat}, {lon})"
        await state.update_data(destination=destination, destination_coords=(lat, lon), distance=None)
        logger.info(f"User {user_id} edited destination to: {destination}")
    elif message.text:
        destination = message.text
        await state.update_data(destination=destination, destination_coords=None, distance=None)
        logger.info(f"User {user_id} edited destination to (text): {destination}")
    else:
        await message.reply("Пожалуйста, отправьте геолокацию или введите адрес вручную.")
        logger.warning(f"User {user_id} sent invalid input for editing destination")
        return
    await state.set_state(OrderForm.confirm_order)
    await display_order_details(message, state)

@dp.message(StateFilter(OrderForm.edit_wheels_locked))
async def edit_wheels_locked(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    valid_options = ["1 колесо", "2 колеса", "3 колеса", "4 колеса", "Не заблокированы", "Не знаю"]
    if message.text in valid_options:
        wheels_locked = message.text
        await state.update_data(wheels_locked=wheels_locked)
        logger.info(f"User {user_id} edited wheels locked to: {wheels_locked}")
    else:
        await message.reply("Пожалуйста, выберите один из вариантов.", reply_markup=wheels_locked_buttons)
        logger.warning(f"User {user_id} sent invalid input for editing wheels locked")
        return
    await state.set_state(OrderForm.confirm_order)
    await display_order_details(message, state)

@dp.message(StateFilter(OrderForm.edit_timing))
async def edit_timing(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    timing = message.text
    await state.update_data(timing=timing)
    logger.info(f"User {user_id} edited timing to: {timing}")
    await state.set_state(OrderForm.confirm_order)
    await display_order_details(message, state)

@dp.message(StateFilter(OrderForm.edit_comment))
async def edit_comment(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    comment = message.text if message.text != "-" else "Без комментария"
    await state.update_data(comment=comment)
    logger.info(f"User {user_id} edited comment to: {comment}")
    await state.set_state(OrderForm.confirm_order)
    await display_order_details(message, state)

# Evacuator response
@dp.callback_query(lambda c: c.data == "respond_to_order")
async def evacuator_respond(callback_query: types.CallbackQuery, state: FSMContext):
    evacuator_id = callback_query.from_user.id
    evacuators = get_approved_evacuators()
    if evacuator_id not in evacuators:
        await callback_query.message.reply("Вы не зарегистрированы как эвакуаторщик.")
        await callback_query.answer()
        logger.warning(f"User {evacuator_id} attempted to respond but is not an approved evacuator")
        return
    
    message_text = callback_query.message.text or callback_query.message.caption
    try:
        order_id = int(message_text.split('#')[1].split('\n')[0])
    except (IndexError, ValueError) as e:
        logger.error(f"Failed to parse order_id from message: {message_text}, Error: {e}")
        await callback_query.message.reply("Произошла ошибка при обработке заказа. Пожалуйста, попробуйте снова позже.")
        await callback_query.answer()
        return
    
    cursor.execute("SELECT status FROM orders WHERE order_id = ?", (order_id,))
    order = cursor.fetchone()
    if not order:
        logger.warning(f"Order #{order_id} not found for evacuator {evacuator_id}")
        await callback_query.message.reply("Заказ не найден.")
        await callback_query.answer()
        return
    
    status = order[0]
    logger.info(f"Order #{order_id} status: {status}")
    if status != "pending":
        logger.info(f"Order #{order_id} status is {status} for evacuator {evacuator_id}")
        await callback_query.message.reply("Заказ уже принят другим эвакуатором или отменен.")
        await callback_query.answer()
        return
    
    cursor.execute("SELECT * FROM responses WHERE order_id = ? AND evacuator_id = ?", (order_id, evacuator_id))
    if cursor.fetchone():
        await callback_query.message.reply("Вы уже отправили предложение для этого заказа.")
        await callback_query.answer()
        logger.info(f"Evacuator {evacuator_id} attempted to respond to order #{order_id} but already responded")
        return
    
    cursor.execute("SELECT username, phone_number FROM evacuators WHERE evacuator_id = ?", (evacuator_id,))
    evacuator = cursor.fetchone()
    if not evacuator:
        logger.error(f"Evacuator {evacuator_id} not found in database")
        await callback_query.message.reply("Ошибка: Ваши данные не найдены. Обратитесь к администратору.")
        await callback_query.answer()
        return
    evacuator_username = evacuator[0] if evacuator[0] else "Неизвестно"
    phone_number = evacuator[1] if evacuator[1] else "Не указан"
    
    # Очищаем старое состояние, чтобы избежать наложения
    await state.clear()
    await state.update_data(
        order_id=order_id,
        evacuator_id=evacuator_id,
        evacuator_username=evacuator_username
    )
    await state.set_state(OrderForm.evacuator_price)
    
    await bot.send_message(
        chat_id=evacuator_id,
        text="Укажите вашу цену (например, '5000' или '5000 руб'):",
        reply_markup=remove_markup
    )
    await callback_query.answer()
    logger.info(f"Evacuator {evacuator_id} (Username: {evacuator_username}, Phone: {phone_number}) is responding to order #{order_id}")

@dp.message(StateFilter(OrderForm.evacuator_price))
async def collect_evacuator_price(message: types.Message, state: FSMContext):
    if not message.text:
        await message.reply("Пожалуйста, укажите цену в текстовом формате.")
        logger.warning(f"Evacuator {message.from_user.id} sent invalid price")
        return
    
    price = message.text.strip()
    if not any(char.isdigit() for char in price):
        await message.reply("Пожалуйста, укажите корректную цену (например, '5000' или '5000 руб').")
        logger.warning(f"Evacuator {message.from_user.id} sent invalid price format: {price}")
        return
    
    await state.update_data(price=price)
    await state.set_state(OrderForm.evacuator_time)
    await message.reply("Укажите время (например, '30' или '30 минут'):")
    logger.info(f"Evacuator {message.from_user.id} entered price: {price}")

@dp.message(StateFilter(OrderForm.evacuator_time))
async def collect_evacuator_time(message: types.Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get('order_id')
    evacuator_id = data.get('evacuator_id')
    price = data.get('price')
    
    if not order_id or not evacuator_id or not price:
        await message.reply("Ошибка: выберите заказ заново, нажав на кнопку 'Указать цену и время'.")
        await state.clear()
        logger.warning(f"Evacuator {message.from_user.id} attempted to enter time but state is invalid: order_id={order_id}, evacuator_id={evacuator_id}, price={price}")
        return
    
    if not message.text:
        await message.reply("Пожалуйста, укажите время в текстовом формате.")
        logger.warning(f"Evacuator {message.from_user.id} sent invalid time")
        return
    
    time = message.text.strip()
    time_num = ''.join(filter(str.isdigit, time))
    if not time_num:
        await message.reply("Пожалуйста, укажите корректное время (например, '30' или '30 минут').")
        logger.warning(f"Evacuator {message.from_user.id} sent invalid time format: {time}")
        return
    
    time_value = int(time_num)
    if time_value > 1440:
        await message.reply("Время не может превышать 24 часов (1440 минут).")
        logger.warning(f"Evacuator {message.from_user.id} entered too large time: {time}")
        return
    
    cursor.execute("SELECT client_id, status FROM orders WHERE order_id = ?", (order_id,))
    order = cursor.fetchone()
    if not order:
        logger.warning(f"Order #{order_id} not found for evacuator {evacuator_id}")
        await message.reply("Заказ не найден.")
        await state.clear()
        return
    
    user_id = order[0]
    status = order[1]
    logger.info(f"Order #{order_id} status: {status}")
    if status != "pending":
        logger.info(f"Order #{order_id} status is {status} for evacuator {evacuator_id}")
        await message.reply("Заказ уже принят другим эвакуатором или отменен. Ожидайте новые заказы.")
        await state.clear()
        return
    
    evacuator_username = data.get('evacuator_username')
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    price_time = f"{price}, {time}"
    evacuator_comment = "Без комментария"
    
    cursor.execute('''
        INSERT INTO responses (order_id, evacuator_id, price_time, evacuator_comment, evacuator_username, client_decision, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        order_id,
        evacuator_id,
        price_time,
        evacuator_comment,
        evacuator_username,
        "pending",
        timestamp
    ))
    conn.commit()
    response_id = cursor.lastrowid
    
    logger.info(f"Evacuator response submitted:\n"
                f"  Response ID: {response_id}\n"
                f"  Order ID: {order_id}\n"
                f"  Evacuator ID: {evacuator_id}\n"
                f"  Username: {evacuator_username}\n"
                f"  Price/Time: {price_time}\n"
                f"  Comment: {evacuator_comment}\n"
                f"  Timestamp: {timestamp}")
    
    await message.reply("Ваше предложение отправлено клиенту. Ожидайте ответа.", reply_markup=remove_markup)
    
    cursor.execute("SELECT * FROM responses WHERE order_id = ? AND client_decision = 'pending'", (order_id,))
    responses = cursor.fetchall()
    
    if responses:
        offers_message = f"📋 *Предложения для заказа #{order_id}:*\n\n"
        inline_buttons = []
        for idx, response in enumerate(responses, 1):
            response_id = response[0]
            price_time = response[3]
            offers_message += f"💼 *Предложение {idx}:* {price_time}\n"
            inline_buttons.append([InlineKeyboardButton(
                text=f"Выбрать предложение {idx}",
                callback_data=f"select_offer_{response_id}"
            )])
        inline_buttons.append([InlineKeyboardButton(
            text="Ожидать другие предложения",
            callback_data="wait_for_offers"
        )])
        offers_keyboard = InlineKeyboardMarkup(inline_keyboard=inline_buttons)
        
        try:
            await bot.send_message(
                chat_id=user_id,
                text=offers_message,
                parse_mode="Markdown",
                reply_markup=offers_keyboard
            )
            logger.info(f"Sent list of {len(responses)} offers to client {user_id} for order #{order_id}")
        except Exception as e:
            logger.error(f"Failed to send offers to client {user_id} for order #{order_id}: {e}")
    
    await state.clear()

def parse_price_time(price_time: str) -> tuple[str, str]:
    try:
        price, time = price_time.split(',')
        price = price.strip()
        time = time.strip()
        return price, time
    except ValueError:
        logger.error(f"Invalid price_time format: {price_time}")
        return "Не указана", "Не указано"
    
# Client selects an offer
@dp.callback_query(lambda c: c.data.startswith("select_offer_") or c.data == "wait_for_offers")
async def handle_client_response(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    message_text = callback_query.message.text
    order_id = int(message_text.split('#')[1].split(':')[0])
    
    logger.info(f"Client {user_id} is handling response for order #{order_id}")
    
    cursor.execute("SELECT status, car, location, destination, distance, wheels_locked, timing, comment, client_phone_number FROM orders WHERE order_id = ? AND client_id = ?", (order_id, user_id))
    order = cursor.fetchone()
    if not order:
        await callback_query.message.edit_text("Заказ не найден.")
        await callback_query.answer()
        logger.warning(f"Order #{order_id} not found for client {user_id}")
        return
    
    status, car, location, destination, distance, wheels_locked, timing, comment, client_phone_number = order
    if status != "pending":
        cursor.execute("SELECT evacuator_id, evacuator_username FROM responses WHERE order_id = ? AND client_decision = 'accepted'", (order_id,))
        accepted_response = cursor.fetchone()
        if accepted_response:
            evacuator_id, evacuator_username = accepted_response
            cursor.execute("SELECT phone_number FROM evacuators WHERE evacuator_id = ?", (evacuator_id,))
            evacuator = cursor.fetchone()
            phone_number = evacuator[0] if evacuator else "Не указан"
            contact_message = f"Эвакуаторщик: @{evacuator_username}\nНомер телефона: +{phone_number}"
            await callback_query.message.edit_text(
                f"📋 *Предложения для заказа #{order_id}:*\n\n"
                f"✅ Вы уже выбрали предложение. Контакт эвакуаторщика:\n{contact_message}",
                parse_mode="Markdown"
            )
        else:
            await callback_query.message.edit_text("Вы уже выбрали предложение для этого заказа.")
        await callback_query.answer()
        logger.info(f"Client {user_id} tried to select offer for order #{order_id} but status is {status}")
        return
    
    if data == "wait_for_offers":
        await callback_query.message.reply("Вы решили ожидать другие предложения.")
        logger.info(f"Client {user_id} chose to wait for more offers for order #{order_id}")
        await callback_query.answer()
        return
    
    response_id = int(data.split("select_offer_")[1])
    cursor.execute("SELECT evacuator_id, price_time, evacuator_username FROM responses WHERE response_id = ? AND order_id = ?", (response_id, order_id))
    response = cursor.fetchone()
    if not response:
        await callback_query.message.edit_text("Предложение не найдено.")
        await callback_query.answer()
        logger.warning(f"Response {response_id} not found for order #{order_id}")
        return
    
    evacuator_id, price_time, evacuator_username = response
    cursor.execute("SELECT phone_number FROM evacuators WHERE evacuator_id = ?", (evacuator_id,))
    evacuator = cursor.fetchone()
    phone_number = evacuator[0] if evacuator else "Не указан"
    
    # Получаем username клиента
    client_username = callback_query.from_user.username
    client_username_display = f"@{client_username}" if client_username else "Не указан"
    
    # Сохраняем время одобрения
    accepted_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("UPDATE orders SET status = 'accepted', accepted_timestamp = ? WHERE order_id = ?", (accepted_timestamp, order_id))
    cursor.execute("UPDATE responses SET client_decision = 'rejected' WHERE order_id = ? AND response_id != ?", (order_id, response_id))
    cursor.execute("UPDATE responses SET client_decision = 'accepted' WHERE response_id = ?", (response_id,))
    conn.commit()
    
    price, time = parse_price_time(price_time)
    # Сообщение клиенту
    contact_message = (
        f"📋 Заказ #{order_id}\n"
        # f"✅ Вы выбрали предложение: {price_time}\n"
        f"✅ Вы выбрали предложение:\n"
        f"💰 Цена: {price} руб.\n"
        f"⏰ Время: {time} минут\n\n"
        f"Контакт эвакуаторщика:\n"
        f"Эвакуаторщик: @{evacuator_username}\n"
        f"Номер телефона: +{phone_number}\n\n"
        "Пожалуйста, свяжитесь с эвакуаторщиком для подтверждения."
    )
    
    await callback_query.message.edit_text(
        contact_message,
        parse_mode="Markdown"
    )
    
    # Уведомление эвакуатору
    client_phone_display = client_phone_number if client_phone_number else "Не указан"
    try:
        await bot.send_message(
            chat_id=evacuator_id,
            text=(
                f"Ваше предложение для заказа #{order_id} принято!\n"
                f"Цена и время: {price_time}\n"
                f"Свяжитесь с клиентом: {client_username_display} (ID: {user_id})\n"
                f"Номер телефона клиента: +{client_phone_display}"
            )
        )
        logger.info(f"Notified evacuator {evacuator_id} that their offer for order #{order_id} was accepted")
    except Exception as e:
        logger.error(f"Failed to notify evacuator {evacuator_id} about order #{order_id} acceptance: {e}")
    
    # Уведомление отклоненным эвакуаторам
    cursor.execute("SELECT * FROM responses WHERE order_id = ? AND client_decision = 'rejected'", (order_id,))
    rejected_responses = cursor.fetchall()
    for rejected in rejected_responses:
        rejected_evacuator_id = rejected[2]
        try:
            await bot.send_message(
                chat_id=rejected_evacuator_id,
                text=f"Ваше предложение для заказа #{order_id} было отклонено."
            )
            logger.info(f"Notified evacuator {rejected_evacuator_id} that their offer for order #{order_id} was rejected")
        except Exception as e:
            logger.error(f"Failed to notify evacuator {rejected_evacuator_id} about rejection: {e}")
    
    # Уведомление администратору
    admin_message = (
        f"📋 *Заказ #{order_id} одобрен клиентом*\n\n"
        f"🚗 *Автомобиль:* {car}\n"
        f"📍 *Местоположение:* {location}\n"
        f"🏁 *Конечный пункт:* {destination}\n"
        f"📏 *Расстояние:* {distance or 'Не указано'}\n"
        f"🔧 *Заблокированные колеса:* {wheels_locked}\n"
        f"⏰ *Время:* {timing}\n"
        f"💬 *Комментарий:* {comment}\n\n"
        f"💼 *Выбранное предложение:*\n"
        f"Цена и время: {price_time}\n"
        f"Эвакуаторщик: @{evacuator_username}\n"
        f"Номер телефона: +{phone_number}\n\n"
        f"👤 *Клиент:* {client_username_display} (ID: {user_id})"
        f"📞 *Номер телефона клиента:* {client_phone_display}"  # Добавлено
    )
    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_message,
            parse_mode="Markdown"
        )
        logger.info(f"Notified admin {ADMIN_ID} about accepted order #{order_id}")
    except Exception as e:
        logger.error(f"Failed to notify admin {ADMIN_ID} about accepted order #{order_id}: {e}")
    
    # # Запрос отзыва у клиента
    # await callback_query.message.reply(
    #     "После завершения заказа, пожалуйста, оставьте отзыв.",
    #     reply_markup=new_order_button
    # )
    
    # Запускаем задачу для запроса отзыва через 24 часа
    asyncio.create_task(request_feedback_later(user_id, order_id, client_username_display))
    
    await callback_query.answer()
    logger.info(f"Client {user_id} selected offer {response_id} for order #{order_id}")

async def request_feedback_later(client_id: int, order_id: int, client_username: str):
    # await asyncio.sleep(60)
    await asyncio.sleep(24 * 3600)  # Ждем 24 часа
    
    # Проверяем, не оставлен ли уже отзыв
    cursor.execute("SELECT * FROM feedback WHERE order_id = ? AND client_id = ?", (order_id, client_id))
    if cursor.fetchone():
        logger.info(f"Feedback for order #{order_id} by client {client_id} already exists, skipping request")
        return
    
    # Создаем клавиатуру для оценки
    rating_buttons = [
        [InlineKeyboardButton(text=str(i), callback_data=f"rate_{order_id}_{i}") for i in range(1, 6)]
    ]
    rating_keyboard = InlineKeyboardMarkup(inline_keyboard=rating_buttons)
    
    try:
        await bot.send_message(
            chat_id=client_id,
            text=(
                f"📋 Заказ #{order_id}\n"
                "Пожалуйста, оцените услугу (от 1 до 5) и оставьте отзыв. "
                "Также укажите, что можно убрать или добавить для улучшения сервиса."
            ),
            reply_markup=rating_keyboard,
            parse_mode="Markdown"
        )
        logger.info(f"Requested feedback for order #{order_id} from client {client_id} ({client_username})")
    except Exception as e:
        logger.error(f"Failed to request feedback for order #{order_id} from client {client_id}: {e}")

@dp.callback_query(lambda c: c.data.startswith("rate_"))
async def process_feedback_rating_callback(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    try:
        _, order_id, rating = callback_query.data.split("_")
        order_id = int(order_id)
        rating = int(rating)
    except ValueError:
        await callback_query.message.reply("Ошибка обработки оценки. Попробуйте снова.")
        await callback_query.answer()
        logger.error(f"Invalid callback data for user {user_id}: {callback_query.data}")
        return

    cursor.execute("SELECT * FROM orders WHERE order_id = ? AND client_id = ?", (order_id, user_id))
    order = cursor.fetchone()
    if not order:
        await callback_query.message.reply("Заказ не найден или вы не можете оставить отзыв.")
        await callback_query.answer()
        logger.warning(f"Order #{order_id} not found for client {user_id} during feedback")
        return

    cursor.execute("SELECT * FROM feedback WHERE order_id = ? AND client_id = ?", (order_id, user_id))
    if cursor.fetchone():
        await callback_query.message.reply("Вы уже оставили отзыв для этого заказа.")
        await callback_query.answer()
        logger.info(f"Client {user_id} tried to leave feedback for order #{order_id} but already exists")
        return

    await state.update_data(order_id=order_id, user_id=user_id, rating=rating)
    await callback_query.message.reply(
        "Спасибо за оценку! Укажите, что можно убрать или добавить для улучшения сервиса (или отправьте '-' для пропуска):",
        reply_markup=remove_markup
    )
    await state.set_state(FeedbackForm.comment)
    await callback_query.answer()
    logger.info(f"Client {user_id} rated order #{order_id} with {rating} stars")

@dp.message(StateFilter(FeedbackForm.comment))
async def process_feedback_comment(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    comment = message.text.strip()
    
    data = await state.get_data()
    order_id = data.get('order_id')
    rating = data.get('rating')
    
    if not order_id or not rating:
        await message.reply("Ошибка: данные отзыва не найдены. Попробуйте снова.")
        await state.clear()
        logger.error(f"Missing feedback data for user {user_id}, order #{order_id}")
        return
    
    # Проверяем, что заказ существует
    cursor.execute("SELECT * FROM orders WHERE order_id = ? AND client_id = ?", (order_id, user_id))
    order = cursor.fetchone()
    if not order:
        await message.reply("Заказ не найден.")
        await state.clear()
        logger.warning(f"Order #{order_id} not found for client {user_id} during feedback")
        return
    
    # Если пользователь пропустил комментарий
    if comment == '-' or comment.lower() == 'пропустить':
        comment = None
    
    # Сохраняем отзыв в базу данных
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        cursor.execute('''
            INSERT INTO feedback (order_id, client_id, rating, comment, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (order_id, user_id, rating, comment, timestamp))
        conn.commit()
        await message.reply(
            f"Спасибо за ваш отзыв о заказе #{order_id}! Хотите создать новый заказ?",
            reply_markup=new_order_button
        )
        logger.info(f"Feedback saved for order #{order_id} by client {user_id}: rating={rating}, comment={comment or 'None'}")
        
        # Отправляем отзыв администратору
        client_username = message.from_user.username
        client_username_display = f"@{client_username}" if client_username else "Не указан"
        admin_feedback_message = (
            f"📋 *Отзыв о заказе #{order_id}*\n\n"
            f"👤 *Клиент:* {client_username_display} (ID: {user_id})\n"
            f"⭐ *Оценка:* {rating}\n"
            f"💬 *Комментарий:* {comment or 'Отсутствует'}\n"
            f"⏰ *Время:* {timestamp}"
        )
        try:
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_feedback_message,
                parse_mode="Markdown"
            )
            logger.info(f"Notified admin {ADMIN_ID} about feedback for order #{order_id}")
        except Exception as e:
            logger.error(f"Failed to notify admin {ADMIN_ID} about feedback for order #{order_id}: {e}")
    
    except sqlite3.OperationalError as e:
        await message.reply("Ошибка при сохранении отзыва. Обратитесь к администратору.")
        logger.error(f"Failed to save feedback for order #{order_id} by client {user_id}: {e}")
    
    await state.clear()

# Create a new order
@dp.message(lambda message: message.text == "Создать новый заказ")
async def create_new_order(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    evacuators = get_approved_evacuators()
    if user_id in evacuators:
        await message.reply("Вы зарегистрированы как эвакуаторщик.")
        logger.info(f"User {user_id} attempted to create order but is an evacuator")
        return
    
    await message.reply(
        "Укажите марку и модель автомобиля (например, Toyota Camry).\n"
        "Вы также можете прикрепить фото автомобиля (по желанию):",
        reply_markup=remove_markup
    )
    await state.set_state(OrderForm.car)
    await state.update_data(user_id=user_id)
    logger.info(f"User {user_id} started new order creation")

# Command for clients to cancel their pending orders
@dp.message(lambda message: message.text == "Отменить заказ" or message.text.startswith('/cancel_order'))
async def cancel_order(message: types.Message):
    user_id = message.from_user.id
    cursor.execute("SELECT * FROM orders WHERE client_id = ? AND status = 'pending' ORDER BY timestamp DESC LIMIT 1", (user_id,))
    order = cursor.fetchone()
    if not order:
        await message.reply("У вас нет активных заказов для отмены.\nХотите создать новый заказ?",
                            reply_markup=new_order_button)
        logger.info(f"User {user_id} attempted to cancel order but no pending orders found")
        return
    
    order_id = order[0]
    cursor.execute("UPDATE orders SET status = ? WHERE order_id = ?", ("canceled", order_id))
    conn.commit()
    
    message_text = f"Ваш заказ #{order_id} успешно отменен.\nХотите создать новый заказ?"
    await notify_and_offer_new_order(user_id, order_id, message_text, is_canceled=True)
    logger.info(f"User {user_id} canceled order #{order_id}")

# Command to request feedback (for testing)
@dp.message(Command(commands=['request_feedback']))
async def request_feedback(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    cursor.execute("SELECT order_id FROM orders WHERE client_id = ? AND status = 'accepted' ORDER BY timestamp DESC LIMIT 1", (user_id,))
    order = cursor.fetchone()
    if not order:
        await message.reply("У вас нет завершенных заказов для оценки.\nХотите создать новый заказ?",
                            reply_markup=new_order_button)
        return
    
    order_id = order[0]
    await state.update_data(order_id=order_id, user_id=user_id)
    await message.reply("Пожалуйста, оцените услугу от 1 до 5:", reply_markup=rating_buttons)
    await state.set_state(FeedbackForm.rating)

@dp.message(StateFilter(FeedbackForm.rating))
async def process_feedback_rating(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.text not in ["1", "2", "3", "4", "5"]:
        await message.reply("Пожалуйста, выберите оценку от 1 до 5.", reply_markup=rating_buttons)
        return
    
    rating = int(message.text)
    await state.update_data(rating=rating)
    await message.reply("Что вам понравилось? (или отправьте '-' для пропуска)", reply_markup=remove_markup)
    await state.set_state(FeedbackForm.pros)

# @dp.message(StateFilter(FeedbackForm.pros))
# async def process_feedback_pros(message: types.Message, state: FSMContext):
#     pros = message.text if message.text != "-" else "Без комментария"
#     await state.update_data(pros=pros)
#     await message.reply("Что можно улучшить? (или отправьте '-' для пропуска)")
#     await state.set_state(FeedbackForm.cons)

# @dp.message(StateFilter(FeedbackForm.cons))
# async def process_feedback_cons(message: types.Message, state: FSMContext):
#     cons = message.text if message.text != "-" else "Без комментария"
#     data = await state.get_data()
#     order_id = data.get('order_id')
#     user_id = data.get('user_id')
#     rating = data.get('rating')
#     timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # cursor.execute('''
    #     INSERT INTO feedback (order_id, client_id, rating, pros, cons, timestamp)
    #     VALUES (?, ?, ?, ?, ?, ?)
    # ''', (order_id, user_id, rating, pros, cons, timestamp))
    # conn.commit()
    
    # await message.reply("Спасибо за ваш отзыв!\nХотите создать новый заказ?", reply_markup=new_order_button)
    # logger.info(f"Feedback submitted:\n"
    #             f"  Order ID: {order_id}\n"
    #             f"  Client ID: {user_id}\n"
    #             f"  Rating: {rating}\n"
    #             f"  Pros: {pros}\n"
    #             f"  Cons: {cons}\n"
    #             f"  Timestamp: {timestamp}")
    # await state.clear()

# Command to resend a specific order (admin only)
@dp.message(Command(commands=['resend_order']))
async def resend_order(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.reply("У вас нет прав для выполнения этой команды.")
        logger.warning(f"User {user_id} attempted to resend order but is not admin")
        return
    
    if not message.text.startswith('/resend_order '):
        await message.reply("Пожалуйста, укажите ID заказа (например, /resend_order 4).")
        return
    
    try:
        order_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.reply("Пожалуйста, укажите корректный ID заказа (только цифры).")
        return
    
    cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    order = cursor.fetchone()
    if not order:
        await message.reply(f"Заказ #{order_id} не найден.")
        logger.warning(f"Order #{order_id} not found for resending")
        return
    if order[12] != "pending":
        await message.reply(f"Заказ #{order_id} уже имеет статус {order[12]} и не может быть отправлен.")
        logger.info(f"Order #{order_id} status is {order[12]}, cannot resend")
        return
    
    client_id = order[1]
    car = order[2]
    photo_id = order[3]
    location = order[4]
    destination = order[6]
    distance = order[8]
    wheels_locked = order[9]
    timing = order[10]
    comment = order[11]
    
    order_details = (
        "📋 *Новый заказ на эвакуатор* #{}\n"
        "🚗 *Марка автомобиля:* {}\n"
        "📍 *Местоположение:* {}\n"
        "🏁 *Конечный пункт:* {}\n"
    ).format(order_id, car, location, destination)
    
    if distance:
        order_details += f"📏 *Расстояние:* {distance}\n"
    order_details += (
        f"🔧 *Заблокированные колеса:* {wheels_locked}\n"
        f"⏰ *Когда нужен эвакуатор:* {timing}\n"
        f"💬 *Комментарий:* {comment}"
    )
    
    evacuators = get_approved_evacuators()
    if not evacuators:
        await message.reply("Нет доступных эвакуаторов для отправки заказа.")
        logger.warning(f"No approved evacuators available to resend order #{order_id}")
        return
    
    successful_sends = 0
    for evacuator_id in evacuators:
        try:
            if photo_id:
                await bot.send_photo(
                    chat_id=evacuator_id,
                    photo=photo_id,
                    caption=order_details,
                    parse_mode="Markdown",
                    reply_markup=evacuator_response_button
                )
            else:
                await bot.send_message(
                    chat_id=evacuator_id,
                    text=order_details,
                    parse_mode="Markdown",
                    reply_markup=evacuator_response_button
                )
            successful_sends += 1
            logger.info(f"Order #{order_id} resent to evacuator {evacuator_id}")
        except Exception as e:
            logger.error(f"Failed to resend order #{order_id} to evacuator {evacuator_id}: {e}")
    
    if successful_sends > 0:
        try:
            await bot.send_message(
                chat_id=client_id,
                text=f"Ваш заказ #{order_id} был повторно отправлен {successful_sends} эвакуаторам."
            )
            logger.info(f"Notified client {client_id} that order #{order_id} was resent to {successful_sends} evacuators")
        except Exception as e:
            logger.error(f"Failed to notify client {client_id} about order #{order_id} resend: {e}")
        await message.reply(f"Заказ #{order_id} успешно отправлен {successful_sends} эвакуаторам.")
    else:
        await message.reply("Не удалось отправить заказ ни одному эвакуатору из-за ошибок.")
        logger.warning(f"Failed to resend order #{order_id} to any evacuators")

async def main():
    logger.info("Bot started")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())