import logging
import json
import os
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ApplicationBuilder
)
from telegram.constants import ParseMode
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Часовой пояс (Москва)
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Админ-аккаунт
ADMIN_CREDENTIALS = {
    "login": "AdminDuty",
    "password": "admin123"
}

# СПЕЦИАЛЬНЫЙ АДМИН
SUPER_ADMIN_USERNAME = "@Tamerlantcik"

# Золотой стандарт данных (Телефоны)
EMPLOYEE_PHONES = {
    "Денисова Е.С.": "8-987-294-93-24",
    "Осипов Р.Э": "8-919-684-48-07",
    "Лиходько А.С.": "8-987-284-16-98",
    "Бадершаехова Э.Р": "8-927-490-95-52",
    "Портнова М.С.": "8-951-891-52-12",
    "Коротких А.А.": "8-999-155-96-34",
    "Лызина С.В.": "8-919-635-55-06",
    "Горбунов Р.Д.": "8-963-124-85-46",
    "Аванесян А.А.": "8-965-622-17-98",
    "Чумаков И.И.": "8-928-098-24-34",
    "Каримов Т.Р.": "8-912-453-34-13",
    "Кудрявцев А.А.": "8-987-284-16-98",
    "Коробова И.А.": "8-917-858-22-50",
}

# Соответствие Telegram username сотрудникам
TELEGRAM_TO_EMPLOYEE = {
    "@lihodko": "Лиходько А.С.",
    "@denisova": "Денисова Е.С.",
    "@portnova": "Портнова М.С.",
    "@lyzina": "Лызина С.В.",
    "@gorbunov": "Горбунов Р.Д.",
    "@osipov": "Осипов Р.Э",
    "@badershaehova": "Бадершаехова Э.Р",
    "@chumakov": "Чумаков И.И.",
    "@karimov": "Каримов Т.Р.",
    "@korotkikh": "Коротких А.А.",
    "@kudryavtsev": "Кудрявцев А.А.",
    "@korobova": "Коробова И.А.",
}

# График дежурств
DUTY_SCHEDULE = [
    {"date": "11.04.2026г.", "date_obj": datetime(2026, 4, 11), "employees": ["Лиходько А.С."], "is_pair": False},
    {"date": "18.04.2026г.", "date_obj": datetime(2026, 4, 18), "employees": ["Кудрявцев А.А.", "Коробова И.А."], "is_pair": True},
    {"date": "25.04.2026г.", "date_obj": datetime(2026, 4, 25), "employees": ["Лызина С.В."], "is_pair": False},
    {"date": "02.05.2026г.", "date_obj": datetime(2026, 5, 2), "employees": ["Портнова М.С."], "is_pair": False},
    {"date": "09.05.2026г.", "date_obj": datetime(2026, 5, 9), "employees": ["Горбунов Р.Д."], "is_pair": False},
    {"date": "16.05.2026г.", "date_obj": datetime(2026, 5, 16), "employees": ["Аванесян А.А."], "is_pair": False},
    {"date": "23.05.2026г.", "date_obj": datetime(2026, 5, 23), "employees": ["Чумаков И.И."], "is_pair": False},
    {"date": "30.05.2026г.", "date_obj": datetime(2026, 5, 30), "employees": ["Каримов Т.Р."], "is_pair": False},
    {"date": "06.06.2026г.", "date_obj": datetime(2026, 6, 6), "employees": ["Осипов Р.Э"], "is_pair": False},
    {"date": "13.06.2026г.", "date_obj": datetime(2026, 6, 13), "employees": ["Бадершаехова Э.Р"], "is_pair": False},
    {"date": "20.06.2026г.", "date_obj": datetime(2026, 6, 20), "employees": ["Лиходько А.С."], "is_pair": False},
]

class DutyScheduleGenerator:
    def __init__(self, schedule_data: List[Dict]):
        self.schedule_data = schedule_data
        self.schedule = {}
        self.initialize_schedule()

    def initialize_schedule(self):
        """Синхронизация данных с актуальными телефонами"""
        self.schedule = {}
        for duty in self.schedule_data:
            clean_employees = [name.strip() for name in duty["employees"]]
            # Получаем телефоны напрямую из EMPLOYEE_PHONES по ключу имени
            phones_list = [EMPLOYEE_PHONES.get(name, "Номер не найден") for name in clean_employees]
            
            self.schedule[duty["date"]] = {
                "employees": clean_employees,
                "phones": phones_list,
                "is_pair": duty["is_pair"],
                "date_obj": duty["date_obj"]
            }
        logger.info(f"Загружен график на {len(self.schedule)} недель")

    def get_schedule_text(self) -> str:
        today = datetime.now(MOSCOW_TZ).replace(tzinfo=None)
        text = "📅 <b>АКТУАЛЬНЫЙ ГРАФИК ДЕЖУРСТВ</b>\n\n"

        sorted_duties = sorted(self.schedule.items(), key=lambda x: x[1]["date_obj"])
        
        has_future = False
        for date_str, duty in sorted_duties:
            if duty["date_obj"].date() >= today.date():
                has_future = True
                is_soon = (duty["date_obj"] - today).days <= 7
                date_display = f"<b>{date_str}</b>" if is_soon else date_str
                
                text += f"{date_display}\n"
                
                # Формируем строку сотрудников и телефонов
                emp_str = " + ".join(duty["employees"])
                phone_str = " + ".join(duty["phones"])
                
                text += f"{emp_str}\n{phone_str}\n\n"

        if not has_future:
            text += "Нет запланированных дежурств\n"

        text += f"<i>Обновлено: {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M')}</i>"
        return text

    def get_employee_schedule(self, employee_name: str) -> List[Dict]:
        result = []
        today = datetime.now(MOSCOW_TZ).replace(tzinfo=None).date()
        for date_str, duty in self.schedule.items():
            if employee_name in duty["employees"] and duty["date_obj"].date() >= today:
                result.append({"date": date_str, "date_obj": duty["date_obj"]})
        return sorted(result, key=lambda x: x["date_obj"])

    def get_todays_duty(self) -> Optional[Dict]:
        today_str = datetime.now(MOSCOW_TZ).strftime("%d.%m.%Yг.")
        return self.schedule.get(today_str)

    # Методы управления сотрудниками и графиком (заглушки для расширения)
    def add_duty(self, date_str: str, employees: List[str], phones: List[str], is_pair: bool):
        try:
            date_clean = date_str.replace("г.", "").strip()
            date_obj = datetime.strptime(date_clean, "%d.%m.%Y")
            self.schedule[date_str] = {"employees": employees, "phones": phones, "is_pair": is_pair, "date_obj": date_obj}
            return True, "Успешно добавлено"
        except Exception as e:
            return False, str(e)

class DutyBot:
    def __init__(self, token: str):
        self.token = token
        self.schedule_generator = DutyScheduleGenerator(DUTY_SCHEDULE)
        self.user_data_file = "user_data.json"
        self.user_data = {}
        self.admin_sessions = {}
        self.application = None
        self.bot_instance = None
        self.scheduler = None
        self.load_user_data()

    def load_user_data(self):
        if os.path.exists(self.user_data_file):
            try:
                with open(self.user_data_file, 'r', encoding='utf-8') as f:
                    self.user_data = json.load(f)
            except: self.user_data = {}
        else: self.user_data = {}

    def save_user_data(self):
        with open(self.user_data_file, 'w', encoding='utf-8') as f:
            json.dump(self.user_data, f, ensure_ascii=False, indent=2)

    def is_admin(self, user_id: str) -> bool:
        return self.user_data.get(user_id, {}).get("is_admin", False)

    def get_main_keyboard(self, user_id: str) -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton("📋 Полный график", callback_data="full_schedule"),
             InlineKeyboardButton("👤 Моё дежурство", callback_data="my_duty")],
            [InlineKeyboardButton("📄 Скачать протокол", callback_data="protocol"),
             InlineKeyboardButton("❓ Частые вопросы", callback_data="questions")],
            [InlineKeyboardButton("📝 Инструкция", callback_data="instructions"),
             InlineKeyboardButton("🔄 Изменить профиль", callback_data="change_profile")]
        ]
        if self.is_admin(user_id):
            keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])
        return InlineKeyboardMarkup(keyboard)

    def get_employee_selection_keyboard(self) -> InlineKeyboardMarkup:
        keyboard = []
        employees_list = sorted(list(EMPLOYEE_PHONES.keys()))
        for i in range(0, len(employees_list), 2):
            row = [InlineKeyboardButton(employees_list[i], callback_data=f"emp_{employees_list[i]}")]
            if i + 1 < len(employees_list):
                row.append(InlineKeyboardButton(employees_list[i+1], callback_data=f"emp_{employees_list[i+1]}"))
            keyboard.append(row)
        return InlineKeyboardMarkup(keyboard)

    async def setup_scheduler(self):
        self.scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)
        # Ср 18:00
        self.scheduler.add_job(self.send_wednesday_notification, CronTrigger(day_of_week='wed', hour=18, minute=0))
        # Пт 18:00
        self.scheduler.add_job(self.send_friday_notification, CronTrigger(day_of_week='fri', hour=18, minute=0))
        # Суб 10:00
        self.scheduler.add_job(self.send_saturday_notification, CronTrigger(day_of_week='sat', hour=10, minute=0))
        self.scheduler.start()

    async def _broadcast(self, text: str):
        for uid in self.user_data.keys():
            try:
                await self.bot_instance.send_message(chat_id=int(uid), text=text, parse_mode=ParseMode.HTML)
                await asyncio.sleep(0.05)
            except: continue

    async def send_wednesday_notification(self):
        # Логика уведомления на субботу
        await self._broadcast("🔔 Напоминание: Проверьте график дежурств на ближайшую субботу!")

    async def send_friday_notification(self):
        await self._broadcast("⚠️ Пятница! Не забудьте заказать ключи в приемной 5600 до 19:00.")

    async def send_saturday_notification(self):
        await self._broadcast("📋 Сегодня дежурство. Не забудьте заполнить протокол!")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        uid = str(user.id)
        if uid not in self.user_data:
            self.user_data[uid] = {
                "username": user.username,
                "selected_employee": None,
                "is_admin": False
            }
            self.save_user_data()
        
        emp = self.user_data[uid].get("selected_employee")
        if not emp:
            await update.message.reply_text("<b>Добро пожаловать!</b>\nВыберите ваше ФИО:", 
                                         reply_markup=self.get_employee_selection_keyboard(), parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(f"<b>Привет, {emp}!</b>", 
                                         reply_markup=self.get_main_keyboard(uid), parse_mode=ParseMode.HTML)

    async def admin_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        if len(context.args) == 2 and context.args[0] == ADMIN_CREDENTIALS["login"] and context.args[1] == ADMIN_CREDENTIALS["password"]:
            self.user_data[uid]["is_admin"] = True
            self.save_user_data()
            await update.message.reply_text("✅ Админ-доступ открыт!", reply_markup=self.get_main_keyboard(uid))
        else:
            await update.message.reply_text("❌ Ошибка входа")

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        uid = str(query.from_user.id)
        data = query.data

        if data.startswith("emp_"):
            name = data[4:]
            self.user_data[uid]["selected_employee"] = name
            self.save_user_data()
            await query.edit_message_text(f"✅ Профиль привязан к: {name}", reply_markup=self.get_main_keyboard(uid))
        
        elif data == "full_schedule":
            text = self.schedule_generator.get_schedule_text()
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, 
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]))
        
        elif data == "my_duty":
            emp = self.user_data[uid].get("selected_employee")
            duties = self.schedule_generator.get_employee_schedule(emp)
            if not duties:
                msg = "У вас нет активных дежурств."
            else:
                msg = f"👤 <b>Ваши дежурства ({emp}):</b>\n\n" + "\n".join([f"• {d['date']}" for d in duties])
            await query.edit_message_text(msg, parse_mode=ParseMode.HTML, 
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]))

        elif data == "change_profile":
            await query.edit_message_text("Выберите ФИО:", reply_markup=self.get_employee_selection_keyboard())

        elif data == "back_to_main":
            await query.edit_message_text("🏠 Главное меню:", reply_markup=self.get_main_keyboard(uid))

    def run(self):
        self.application = ApplicationBuilder().token(self.token).build()
        self.bot_instance = self.application.bot

        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("admin", self.admin_login))
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Запуск планировщика в цикле событий
        loop = asyncio.get_event_loop()
        loop.create_task(self.setup_scheduler())

        logger.info("Бот запущен...")
        self.application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    BOT_TOKEN = "8485938284:AAHl6RjZbecjayHhSrImN0uwmQ3LlajliwQ"
    bot = DutyBot(BOT_TOKEN)
    bot.run()
