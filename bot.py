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

# Админ-аккаунт (логин: AdminDuty, пароль: admin123)
ADMIN_CREDENTIALS = {
    "login": "AdminDuty",
    "password": "admin123"
}

# СПЕЦИАЛЬНЫЙ АДМИН - ТОЛЬКО ЭТОТ ПОЛЬЗОВАТЕЛЬ МОЖЕТ ЗАПУСКАТЬ ДИАГНОСТИЧЕСКИЕ КОМАНДЫ
SUPER_ADMIN_USERNAME = "@Tamerlantcik"  # Специальный админ для диагностики

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

# Телефоны сотрудников
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
    "Кудрявцев А.А.": "8-000-000-00-00",
    "Коробова И.А.": "8-000-000-00-00",
}

# Обновленный график дежурств по фото
DUTY_SCHEDULE = [
    {
        "date": "18.04.2026г.",
        "date_obj": datetime(2026, 4, 18),
        "employees": ["Портнова М.С."],
        "phones": ["8-951-891-52-12"],
        "is_pair": False
    },
    {
        "date": "25.04.2026г.",
        "date_obj": datetime(2026, 4, 25),
        "employees": ["Лызина С.В."],
        "phones": ["8-919-635-55-06"],
        "is_pair": False
    },
    {
        "date": "02.05.2026г.",
        "date_obj": datetime(2026, 5, 2),
        "employees": ["Горбунов Р.Д."],
        "phones": ["8-963-124-85-46"],
        "is_pair": False
    },
    {
        "date": "09.05.2026г.",
        "date_obj": datetime(2026, 5, 9),
        "employees": ["Аванесян А.А."],
        "phones": ["8-965-622-17-98"],
        "is_pair": False
    },
    {
        "date": "16.05.2026г.",
        "date_obj": datetime(2026, 5, 16),
        "employees": ["Чумаков И.И."],
        "phones": ["8-928-098-24-34"],
        "is_pair": False
    },
    {
        "date": "23.05.2026г.",
        "date_obj": datetime(2026, 5, 23),
        "employees": ["Каримов Т.Р."],
        "phones": ["8-912-453-34-13"],
        "is_pair": False
    },
    {
        "date": "30.05.2026г.",
        "date_obj": datetime(2026, 5, 30),
        "employees": ["Осипов Р.Э"],
        "phones": ["8-919-684-48-07"],
        "is_pair": False
    },
    {
        "date": "06.06.2026г.",
        "date_obj": datetime(2026, 6, 6),
        "employees": ["Бадершаехова Э.Р"],
        "phones": ["8-927-490-95-52"],
        "is_pair": False
    },
    {
        "date": "13.06.2026г.",
        "date_obj": datetime(2026, 6, 13),
        "employees": ["Коротких А.А."],
        "phones": ["8-999-155-96-34"],
        "is_pair": False
    },
    {
        "date": "20.06.2026г.",
        "date_obj": datetime(2026, 6, 20),
        "employees": ["Денисова Е.С."],
        "phones": ["8-987-294-93-24"],
        "is_pair": False
    },
    {
        "date": "27.06.2026г.",
        "date_obj": datetime(2026, 6, 27),
        "employees": ["Лиходько А.С."],
        "phones": ["8-987-284-16-98"],
        "is_pair": False
    },
]


class DutyScheduleGenerator:
    """Генератор графика дежурств"""

    def __init__(self, schedule_data: List[Dict]):
        self.schedule_data = schedule_data
        self.schedule = {}
        self.initialize_schedule()

    def initialize_schedule(self):
        """Инициализация графика из данных"""
        for duty in self.schedule_data:
            self.schedule[duty["date"]] = {
                "employees": duty["employees"],
                "phones": duty["phones"],
                "is_pair": duty["is_pair"],
                "date_obj": duty["date_obj"]
            }
        logger.info(f"Загружен график на {len(self.schedule)} недель")
        # Удаляем прошедшие дежурства при инициализации
        self.remove_past_duties()

    def remove_past_duties(self):
        """Удаление прошедших дежурств"""
        today = datetime.now(MOSCOW_TZ).replace(tzinfo=None)
        dates_to_remove = []

        for date_str, duty in self.schedule.items():
            if duty["date_obj"] < today:
                dates_to_remove.append(date_str)

        for date_str in dates_to_remove:
            del self.schedule[date_str]
            self.schedule_data = [d for d in self.schedule_data if d["date"] != date_str]

        if dates_to_remove:
            logger.info(f"Удалено {len(dates_to_remove)} прошедших дежурств")

    def get_schedule_text(self) -> str:
        """Форматирование графика в текстовый вид"""
        today = datetime.now(MOSCOW_TZ).replace(tzinfo=None)
        text = "📅 <b>АКТУАЛЬНЫЙ ГРАФИК ДЕЖУРСТВ</b>\n\n"

        # Собираем все дежурства
        duties_list = []
        for date_str, duty in self.schedule.items():
            duties_list.append((date_str, duty))

        # Сортируем по дате
        duties_list.sort(key=lambda x: x[1]["date_obj"])

        # Формируем текст только для будущих дежурств
        future_duties = [d for d in duties_list if d[1]["date_obj"] >= today]

        if not future_duties:
            text += "Нет запланированных дежурств\n"
        else:
            for date_str, duty in future_duties:
                days_left = (duty["date_obj"] - today).days

                if days_left <= 7:
                    text += f"<b>{date_str}</b>\n"
                else:
                    text += f"{date_str}\n"

                if duty["is_pair"]:
                    text += f"{duty['employees'][0]} + {duty['employees'][1]}\n"
                    text += f"{duty['phones'][0]} + {duty['phones'][1]}\n\n"
                else:
                    text += f"{duty['employees'][0]}\n"
                    text += f"{duty['phones'][0]}\n\n"

        text += f"<i>Актуально на: {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M')}</i>"
        return text

    def get_employee_schedule(self, employee_name: str) -> List[Dict]:
        """Получить все дежурства конкретного сотрудника"""
        result = []
        today = datetime.now(MOSCOW_TZ).replace(tzinfo=None)

        for date_str, duty in self.schedule.items():
            if employee_name in duty["employees"] and duty["date_obj"] >= today:
                result.append({
                    "date": date_str,
                    "employees": duty["employees"],
                    "phones": duty["phones"],
                    "is_pair": duty["is_pair"],
                    "date_obj": duty["date_obj"]
                })
        return sorted(result, key=lambda x: x["date_obj"])

    def get_next_duty(self, employee_name: str) -> Optional[Dict]:
        """Получить следующее дежурство сотрудника"""
        today = datetime.now(MOSCOW_TZ).replace(tzinfo=None)

        for date_str, duty in sorted(self.schedule.items(), key=lambda x: x[1]["date_obj"]):
            if employee_name in duty["employees"] and duty["date_obj"] > today:
                return {
                    "date": date_str,
                    "employees": duty["employees"],
                    "phones": duty["phones"],
                    "is_pair": duty["is_pair"],
                    "date_obj": duty["date_obj"]
                }
        return None

    def get_todays_duty(self) -> Optional[Dict]:
        """Получить дежурных на сегодня (если сегодня суббота)"""
        today = datetime.now(MOSCOW_TZ).replace(tzinfo=None)
        today_str = today.strftime("%d.%m.%Yг.")

        for date_str, duty in self.schedule.items():
            if date_str == today_str:
                return duty

        return None

    def add_duty(self, date_str: str, employees: List[str], phones: List[str], is_pair: bool):
        """Добавить дежурство"""
        try:
            date_str_clean = date_str.replace("г.", "").strip()
            date_obj = datetime.strptime(date_str_clean, "%d.%m.%Y")

            today = datetime.now(MOSCOW_TZ).replace(tzinfo=None)

            # Проверяем, чтобы дата была в будущем
            if date_obj < today:
                return False, "Дата должна быть в будущем"

            self.schedule[date_str] = {
                "employees": employees,
                "phones": phones,
                "is_pair": is_pair,
                "date_obj": date_obj
            }

            self.schedule_data.append({
                "date": date_str,
                "date_obj": date_obj,
                "employees": employees,
                "phones": phones,
                "is_pair": is_pair
            })

            logger.info(f"Добавлено дежурство: {date_str} - {employees}")
            return True, "Дежурство успешно добавлено"
        except Exception as e:
            logger.error(f"Ошибка добавления дежурства: {e}")
            return False, f"Ошибка: {str(e)}"

    def remove_duty(self, date_str: str) -> bool:
        """Удалить дежурство"""
        if date_str in self.schedule:
            del self.schedule[date_str]
            self.schedule_data = [d for d in self.schedule_data if d["date"] != date_str]
            logger.info(f"Удалено дежурство: {date_str}")
            return True
        return False

    def update_employee_phone(self, employee_name: str, new_phone: str) -> bool:
        """Обновить телефон сотрудника"""
        global EMPLOYEE_PHONES
        if employee_name in EMPLOYEE_PHONES:
            EMPLOYEE_PHONES[employee_name] = new_phone
            logger.info(f"Обновлен телефон {employee_name}: {new_phone}")
            return True
        return False

    def add_employee(self, employee_name: str, phone: str) -> bool:
        """Добавить нового сотрудника"""
        global EMPLOYEE_PHONES
        if employee_name not in EMPLOYEE_PHONES:
            EMPLOYEE_PHONES[employee_name] = phone
            logger.info(f"Добавлен сотрудник: {employee_name} - {phone}")
            return True
        return False

    def remove_employee(self, employee_name: str) -> bool:
        """Удалить сотрудника"""
        global EMPLOYEE_PHONES
        if employee_name in EMPLOYEE_PHONES:
            del EMPLOYEE_PHONES[employee_name]
            logger.info(f"Удален сотрудник: {employee_name}")
            return True
        return False


class DutyBot:
    def __init__(self, token: str):
        self.token = token
        self.schedule_generator = DutyScheduleGenerator(DUTY_SCHEDULE)
        self.user_data_file = "user_data.json"
        self.protocol_file_path = "Протокол разногласий — пример.docx"
        self.protocol_attached_file_id = None
        self.admin_sessions = {}
        self.application = None
        self.bot_instance = None
        self.scheduler = None
        self.load_user_data()

    async def setup_scheduler(self):
        """Настройка автоматических задач - 3 УВЕДОМЛЕНИЯ В НЕДЕЛЮ ВСЕМ ПОЛЬЗОВАТЕЛЯМ"""
        # Создаем асинхронный планировщик
        self.scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)

        # 1. Уведомление в СРЕДУ в 18:00 - ВСЕМ пользователям о дежурстве в эту субботу
        self.scheduler.add_job(
            self.send_wednesday_notification,
            CronTrigger(day_of_week='wed', hour=18, minute=0, second=0, timezone=MOSCOW_TZ),
            id='wednesday_notification',
            replace_existing=True
        )

        # 2. Уведомление в ПЯТНИЦУ в 18:00 - ВСЕМ пользователям о завтрашнем дежурстве
        self.scheduler.add_job(
            self.send_friday_notification_all,
            CronTrigger(day_of_week='fri', hour=18, minute=0, second=0, timezone=MOSCOW_TZ),
            id='friday_notification_all',
            replace_existing=True
        )

        # 3. Уведомление в СУББОТУ в 10:00 - ВСЕМ пользователям в день дежурства (ИЗМЕНЕНО С 13 НА 10)
        self.scheduler.add_job(
            self.send_saturday_notification_all,
            CronTrigger(day_of_week='sat', hour=10, minute=0, second=0, timezone=MOSCOW_TZ),
            id='saturday_notification_all',
            replace_existing=True
        )

        self.scheduler.start()
        logger.info("Планировщик задач запущен: среда 18:00 (всем), пятница 18:00 (всем), суббота 10:00 (всем)")

    async def send_wednesday_notification(self):
        """Отправка уведомления в СРЕДУ в 18:00 ВСЕМ пользователям о дежурстве в эту субботу"""
        try:
            today = datetime.now(MOSCOW_TZ).replace(tzinfo=None)

            # Проверяем, сегодня действительно среда?
            if today.weekday() != 2:  # 2 = среда
                logger.warning(f"send_wednesday_notification вызван не в среду! День недели: {today.weekday()}")
                return

            logger.info(f"Запуск send_wednesday_notification в среду {today.strftime('%d.%m.%Y %H:%M')}")

            # Находим ближайшую субботу (через 3 дня от среды)
            saturday = today + timedelta(days=3)

            # Ищем дежурных на эту субботу
            duty_saturday = None
            for date_str, duty in self.schedule_generator.schedule.items():
                if duty["date_obj"].date() == saturday.date():
                    duty_saturday = duty
                    break

            # Формируем сообщение
            if not duty_saturday:
                logger.info(f"На {saturday.strftime('%d.%m.%Y')} дежурных нет")

                message = (
                    f"🔔 <b>НАПОМИНАНИЕ О ДЕЖУРСТВЕ В СУББОТУ</b>\n\n"
                    f"📅 <b>{saturday.strftime('%d.%m.%Y')}</b>\n\n"
                    f"⚠️ <b>В эту субботу дежурных нет</b>\n\n"
                    f"✅ Можно отдыхать!\n\n"
                    f"<i>Следующее напоминание: пятница в 18:00</i>"
                )
            else:
                # Формируем сообщение о дежурстве
                if duty_saturday["is_pair"]:
                    duty_text = f"{duty_saturday['employees'][0]} + {duty_saturday['employees'][1]}"
                    phones_text = f"{duty_saturday['phones'][0]} + {duty_saturday['phones'][1]}"
                else:
                    duty_text = f"{duty_saturday['employees'][0]}"
                    phones_text = f"{duty_saturday['phones'][0]}"

                message = (
                    f"🔔 <b>НАПОМИНАНИЕ О ДЕЖУРСТВЕ В СУББОТУ</b>\n\n"
                    f"📅 <b>Дата:</b> {saturday.strftime('%d.%m.%Y')}\n"
                    f"👤 <b>Дежурит:</b> {duty_text}\n"
                    f"📞 <b>Телефоны:</b> {phones_text}\n\n"
                    f"⏰ <b>Время:</b> 6:50 - 8:00\n"
                    f"📍 <b>Место:</b> кабинет 6002, 6 этаж, АДЦ\n\n"
                    f"📋 <b>Инструкция:</b>\n"
                    f"• В пятницу до 17:00 позвонить в приемную: 5600\n"
                    f"• Прийти в субботу к 6:50 в АДЦ\n"
                    f"• Взять ключ на охране от кубов\n"
                    f"• Сфотографировать открытый кабинет\n"
                    f"• Находиться там до 8:00\n\n"
                    f"<i>Следующее напоминание: пятница в 18:00</i>"
                )

            # Отправляем ВСЕМ зарегистрированным пользователям
            await self._send_notification_to_all_users(message, "среда")

        except Exception as e:
            logger.error(f"Ошибка отправки уведомления в среду: {e}")

    async def send_friday_notification_all(self):
        """Отправка уведомления в ПЯТНИЦУ в 18:00 ВСЕМ пользователям о завтрашнем дежурстве"""
        try:
            today = datetime.now(MOSCOW_TZ).replace(tzinfo=None)

            # Проверяем, сегодня действительно пятница?
            if today.weekday() != 4:  # 4 = пятница
                logger.warning(f"send_friday_notification_all вызван не в пятницу! День недели: {today.weekday()}")
                return

            logger.info(f"Запуск send_friday_notification_all в пятницу {today.strftime('%d.%m.%Y %H:%M')}")

            tomorrow = today + timedelta(days=1)  # Завтра - суббота

            # Ищем дежурных на завтра
            duty_tomorrow = None
            for date_str, duty in self.schedule_generator.schedule.items():
                if duty["date_obj"].date() == tomorrow.date():
                    duty_tomorrow = duty
                    break

            # Формируем сообщение
            if not duty_tomorrow:
                logger.info(f"На {tomorrow.strftime('%d.%m.%Y')} дежурных нет")

                message = (
                    f"🔔 <b>НАПОМИНАНИЕ О ЗАВТРАШНЕМ ДЕЖУРСТВЕ</b>\n\n"
                    f"📅 <b>Завтра ({tomorrow.strftime('%d.%m.%Y')}) дежурных нет</b>\n\n"
                    f"✅ Можете не беспокоиться!\n\n"
                    f"<i>Следующее напоминание: суббота в 10:00</i>"  # ИЗМЕНЕНО
                )
            else:
                # Формируем сообщение о дежурстве
                if duty_tomorrow["is_pair"]:
                    duty_text = f"{duty_tomorrow['employees'][0]} + {duty_tomorrow['employees'][1]}"
                    phones_text = f"{duty_tomorrow['phones'][0]} + {duty_tomorrow['phones'][1]}"
                else:
                    duty_text = f"{duty_tomorrow['employees'][0]}"
                    phones_text = f"{duty_tomorrow['phones'][0]}"

                message = (
                    f"🔔 <b>НАПОМИНАНИЕ О ЗАВТРАШНЕМ ДЕЖУРСТВЕ</b>\n\n"
                    f"📅 <b>Завтра ({tomorrow.strftime('%d.%m.%Y')}) дежурит:</b>\n"
                    f"👤 {duty_text}\n"
                    f"📞 {phones_text}\n\n"
                    f"⏰ <b>Время:</b> 6:50 - 8:00\n"
                    f"📍 <b>Место:</b> кабинет 6002, 6 этаж, АДЦ\n\n"
                    f"⚠️ <b>ВАЖНО! СЕГОДНЯ ДО 19:00:</b>\n"
                    f"• Дежурным позвонить в приемную: 5600\n"
                    f"• Сообщить о дежурстве\n"
                    f"• Попросить оставить ключи на вахте\n\n"
                    f"📋 <b>План на завтра:</b>\n"
                    f"• Прийти в АДЦ к 6:50\n"
                    f"• Взять ключ на охране от кубов\n"
                    f"• Открыть кабинет 6002\n"
                    f"• Сфотографировать открытый кабинет\n"
                    f"• Находиться там до 8:00\n"
                    f"• Оформить протокол разногласий\n\n"
                    f"<i>Следующее напоминание: суббота в 10:00</i>"  # ИЗМЕНЕНО
                )

            # Отправляем ВСЕМ зарегистрированным пользователям
            await self._send_notification_to_all_users(message, "пятница")

        except Exception as e:
            logger.error(f"Ошибка отправки уведомления в пятницу: {e}")

    async def send_saturday_notification_all(self):
        """Отправка уведомления в СУББОТУ в 10:00 ВСЕМ пользователям в день дежурства (ИЗМЕНЕНО С 13 НА 10)"""
        try:
            today = datetime.now(MOSCOW_TZ).replace(tzinfo=None)

            # Проверяем, сегодня действительно суббота?
            if today.weekday() != 5:  # 5 = суббота
                logger.warning(f"send_saturday_notification_all вызван не в субботу! День недели: {today.weekday()}")
                return

            logger.info(f"Запуск send_saturday_notification_all в субботу {today.strftime('%d.%m.%Y %H:%M')}")

            today_str = today.strftime("%d.%m.%Yг.")

            # Ищем дежурных на сегодня
            duty_today = None
            for date_str, duty in self.schedule_generator.schedule.items():
                if date_str == today_str:
                    duty_today = duty
                    break

            # Формируем сообщение
            if not duty_today:
                logger.info(f"На {today.strftime('%d.%m.%Y')} дежурных нет")

                message = (
                    f"🔔 <b>ИНФОРМАЦИЯ О ДЕЖУРСТВЕ</b>\n\n"
                    f"📅 <b>Сегодня ({today.strftime('%d.%m.%Y')}) дежурных нет</b>\n\n"
                    f"✅ Всем хороших выходных!\n\n"
                    f"<i>Следующее напоминание: среда в 18:00</i>"
                )
            else:
                # Формируем сообщение о дежурстве
                if duty_today["is_pair"]:
                    duty_text = f"{duty_today['employees'][0]} + {duty_today['employees'][1]}"
                    phones_text = f"{duty_today['phones'][0]} + {duty_today['phones'][1]}"
                else:
                    duty_text = f"{duty_today['employees'][0]}"
                    phones_text = f"{duty_today['phones'][0]}"

                # Проверяем, прошло ли уже время дежурства (после 8:00)
                current_hour = today.hour
                current_minute = today.minute
                is_after_duty = current_hour > 8 or (current_hour == 8 and current_minute > 0)

                if is_after_duty:
                    # После 8:00 - спрашиваем, как прошло дежурство
                    message = (
                        f"🔔 <b>ИТОГИ ДЕЖУРСТВА</b>\n\n"
                        f"📅 <b>Сегодня ({today.strftime('%d.%m.%Y')}) дежурили:</b>\n"
                        f"👤 {duty_text}\n"
                        f"📞 {phones_text}\n\n"
                        f"✅ <b>Дежурство завершилось в 8:00</b>\n\n"
                        f"📋 <b>Напоминание дежурным:</b>\n"
                        f"• Не забудьте оформить протокол разногласий\n"
                        f"• Протокол оставить у Е.С. Денисовой\n\n"
                        f"<i>Следующее напоминание: среда в 18:00</i>"
                    )
                else:
                    # До 8:00 - дежурство еще идет
                    time_remaining = ""
                    if current_hour < 6 or (current_hour == 6 and current_minute < 50):
                        time_remaining = "⏰ Дежурство начнется в 6:50"
                    elif current_hour < 8:
                        time_remaining = f"⏰ До окончания дежурства осталось: {7 - current_hour} ч {60 - current_minute} мин"
                    
                    message = (
                        f"🔔 <b>ДЕЖУРСТВО СЕГОДНЯ</b>\n\n"
                        f"📅 <b>Сегодня ({today.strftime('%d.%m.%Y')}) дежурят:</b>\n"
                        f"👤 {duty_text}\n"
                        f"📞 {phones_text}\n\n"
                        f"⏰ <b>Текущее время:</b> {today.strftime('%H:%M')}\n"
                        f"{time_remaining}\n\n"
                        f"📍 <b>Место:</b> кабинет 6002, 6 этаж, АДЦ\n\n"
                        f"📋 <b>Напоминание:</b>\n"
                        f"• Дежурные должны находиться в кабинете\n"
                        f"• Сделать фото открытого кабинета\n"
                        f"• После дежурства оформить протокол\n\n"
                        f"<i>Следующее напоминание: среда в 18:00</i>"
                    )

            # Отправляем ВСЕМ зарегистрированным пользователям
            await self._send_notification_to_all_users(message, "суббота")

        except Exception as e:
            logger.error(f"Ошибка отправки уведомления в субботу: {e}")

    async def _send_notification_to_all_users(self, message: str, notification_type: str):
        """ИСПРАВЛЕНО: Отправка уведомлений ВСЕМ пользователям с проверкой ID"""
        sent_count = 0
        error_count = 0
        deactivated_users = []
        
        # Принудительно загружаем свежие данные
        self.load_user_data()
        
        logger.info(f"Отправка уведомления {notification_type} - всего пользователей: {len(self.user_data)}")
        
        for user_id, user_info in list(self.user_data.items()):
            try:
                # Проверяем, что user_id можно преобразовать в int
                chat_id = int(user_id)
                
                await self.bot_instance.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode=ParseMode.HTML
                )
                sent_count += 1
                logger.debug(f"✓ Отправлено пользователю {user_id}")
                
                # Небольшая задержка чтобы не флудить
                await asyncio.sleep(0.1)
                
            except ValueError:
                logger.error(f"✗ Некорректный ID пользователя: {user_id}")
                error_count += 1
                deactivated_users.append(user_id)
                
            except Exception as e:
                error_count += 1
                error_msg = str(e).lower()
                logger.error(f"✗ Ошибка отправки пользователю {user_id}: {error_msg[:100]}")
                
                # Удаляем неактивных пользователей
                if any(phrase in error_msg for phrase in [
                    'bot was blocked', 'user not found', 'chat not found', 
                    'kicked', 'deactivated', 'forbidden', 'can\'t initiate'
                ]):
                    logger.warning(f"Удаляю неактивного пользователя: {user_id}")
                    deactivated_users.append(user_id)
        
        # Удаляем неактивных
        for user_id in deactivated_users:
            self.user_data.pop(user_id, None)
        
        if deactivated_users:
            self.save_user_data()
        
        # Подробный лог
        logger.info(f"=== ИТОГИ УВЕДОМЛЕНИЯ {notification_type.upper()} ===")
        logger.info(f"Всего в базе: {len(self.user_data) + len(deactivated_users)}")
        logger.info(f"Отправлено успешно: {sent_count}")
        logger.info(f"Ошибок: {error_count}")
        logger.info(f"Удалено неактивных: {len(deactivated_users)}")
        
        # Если никому не отправилось - это проблема!
        if sent_count == 0 and len(self.user_data) > 0:
            logger.error("⚠️ КРИТИЧЕСКАЯ ПРОБЛЕМА: НЕ УДАЛОСЬ ОТПРАВИТЬ НИ ОДНОГО УВЕДОМЛЕНИЯ!")

    def load_user_data(self):
        """Загрузка данных пользователей"""
        if os.path.exists(self.user_data_file):
            try:
                with open(self.user_data_file, 'r', encoding='utf-8') as f:
                    self.user_data = json.load(f)
            except Exception as e:
                logger.error(f"Ошибка загрузки user_data.json: {e}")
                self.user_data = {}
        else:
            self.user_data = {}

    def save_user_data(self):
        """Сохранение данных пользователей"""
        try:
            with open(self.user_data_file, 'w', encoding='utf-8') as f:
                json.dump(self.user_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения user_data.json: {e}")

    def is_admin(self, user_id: str) -> bool:
        """Проверка, является ли пользователь админом"""
        return self.user_data.get(user_id, {}).get("is_admin", False)
    
    def is_super_admin(self, username: str) -> bool:
        """Проверка, является ли пользователь супер-админом (@Tamerlantcik)"""
        if not username:
            return False
        if not username.startswith('@'):
            username = '@' + username
        return username.lower() == SUPER_ADMIN_USERNAME.lower()

    def get_employee_by_username(self, username: str) -> Optional[str]:
        """Найти сотрудника по Telegram username"""
        if not username.startswith('@'):
            username = '@' + username
        return TELEGRAM_TO_EMPLOYEE.get(username.lower())

    def get_main_keyboard(self, user_id: str) -> InlineKeyboardMarkup:
        """Клавиатура главного меню"""
        keyboard = [
            [
                InlineKeyboardButton("📋 Полный график", callback_data="full_schedule"),
                InlineKeyboardButton("👤 Моё дежурство", callback_data="my_duty")
            ],
            [
                InlineKeyboardButton("📄 Скачать протокол", callback_data="protocol"),
                InlineKeyboardButton("❓ Частые вопросы", callback_data="questions")
            ],
            [
                InlineKeyboardButton("📝 Инструкция", callback_data="instructions"),
                InlineKeyboardButton("🔄 Изменить профиль", callback_data="change_profile")
            ]
        ]

        if self.is_admin(user_id):
            keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])

        return InlineKeyboardMarkup(keyboard)

    def get_admin_keyboard(self) -> InlineKeyboardMarkup:
        """Клавиатура админ-панели"""
        keyboard = [
            [
                InlineKeyboardButton("📅 Управление графиком", callback_data="admin_schedule"),
                InlineKeyboardButton("👥 Управление сотрудниками", callback_data="admin_employees")
            ],
            [
                InlineKeyboardButton("📁 Управление файлами", callback_data="admin_files"),
                InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
            ],
            [
                InlineKeyboardButton("🔙 В главное меню", callback_data="back_to_main"),
                InlineKeyboardButton("🚪 Выйти из админки", callback_data="admin_logout")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    def get_schedule_admin_keyboard(self) -> InlineKeyboardMarkup:
        """Клавиатура управления графиком"""
        keyboard = [
            [
                InlineKeyboardButton("➕ Добавить дежурство", callback_data="admin_add_duty"),
                InlineKeyboardButton("➖ Удалить дежурство", callback_data="admin_remove_duty")
            ],
            [
                InlineKeyboardButton("📋 Просмотреть график", callback_data="full_schedule"),
                InlineKeyboardButton("🔄 Обновить график", callback_data="admin_refresh_schedule")
            ],
            [InlineKeyboardButton("🔙 Назад в админку", callback_data="admin_panel")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def get_employees_admin_keyboard(self) -> InlineKeyboardMarkup:
        """Клавиатура управления сотрудниками"""
        keyboard = [
            [
                InlineKeyboardButton("➕ Добавить сотрудника", callback_data="admin_add_employee"),
                InlineKeyboardButton("➖ Удалить сотрудника", callback_data="admin_remove_employee")
            ],
            [
                InlineKeyboardButton("📞 Изменить телефон", callback_data="admin_edit_phone"),
                InlineKeyboardButton("👥 Список сотрудников", callback_data="admin_list_employees")
            ],
            [InlineKeyboardButton("🔙 Назад в админку", callback_data="admin_panel")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def get_files_admin_keyboard(self) -> InlineKeyboardMarkup:
        """Клавиатура управления файлами"""
        keyboard = [
            [
                InlineKeyboardButton("📤 Загрузить протокол", callback_data="admin_upload_protocol"),
                InlineKeyboardButton("📎 Прикрепить протокол", callback_data="admin_pin_protocol")
            ],
            [
                InlineKeyboardButton("🗑 Удалить протокол", callback_data="admin_delete_protocol"),
                InlineKeyboardButton("📄 Проверить файл", callback_data="admin_check_protocol")
            ],
            [InlineKeyboardButton("🔙 Назад в админку", callback_data="admin_panel")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def get_back_keyboard(self) -> InlineKeyboardMarkup:
        """Клавиатура с кнопкой назад"""
        keyboard = [[InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_main")]]
        return InlineKeyboardMarkup(keyboard)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        user_id = str(user.id)
        username = user.username

        if user_id not in self.user_data:
            self.user_data[user_id] = {
                "username": username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "telegram_name": f"{user.first_name} {user.last_name or ''}".strip(),
                "notifications": True,  # По умолчанию ВКЛЮЧЕНЫ!
                "selected_employee": None,
                "registered_at": datetime.now().isoformat(),
                "last_active": datetime.now().isoformat(),
                "is_admin": False
            }

            if username:
                employee_name = self.get_employee_by_username(username)
                if employee_name:
                    self.user_data[user_id]["selected_employee"] = employee_name

            self.save_user_data()

        self.user_data[user_id]["last_active"] = datetime.now().isoformat()
        self.save_user_data()

        user_info = self.user_data[user_id]
        employee_name = user_info.get("selected_employee")

        if employee_name:
            welcome_text = (
                f"<b>ДОБРО ПОЖАЛОВАТЬ, {user.first_name}!</b>\n\n"
                f"👤 <b>Ваш профиль:</b>\n"
                f"• Сотрудник: {employee_name}\n"
                f"• Телефон: {EMPLOYEE_PHONES.get(employee_name, 'не указан')}\n"
                f"• Уведомления: {'✅ Включены' if user_info.get('notifications', True) else '❌ Отключены'}\n\n"
                "<i>Выберите действие:</i>"
            )
        else:
            welcome_text = (
                f"<b>ДОБРО ПОЖАЛОВАТЬ, {user.first_name}!</b>\n\n"
                "Я бот для управления графиком дежурств.\n\n"
            )

            if username:
                welcome_text += f"Ваш username: @{username}\n"

            welcome_text += "<i>Пожалуйста, выберите ваше ФИО из списка:</i>"

            await update.message.reply_text(
                welcome_text,
                reply_markup=self.get_employee_selection_keyboard(),
                parse_mode=ParseMode.HTML
            )
            return

        await update.message.reply_text(
            welcome_text,
            reply_markup=self.get_main_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )

    def get_employee_selection_keyboard(self) -> InlineKeyboardMarkup:
        """Клавиатура для выбора сотрудника"""
        keyboard = []
        employees_list = list(EMPLOYEE_PHONES.keys())

        for i in range(0, len(employees_list), 2):
            row = []
            if i < len(employees_list):
                row.append(InlineKeyboardButton(
                    f"{employees_list[i]}",
                    callback_data=f"emp_{employees_list[i]}"
                ))
            if i + 1 < len(employees_list):
                row.append(InlineKeyboardButton(
                    f"{employees_list[i + 1]}",
                    callback_data=f"emp_{employees_list[i + 1]}"
                ))
            if row:
                keyboard.append(row)

        return InlineKeyboardMarkup(keyboard)

    async def admin_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Вход в админ-панель"""
        user = update.effective_user
        user_id = str(user.id)

        if len(context.args) != 2:
            await update.message.reply_text(
                "❌ <b>Неверный формат команды</b>\n\n"
                "Используйте: /admin логин пароль\n",
                parse_mode=ParseMode.HTML
            )
            return

        login = context.args[0]
        password = context.args[1]

        if login == ADMIN_CREDENTIALS["login"] and password == ADMIN_CREDENTIALS["password"]:
            if user_id in self.user_data:
                self.user_data[user_id]["is_admin"] = True
                self.save_user_data()

            self.admin_sessions[user_id] = {
                "logged_in": True,
                "login_time": datetime.now().isoformat()
            }

            await update.message.reply_text(
                "✅ <b>УСПЕШНЫЙ ВХОД В АДМИН-ПАНЕЛЬ</b>\n\n"
                "Доступные функции:\n"
                "• Управление графиком дежурств\n"
                "• Управление сотрудниками\n"
                "• Управление файлами\n"
                "• Просмотр статистики\n\n"
                "<i>Выберите действие:</i>",
                reply_markup=self.get_admin_keyboard(),
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                "❌ <b>НЕВЕРНЫЙ ЛОГИН ИЛИ ПАРОЛЬ</b>\n\n"
                "Попробуйте снова:\n",
                parse_mode=ParseMode.HTML
            )

    # ============= НОВЫЕ ДИАГНОСТИЧЕСКИЕ КОМАНДЫ ДЛЯ @Tamerlantcik =============
    
    async def check_users_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Подробная проверка статуса всех пользователей - ТОЛЬКО ДЛЯ @Tamerlantcik"""
        user = update.effective_user
        
        # Проверяем, что это @Tamerlantcik
        if not self.is_super_admin(user.username):
            await update.message.reply_text(
                "❌ <b>ДОСТУП ЗАПРЕЩЕН</b>\n\n"
                "Эта команда доступна только @Tamerlantcik",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Принудительно загружаем свежие данные
        self.load_user_data()
        
        text = "📊 <b>СТАТУС ПОЛЬЗОВАТЕЛЕЙ</b>\n\n"
        
        # Счетчики
        total = len(self.user_data)
        with_employee = 0
        notifications_on = 0
        notifications_off = 0
        
        for uid, info in self.user_data.items():
            name = info.get('telegram_name', 'Неизвестно')
            username = info.get('username', 'Нет username')
            employee = info.get('selected_employee', None)
            notifications = info.get('notifications', True)
            
            # Подсчет статистики - ИСПРАВЛЕНО
            if employee and employee != 'None' and employee != '❌ НЕ ВЫБРАН':
                with_employee += 1
            if notifications:
                notifications_on += 1
            else:
                notifications_off += 1
            
            # Статус уведомлений
            notif_status = "✅ ВКЛ" if notifications else "❌ ВЫКЛ"
            employee_display = employee if employee else "❌ НЕ ВЫБРАН"
            
            text += f"<b>{name}</b>\n"
            text += f"📱 @{username}\n"
            text += f"🆔 {uid}\n"
            text += f"👤 {employee_display}\n"
            text += f"🔔 {notif_status}\n"
            text += f"📅 Последний вход: {info.get('last_active', 'Неизвестно')[:16]}\n\n"
        
        text += f"<b>ИТОГО:</b> {total} пользователей\n"
        text += f"👤 С выбором сотрудника: {with_employee}\n"
        text += f"🔔 Уведомления включены: {notifications_on}\n"
        text += f"🔕 Уведомления выключены: {notifications_off}"
        
        # Отправляем
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    
    async def enable_notifications_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Включить уведомления для всех пользователей - ТОЛЬКО ДЛЯ @Tamerlantcik"""
        user = update.effective_user
        
        # Проверяем, что это @Tamerlantcik
        if not self.is_super_admin(user.username):
            await update.message.reply_text(
                "❌ <b>ДОСТУП ЗАПРЕЩЕН</b>\n\n"
                "Эта команда доступна только @Tamerlantcik",
                parse_mode=ParseMode.HTML
            )
            return
        
        self.load_user_data()
        
        enabled_count = 0
        for uid, info in self.user_data.items():
            if not info.get('notifications', True):
                self.user_data[uid]['notifications'] = True
                enabled_count += 1
        
        self.save_user_data()
        
        await update.message.reply_text(
            f"✅ Уведомления включены для {enabled_count} пользователей\n"
            f"📊 Всего пользователей: {len(self.user_data)}",
            parse_mode=ParseMode.HTML
        )
    
    async def test_send_to_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Тест отправки конкретному пользователю - ТОЛЬКО ДЛЯ @Tamerlantcik"""
        user = update.effective_user
        
        # Проверяем, что это @Tamerlantcik
        if not self.is_super_admin(user.username):
            await update.message.reply_text(
                "❌ <b>ДОСТУП ЗАПРЕЩЕН</b>\n\n"
                "Эта команда доступна только @Tamerlantcik",
                parse_mode=ParseMode.HTML
            )
            return
        
        args = context.args
        if len(args) < 1:
            await update.message.reply_text(
                "❌ Укажите user_id или username\n"
                "Пример: /test_send 123456789\n"
                "Или: /test_send @username"
            )
            return
        
        target = args[0]
        
        # Пробуем найти пользователя
        target_id = None
        target_name = target
        
        if target.startswith('@'):
            # Поиск по username
            username = target[1:].lower()
            for uid, info in self.user_data.items():
                if info.get('username', '').lower() == username:
                    target_id = uid
                    target_name = info.get('telegram_name', target)
                    break
            if not target_id:
                await update.message.reply_text(f"❌ Пользователь {target} не найден в базе")
                return
        else:
            # Прямой ID
            target_id = target
        
        # Тестовое сообщение
        test_msg = (
            f"🔔 <b>ТЕСТОВОЕ УВЕДОМЛЕНИЕ</b>\n\n"
            f"👤 Получатель: {target_name}\n"
            f"🆔 ID: {target_id}\n"
            f"📅 Время: {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M:%S')}\n\n"
            f"✅ Если вы видите это сообщение, значит:\n"
            f"   • Бот может отправлять вам сообщения\n"
            f"   • Вы не блокировали бота\n"
            f"   • Уведомления будут приходить по расписанию\n\n"
            f"📅 Расписание уведомлений:\n"
            f"• Среда 18:00 - о дежурстве в субботу\n"
            f"• Пятница 18:00 - о завтрашнем дежурстве\n"
            f"• Суббота 10:00 - в день дежурства"  # ИЗМЕНЕНО
        )
        
        try:
            await self.bot_instance.send_message(
                chat_id=int(target_id),
                text=test_msg,
                parse_mode=ParseMode.HTML
            )
            await update.message.reply_text(f"✅ Тестовое сообщение отправлено {target_name}")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка отправки: {str(e)[:200]}")
    
    async def check_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверка времени на сервере - ТОЛЬКО ДЛЯ @Tamerlantcik"""
        user = update.effective_user
        
        # Проверяем, что это @Tamerlantcik
        if not self.is_super_admin(user.username):
            await update.message.reply_text(
                "❌ <b>ДОСТУП ЗАПРЕЩЕН</b>\n\n"
                "Эта команда доступна только @Tamerlantcik",
                parse_mode=ParseMode.HTML
            )
            return
        
        now = datetime.now(MOSCOW_TZ)
        
        # Дни недели на русском
        weekdays = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        weekday_ru = weekdays[now.weekday()]
        
        # Следующее уведомление
        next_notification = ""
        if now.weekday() == 1 and now.hour < 18:  # Вторник до 18
            next_notification = "Среда 18:00 (через 1 день)"
        elif now.weekday() == 2 and now.hour < 18:  # Среда до 18
            next_notification = "Среда 18:00 (сегодня)"
        elif now.weekday() == 3:  # Четверг
            next_notification = "Пятница 18:00 (через 1 день)"
        elif now.weekday() == 4 and now.hour < 18:  # Пятница до 18
            next_notification = "Пятница 18:00 (сегодня)"
        elif now.weekday() == 5 and now.hour < 10:  # Суббота до 10 (ИЗМЕНЕНО)
            next_notification = "Суббота 10:00 (сегодня)"
        elif now.weekday() == 6:  # Воскресенье
            next_notification = "Среда 18:00 (через 3 дня)"
        else:
            next_notification = "Среда 18:00"
        
        await update.message.reply_text(
            f"🕐 <b>ИНФОРМАЦИЯ О ВРЕМЕНИ</b>\n\n"
            f"📅 Дата: {now.strftime('%d.%m.%Y')}\n"
            f"⏰ Время: {now.strftime('%H:%M:%S')}\n"
            f"📆 День недели: {weekday_ru}\n"
            f"🌍 Часовой пояс: Москва (UTC+3)\n\n"
            f"🔄 <b>Следующее уведомление:</b> {next_notification}\n\n"
            f"📋 <b>Расписание:</b>\n"
            f"• Среда 18:00 - всем\n"
            f"• Пятница 18:00 - всем\n"
            f"• Суббота 10:00 - всем",  # ИЗМЕНЕНО
            parse_mode=ParseMode.HTML
        )
    
    async def fix_all_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ИСПРАВИТЬ: Включить уведомления и проверить всех пользователей"""
        user = update.effective_user
        
        # Проверяем, что это @Tamerlantcik
        if not self.is_super_admin(user.username):
            await update.message.reply_text(
                "❌ <b>ДОСТУП ЗАПРЕЩЕН</b>\n\n"
                "Эта команда доступна только @Tamerlantcik",
                parse_mode=ParseMode.HTML
            )
            return
        
        self.load_user_data()
        
        fixed_count = 0
        for uid, info in self.user_data.items():
            changes = []
            
            # Включаем уведомления
            if not info.get('notifications', True):
                info['notifications'] = True
                changes.append("включены уведомления")
            
            # Проверяем наличие всех полей
            if 'telegram_name' not in info:
                info['telegram_name'] = info.get('first_name', 'Пользователь')
                changes.append("добавлено имя")
            
            if changes:
                fixed_count += 1
                logger.info(f"Исправлен пользователь {uid}: {', '.join(changes)}")
        
        self.save_user_data()
        
        # Теперь отправляем тестовое уведомление всем
        test_msg = (
            f"🔔 <b>ТЕСТОВОЕ УВЕДОМЛЕНИЕ ОТ АДМИНИСТРАТОРА</b>\n\n"
            f"✅ Ваши уведомления были включены!\n\n"
            f"📅 Вы будете получать напоминания:\n"
            f"• В среду в 18:00 - о дежурстве в субботу\n"
            f"• В пятницу в 18:00 - о завтрашнем дежурстве\n"
            f"• В субботу в 10:00 - в день дежурства\n\n"  # ИЗМЕНЕНО
            f"📋 Используйте /start для просмотра меню"
        )
        
        sent_count = 0
        error_count = 0
        
        for uid in self.user_data.keys():
            try:
                await self.bot_instance.send_message(
                    chat_id=int(uid),
                    text=test_msg,
                    parse_mode=ParseMode.HTML
                )
                sent_count += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                error_count += 1
                logger.error(f"Ошибка отправки теста пользователю {uid}: {e}")
        
        await update.message.reply_text(
            f"✅ <b>ИСПРАВЛЕНИЕ ЗАВЕРШЕНО</b>\n\n"
            f"📊 Исправлено пользователей: {fixed_count}\n"
            f"📤 Отправлено тестовых уведомлений: {sent_count}\n"
            f"❌ Ошибок отправки: {error_count}\n\n"
            f"🔔 Теперь все пользователи будут получать уведомления!",
            parse_mode=ParseMode.HTML
        )

    # ============= КОНЕЦ НОВЫХ ДИАГНОСТИЧЕСКИХ КОМАНД =============

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий кнопок"""
        query = update.callback_query
        await query.answer()

        user_id = str(query.from_user.id)
        data = query.data

        if data == "admin_panel":
            if self.is_admin(user_id) and self.admin_sessions.get(user_id, {}).get("logged_in"):
                await self.show_admin_panel(query)
            else:
                await query.edit_message_text(
                    "❌ <b>ДОСТУП ЗАПРЕЩЕН</b>\n\n"
                    "Доступ только админам\n"
                    "<code>Зайдите с нужного аккаунта!!</code>",
                    parse_mode=ParseMode.HTML
                )
            return

        handlers = {
            "full_schedule": self.show_full_schedule,
            "my_duty": self.show_my_duty,
            "instructions": self.show_instructions,
            "protocol": self.download_protocol,
            "questions": self.show_questions,
            "back_to_main": self.back_to_main,
            "change_profile": self.change_profile,
            "admin_panel": self.show_admin_panel,
            "admin_logout": self.admin_logout,
            "admin_refresh_schedule": self.admin_refresh_schedule,
            "admin_schedule": self.show_admin_schedule,
            "admin_employees": self.show_admin_employees,
            "admin_files": self.show_admin_files,
            "admin_stats": self.show_admin_stats,
            "admin_add_duty": self.admin_add_duty,
            "admin_remove_duty": self.admin_remove_duty,
            "admin_add_employee": self.admin_add_employee,
            "admin_remove_employee": self.admin_remove_employee,
            "admin_edit_phone": self.admin_edit_phone,
            "admin_list_employees": self.admin_list_employees,
            "admin_upload_protocol": self.admin_upload_protocol,
            "admin_delete_protocol": self.admin_delete_protocol,
            "admin_check_protocol": self.admin_check_protocol,
            "admin_pin_protocol": self.admin_pin_protocol,
            # "admin_send_protocol" - УДАЛЕНО, так как нет обработчика
        }

        if data.startswith("emp_"):
            employee_name = data[4:]
            await self.register_employee(query, employee_name)
        elif data in handlers:
            await handlers[data](query, context)

    async def show_full_schedule(self, query, context=None):
        """Показать полный график дежурств"""
        schedule_text = self.schedule_generator.get_schedule_text()
        text = schedule_text

        if len(text) > 4000:
            await query.edit_message_text(
                text[:4000],
                parse_mode=ParseMode.HTML
            )
            await query.message.reply_text(
                text[4000:],
                parse_mode=ParseMode.HTML,
                reply_markup=self.get_back_keyboard()
            )
        else:
            await query.edit_message_text(
                text,
                reply_markup=self.get_back_keyboard(),
                parse_mode=ParseMode.HTML
            )

    async def show_my_duty(self, query, context=None):
        """Показать дежурства текущего пользователя"""
        user_id = str(query.from_user.id)

        if user_id not in self.user_data:
            await query.edit_message_text("❌ Сначала зарегистрируйтесь /start")
            return

        employee_name = self.user_data[user_id].get("selected_employee")

        if not employee_name:
            await query.edit_message_text("❌ Выберите сотрудника в меню")
            return

        duties = self.schedule_generator.get_employee_schedule(employee_name)
        today = datetime.now(MOSCOW_TZ).replace(tzinfo=None)
        future_duties = [d for d in duties if d["date_obj"] >= today]

        if not future_duties:
            text = f"📅 <b>БЛИЖАЙШИЕ ДЕЖУРСТВА: {employee_name}</b>\n\n"
            text += "Нет запланированных дежурств"
        else:
            text = f"📅 <b>БЛИЖАЙШИЕ ДЕЖУРСТВА: {employee_name}</b>\n\n"

            for duty in future_duties[:3]:
                days_left = (duty["date_obj"] - today).days

                if duty["is_pair"]:
                    partners = [e for e in duty["employees"] if e != employee_name]
                    duty_text = f"{duty['date']} (с {', '.join(partners)})"
                    phones = ', '.join(duty['phones'])
                else:
                    duty_text = duty['date']
                    phones = duty['phones'][0]

                text += f"{duty_text}\n"
                text += f"📅 Осталось: {days_left} дней\n\n"
                text += f"📞 {phones}\n\n"

        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    async def back_to_main(self, query, context=None):
        """Вернуться в главное меню"""
        user_id = str(query.from_user.id)
        user_info = self.user_data.get(user_id, {})
        employee_name = user_info.get("selected_employee")

        if employee_name:
            text = (
                "<b>🏠 ГЛАВНОЕ МЕНЮ</b>\n\n"
                f"👤 <b>Сотрудник:</b> {employee_name}\n"
                f"📞 <b>Телефон:</b> {EMPLOYEE_PHONES.get(employee_name, 'не указан')}\n\n"
                "<i>Выберите действие:</i>"
            )
        else:
            text = (
                "<b>🏠 ГЛАВНОЕ МЕНЮ</b>\n\n"
                "<i>Для доступа к функциям\n"
                "необходима регистрация.</i>\n\n"
                "Выберите действие:"
            )

        await query.edit_message_text(
            text,
            reply_markup=self.get_main_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )

    async def download_protocol(self, query, context=None):
        """Скачать протокол разногласий"""
        try:
            if not os.path.exists(self.protocol_file_path):
                await query.edit_message_text(
                    "❌ Файл не найден",
                    reply_markup=self.get_back_keyboard(),
                    parse_mode=ParseMode.HTML
                )
                return

            with open(self.protocol_file_path, 'rb') as f:
                await query.message.reply_document(
                    document=f,
                    filename="Протокол разногласий.docx",
                    caption="📄 Протокол разногласий",
                    parse_mode=ParseMode.HTML
                )

            await query.edit_message_text(
                "✅ Файл отправлен",
                reply_markup=self.get_back_keyboard(),
                parse_mode=ParseMode.HTML
            )

        except Exception as e:
            await query.edit_message_text(
                f"❌ Ошибка: {str(e)[:50]}",
                reply_markup=self.get_back_keyboard(),
                parse_mode=ParseMode.HTML
            )

    async def show_instructions(self, query, context=None):
        """Показать инструкцию по дежурству"""
        text = (
            "<b>📝 ИНСТРУКЦИЯ ПО ДЕЖУРСТВУ</b>\n\n"
            "<b>▸ ПЕРЕД ДЕЖУРСТВОМ (пятница):</b>\n"
            "1. Позвонить в приемную: 5600 через вн. телефон в 17:00\n"
            "2. Сообщить о дежурстве и попросить оставить ключи на вахте\n\n"
            "<b>▸ В ДЕНЬ ДЕЖУРСТВА (суббота):</b>\n"
            "1. Прийти к 6:50 в АДЦ\n"
            "2. Взять ключ на охране от кубов\n"
            "3. Открыть кабинет 6002\n"
            "4. Сфотографировать открытый 6002 кабинет (как доказательство присутствия)\n"
            "5. Находиться там до 8:00\n"
            "6. После дежурства отписать в группу (пример: Доброе утро, никого из ЗГД не было)\n\n"
            "<b>▸ ОФОРМЛЕНИЕ ПРОТОКОЛА:</b>\n"
            "1. Распечатать бланк (предварительно написать дату)\n"
            "2. Расписаться на обороте:\n"
            "   ФИО, Должность, Модуль, Дата, Подпись\n"
            "3. Оставить у Е.С. Денисовой"
        )

        await query.edit_message_text(
            text,
            reply_markup=self.get_back_keyboard(),
            parse_mode=ParseMode.HTML
        )

    async def show_questions(self, query, context=None):
        """Показать частые вопросы"""
        text = (
            "<b>❓ ЧАСТЫЕ ВОПРОСЫ</b>\n\n"
            "<b>▸ Не могу прийти на дежурство?</b>\n"
            "• Найти замену из списка\n"
            "• Сообщить М.С. Портновой\n"
            "• Пропуск = депремирование\n\n"
            "<b>▸ Ключ не на месте?</b>\n"
            "• Взять на охране ключ от теннисной переговорной\n"
            "• Сидеть возле кубов\n"
            "• В случае если пришёл ЗГД, провести в другую переговорную"
        )

        await query.edit_message_text(
            text,
            reply_markup=self.get_back_keyboard(),
            parse_mode=ParseMode.HTML
        )

    async def change_profile(self, query, context=None):
        """Изменение привязанного сотрудника"""
        text = (
            "<b>👤 ИЗМЕНЕНИЕ ПРОФИЛЯ</b>\n\n"
            "Выберите ваше ФИО из списка сотрудников.\n\n"
            "<i>Текущий выбор будет заменен.</i>"
        )

        keyboard = []
        employees_list = list(EMPLOYEE_PHONES.keys())

        for i in range(0, len(employees_list), 2):
            row = []
            if i < len(employees_list):
                row.append(InlineKeyboardButton(
                    f"{employees_list[i]}",
                    callback_data=f"emp_{employees_list[i]}"
                ))
            if i + 1 < len(employees_list):
                row.append(InlineKeyboardButton(
                    f"{employees_list[i + 1]}",
                    callback_data=f"emp_{employees_list[i + 1]}"
                ))
            if row:
                keyboard.append(row)

        keyboard.append([InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_main")])

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    async def register_employee(self, query, employee_name: str):
        """Регистрация сотрудника для пользователя"""
        user_id = str(query.from_user.id)

        if user_id in self.user_data:
            self.user_data[user_id]["selected_employee"] = employee_name
            self.user_data[user_id]["registered_at"] = datetime.now().isoformat()
            self.save_user_data()

            text = (
                "<b>✅ РЕГИСТРАЦИЯ УСПЕШНА</b>\n\n"
                f"Ваш аккаунт привязан к:\n"
                f"<b>{employee_name}</b>\n\n"
                f"📞 Телефон: {EMPLOYEE_PHONES.get(employee_name, 'не указан')}\n"
                f"🔔 Уведомления: {'✅ Включены' if self.user_data[user_id].get('notifications', True) else '❌ Отключены'}\n\n"
                "<i>Теперь вы можете пользоваться всеми функциями бота.</i>\n\n"
                "Выберите действие:"
            )

            await query.edit_message_text(
                text,
                reply_markup=self.get_main_keyboard(user_id),
                parse_mode=ParseMode.HTML
            )
        else:
            await query.edit_message_text(
                "Ошибка регистрации. Пожалуйста, начните снова командой /start",
                parse_mode=ParseMode.HTML
            )

    async def show_admin_panel(self, query, context=None):
        """Показать админ-панель"""
        user_id = str(query.from_user.id)

        if not self.is_admin(user_id) or not self.admin_sessions.get(user_id, {}).get("logged_in"):
            await query.edit_message_text(
                "❌ <b>ДОСТУП ЗАПРЕЩЕН</b>",
                parse_mode=ParseMode.HTML
            )
            return

        text = (
            "⚙️ <b>АДМИН-ПАНЕЛЬ</b>\n\n"
            "Доступные функции:\n\n"
            "📅 <b>Управление графиком:</b>\n"
            "• Добавить/удалить дежурство\n"
            "• Просмотреть график\n\n"
            "👥 <b>Управление сотрудниками:</b>\n"
            "• Добавить/удалить сотрудника\n"
            "• Изменить телефон\n"
            "• Список сотрудников\n\n"
            "📁 <b>Управление файлами:</b>\n"
            "• Загрузить протокол\n"
            "• Прикрепить протокол\n"
            "• Удалить файлы\n"
            "• Проверить файл\n\n"
            "📊 <b>Статистика:</b>\n"
            "• Активность пользователей\n"
            "• История действий\n\n"
            "<i>Выберите раздел:</i>"
        )

        await query.edit_message_text(
            text,
            reply_markup=self.get_admin_keyboard(),
            parse_mode=ParseMode.HTML
        )

    async def admin_logout(self, query, context=None):
        """Выход из админ-панели"""
        user_id = str(query.from_user.id)

        if user_id in self.admin_sessions:
            del self.admin_sessions[user_id]

        if user_id in self.user_data:
            self.user_data[user_id]["is_admin"] = False
            self.save_user_data()

        await query.edit_message_text(
            "✅ <b>ВЫ УСПЕШНО ВЫШЛИ ИЗ АДМИН-ПАНЕЛИ</b>\n\n"
            "Все права администратора отозваны.",
            reply_markup=self.get_main_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )

    async def admin_refresh_schedule(self, query, context=None):
        """Обновить отображение графика"""
        await self.show_admin_schedule(query, context)

    async def show_admin_schedule(self, query, context=None):
        """Показать управление графиком"""
        text = (
            "📅 <b>УПРАВЛЕНИЕ ГРАФИКОМ ДЕЖУРСТВ</b>\n\n"
            "Доступные действия:\n\n"
            "➕ <b>Добавить дежурство:</b>\n"
            "Создать новую запись в графике\n\n"
            "➖ <b>Удалить дежурство:</b>\n"
            "Удалить существующую запись\n\n"
            "📋 <b>Просмотреть график:</b>\n"
            "Посмотреть текущий график\n\n"
            "🔄 <b>Обновить график:</b>\n"
            "Обновить отображение графика\n\n"
            "<i>Выберите действие:</i>"
        )

        await query.edit_message_text(
            text,
            reply_markup=self.get_schedule_admin_keyboard(),
            parse_mode=ParseMode.HTML
        )

    async def show_admin_employees(self, query, context=None):
        """Показать управление сотрудниками"""
        text = (
            "👥 <b>УПРАВЛЕНИЕ СОТРУДНИКАМИ</b>\n\n"
            "Доступные действия:\n\n"
            "➕ <b>Добавить сотрудника:</b>\n"
            "Добавить нового сотрудника в систему\n\n"
            "➖ <b>Удалить сотрудника:</b>\n"
            "Удалить сотрудника из системы\n\n"
            "📞 <b>Изменить телефон:</b>\n"
            "Обновить контактный номер\n\n"
            "👥 <b>Список сотрудников:</b>\n"
            "Просмотреть всех сотрудников\n\n"
            "<i>Выберите действие:</i>"
        )

        await query.edit_message_text(
            text,
            reply_markup=self.get_employees_admin_keyboard(),
            parse_mode=ParseMode.HTML
        )

    async def show_admin_files(self, query, context=None):
        """Показать управление файлами"""
        protocol_exists = os.path.exists(self.protocol_file_path)

        text = (
            "📁 <b>УПРАВЛЕНИЕ ФАЙЛАМИ</b>\n\n"
            f"📄 <b>Протокол разногласий:</b>\n"
            f"Статус: {'✅ Доступен' if protocol_exists else '❌ Отсутствует'}\n"
            f"Прикреплен: {'✅ Да' if self.protocol_attached_file_id else '❌ Нет'}\n\n"
            "Доступные действия:\n\n"
            "📤 <b>Загрузить протокол:</b>\n"
            "Добавить новый файл протокола\n\n"
            "📎 <b>Прикрепить протокол:</b>\n"
            "Сделать файл доступным в закрепленном сообщении\n\n"
            "🗑 <b>Удалить протокол:</b>\n"
            "Удалить текущий файл протокола\n\n"
            "📄 <b>Проверить файл:</b>\n"
            "Проверить наличие и доступность\n\n"
            "<i>Выберите действие:</i>"
        )

        await query.edit_message_text(
            text,
            reply_markup=self.get_files_admin_keyboard(),
            parse_mode=ParseMode.HTML
        )

    async def show_admin_stats(self, query, context=None):
        """Показать статистику"""
        total_users = len(self.user_data)
        active_today = 0
        today = datetime.now().date()

        for user_info in self.user_data.values():
            last_active = user_info.get("last_active")
            if last_active:
                try:
                    last_active_date = datetime.fromisoformat(last_active).date()
                    if last_active_date == today:
                        active_today += 1
                except:
                    pass

        auto_linked = 0
        for user_info in self.user_data.values():
            if user_info.get("selected_employee"):
                username = user_info.get("username", "")
                if username and self.get_employee_by_username(username):
                    auto_linked += 1

        # Проверяем, сколько дежурств запланировано на ближайшую субботу
        next_saturday = None
        today_date = datetime.now(MOSCOW_TZ).replace(tzinfo=None).date()
        for date in range(1, 8):  # Проверяем ближайшие 7 дней
            check_date = today_date + timedelta(days=date)
            if check_date.weekday() == 5:  # 5 = суббота
                next_saturday = check_date
                break

        next_duty = None
        if next_saturday:
            for date_str, duty in self.schedule_generator.schedule.items():
                if duty["date_obj"].date() == next_saturday:
                    next_duty = duty
                    break

        text = (
            "📊 <b>СТАТИСТИКА СИСТЕМЫ</b>\n\n"
            f"👥 <b>Всего пользователей:</b> {total_users}\n"
            f"📱 <b>Активных сегодня:</b> {active_today}\n"
            f"🤖 <b>Автопривязанных:</b> {auto_linked}\n"
            f"📅 <b>Дежурств в графике:</b> {len(self.schedule_generator.schedule)}\n"
            f"👤 <b>Всего сотрудников:</b> {len(EMPLOYEE_PHONES)}\n\n"
        )

        if next_duty:
            text += f"<b>Следующее дежурство ({next_saturday.strftime('%d.%m.%Y')}):</b>\n"
            if next_duty["is_pair"]:
                text += f"• {next_duty['employees'][0]} + {next_duty['employees'][1]}\n"
            else:
                text += f"• {next_duty['employees'][0]}\n"
        else:
            text += f"<b>Ближайшая суббота ({next_saturday.strftime('%d.%m.%Y')}):</b>\n"
            text += "• Дежурных нет\n"

        text += f"\n<b>Расписание уведомлений (ВСЕМ):</b>\n"
        text += "• Среда 18:00 - уведомление о дежурстве в субботу\n"
        text += "• Пятница 18:00 - напоминание о завтрашнем дежурстве\n"
        text += "• Суббота 10:00 - напоминание в день дежурства\n"  # ИЗМЕНЕНО

        keyboard = [
            [InlineKeyboardButton("🔙 Назад в админку", callback_data="admin_panel")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats")]
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    async def admin_add_duty(self, query, context):
        """Добавить дежурство (инструкция)"""
        text = (
            "➕ <b>ДОБАВЛЕНИЕ ДЕЖУРСТВА</b>\n\n"
            "<i>Для добавления дежурства отправьте сообщение в формате:</i>\n\n"
            "<code>дата;сотрудник1,сотрудник2;телефон1,телефон2;пара</code>\n\n"
            "<b>Примеры:</b>\n"
            "• Для пары:\n"
            "<code>18.04.2026г.;Иванов И.И.,Петров П.П.;8-999-111-11-11,8-999-222-22-22;да</code>\n\n"
            "• Для одиночного:\n"
            "<code>25.04.2026г.;Сидоров С.С.;8-999-333-33-33;нет</code>\n\n"
            "<i>Примечание:</i> Можно добавлять только будущие дежурства.\n"
            "Прошедшие дежурства автоматически удаляются.\n\n"
            "<i>Отправьте сообщение с данными или нажмите 'Отмена':</i>"
        )

        keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="admin_schedule")]]
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        context.user_data['awaiting_duty_data'] = True

    async def admin_remove_duty(self, query, context):
        """Удалить дежурство (список)"""
        schedule_text = self.schedule_generator.get_schedule_text()

        text = (
                "➖ <b>УДАЛЕНИЕ ДЕЖУРСТВА</b>\n\n"
                "<i>Текущий график (только будущие дежурства):</i>\n\n" +
                schedule_text[:1500] +
                "\n\nДля удаления дежурства отправьте дату в формате:\n"
                "<code>дд.мм.ггггг.</code>\n\n"
                "<b>Пример:</b> <code>07.02.2026г.</code>\n\n"
                "<i>Отправьте дату или нажмите 'Отмена':</i>"
        )

        keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="admin_schedule")]]
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        context.user_data['awaiting_duty_remove'] = True

    async def admin_add_employee(self, query, context):
        """Добавить сотрудника (инструкция)"""
        text = (
            "➕ <b>ДОБАВЛЕНИЕ СОТРУДНИКА</b>\n\n"
            "<i>Для добавления сотрудника отправьте сообщение в формате:</i>\n\n"
            "<code>ФИО;телефон;telegram_username</code>\n\n"
            "<b>Пример:</b>\n"
            "<code>Иванов Иван Иванович;8-999-111-11-11;@ivanov</code>\n\n"
            "<i>Важно:</i>\n"
            "• ФИО в формате: Фамилия И.О.\n"
            "• Телефон в формате: 8-XXX-XXX-XX-XX\n"
            "• Telegram username с @ или без\n\n"
            "<i>Отправьте данные или нажмите 'Отмена':</i>"
        )

        keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="admin_employees")]]
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        context.user_data['awaiting_employee_add'] = True

    async def admin_remove_employee(self, query, context):
        """Удалить сотрудника (инструкция)"""
        employees_list = "\n".join([f"• {emp}" for emp in EMPLOYEE_PHONES.keys()])

        text = (
            "➖ <b>УДАЛЕНИЕ СОТРУДНИКА</b>\n\n"
            f"<b>Список сотрудников:</b>\n{employees_list}\n\n"
            "<i>Для удаления сотрудника отправьте его ФИО:</i>\n\n"
            "<b>Пример:</b>\n"
            "<code>Иванов И.И.</code>\n\n"
            "<i>Отправьте ФИО или нажмите 'Отмена':</i>"
        )

        keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="admin_employees")]]
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        context.user_data['awaiting_employee_remove'] = True

    async def admin_edit_phone(self, query, context):
        """Изменить телефон сотрудника (инструкция)"""
        employees_list = "\n".join([f"• {emp}" for emp in EMPLOYEE_PHONES.keys()])

        text = (
            "📞 <b>ИЗМЕНЕНИЕ ТЕЛЕФОНА СОТРУДНИКА</b>\n\n"
            f"<b>Список сотрудников:</b>\n{employees_list}\n\n"
            "<i>Для изменения телефона отправьте сообщение в формате:</i>\n\n"
            "<code>ФИО;новый телефон</code>\n\n"
            "<b>Пример:</b>\n"
            "<code>Денисова Е.С.;8-987-294-93-24</code>\n\n"
            "<i>Отправьте данные или нажмите 'Отмена':</i>"
        )

        keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="admin_employees")]]
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        context.user_data['awaiting_phone_edit'] = True

    async def admin_list_employees(self, query, context=None):
        """Показать список сотрудников"""
        employees_text = ""
        for i, (employee, phone) in enumerate(EMPLOYEE_PHONES.items(), 1):
            telegram_username = None
            for tg_user, emp_name in TELEGRAM_TO_EMPLOYEE.items():
                if emp_name == employee:
                    telegram_username = tg_user
                    break

            employees_text += f"{i}. <b>{employee}</b>\n"
            employees_text += f"   📞 {phone}\n"
            if telegram_username:
                employees_text += f"   📱 Telegram: {telegram_username}\n"
            employees_text += "\n"

        text = (
                "👥 <b>СПИСОК СОТРУДНИКОВ</b>\n\n" +
                employees_text +
                f"<b>Всего сотрудников:</b> {len(EMPLOYEE_PHONES)}"
        )

        keyboard = [
            [InlineKeyboardButton("➕ Добавить сотрудника", callback_data="admin_add_employee")],
            [InlineKeyboardButton("📞 Изменить телефон", callback_data="admin_edit_phone")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_employees")]
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    async def admin_upload_protocol(self, query, context=None):
        """Загрузить протокол (инструкция)"""
        text = (
            "📤 <b>ЗАГРУЗКА ПРОТОКОЛА</b>\n\n"
            "<i>Для загрузки файла протокола:</i>\n\n"
            "1. Отправьте файл в этот чат\n"
            "2. В подписи к файлу напишите <code>протокол</code>\n\n"
            "Файл будет автоматически сохранен.\n\n"
            "<b>Формат файла:</b> .docx\n"
            "<b>Рекомендуемое имя:</b> Протокол разногласий — пример.docx"
        )

        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_files")],
            [InlineKeyboardButton("📄 Проверить файл", callback_data="admin_check_protocol")]
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    async def admin_delete_protocol(self, query, context=None):
        """Удалить протокол"""
        if os.path.exists(self.protocol_file_path):
            try:
                os.remove(self.protocol_file_path)
                self.protocol_attached_file_id = None
                text = (
                    "🗑 <b>ФАЙЛ ПРОТОКОЛА УДАЛЕН</b>\n\n"
                    "Файл протокола был успешно удален.\n\n"
                    "<i>Пользователи больше не смогут скачать протокол.</i>"
                )
            except Exception as e:
                text = f"❌ <b>ОШИБКА УДАЛЕНИЯ:</b> {str(e)}"
        else:
            text = (
                "ℹ️ <b>ФАЙЛ НЕ НАЙДЕН</b>\n\n"
                "Файл протокола уже отсутствует."
            )

        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_files")],
            [InlineKeyboardButton("📄 Проверить файл", callback_data="admin_check_protocol")]
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    async def admin_check_protocol(self, query, context=None):
        """Проверить наличие файла протокола"""
        protocol_exists = os.path.exists(self.protocol_file_path)

        if protocol_exists:
            file_size = os.path.getsize(self.protocol_file_path)
            file_size_mb = file_size / (1024 * 1024)

            text = (
                "✅ <b>ФАЙЛ ПРОТОКОЛА НАЙДЕН</b>\n\n"
                f"📄 <b>Имя файла:</b> {os.path.basename(self.protocol_file_path)}\n"
                f"📁 <b>Размер:</b> {file_size_mb:.2f} МБ\n"
                f"📍 <b>Путь:</b> {self.protocol_file_path}\n"
                f"📎 <b>Прикреплен:</b> {'Да' if self.protocol_attached_file_id else 'Нет'}\n\n"
                "<i>Файл доступен для скачивания пользователями.</i>"
            )
        else:
            text = (
                "❌ <b>ФАЙЛ ПРОТОКОЛА НЕ НАЙДЕН</b>\n\n"
                f"<i>Путь:</i> {self.protocol_file_path}\n\n"
                "<b>Что делать:</b>\n"
                "1. Загрузите файл протокола\n"
                "2. Используйте кнопку 'Загрузить протокол'"
            )

        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_files")],
            [InlineKeyboardButton("📤 Загрузить протокол", callback_data="admin_upload_protocol")]
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    async def admin_pin_protocol(self, query, context=None):
        """Прикрепить протокол в закрепленное сообщение - ИСПРАВЛЕНО (удалена проблемная кнопка)"""
        if not os.path.exists(self.protocol_file_path):
            text = (
                "❌ <b>ФАЙЛ НЕ НАЙДЕН</b>\n\n"
                "Сначала загрузите файл протокола.\n"
                "Используйте кнопку 'Загрузить протокол'."
            )

            keyboard = [
                [InlineKeyboardButton("📤 Загрузить протокол", callback_data="admin_upload_protocol")],
                [InlineKeyboardButton("🔙 Назад", callback_data="admin_files")]
            ]

            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            return

        text = (
            "📎 <b>ПРИКРЕПЛЕНИЕ ПРОТОКОЛА</b>\n\n"
            "Для прикрепления протокола в закрепленное сообщение:\n\n"
            "1. Отправьте боту файл протокола\n"
            "2. В подписи к файлу напишите <code>закрепить</code>\n\n"
            "Файл будет автоматически закреплен в чате."
        )

        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_files")]
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    async def message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик текстовых сообщений для админ-панели"""
        user = update.effective_user
        user_id = str(user.id)
        message_text = update.message.text if update.message else ""

        if not self.is_admin(user_id) or not self.admin_sessions.get(user_id, {}).get("logged_in"):
            if message_text and message_text.startswith('/'):
                pass
            else:
                await update.message.reply_text(
                    "ℹ️ <b>ИНФОРМАЦИЯ</b>\n\n"
                    "Я бот для управления графиком дежурств.\n"
                    "Используйте кнопки меню для навигации.\n\n"
                    "<i>Для админ-функций необходимо войти в админ-панель.</i>",
                    parse_mode=ParseMode.HTML
                )
            return

        # Обработка админских команд
        if context.user_data.get('awaiting_duty_data'):
            try:
                parts = message_text.split(';')
                if len(parts) == 4:
                    date_str = parts[0].strip()
                    employees = [e.strip() for e in parts[1].split(',')]
                    phones = [p.strip() for p in parts[2].split(',')]
                    is_pair = parts[3].strip().lower() in ['да', 'yes', 'true', '1']

                    if len(employees) != len(phones):
                        await update.message.reply_text(
                            "❌ <b>ОШИБКА</b>\n\n"
                            "Количество сотрудников и телефонов не совпадает.",
                            parse_mode=ParseMode.HTML
                        )
                        return

                    success, message = self.schedule_generator.add_duty(date_str, employees, phones, is_pair)

                    if success:
                        await update.message.reply_text(
                            f"✅ <b>ДЕЖУРСТВО ДОБАВЛЕНО</b>\n\n"
                            f"📅 Дата: {date_str}\n"
                            f"👥 Сотрудники: {', '.join(employees)}\n"
                            f"📞 Телефоны: {', '.join(phones)}\n"
                            f"👫 Пара: {'Да' if is_pair else 'Нет'}\n\n"
                            "<i>График успешно обновлен.</i>",
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        await update.message.reply_text(
                            f"❌ <b>ОШИБКА ДОБАВЛЕНИЯ</b>\n\n{message}",
                            parse_mode=ParseMode.HTML
                        )
                else:
                    await update.message.reply_text(
                        "❌ <b>НЕВЕРНЫЙ ФОРМАТ</b>\n\n"
                        "Используйте формат:\n"
                        "<code>дата;сотрудники;телефоны;пара</code>",
                        parse_mode=ParseMode.HTML
                    )
            except Exception as e:
                await update.message.reply_text(
                    f"❌ <b>ОШИБКА:</b> {str(e)}\n\n"
                    "Проверьте правильность данных.",
                    parse_mode=ParseMode.HTML
                )
            context.user_data.pop('awaiting_duty_data', None)

        elif context.user_data.get('awaiting_duty_remove'):
            date_str = message_text.strip()
            success = self.schedule_generator.remove_duty(date_str)

            if success:
                await update.message.reply_text(
                    f"✅ <b>ДЕЖУРСТВО УДАЛЕНО</b>\n\n"
                    f"📅 Дата: {date_str}\n\n"
                    "<i>График успешно обновлен.</i>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    f"❌ <b>ДЕЖУРСТВО НЕ НАЙДЕНО</b>\n\n"
                    f"Дата: {date_str}\n\n"
                    "Проверьте правильность даты.",
                    parse_mode=ParseMode.HTML
                )
            context.user_data.pop('awaiting_duty_remove', None)

        elif context.user_data.get('awaiting_employee_add'):
            try:
                parts = message_text.split(';')
                if len(parts) == 3:
                    employee_name = parts[0].strip()
                    phone = parts[1].strip()
                    telegram_username = parts[2].strip()

                    success = self.schedule_generator.add_employee(employee_name, phone)

                    if success:
                        if telegram_username:
                            if not telegram_username.startswith('@'):
                                telegram_username = '@' + telegram_username
                            TELEGRAM_TO_EMPLOYEE[telegram_username.lower()] = employee_name

                        await update.message.reply_text(
                            f"✅ <b>СОТРУДНИК ДОБАВЛЕН</b>\n\n"
                            f"👤 ФИО: {employee_name}\n"
                            f"📞 Телефон: {phone}\n"
                            f"📱 Telegram: {telegram_username if telegram_username else 'не указан'}\n\n"
                            "<i>Сотрудник добавлен в систему.</i>",
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        await update.message.reply_text(
                            f"❌ <b>СОТРУДНИК УЖЕ СУЩЕСТВУЕТ</b>\n\n"
                            f"Имя: {employee_name}\n\n"
                            "Используйте другое ФИО.",
                            parse_mode=ParseMode.HTML
                        )
                else:
                    await update.message.reply_text(
                        "❌ <b>НЕВЕРНЫЙ ФОРМАТ</b>\n\n"
                        "Используйте формат:\n"
                        "<code>ФИО;телефон;telegram_username</code>",
                        parse_mode=ParseMode.HTML
                    )
            except Exception as e:
                await update.message.reply_text(
                    f"❌ <b>ОШИБКА:</b> {str(e)}\n\n"
                    "Проверьте правильность данных.",
                    parse_mode=ParseMode.HTML
                )
            context.user_data.pop('awaiting_employee_add', None)

        elif context.user_data.get('awaiting_employee_remove'):
            employee_name = message_text.strip()
            success = self.schedule_generator.remove_employee(employee_name)

            if success:
                telegram_usernames = []
                for tg_user, emp_name in list(TELEGRAM_TO_EMPLOYEE.items()):
                    if emp_name == employee_name:
                        telegram_usernames.append(tg_user)
                        del TELEGRAM_TO_EMPLOYEE[tg_user]

                telegram_info = f"\n📱 Telegram: {', '.join(telegram_usernames)}" if telegram_usernames else ""

                await update.message.reply_text(
                    f"✅ <b>СОТРУДНИК УДАЛЕН</b>\n\n"
                    f"👤 ФИО: {employee_name}{telegram_info}\n\n"
                    "<i>Сотрудник удален из системы.</i>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    f"❌ <b>СОТРУДНИК НЕ НАЙДЕН</b>\n\n"
                    f"Имя: {employee_name}\n\n"
                    "Проверьте правильность ФИО.",
                    parse_mode=ParseMode.HTML
                )
            context.user_data.pop('awaiting_employee_remove', None)

        elif context.user_data.get('awaiting_phone_edit'):
            try:
                parts = message_text.split(';')
                if len(parts) == 2:
                    employee_name = parts[0].strip()
                    new_phone = parts[1].strip()

                    success = self.schedule_generator.update_employee_phone(employee_name, new_phone)

                    if success:
                        await update.message.reply_text(
                            f"✅ <b>ТЕЛЕФОН ОБНОВЛЕН</b>\n\n"
                            f"👤 Сотрудник: {employee_name}\n"
                            f"📞 Новый телефон: {new_phone}\n\n"
                            "<i>Телефон успешно обновлен.</i>",
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        await update.message.reply_text(
                            f"❌ <b>СОТРУДНИК НЕ НАЙДЕН</b>\n\n"
                            f"Имя: {employee_name}\n\n"
                            "Проверьте правильность ФИО.",
                            parse_mode=ParseMode.HTML
                        )
                else:
                    await update.message.reply_text(
                        "❌ <b>НЕВЕРНЫЙ ФОРМАТ</b>\n\n"
                        "Используйте формат:\n"
                        "<code>ФИО;новый телефон</code>",
                        parse_mode=ParseMode.HTML
                    )
            except Exception as e:
                await update.message.reply_text(
                    f"❌ <b>ОШИБКА:</b> {str(e)}\n\n"
                    "Проверьте правильность данных.",
                    parse_mode=ParseMode.HTML
                )
            context.user_data.pop('awaiting_phone_edit', None)

        # Обработка загрузки файлов
        elif update.message and update.message.document:
            document = update.message.document
            caption = update.message.caption or ""

            if caption.lower() in ['протокол', 'protocol']:
                if document.file_name.endswith('.docx'):
                    try:
                        file = await document.get_file()
                        await file.download_to_drive(self.protocol_file_path)

                        await update.message.reply_text(
                            f"✅ <b>ФАЙЛ ПРОТОКОЛА ЗАГРУЖЕН</b>\n\n"
                            f"📄 Имя файла: {document.file_name}\n"
                            f"📁 Размер: {document.file_size / 1024:.1f} КБ\n\n"
                            "<i>Файл успешно сохранен и доступен для скачивания.</i>",
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        await update.message.reply_text(
                            f"❌ <b>ОШИБКА ЗАГРУЗКИ:</b> {str(e)}",
                            parse_mode=ParseMode.HTML
                        )
                else:
                    await update.message.reply_text(
                        "❌ <b>НЕВЕРНЫЙ ФОРМАТ ФАЙЛА</b>\n\n"
                        "Поддерживаются только файлы .docx",
                        parse_mode=ParseMode.HTML
                    )

            elif caption.lower() in ['закрепить', 'pin', 'прикрепить']:
                if document.file_name.endswith('.docx'):
                    try:
                        self.protocol_attached_file_id = document.file_id

                        message = await update.message.reply_document(
                            document=document.file_id,
                            caption="📄 <b>ПРОТОКОЛ РАЗНОГЛАСИЙ</b>\n\n"
                                    "<i>Бланк для заполнения во время дежурства</i>\n\n"
                                    "<b>ИНСТРУКЦИЯ:</b>\n"
                                    "1. Скачайте файл\n"
                                    "2. Распечатайте бланк\n"
                                    "3. Заполните дату дежурства\n"
                                    "4. Распишитесь на обороте\n"
                                    "5. Оставить у Е.С. Денисовой",
                            parse_mode=ParseMode.HTML
                        )

                        await context.bot.pin_chat_message(
                            chat_id=update.effective_chat.id,
                            message_id=message.message_id,
                            disable_notification=True
                        )

                        await update.message.reply_text(
                            f"✅ <b>ФАЙЛ ПРОТОКОЛА ПРИКРЕПЛЕН</b>\n\n"
                            f"📄 Имя файла: {document.file_name}\n"
                            f"📎 ID файла: {document.file_id}\n\n"
                            "<i>Файл закреплен в чате и доступен для скачивания.</i>",
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        await update.message.reply_text(
                            f"❌ <b>ОШИБКА ПРИКРЕПЛЕНИЯ:</b> {str(e)}",
                            parse_mode=ParseMode.HTML
                        )
                else:
                    await update.message.reply_text(
                        "❌ <b>НЕВЕРНЫЙ ФОРМАТ ФАЙЛА</b>\n\n"
                        "Поддерживаются только файлы .docx",
                        parse_mode=ParseMode.HTML
                    )

        elif message_text and not message_text.startswith('/'):
            await update.message.reply_text(
                "ℹ️ <b>ИНФОРМАЦИЯ</b>\n\n"
                "Для работы с админ-панелью используйте кнопки меню.\n"
                "Или вернитесь в главное меню.",
                reply_markup=self.get_admin_keyboard(),
                parse_mode=ParseMode.HTML
            )

    async def send_test_wednesday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда для тестирования отправки среднего уведомления"""
        user_id = str(update.effective_user.id)

        if not self.is_admin(user_id):
            await update.message.reply_text("❌ Только администратор может использовать эту команду.")
            return

        await update.message.reply_text("🔄 Отправляю тестовое среднее уведомление всем пользователям...")
        await self.send_wednesday_notification()
        await update.message.reply_text("✅ Тестовое среднее уведомление отправлено!")

    async def send_test_friday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда для тестирования отправки пятничного уведомления"""
        user_id = str(update.effective_user.id)

        if not self.is_admin(user_id):
            await update.message.reply_text("❌ Только администратор может использовать эту команду.")
            return

        await update.message.reply_text("🔄 Отправляю тестовое пятничное уведомление всем пользователям...")
        await self.send_friday_notification_all()
        await update.message.reply_text("✅ Тестовое пятничное уведомление отправлено!")

    async def send_test_saturday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда для тестирования отправки субботнего уведомления"""
        user_id = str(update.effective_user.id)

        if not self.is_admin(user_id):
            await update.message.reply_text("❌ Только администратор может использовать эту команду.")
            return

        await update.message.reply_text("🔄 Отправляю тестовое субботнее уведомление всем пользователям...")
        await self.send_saturday_notification_all()
        await update.message.reply_text("✅ Тестовое субботнее уведомление отправлено!")

    async def test_notification_for_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Тестирование уведомления для конкретного пользователя"""
        user_id = str(update.effective_user.id)

        if not self.is_admin(user_id):
            await update.message.reply_text("❌ Только администратор может использовать эту команду.")
            return

        # Проверяем аргументы
        if len(context.args) != 1:
            await update.message.reply_text(
                "❌ Неверный формат команды\n\n"
                "Используйте: /test_user <user_id>\n"
                "Пример: /test_user 123456789"
            )
            return

        target_user_id = context.args[0]

        # Тестовое сообщение
        test_message = (
            f"🔔 <b>ТЕСТОВОЕ УВЕДОМЛЕНИЕ</b>\n\n"
            f"📅 <b>Это тестовое сообщение от администратора</b>\n\n"
            f"✅ Получено: {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M')}\n\n"
            f"<i>Если вы видите это сообщение, значит система уведомлений работает корректно.</i>\n\n"
            f"<b>Расписание уведомлений (ВСЕМ):</b>\n"
            f"• Среда 18:00 - о дежурстве в субботу\n"
            f"• Пятница 18:00 - о завтрашнем дежурстве\n"
            f"• Суббота 10:00 - в день дежурства"  # ИЗМЕНЕНО
        )

        try:
            await self.bot_instance.send_message(
                chat_id=int(target_user_id),
                text=test_message,
                parse_mode=ParseMode.HTML
            )
            await update.message.reply_text(f"✅ Тестовое сообщение отправлено пользователю {target_user_id}")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка отправки: {str(e)}")

    async def send_notification_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Немедленная отправка уведомления (по умолчанию среднего)"""
        await self.send_test_wednesday(update, context)

    def run(self):
        """Запуск бота"""
        self.application = ApplicationBuilder().token(self.token).build()

        # Сохраняем ссылку на бота для использования в планировщике
        self.bot_instance = self.application.bot

        # Добавляем обработчики
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("admin", self.admin_login))
        self.application.add_handler(CommandHandler("test_wednesday", self.send_test_wednesday))
        self.application.add_handler(CommandHandler("test_friday", self.send_test_friday))
        self.application.add_handler(CommandHandler("test_saturday", self.send_test_saturday))
        self.application.add_handler(CommandHandler("test_user", self.test_notification_for_user))
        self.application.add_handler(CommandHandler("send_now", self.send_notification_now))
        
        # НОВЫЕ ДИАГНОСТИЧЕСКИЕ КОМАНДЫ (только для @Tamerlantcik)
        self.application.add_handler(CommandHandler("users", self.check_users_status))
        self.application.add_handler(CommandHandler("enable_all", self.enable_notifications_all))
        self.application.add_handler(CommandHandler("test_send", self.test_send_to_user))
        self.application.add_handler(CommandHandler("time", self.check_time))
        self.application.add_handler(CommandHandler("fix", self.fix_all_users))
        
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message_handler))
        self.application.add_handler(MessageHandler(filters.Document.ALL, self.message_handler))

        logger.info("Бот запущен...")
        logger.info("Режим уведомлений: среда 18:00 (всем), пятница 18:00 (всем), суббота 10:00 (всем)")  # ИЗМЕНЕНО
        logger.info(f"Диагностические команды доступны только для {SUPER_ADMIN_USERNAME}")

        # Запускаем планировщик
        loop = asyncio.get_event_loop()
        loop.create_task(self.setup_scheduler())

        self.application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )


if __name__ == "__main__":
    BOT_TOKEN = "8485938284:AAHl6RjZbecjayHhSrImN0uwmQ3LlajliwQ"
    bot = DutyBot(BOT_TOKEN)
    bot.run()
