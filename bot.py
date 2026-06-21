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
    "@karimov": "Каримов Т.Р.",
    "@korotkikh": "Коротких А.А.",
    "@kudryavtsev": "Кудрявцев А.А.",
    "@korobova": "Коробова И.А.",
}

# Телефоны сотрудников (Актуализированы по вашему новому фото)
EMPLOYEE_PHONES = {
    "Осипов Р.Э": "8-919-684-48-07",
    "Бадершаехова Э.Р": "8-927-490-95-52",
    "Коротких А.А.": "8-999-155-96-34",
    "Денисова Е.С.": "8-987-294-93-24",
    "Лиходько А.С.": "8-987-284-16-98",
    "Кудрявцев А.А.": "8-937-015-32-73",
    "Коробова И.А.": "8-917-858-22-50",
    "Лызина С.В.": "8-919-635-55-06",
    "Портнова М.С.": "8-951-891-52-12",
    "Горбунов Р.Д.": "8-963-124-85-46",
    "Аванесян А.А.": "8-965-622-17-98",
    "Каримов Т.Р.": "8-912-453-34-13",
}

# Строгая последовательность дежурств по кругу (из таблицы на фото)
DUTY_ROTATION_CIRCLE = [
    "Осипов Р.Э",
    "Бадершаехова Э.Р",
    "Коротких А.А.",
    "Денисова Е.С.",
    "Лиходько А.С.",
    "Кудрявцев А.А.",
    "Коробова И.А.",
    "Лызина С.В.",
    "Портнова М.С.",
    "Горбунов Р.Д.",
    "Аванесян А.А.",
    "Каримов Т.Р."
]

# Исходный базовый список для хранения ручных правок админов
DUTY_SCHEDULE = []


class DutyScheduleGenerator:
    """Генератор графика дежурств с поддержкой полного цикла из 12 недель"""

    def __init__(self, schedule_data: List[Dict]):
        self.schedule_data = schedule_data
        self.schedule = {}
        self.initialize_schedule()

    def initialize_schedule(self):
        """Инициализация первоначального графика"""
        for duty in self.schedule_data:
            self.schedule[duty["date"]] = {
                "employees": duty["employees"],
                "phones": duty["phones"],
                "is_pair": duty["is_pair"],
                "date_obj": duty["date_obj"]
            }
        logger.info(f"Загружен график на {len(self.schedule)} недель")
        self.remove_past_duties()

    def remove_past_duties(self):
        """Удаление прошедших ручных дежурств"""
        today = datetime.now(MOSCOW_TZ).replace(tzinfo=None)
        dates_to_remove = []

        for date_str, duty in self.schedule.items():
            if duty["date_obj"] < today:
                dates_to_remove.append(date_str)

        for date_str in dates_to_remove:
            del self.schedule[date_str]
            self.schedule_data = [d for d in self.schedule_data if d["date"] != date_str]

        if dates_to_remove:
            logger.info(f"Удалено {len(dates_to_remove)} прошедших ручных дежурств")

    def _get_upcoming_saturdays(self, count: int = 12) -> List[datetime]:
        """Генерирует список суббот вперед, начиная с текущей недели"""
        saturdays = []
        today = datetime.now(MOSCOW_TZ).replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)

        days_ahead = 5 - today.weekday()
        if days_ahead < 0:
            days_ahead += 7

        current_saturday = today + timedelta(days=days_ahead)

        for _ in range(count):
            saturdays.append(current_saturday)
            current_saturday += timedelta(days=7)

        return saturdays

    def _generate_dynamic_schedule(self) -> Dict[str, Dict]:
        """ИСПРАВЛЕНО: Строит полный цикл из 12 суббот подряд, накладывая ручные правки на автоматический круг"""
        # Базовая точка отсчета: 30.05.2026 — это Осипов Р.Э (индекс 0 в кругу)
        base_date = datetime(2026, 5, 30)
        base_index = 0

        now_moscow = datetime.now(MOSCOW_TZ).replace(tzinfo=None)
        all_saturdays = self._get_upcoming_saturdays(count=13)

        # Если сегодня суббота и время >= 8:00 утра, текущая суббота завершена — сдвигаем цикл на следующую субботу
        if now_moscow.weekday() == 5 and now_moscow.hour >= 8:
            active_saturdays = all_saturdays[1:13]  # Берем ровно 12 суббот со следующей недели
        else:
            active_saturdays = all_saturdays[:12]  # Берем ровно 12 суббот начиная с текущей недели

        dynamic_schedule = {}

        for sat in active_saturdays:
            date_str = sat.strftime("%d.%m.%Yг.")

            # Приоритет ручной записи админа
            if date_str in self.schedule:
                dynamic_schedule[date_str] = self.schedule[date_str]
            else:
                # Математический расчет по кругу (всегда выстраивает полный цикл из 12 человек вперед)
                weeks_diff = int((sat - base_date).days / 7)
                employee_index = (base_index + weeks_diff) % len(DUTY_ROTATION_CIRCLE)
                employee_name = DUTY_ROTATION_CIRCLE[employee_index]
                phone = EMPLOYEE_PHONES.get(employee_name, "не указан")

                dynamic_schedule[date_str] = {
                    "employees": [employee_name],
                    "phones": [phone],
                    "is_pair": False,
                    "date_obj": sat
                }

        return dynamic_schedule

    def get_schedule_text(self) -> str:
        """Форматирование графика в текстовый вид"""
        text = "📅 <b>АКТУАЛЬНЫЙ ГРАФИК ДЕЖУРСТВ</b>\n\n"

        # Получаем объединенный динамический график
        current_schedule = self._generate_dynamic_schedule()

        # Сортируем по дате
        duties_list = sorted(current_schedule.items(), key=lambda x: x[1]["date_obj"])

        if not duties_list:
            text += "Нет запланированных дежурств\n"
        else:
            for i, (date_str, duty) in enumerate(duties_list):
                if i == 0:
                    text += f"<b>{date_str} (Ближайшее)</b>\n"
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
        current_schedule = self._generate_dynamic_schedule()

        for date_str, duty in current_schedule.items():
            if employee_name in duty["employees"]:
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
        duties = self.get_employee_schedule(employee_name)
        return duties[0] if duties else None

    def get_todays_duty(self) -> Optional[Dict]:
        """Получить дежурных на сегодня"""
        now_moscow = datetime.now(MOSCOW_TZ).replace(tzinfo=None)
        today_str = now_moscow.strftime("%d.%m.%Yг.")

        # Проверяем ручные записи
        if today_str in self.schedule:
            return self.schedule[today_str]

        # Проверяем автоматический круг
        base_date = datetime(2026, 5, 30)
        all_saturdays = self._get_upcoming_saturdays(count=5)
        for sat in all_saturdays:
            if sat.strftime("%d.%m.%Yг.") == today_str:
                weeks_diff = int((sat - base_date).days / 7)
                employee_index = weeks_diff % len(DUTY_ROTATION_CIRCLE)
                employee_name = DUTY_ROTATION_CIRCLE[employee_index]
                return {
                    "employees": [employee_name],
                    "phones": [EMPLOYEE_PHONES.get(employee_name)],
                    "is_pair": False,
                    "date_obj": sat
                }
        return None

    def add_duty(self, date_str: str, employees: List[str], phones: List[str], is_pair: bool):
        """Добавить ручное дежурство (перезаписывает круг на эту дату)"""
        try:
            date_str_clean = date_str.replace("г.", "").strip()
            date_obj = datetime.strptime(date_str_clean, "%d.%m.%Y")
            today = datetime.now(MOSCOW_TZ).replace(tzinfo=None)

            if date_obj < today and date_str != today.strftime("%d.%m.%Yг."):
                return False, "Дата должна быть в будущем или текущей"

            if not date_str.endswith("г."):
                date_str += "г."

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

            logger.info(f"Добавлено ручное дежурство: {date_str} - {employees}")
            return True, "Дежурство успешно добавлено"
        except Exception as e:
            logger.error(f"Ошибка добавления дежурства: {e}")
            return False, f"Ошибка: {str(e)}"

    def remove_duty(self, date_str: str) -> bool:
        """Удалить ручное дежурство (вернуть на эту дату автоматический круг)"""
        if not date_str.endswith("г."):
            date_str += "г."
        if date_str in self.schedule:
            del self.schedule[date_str]
            self.schedule_data = [d for d in self.schedule_data if d["date"] != date_str]
            logger.info(f"Удалено ручное дежурство: {date_str}")
            return True
        return False

    def update_employee_phone(self, employee_name: str, new_phone: str) -> bool:
        global EMPLOYEE_PHONES
        if employee_name in EMPLOYEE_PHONES:
            EMPLOYEE_PHONES[employee_name] = new_phone
            logger.info(f"Обновлен телефон {employee_name}: {new_phone}")
            return True
        return False

    def add_employee(self, employee_name: str, phone: str) -> bool:
        global EMPLOYEE_PHONES
        if employee_name not in EMPLOYEE_PHONES:
            EMPLOYEE_PHONES[employee_name] = phone
            logger.info(f"Добавлен сотрудник: {employee_name} - {phone}")
            return True
        return False

    def remove_employee(self, employee_name: str) -> bool:
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

        # 3. Уведомление в СУББОТУ в 10:00 - ВСЕМ пользователям в день дежурства
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

            if today.weekday() != 2:  # 2 = среда
                logger.warning(f"send_wednesday_notification вызван не в среду! День недели: {today.weekday()}")
                return

            logger.info(f"Запуск send_wednesday_notification в среду {today.strftime('%d.%m.%Y %H:%M')}")
            saturday = today + timedelta(days=3)

            # Ищем дежурных на эту субботу в динамическом расписании
            current_schedule = self.schedule_generator._generate_dynamic_schedule()
            duty_saturday = next((d for d in current_schedule.values() if d["date_obj"].date() == saturday.date()),
                                 None)

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

            await self._send_notification_to_all_users(message, "среда")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления в среду: {e}")

    async def send_friday_notification_all(self):
        """Отправка уведомления в ПЯТНИЦУ в 18:00 ВСЕМ пользователям о завтрашнем дежурстве"""
        try:
            today = datetime.now(MOSCOW_TZ).replace(tzinfo=None)

            if today.weekday() != 4:  # 4 = пятница
                logger.warning(f"send_friday_notification_all вызван не в пятницу! День недели: {today.weekday()}")
                return

            logger.info(f"Запуск send_friday_notification_all в пятницу {today.strftime('%d.%m.%Y %H:%M')}")
            tomorrow = today + timedelta(days=1)

            current_schedule = self.schedule_generator._generate_dynamic_schedule()
            duty_tomorrow = next((d for d in current_schedule.values() if d["date_obj"].date() == tomorrow.date()),
                                 None)

            if not duty_tomorrow:
                logger.info(f"На {tomorrow.strftime('%d.%m.%Y')} дежурных нет")
                message = (
                    f"🔔 <b>НАПОМИНАНИЕ О ЗАВТРАШНЕМ ДЕЖУРСТВЕ</b>\n\n"
                    f"📅 <b>Завтра ({tomorrow.strftime('%d.%m.%Y')}) дежурных нет</b>\n\n"
                    f"✅ Можете не беспокоиться!\n\n"
                    f"<i>Следующее напоминание: суббота в 10:00</i>"
                )
            else:
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
                    f"<i>Следующее напоминание: суббота в 10:00</i>"
                )

            await self._send_notification_to_all_users(message, "пятница")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления в пятницу: {e}")

    async def send_saturday_notification_all(self):
        """Отправка уведомления в СУББОТУ в 10:00 ВСЕМ пользователям в день дежурства"""
        try:
            today = datetime.now(MOSCOW_TZ).replace(tzinfo=None)

            if today.weekday() != 5:  # 5 = суббота
                logger.warning(f"send_saturday_notification_all вызван не в субботу! День недели: {today.weekday()}")
                return

            logger.info(f"Запуск send_saturday_notification_all в субботу {today.strftime('%d.%m.%Y %H:%M')}")
            duty_today = self.schedule_generator.get_todays_duty()

            if not duty_today:
                logger.info(f"На {today.strftime('%d.%m.%Y')} дежурных нет")
                message = (
                    f"🔔 <b>ИНФОРМАЦИЯ О ДЕЖУРСТВЕ</b>\n\n"
                    f"📅 <b>Сегодня ({today.strftime('%d.%m.%Y')}) дежурных нет</b>\n\n"
                    f"✅ Всем хороших выходных!\n\n"
                    f"<i>Следующее напоминание: среда в 18:00</i>"
                )
            else:
                if duty_today["is_pair"]:
                    duty_text = f"{duty_today['employees'][0]} + {duty_today['employees'][1]}"
                    phones_text = f"{duty_today['phones'][0]} + {duty_today['phones'][1]}"
                else:
                    duty_text = f"{duty_today['employees'][0]}"
                    phones_text = f"{duty_today['phones'][0]}"

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

            await self._send_notification_to_all_users(message, "суббота")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления в субботу: {e}")

    async def _send_notification_to_all_users(self, message: str, notification_type: str):
        """Отправка уведомлений ВСЕМ пользователям с проверкой ID"""
        sent_count = 0
        error_count = 0
        deactivated_users = []

        self.load_user_data()
        logger.info(f"Отправка уведомления {notification_type} - всего пользователей: {len(self.user_data)}")

        for user_id, user_info in list(self.user_data.items()):
            try:
                chat_id = int(user_id)
                await self.bot_instance.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode=ParseMode.HTML
                )
                sent_count += 1
                logger.debug(f"✓ Отправлено пользователю {user_id}")
                await asyncio.sleep(0.1)
            except ValueError:
                logger.error(f"✗ Некорректный ID пользователя: {user_id}")
                error_count += 1
                deactivated_users.append(user_id)
            except Exception as e:
                error_count += 1
                error_msg = str(e).lower()
                logger.error(f"✗ Ошибка отправки пользователю {user_id}: {error_msg[:100]}")

                if any(phrase in error_msg for phrase in [
                    'bot was blocked', 'user not found', 'chat not found',
                    'kicked', 'deactivated', 'forbidden', 'can\'t initiate'
                ]):
                    logger.warning(f"Удаляю неактивного пользователя: {user_id}")
                    deactivated_users.append(user_id)

        for user_id in deactivated_users:
            self.user_data.pop(user_id, None)

        if deactivated_users:
            self.save_user_data()

        logger.info(f"=== ИТОГИ УВЕДОМЛЕНИЯ {notification_type.upper()} ===")
        logger.info(f"Всего в базе: {len(self.user_data) + len(deactivated_users)}")
        logger.info(f"Отправлено успешно: {sent_count}")
        logger.info(f"Ошибок: {error_count}")
        logger.info(f"Удалено неактивных: {len(deactivated_users)}")

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

    def get_employee_selection_keyboard(self, prefix: str = "emp_") -> InlineKeyboardMarkup:
        """Динамическая клавиатура для выбора сотрудника"""
        keyboard = []
        employees_list = list(EMPLOYEE_PHONES.keys())

        for i in range(0, len(employees_list), 2):
            row = []
            if i < len(employees_list):
                row.append(InlineKeyboardButton(f"{employees_list[i]}", callback_data=f"{prefix}{employees_list[i]}"))
            if i + 1 < len(employees_list):
                row.append(
                    InlineKeyboardButton(f"{employees_list[i + 1]}", callback_data=f"{prefix}{employees_list[i + 1]}"))
            if row:
                keyboard.append(row)

        if prefix.startswith("add_e"):
            keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="admin_schedule")])

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
                "notifications": True,
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
                reply_markup=self.get_employee_selection_keyboard(prefix="emp_"),
                parse_mode=ParseMode.HTML
            )
            return

        await update.message.reply_text(
            welcome_text,
            reply_markup=self.get_main_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )

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

    # ============= ДИАГНОСТИЧЕСКИЕ КОМАНДЫ ДЛЯ @Tamerlantcik =============
    async def check_users_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Подробная проверка статуса всех пользователей - ТОЛЬКО ДЛЯ @Tamerlantcik"""
        user = update.effective_user

        if not self.is_super_admin(user.username):
            await update.message.reply_text(
                "❌ <b>ДОСТУП ЗАПРЕЩЕН</b>\n\nЭта команда доступна только @Tamerlantcik",
                parse_mode=ParseMode.HTML
            )
            return

        self.load_user_data()
        text = "📊 <b>СТАТУС ПОЛЬЗОВАТЕЛЕЙ</b>\n\n"
        total = len(self.user_data)
        with_employee = 0
        notifications_on = 0
        notifications_off = 0

        for uid, info in self.user_data.items():
            name = info.get('telegram_name', 'Неизвестно')
            username = info.get('username', 'Нет username')
            employee = info.get('selected_employee', None)
            notifications = info.get('notifications', True)

            if employee and employee != 'None' and employee != '❌ НЕ ВЫБРАН':
                with_employee += 1
            if notifications:
                notifications_on += 1
            else:
                notifications_off += 1

            notif_status = "✅ ВКЛ" if notifications else "❌ ВЫКЛ"
            employee_display = employee if employee else "❌ НЕ ВЫБРАН"

            text += f"<b>{name}</b>\n📱 @{username}\n🆔 {uid}\n👤 {employee_display}\n🔔 {notif_status}\n📅 Последний вход: {info.get('last_active', 'Неизвестно')[:16]}\n\n"

        text += f"<b>ИТОГО:</b> {total} пользователей\n👤 С выбором сотрудника: {with_employee}\n🔔 Уведомления включены: {notifications_on}\n🔕 Уведомления выключены: {notifications_off}"
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    async def enable_notifications_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Включить уведомления для всех пользователей - ТОЛЬКО ДЛЯ @Tamerlantcik"""
        user = update.effective_user
        if not self.is_super_admin(user.username): return

        self.load_user_data()
        enabled_count = 0
        for uid, info in self.user_data.items():
            if not info.get('notifications', True):
                self.user_data[uid]['notifications'] = True
                enabled_count += 1

        self.save_user_data()
        await update.message.reply_text(
            f"✅ Уведомления включены для {enabled_count} пользователей\n📊 Всего пользователей: {len(self.user_data)}",
            parse_mode=ParseMode.HTML)

    async def test_send_to_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Тест отправки конкретному пользователю - ТОЛЬКО ДЛЯ @Tamerlantcik"""
        user = update.effective_user
        if not self.is_super_admin(user.username): return

        args = context.args
        if len(args) < 1:
            await update.message.reply_text(
                "❌ Укажите user_id или username\nПример: /test_send 123456789\nИли: /test_send @username")
            return

        target = args[0]
        target_id = None
        target_name = target

        if target.startswith('@'):
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
            target_id = target

        test_msg = (
            f"🔔 <b>ТЕСТОВОЕ УВЕДОМЛЕНИЕ</b>\n\n👤 Получатель: {target_name}\n🆔 ID: {target_id}\n📅 Время: {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M:%S')}\n\n"
            f"✅ Если вы видите это сообщение, значит:\n   • Бот может отправлять вам сообщения\n   • Вы не блокировали бота\n   • Уведомления будут приходить по расписанию\n\n"
            f"📅 Расписание уведомлений:\n• Среда 18:00 - о дежурстве в субботу\n• Пятница 18:00 - о завтрашнем дежурстве\n• Суббота 10:00 - в день дежурства"
        )

        try:
            await self.bot_instance.send_message(chat_id=int(target_id), text=test_msg, parse_mode=ParseMode.HTML)
            await update.message.reply_text(f"✅ Тестовое сообщение отправлено {target_name}")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка отправки: {str(e)[:200]}")

    async def check_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверка времени на сервере - ТОЛЬКО ДЛЯ @Tamerlantcik"""
        user = update.effective_user
        if not self.is_super_admin(user.username): return

        now = datetime.now(MOSCOW_TZ)
        weekdays = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        weekday_ru = weekdays[now.weekday()]

        next_notification = ""
        if now.weekday() == 1 and now.hour < 18:
            next_notification = "Среда 18:00 (через 1 день)"
        elif now.weekday() == 2 and now.hour < 18:
            next_notification = "Среда 18:00 (сегодня)"
        elif now.weekday() == 3:
            next_notification = "Пятница 18:00 (через 1 день)"
        elif now.weekday() == 4 and now.hour < 18:
            next_notification = "Пятница 18:00 (сегодня)"
        elif now.weekday() == 5 and now.hour < 10:
            next_notification = "Суббота 10:00 (сегодня)"
        elif now.weekday() == 6:
            next_notification = "Среда 18:00 (через 3 дня)"
        else:
            next_notification = "Среда 18:00"

        await update.message.reply_text(
            f"🕐 <b>ИНФОРМАЦИЯ О ВРЕМЕНИ</b>\n\n📅 Дата: {now.strftime('%d.%m.%Y')}\n⏰ Время: {now.strftime('%H:%M:%S')}\n📆 День недели: {weekday_ru}\n🌍 Часовой пояс: Москва (UTC+3)\n\n"
            f"🔄 <b>Следующее уведомление:</b> {next_notification}\n\n📋 <b>Расписание:</b>\n• Среда 18:00 - всем\n• Пятница 18:00 - всем\n• Суббота 10:00 - всем",
            parse_mode=ParseMode.HTML
        )

    async def fix_all_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ИСПРАВИТЬ: Включить уведомления и проверить всех пользователей"""
        user = update.effective_user
        if not self.is_super_admin(user.username): return

        self.load_user_data()
        fixed_count = 0
        for uid, info in self.user_data.items():
            changes = []
            if not info.get('notifications', True):
                info['notifications'] = True
                changes.append("включены уведомления")
            if 'telegram_name' not in info:
                info['telegram_name'] = info.get('first_name', 'Пользователь')
                changes.append("добавлено имя")
            if changes:
                fixed_count += 1
                logger.info(f"Исправлен пользователь {uid}: {', '.join(changes)}")

        self.save_user_data()

        test_msg = (
            f"🔔 <b>ТЕСТОВОЕ УВЕДОМЛЕНИЕ ОТ АДМИНИСТРАТОРА</b>\n\n✅ Ваши уведомления были включены!\n\n"
            f"📅 Вы будете получать напоминания:\n• В среду в 18:00 - о дежурстве в субботу\n• В пятницу в 18:00 - о завтрашнем дежурстве\n• В субботу в 10:00 - в день дежурства\n\n📋 Используйте /start для просмотра меню"
        )

        sent_count = 0
        error_count = 0
        for uid in self.user_data.keys():
            try:
                await self.bot_instance.send_message(chat_id=int(uid), text=test_msg, parse_mode=ParseMode.HTML)
                sent_count += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                error_count += 1
                logger.error(f"Ошибка отправки теста пользователю {uid}: {e}")

        await update.message.reply_text(
            f"✅ <b>ИСПРАВЛЕНИЕ ЗАВЕРШЕНО</b>\n\n📊 Исправлено пользователей: {fixed_count}\n📤 Отправлено тестовых уведомлений: {sent_count}\n❌ Ошибок отправки: {error_count}\n\n🔔 Теперь все пользователи будут получать уведомления!",
            parse_mode=ParseMode.HTML
        )

    # ============= КОНЕЦ ДИАГНОСТИЧЕСКИХ КОМАНД =============

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
                    "❌ <b>ДОСТУП ЗАПРЕЩЕН</b>\n\nДоступ только админам\n<code>Зайдите с нужного аккаунта!!</code>",
                    parse_mode=ParseMode.HTML)
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
            "admin_remove_duty": self.admin_remove_duty,
            "admin_add_employee": self.admin_add_employee,
            "admin_remove_employee": self.admin_remove_employee,
            "admin_edit_phone": self.admin_edit_phone,
            "admin_list_employees": self.admin_list_employees,
            "admin_upload_protocol": self.admin_upload_protocol,
            "admin_delete_protocol": self.admin_delete_protocol,
            "admin_check_protocol": self.admin_check_protocol,
            "admin_pin_protocol": self.admin_pin_protocol,
        }

        # Регистрация пользователя из меню
        if data.startswith("emp_"):
            employee_name = data[4:]
            await self.register_employee(query, employee_name)

        # ПОШАГОВОЕ ДОБАВЛЕНИЕ ДЕЖУРСТВА (ИНТЕГРИРОВАНО)
        elif data == "admin_add_duty":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 Один дежурный", callback_data="add_type_single"),
                 InlineKeyboardButton("👥 Пара (2 чел.)", callback_data="add_type_pair")],
                [InlineKeyboardButton("❌ Отмена", callback_data="admin_schedule")]
            ])
            await query.edit_message_text("➕ <b>НОВОЕ ДЕЖУРСТВО</b>\n\n<b>Шаг 1:</b> Выберите формат дежурства:",
                                          reply_markup=kb, parse_mode=ParseMode.HTML)

        elif data.startswith("add_type_"):
            is_pair = (data == "add_type_pair")
            context.user_data['new_duty'] = {'is_pair': is_pair, 'employees': [], 'phones': []}
            context.user_data['awaiting_step'] = 'wait_date'
            await query.edit_message_text(
                "📅 <b>Шаг 2:</b> Введите дату в чат\n\nФормат: <code>дд.мм.гггг</code>\n<i>Например: 07.02.2026</i>",
                parse_mode=ParseMode.HTML)

        elif data.startswith("add_e1_"):
            name = data.replace("add_e1_", "")
            context.user_data['new_duty']['employees'].append(name)

            if context.user_data['new_duty']['is_pair']:
                await query.edit_message_text(
                    f"✅ Выбран первый: <b>{name}</b>\n\n👥 <b>Шаг 4:</b> Выберите второго дежурного:",
                    reply_markup=self.get_employee_selection_keyboard("add_e2_"), parse_mode=ParseMode.HTML)
            else:
                context.user_data['awaiting_step'] = 'wait_phones'
                await query.edit_message_text(
                    f"✅ Выбран: <b>{name}</b>\n\n📞 <b>Шаг 4:</b> Введите номер телефона в чат.\n\n<i>Лайфхак: Напишите в чат слово <b>ок</b>, и бот сам подставит сохраненный номер сотрудника!</i>",
                    parse_mode=ParseMode.HTML)

        elif data.startswith("add_e2_"):
            name = data.replace("add_e2_", "")
            context.user_data['new_duty']['employees'].append(name)
            context.user_data['awaiting_step'] = 'wait_phones'
            await query.edit_message_text(
                f"✅ Выбрана пара: <b>{context.user_data['new_duty']['employees'][0]} + {name}</b>\n\n"
                "📞 <b>Шаг 5:</b> Введите телефоны через запятую.\n\n<i>Лайфхак: Напишите в чат слово <b>ок</b>, и бот сам подставит номера обоих сотрудников!</i>",
                parse_mode=ParseMode.HTML
            )

        # Стандартные обработчики кнопок
        elif data in handlers:
            await handlers[data](query, context)

    async def show_full_schedule(self, query, context=None):
        """Показать полный график дежурств"""
        schedule_text = self.schedule_generator.get_schedule_text()
        text = schedule_text

        if len(text) > 4000:
            await query.edit_message_text(text[:4000], parse_mode=ParseMode.HTML)
            await query.message.reply_text(text[4000:], parse_mode=ParseMode.HTML,
                                           reply_markup=self.get_back_keyboard())
        else:
            await query.edit_message_text(text, reply_markup=self.get_back_keyboard(), parse_mode=ParseMode.HTML)

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

        if not duties:
            text = f"📅 <b>БЛИЖАЙШИЕ ДЕЖУРСТВА: {employee_name}</b>\n\nНет запланированных дежурств"
        else:
            text = f"📅 <b>БЛИЖАЙШИЕ ДЕЖУРСТВА: {employee_name}</b>\n\n"
            for duty in duties[:3]:
                days_left = (duty["date_obj"] - today).days
                if duty["is_pair"]:
                    partners = [e for e in duty["employees"] if e != employee_name]
                    duty_text = f"{duty['date']} (с {', '.join(partners)})"
                    phones = ', '.join(duty['phones'])
                else:
                    duty_text = duty['date']
                    phones = duty['phones'][0]

                text += f"{duty_text}\n📅 Осталось: {max(0, days_left)} дней\n📞 {phones}\n\n"

        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

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
            text = "<b>🏠 ГЛАВНОЕ МЕНЮ</b>\n\n<i>Для доступа к функциям\nнеобходима регистрация.</i>\n\nВыберите действие:"

        await query.edit_message_text(text, reply_markup=self.get_main_keyboard(user_id), parse_mode=ParseMode.HTML)

    async def download_protocol(self, query, context=None):
        """Скачать протокол разногласий"""
        try:
            if not os.path.exists(self.protocol_file_path):
                await query.edit_message_text("❌ Файл не найден", reply_markup=self.get_back_keyboard(),
                                              parse_mode=ParseMode.HTML)
                return

            with open(self.protocol_file_path, 'rb') as f:
                await query.message.reply_document(
                    document=f,
                    filename="Протокол разногласий.docx",
                    caption="📄 Протокол разногласий",
                    parse_mode=ParseMode.HTML
                )

            await query.edit_message_text("✅ Файл отправлен", reply_markup=self.get_back_keyboard(),
                                          parse_mode=ParseMode.HTML)
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка: {str(e)[:50]}", reply_markup=self.get_back_keyboard(),
                                          parse_mode=ParseMode.HTML)

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
        await query.edit_message_text(text, reply_markup=self.get_back_keyboard(), parse_mode=ParseMode.HTML)

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
        await query.edit_message_text(text, reply_markup=self.get_back_keyboard(), parse_mode=ParseMode.HTML)

    async def change_profile(self, query, context=None):
        """Изменение привязанного сотрудника"""
        text = "<b>👤 ИЗМЕНЕНИЕ ПРОФИЛЯ</b>\n\nВыберите ваше ФИО из списка сотрудников.\n\n<i>Текущий выбор будет заменен.</i>"
        await query.edit_message_text(text, reply_markup=self.get_employee_selection_keyboard(prefix="emp_"),
                                      parse_mode=ParseMode.HTML)

    async def register_employee(self, query, employee_name: str):
        """Регистрация сотрудника для пользователя"""
        user_id = str(query.from_user.id)
        if user_id in self.user_data:
            self.user_data[user_id]["selected_employee"] = employee_name
            self.user_data[user_id]["registered_at"] = datetime.now().isoformat()
            self.save_user_data()

            text = (
                "<b>✅ РЕГИСТРАЦИЯ УСПЕШНА</b>\n\n"
                f"Ваш аккаунт привязан к:\n<b>{employee_name}</b>\n\n"
                f"📞 Телефон: {EMPLOYEE_PHONES.get(employee_name, 'не указан')}\n"
                f"🔔 Уведомления: {'✅ Включены' if self.user_data[user_id].get('notifications', True) else '❌ Отключены'}\n\n"
                "<i>Теперь вы можете пользоваться всеми функциями бота.</i>\n\nВыберите действие:"
            )
            await query.edit_message_text(text, reply_markup=self.get_main_keyboard(user_id), parse_mode=ParseMode.HTML)
        else:
            await query.edit_message_text("Ошибка регистрации. Пожалуйста, начните снова командой /start",
                                          parse_mode=ParseMode.HTML)

    async def show_admin_panel(self, query, context=None):
        """Показать админ-панель"""
        user_id = str(query.from_user.id)
        if not self.is_admin(user_id) or not self.admin_sessions.get(user_id, {}).get("logged_in"):
            await query.edit_message_text("❌ <b>ДОСТУП ЗАПРЕЩЕН</b>", parse_mode=ParseMode.HTML)
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
        await query.edit_message_text(text, reply_markup=self.get_admin_keyboard(), parse_mode=ParseMode.HTML)

    async def admin_logout(self, query, context=None):
        """Выход из админ-панели"""
        user_id = str(query.from_user.id)
        if user_id in self.admin_sessions:
            del self.admin_sessions[user_id]

        if user_id in self.user_data:
            self.user_data[user_id]["is_admin"] = False
            self.save_user_data()

        await query.edit_message_text(
            "✅ <b>ВЫ УСПЕШНО ВЫШЛИ ИЗ АДМИН-ПАНЕЛИ</b>\n\nВсе права администратора отозваны.",
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
            "➕ <b>Добавить дежурство:</b>\nСоздать новую ручную запись в графике поверх круга\n\n"
            "➖ <b>Удалить дежурство:</b>\nУдалить существующую ручную запись\n\n"
            "📋 <b>Просмотреть график:</b>\nПосмотреть текущий график\n\n"
            "🔄 <b>Обновить график:</b>\nОбновить отображение графика\n\n"
            "<i>Выберите действие:</i>"
        )
        await query.edit_message_text(text, reply_markup=self.get_schedule_admin_keyboard(), parse_mode=ParseMode.HTML)

    async def show_admin_employees(self, query, context=None):
        """Показать управление сотрудниками"""
        text = (
            "👥 <b>УПРАВЛЕНИЕ СОТРУДНИКАМИ</b>\n\n"
            "Доступные действия:\n\n"
            "➕ <b>Добавить сотрудника:</b>\nДобавить нового сотрудника в систему\n\n"
            "➖ <b>Удалить сотрудника:</b>\nУдалить сотрудника из системы\n\n"
            "📞 <b>Изменить телефон:</b>\nОбновить контактный номер\n\n"
            "👥 <b>Список сотрудников:</b>\nПросмотреть всех сотрудников\n\n"
            "<i>Выберите действие:</i>"
        )
        await query.edit_message_text(text, reply_markup=self.get_employees_admin_keyboard(), parse_mode=ParseMode.HTML)

    async def show_admin_files(self, query, context=None):
        """Показать управление файлами"""
        protocol_exists = os.path.exists(self.protocol_file_path)
        text = (
            "📁 <b>УПРАВЛЕНИЕ ФАЙЛАМИ</b>\n\n"
            f"📄 <b>Протокол разногласий:</b>\n"
            f"Статус: {'✅ Доступен' if protocol_exists else '❌ Отсутствует'}\n"
            f"Прикреплен: {'✅ Да' if self.protocol_attached_file_id else '❌ Нет'}\n\n"
            "Доступные действия:\n\n"
            "📤 <b>Загрузить протокол:</b>\nДобавить новый файл протокола\n\n"
            "📎 <b>Прикрепить протокол:</b>\nСделать файл доступным в закрепленном сообщении\n\n"
            "🗑 <b>Удалить протокол:</b>\nУдалить текущий файл протокола\n\n"
            "📄 <b>Проверить файл:</b>\nПроверить наличие и доступность\n\n"
            "<i>Выберите действие:</i>"
        )
        await query.edit_message_text(text, reply_markup=self.get_files_admin_keyboard(), parse_mode=ParseMode.HTML)

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

        next_saturday = None
        today_date = datetime.now(MOSCOW_TZ).replace(tzinfo=None).date()
        for date in range(1, 8):
            check_date = today_date + timedelta(days=date)
            if check_date.weekday() == 5:
                next_saturday = check_date
                break

        current_schedule = self.schedule_generator._generate_dynamic_schedule()
        next_duty = next((d for d in current_schedule.values() if d["date_obj"].date() == next_saturday), None)

        text = (
            "📊 <b>СТАТИСТИКА СИСТЕМЫ</b>\n\n"
            f"👥 <b>Всего пользователей:</b> {total_users}\n"
            f"📱 <b>Активных сегодня:</b> {active_today}\n"
            f"🤖 <b>Автопривязанных:</b> {auto_linked}\n"
            f"📅 <b>Дежурств на выводе:</b> {len(current_schedule)}\n"
            f"👥 <b>Ручных правок в базе:</b> {len(self.schedule_generator.schedule)}\n"
            f"👤 <b>Всего сотрудников:</b> {len(EMPLOYEE_PHONES)}\n\n"
        )

        if next_duty:
            text += f"<b>Следующее дежурство ({next_saturday.strftime('%d.%m.%Y')}):</b>\n"
            if next_duty["is_pair"]:
                text += f"• {next_duty['employees'][0]} + {next_duty['employees'][1]}\n"
            else:
                text += f"• {next_duty['employees'][0]}\n"
        else:
            text += f"<b>Ближайшая суббота ({next_saturday.strftime('%d.%m.%Y')}):</b>\n• Дежурных нет\n"

        text += f"\n<b>Расписание уведомлений (ВСЕМ):</b>\n• Среда 18:00 - уведомление о дежурстве в субботу\n• Пятница 18:00 - напоминание о завтрашнем дежурстве\n• Суббота 10:00 - напоминание в день дежурства\n"

        keyboard = [
            [InlineKeyboardButton("🔙 Назад в админку", callback_data="admin_panel")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    async def admin_remove_duty(self, query, context):
        """Удалить дежурство (список)"""
        schedule_text = self.schedule_generator.get_schedule_text()
        text = (
                "➖ <b>УДАЛЕНИЕ РУЧНОГО ДЕЖУРСТВА</b>\n\n"
                "<i>Текущий график дежурств:</i>\n\n" +
                schedule_text[:1500] +
                "\n\nДля удаления ручной правки и возврата автоматического круга отправьте дату:\n"
                "<code>дд.мм.ггггг.</code>\n\n"
                "<b>Пример:</b> <code>06.06.2026г.</code>\n\n"
                "<i>Отправьте дату или нажмите 'Отмена':</i>"
        )
        keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="admin_schedule")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
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
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        context.user_data['awaiting_employee_add'] = True

    async def admin_remove_employee(self, query, context):
        """Удалить сотрудника (инструкция)"""
        employees_list = "\n".join([f"• {emp}" for emp in EMPLOYEE_PHONES.keys()])
        text = (
            "➖ <b>УДАЛЕНИЕ СОТРУДНИКА</b>\n\n"
            f"<b>Список сотрудников:</b>\n{employees_list}\n\n"
            "<i>Для удаления сотрудника отправьте его ФИО:</i>\n\n"
            "<b>Пример:</b>\n<code>Иванов И.И.</code>\n\n"
            "<i>Отправьте ФИО или нажмите 'Отмена':</i>"
        )
        keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="admin_employees")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        context.user_data['awaiting_employee_remove'] = True

    async def admin_edit_phone(self, query, context):
        """Изменить телефон сотрудника (инструкция)"""
        employees_list = "\n".join([f"• {emp}" for emp in EMPLOYEE_PHONES.keys()])
        text = (
            "📞 <b>ИЗМЕНЕНИЕ ТЕЛЕФОНА СОТРУДНИКА</b>\n\n"
            f"<b>Список сотрудников:</b>\n{employees_list}\n\n"
            "<i>Для изменения телефона отправьте сообщение в формате:</i>\n\n"
            "<code>ФИО;новый телефон</code>\n\n"
            "<b>Пример:</b>\n<code>Денисова Е.С.;8-987-294-93-24</code>\n\n"
            "<i>Отправьте данные или нажмите 'Отмена':</i>"
        )
        keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="admin_employees")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
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
            employees_text += f"{i}. <b>{employee}</b>\n   📞 {phone}\n"
            if telegram_username:
                employees_text += f"   📱 Telegram: {telegram_username}\n"
            employees_text += "\n"

        text = f"👥 <b>СПИСОК СОТРУДНИКОВ</b>\n\n{employees_text}<b>Всего сотрудников:</b> {len(EMPLOYEE_PHONES)}"
        keyboard = [
            [InlineKeyboardButton("➕ Добавить сотрудника", callback_data="admin_add_employee")],
            [InlineKeyboardButton("📞 Изменить телефон", callback_data="admin_edit_phone")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_employees")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

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
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    async def admin_delete_protocol(self, query, context=None):
        """Удалить протокол"""
        if os.path.exists(self.protocol_file_path):
            try:
                os.remove(self.protocol_file_path)
                self.protocol_attached_file_id = None
                text = "🗑 <b>ФАЙЛ ПРОТОКОЛА УДАЛЕН</b>\n\nФайл протокола был успешно удален.\n\n<i>Пользователи больше не смогут скачать протокол.</i>"
            except Exception as e:
                text = f"❌ <b>ОШИБКА УДАЛЕНИЯ:</b> {str(e)}"
        else:
            text = "ℹ️ <b>ФАЙЛ НЕ НАЙДЕН</b>\n\nФайл протокола уже отсутствует."

        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_files")],
            [InlineKeyboardButton("📄 Проверить файл", callback_data="admin_check_protocol")]
        ]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

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
                "<b>Что делать:</b>\n1. Загрузите файл протокола\n2. Используйте кнопку 'Загрузить протокол'"
            )

        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_files")],
            [InlineKeyboardButton("📤 Загрузить протокол", callback_data="admin_upload_protocol")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    async def admin_pin_protocol(self, query, context=None):
        """Прикрепить протокол в закрепленное сообщение"""
        if not os.path.exists(self.protocol_file_path):
            text = "❌ <b>ФАЙЛ НЕ НАЙДЕН</b>\n\nСначала загрузите файл протокола.\nИспользуйте кнопку 'Загрузить протокол'."
            keyboard = [
                [InlineKeyboardButton("📤 Загрузить протокол", callback_data="admin_upload_protocol")],
                [InlineKeyboardButton("🔙 Назад", callback_data="admin_files")]
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
            return

        text = (
            "📎 <b>ПРИКРЕПЛЕНИЕ ПРОТОКОЛА</b>\n\n"
            "Для прикрепления протокола в закрепленное сообщение:\n\n"
            "1. Отправьте боту файл протокола\n"
            "2. В подписи к файлу напишите <code>закрепить</code>\n\n"
            "Файл будет автоматически закреплен в чате."
        )
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_files")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    async def message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ (И ВВОД ДАННЫХ МАСТЕРА)"""
        user = update.effective_user
        user_id = str(user.id)
        message_text = update.message.text if update.message else ""

        # Проверка авторизации
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

        step = context.user_data.get('awaiting_step')

        # --- ЛОГИКА ПОШАГОВОГО МАСТЕРА ---
        if step == 'wait_date':
            context.user_data['new_duty']['date'] = message_text if "г." in message_text else message_text + "г."
            await update.message.reply_text(
                f"✅ Дата сохранена: <b>{message_text}</b>\n\n👤 <b>Шаг 3:</b> Выберите первого дежурного из списка:",
                reply_markup=self.get_employee_selection_keyboard("add_e1_"),
                parse_mode=ParseMode.HTML
            )
            context.user_data['awaiting_step'] = None
            return

        elif step == 'wait_phones':
            duty_info = context.user_data['new_duty']

            # Автоподстановка, если админ ввел "ок"
            if message_text.lower() in ["ок", "ok", "да", "авто"]:
                phones = [EMPLOYEE_PHONES.get(emp, "Номер не найден") for emp in duty_info['employees']]
            else:
                phones = [p.strip() for p in message_text.split(',')]

            if len(duty_info['employees']) != len(phones):
                await update.message.reply_text(
                    "❌ <b>ОШИБКА</b>\n\nКоличество сотрудников и телефонов не совпадает. Введите телефоны заново:",
                    parse_mode=ParseMode.HTML
                )
                return

            success, msg = self.schedule_generator.add_duty(
                duty_info['date'], duty_info['employees'], phones, duty_info['is_pair']
            )

            if success:
                await update.message.reply_text(
                    f"✅ <b>РУЧНОЕ ДЕЖУРСТВО ДОБАВЛЕНО</b>\n\n"
                    f"📅 Дата: {duty_info['date']}\n"
                    f"👥 Сотрудники: {', '.join(duty_info['employees'])}\n"
                    f"📞 Телефоны: {', '.join(phones)}\n\n"
                    "<i>График успешно обновлен (круг перезаписан на этот день).</i>",
                    reply_markup=self.get_admin_keyboard(),
                    parse_mode=ParseMode.HTML
                )
                context.user_data.clear()  # Очищаем временные данные мастера
            else:
                await update.message.reply_text(
                    f"❌ <b>ОШИБКА ДОБАВЛЕНИЯ</b>\n\n{msg}",
                    reply_markup=self.get_admin_keyboard(),
                    parse_mode=ParseMode.HTML
                )
                context.user_data.clear()
            return

        # --- СТАРЫЕ ОБРАБОТЧИКИ ТЕКСТА (Удаление, добавление сотрудников и т.д.) ---
        if context.user_data.get('awaiting_duty_remove'):
            date_str = message_text.strip()
            success = self.schedule_generator.remove_duty(date_str)

            if success:
                await update.message.reply_text(
                    f"✅ <b>РУЧНАЯ ПРАВКА УДАЛЕНА</b>\n\n📅 Дата: {date_str}\n\n<i>На этот день вернулся автоматический расчет по кругу.</i>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    f"❌ <b>РУЧНАЯ ПРАВКА НЕ НАЙДЕНА</b>\n\nДата: {date_str}\n\nПроверьте правильность введённой даты.",
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
                            f"✅ <b>СОТРУДНИК ДОБАВЛЕН</b>\n\n👤 ФИО: {employee_name}\n📞 Телефон: {phone}\n📱 Telegram: {telegram_username if telegram_username else 'не указан'}\n\n<i>Сотрудник добавлен в систему.</i>",
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        await update.message.reply_text(
                            f"❌ <b>СОТРУДНИК УЖЕ СУЩЕСТВУЕТ</b>\n\nИмя: {employee_name}\n\nИспользуйте другое ФИО.",
                            parse_mode=ParseMode.HTML
                        )
                else:
                    await update.message.reply_text(
                        "❌ <b>НЕВЕРНЫЙ ФОРМАТ</b>\n\nИспользуйте формат:\n<code>ФИО;телефон;telegram_username</code>",
                        parse_mode=ParseMode.HTML)
            except Exception as e:
                await update.message.reply_text(f"❌ <b>ОШИБКА:</b> {str(e)}\n\nПроверьте правильность данных.",
                                                parse_mode=ParseMode.HTML)
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
                    f"✅ <b>СОТРУДНИК УДАЛЕН</b>\n\n👤 ФИО: {employee_name}{telegram_info}\n\n<i>Сотрудник удален из системы.</i>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    f"❌ <b>СОТРУДНИК НЕ НАЙДЕН</b>\n\nИмя: {employee_name}\n\nПроверьте правильность ФИО.",
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
                            f"✅ <b>ТЕЛЕФОН ОБНОВЛЕН</b>\n\n👤 Сотрудник: {employee_name}\n📞 Новый телефон: {new_phone}\n\n<i>Телефон успешно обновлен.</i>",
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        await update.message.reply_text(
                            f"❌ <b>СОТРУДНИК НЕ НАЙДЕН</b>\n\nИмя: {employee_name}\n\nПроверьте правильность ФИО.",
                            parse_mode=ParseMode.HTML)
                else:
                    await update.message.reply_text(
                        "❌ <b>НЕВЕРНЫЙ ФОРМАТ</b>\n\nИспользуйте формат:\n<code>ФИО;новый телефон</code>",
                        parse_mode=ParseMode.HTML)
            except Exception as e:
                await update.message.reply_text(f"❌ <b>ОШИБКА:</b> {str(e)}\n\nПроверьте правильность данных.",
                                                parse_mode=ParseMode.HTML)
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
                            f"✅ <b>ФАЙЛ ПРОТОКОЛА ЗАГРУЖЕН</b>\n\n📄 Имя файла: {document.file_name}\n📁 Размер: {document.file_size / 1024:.1f} КБ\n\n<i>Файл успешно сохранен и доступен для скачивания.</i>",
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        await update.message.reply_text(f"❌ <b>ОШИБКА ЗАГРУЗКИ:</b> {str(e)}",
                                                        parse_mode=ParseMode.HTML)
                else:
                    await update.message.reply_text(
                        "❌ <b>НЕВЕРНЫЙ ФОРМАТ ФАЙЛА</b>\n\nПоддерживаются только файлы .docx",
                        parse_mode=ParseMode.HTML)

            elif caption.lower() in ['закрепить', 'pin', 'прикрепить']:
                if document.file_name.endswith('.docx'):
                    try:
                        self.protocol_attached_file_id = document.file_id
                        message = await update.message.reply_document(
                            document=document.file_id,
                            caption="📄 <b>ПРОТОКОЛ РАЗНОГЛАСИЙ</b>\n\n<i>Бланк для заполнения во время дежурства</i>\n\n<b>ИНСТРУКЦИЯ:</b>\n1. Скачайте файл\n2. Распечатайте бланк\n3. Заполните дату дежурства\n4. Распишитесь на обороте\n5. Оставить у Е.С. Денисовой",
                            parse_mode=ParseMode.HTML
                        )
                        await context.bot.pin_chat_message(
                            chat_id=update.effective_chat.id,
                            message_id=message.message_id,
                            disable_notification=True
                        )
                        await update.message.reply_text(
                            f"✅ <b>ФАЙЛ ПРОТОКОЛА ПРИКРЕПЛЕН</b>\n\n📄 Имя файла: {document.file_name}\n📎 ID файла: {document.file_id}\n\n<i>Файл закреплен в чате и доступен для скачивания.</i>",
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        await update.message.reply_text(f"❌ <b>ОШИБКА ПРИКРЕПЛЕНИЯ:</b> {str(e)}",
                                                        parse_mode=ParseMode.HTML)
                else:
                    await update.message.reply_text(
                        "❌ <b>НЕВЕРНЫЙ ФОРМАТ ФАЙЛА</b>\n\nПоддерживаются только файлы .docx",
                        parse_mode=ParseMode.HTML)

        elif message_text and not message_text.startswith('/'):
            await update.message.reply_text(
                "ℹ️ <b>ИНФОРМАЦИЯ</b>\n\nДля работы с админ-панелью используйте кнопки меню.\nИли вернитесь в главное меню.",
                reply_markup=self.get_admin_keyboard(),
                parse_mode=ParseMode.HTML
            )

    async def send_test_wednesday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        if not self.is_admin(user_id): return
        await update.message.reply_text("🔄 Отправляю тестовое среднее уведомление всем пользователям...")
        await self.send_wednesday_notification()
        await update.message.reply_text("✅ Тестовое среднее уведомление отправлено!")

    async def send_test_friday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        if not self.is_admin(user_id): return
        await update.message.reply_text("🔄 Отправляю тестовое пятничное уведомление всем пользователям...")
        await self.send_friday_notification_all()
        await update.message.reply_text("✅ Тестовое пятничное уведомление отправлено!")

    async def send_test_saturday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        if not self.is_admin(user_id): return
        await update.message.reply_text("🔄 Отправляю тестовое субботнее уведомление всем пользователям...")
        await self.send_saturday_notification_all()
        await update.message.reply_text("✅ Тестовое субботнее уведомление отправлено!")

    async def test_notification_for_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        if not self.is_admin(user_id): return
        if len(context.args) != 1:
            await update.message.reply_text("❌ Неверный формат. Используйте: /test_user <user_id>")
            return

        target_user_id = context.args[0]
        test_message = (
            f"🔔 <b>ТЕСТОВОЕ УВЕДОМЛЕНИЕ</b>\n\n📅 <b>Это тестовое сообщение от администратора</b>\n\n... "
        )
        try:
            await self.bot_instance.send_message(chat_id=int(target_user_id), text=test_message,
                                                 parse_mode=ParseMode.HTML)
            await update.message.reply_text(f"✅ Тестовое сообщение отправлено пользователю {target_user_id}")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка отправки: {str(e)}")

    def run(self):
        """Запуск бота"""
        self.application = ApplicationBuilder().token(self.token).build()
        self.bot_instance = self.application.bot

        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("admin", self.admin_login))
        self.application.add_handler(CommandHandler("test_wednesday", self.send_test_wednesday))
        self.application.add_handler(CommandHandler("test_friday", self.send_test_friday))
        self.application.add_handler(CommandHandler("test_saturday", self.send_test_saturday))
        self.application.add_handler(CommandHandler("test_user", self.test_notification_for_user))

        self.application.add_handler(CommandHandler("users", self.check_users_status))
        self.application.add_handler(CommandHandler("enable_all", self.enable_notifications_all))
        self.application.add_handler(CommandHandler("test_send", self.test_send_to_user))
        self.application.add_handler(CommandHandler("time", self.check_time))
        self.application.add_handler(CommandHandler("fix", self.fix_all_users))

        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message_handler))
        self.application.add_handler(MessageHandler(filters.Document.ALL, self.message_handler))

        logger.info("Бот запущен...")

        loop = asyncio.get_event_loop()
        loop.create_task(self.setup_scheduler())

        self.application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )


if __name__ == "__main__":
    BOT_TOKEN = "8485938284:AAEpyohCu82mHE0jm0rcbQk31T1s2uxw8UA"
    bot = DutyBot(BOT_TOKEN)
    bot.run()
