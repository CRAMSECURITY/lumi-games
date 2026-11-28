import asyncio
import lumi_analytics_live as live_analytics
import lumi_shop_live as live_shop
import lumi_clubs as clubs
from lumi_locale import strings as locale_strings
from lumi_marketplace import CATALOG as SHOP_CATALOG
from lumi_polling import bounded_polling
from lumi_matching import score as matching_score
from html import escape as html_escape
import logging
import os
import sqlite3
import re
import random
import secrets
import shutil
import time
from lumi_cache import RecentMap, RecentSet, byte_cache
from collections import defaultdict
from lumi_memory import UserWindows
from io import BytesIO
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove, BotCommand, FSInputFile, BufferedInputFile, LabeledPrice, PreCheckoutQuery, WebAppInfo,
)
from dotenv import load_dotenv
from lumi_operations import init_ops, can_notify, toggle_notify, flag_due, alert_due, record_metric
from lumi_economy import pair_battles_today, eligible_for_reward, claim_training
from lumi_daily import init_daily_rewards, claim_daily_reward, daily_reward_status
from lumi_antifraud import record_report_once, isolate_pair
from lumi_anti_scam import warning_for
from lumi_profile_moderation import profile_text_allowed
from lumi_media import media_size_allowed, BoundedMediaBuffer
from lumi_profile_media import media_identity, init_media_identity, media_available
from lumi_verification import new_review_id, parse_review_callback, decide_review
from lumi_referrals import (init_referrals, register_referral, confirm_registration,
                            referral_count, has_referral_frame, delete_referral_data, REFERRAL_GOAL)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
# Optional public HTTPS URL of the separate game-only Telegram Mini App.
LUMI_GAMES_URL = os.getenv("LUMI_GAMES_URL", "").strip()
if LUMI_GAMES_URL and not LUMI_GAMES_URL.startswith("https://"):
    raise RuntimeError("LUMI_GAMES_URL должен начинаться с https://")


def game_button():
    if LUMI_GAMES_URL:
        return InlineKeyboardButton(text="🎮 LUMI GAMES · Mini App", web_app=WebAppInfo(url=LUMI_GAMES_URL))
    return InlineKeyboardButton(text="🎮 LUMI GAMES", callback_data="games:not_configured")

DB_PATH = Path(__file__).resolve().parent / "lumi.db"
dp = Dispatcher(storage=MemoryStorage())

# LUMI SECURITY: личные анкеты обрабатываются только в личном чате.
# Защита от массового перебора кнопок/флуда. Для больших нагрузок — Redis.
class PrivateChatGuard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        chat = getattr(event, "chat", None)
        if chat is None:
            chat = getattr(getattr(event, "message", None), "chat", None)
        if chat is None or getattr(chat, "type", None) != "private":
            if isinstance(event, CallbackQuery):
                await event.answer("LUMI доступен только в личном чате", show_alert=True)
            return
        return await handler(event, data)

class UserRateLimit(BaseMiddleware):
    def __init__(self, max_events=25, period=20):
        self.max_events, self.period = max_events, period
        self.events = UserWindows(10000, period)
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user:
            now = time.monotonic()
            queue = self.events.acquire(user.id, now)
            if queue is None or len(queue) >= self.max_events:
                if isinstance(event, CallbackQuery):
                    await event.answer("Слишком много действий. Подожди немного.", show_alert=True)
                return
            queue.append(now)
        return await handler(event, data)

dp.message.outer_middleware(PrivateChatGuard())
dp.callback_query.outer_middleware(PrivateChatGuard())
dp.message.outer_middleware(UserRateLimit())
dp.callback_query.outer_middleware(UserRateLimit())

class AccountSuspensionGuard(BaseMiddleware):
    """Enforce account bans on every update, but preserve support and data rights."""
    async def __call__(self, handler, event, data):
        user = getattr(event, 'from_user', None)
        if user is None:
            return await handler(event, data)
        from lumi_database_vault import connect_private
        with connect_private(DB_PATH, timeout=10) as db:
            try:
                row = db.execute("SELECT reason,expires_at FROM account_suspensions WHERE user_id=? "
                                 "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)", (user.id,)).fetchone()
            except sqlite3.OperationalError as exc:
                if 'no such table' in str(exc):
                    return await handler(event, data)
                raise
        if not row:
            return await handler(event, data)
        allowed = False
        if isinstance(event, Message):
            # Payments and refunds MUST still be processed if an old invoice settles.
            if event.successful_payment or getattr(event, 'refunded_payment', None):
                return await handler(event, data)
            content=(event.text or '').strip().lower()
            allowed = content.split(' ',1)[0] in {'/support','/endsupport','/deleteaccount','/mydata','/cancel','/analytics_off'}
            fsm=data.get('state')
            if fsm and await fsm.get_state() == SupportForm.message.state:
                allowed=True
        if isinstance(event, CallbackQuery):
            allowed=(event.data or '') in {'ux:support','ux:delete'} or (event.data or '').startswith('delete:')
        if allowed:
            return await handler(event,data)
        until=row[1]+' UTC' if row[1] else 'бессрочно'
        msg=('🚫 Доступ к LUMI ограничен.\n'
             f'До: {until}\n'
             'Чтобы обратиться за пересмотром: /support\n'
             'Удалить свои данные: /deleteaccount')
        if isinstance(event, CallbackQuery):
            await event.answer('Аккаунт ограничен. Напиши /support.',show_alert=True)
        elif isinstance(event, Message):
            await event.answer(msg)


dp.message.outer_middleware(AccountSuspensionGuard())
dp.callback_query.outer_middleware(AccountSuspensionGuard())

class OperationsMonitor(BaseMiddleware):
    """Telemetry with no names/media/message contents; security flag is review-only."""
    def __init__(self):
        self.hits = UserWindows(5000, 600)
        self.aggregate = defaultdict(int)
        self.last_flush = time.monotonic()

    async def __call__(self, handler, event, data):
        uid=getattr(getattr(event,'from_user',None),'id',None)
        start=time.perf_counter()
        if uid:
            q=self.hits.acquire(uid, time.monotonic())
            if q is not None:
                q.append(time.monotonic())
            # Abnormally frequent interactions: flag for review, never auto-ban.
            if q is not None and len(q)>=120:
                try:
                    with connect_db() as db:
                        if flag_due(db,uid):
                            admin_event(db,'guard',uid)
                            self.aggregate['security']+=1
                except sqlite3.Error: logger.exception('Ошибка мониторинга активности')
                self.hits.discard(uid)
        self.aggregate['update']+=1
        try:
            return await handler(event,data)
        except Exception:
            self.aggregate['error']+=1
            raise
        finally:
            elapsed=time.perf_counter()-start
            if elapsed >= 2.0:
                self.aggregate['slow']+=1
                if elapsed>=5.0:
                    logger.warning('LUMI медленный обработчик %.2f с (%s)',elapsed,type(event).__name__)
            now=time.monotonic()
            if now-self.last_flush>=60:
                # Flush bounded aggregate counters at most once a minute.
                try:
                    with connect_db() as db:
                        for name,count in list(self.aggregate.items()):
                            if count:record_metric(db,name,min(count,100000))
                        if self.aggregate.get('slow',0)>=5 and alert_due(db,'slow',30):
                            admin_event(db,'slow')
                        self.aggregate.clear()
                except sqlite3.Error:logger.exception('Не удалось сохранить телеметрию')
                self.last_flush=now

_ops_monitor=OperationsMonitor()
dp.message.outer_middleware(_ops_monitor)
dp.callback_query.outer_middleware(_ops_monitor)


ADMIN_IDS = {int(x) for x in os.getenv("LUMI_ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
from lumi_secrets import install_log_redaction
install_log_redaction()
logger = logging.getLogger("lumi")
PREMIUM_STARS = 199
PREMIUM_SECONDS = 30 * 24 * 3600
TEASER_COOLDOWN_SECONDS = 24 * 3600  # Не чаще одного интригующего уведомления в сутки.
_teaser_tasks=set()
def _teaser_finished(task):
    _teaser_tasks.discard(task)
    if task.cancelled():return
    exc=task.exception()
    if exc:
        logger.warning('Не удалось доставить анонимное уведомление: %s',type(exc).__name__)

# Automated, clearly labelled playful lines — never attributed as a real user message.
LUMI_TEASER_PHRASES = (
    "Ну что, лайкнешь меня? Если нет — я обижусь 😏💜",
    "Ты ещё долго будешь делать вид, что меня не замечаешь? 👀",
    "Может, хватит листать? Вдруг я именно тот, кого ты ищешь? 💘",
    "Я тут уже лайк поставил(а)… Теперь твоя очередь 😉",
    "Ну давай, рискни. Вдруг у нас получится красивая история? 💜",
    "Я вообще-то жду взаимности. Не заставляй меня краснеть 🤭",
    "Ты мне понравился(ась). А я тебе? Давай проверим 😏",
    "Неужели оставишь меня без взаимного лайка? 🥺",
    "Я уже сделал(а) первый шаг… Теперь твоя очередь 💌",
    "Если это взаимно, обещаю не начинать разговор с «Привет, как дела?» 😂",
    "И долго мне ждать сообщения? 😏",
)

LUMI_STARTED_MONOTONIC = time.monotonic()
# No personal information or profile text in runtime metrics.
LUMI_METRICS = {"updates": 0, "errors": 0, "last_error_utc": None}


# LUMI MOBILE UX 2.4 — inline-first navigation: old reply keyboards are removed.
# This prevents huge persistent keyboards on mobile and keeps old text commands valid.
menu = ReplyKeyboardRemove()
quick_menu = ReplyKeyboardRemove()

# Three selectable display modes, default inline. "compact" reproduces the 1–4
# row; "hybrid" uses compact keys only for home, inline keys elsewhere.
LUMI_UI_MODE = os.getenv("LUMI_UI_MODE", "inline").strip().lower()
if LUMI_UI_MODE not in {"inline", "compact", "hybrid"}:
    LUMI_UI_MODE = "inline"

compact_home_keyboard = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="1 🚀"), KeyboardButton(text="2"),
     KeyboardButton(text="3"), KeyboardButton(text="4")],
], resize_keyboard=True, is_persistent=False,
    input_field_placeholder="1–4 · Выбери раздел")


def mobile_home_keyboard():
    """Главное меню: одно основное действие, два быстрых, всё остальное в разделе Ещё."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❤️ Анкеты", callback_data="ux:browse")],
        [InlineKeyboardButton(text="💞 Совпадения", callback_data="ux:matches"),
         InlineKeyboardButton(text="👤 Моя анкета", callback_data="ux:profile")],
        [game_button()],
        [InlineKeyboardButton(text="⋯ Ещё", callback_data="ux:more")],
    ])


def mobile_profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📷 Фото / видео", callback_data="ux:edit_photo"),
         InlineKeyboardButton(text="✏️ Описание", callback_data="ux:edit_text")],
        [InlineKeyboardButton(text="🔒 Приватность", callback_data="ux:privacy")],
        [InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")],
    ])


def profile_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Моя анкета", callback_data="ux:profile")]])


def mobile_more_keyboard():
    """Все второстепенные разделы в отдельном экране, чтобы не загромождать главную."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [game_button()],
        [InlineKeyboardButton(text="⚔️ Мои герои", callback_data="ux:heroes"),
         InlineKeyboardButton(text="💜 Создать анкету", callback_data="ux:register")],
        [InlineKeyboardButton(text="🔎 Настройки поиска", callback_data="ux:search")],
        [InlineKeyboardButton(text="🎭 Mystery", callback_data="ux:mystery"),
         InlineKeyboardButton(text="💫 Moment", callback_data="ux:moment")],
        [InlineKeyboardButton(text="✨ Возможности", callback_data="ux:features")],
        [InlineKeyboardButton(text="🔗 Контакты", callback_data="ux:contact"),
         InlineKeyboardButton(text="🔔 Уведомления", callback_data="notify:menu")],
        [InlineKeyboardButton(text="🆘 Поддержка", callback_data="ux:support"),
         InlineKeyboardButton(text="⭐ Premium", callback_data="ux:premium")],
        [InlineKeyboardButton(text="🏅 Первые 100 сердец", callback_data="founder:open"),
         InlineKeyboardButton(text="🎁 Пригласить друзей", callback_data="referral:open")],
        [InlineKeyboardButton(text="💝 Подарок дня", callback_data="daily4:open"),
         InlineKeyboardButton(text="🛡 Центр безопасности", callback_data="safety4:open")],
        [InlineKeyboardButton(text="🗑 Удалить анкету", callback_data="ux:delete")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="ux:home")],
    ])



# UX3: only explicitly marked transient bot messages can be removed.
_CLEAN_UI = {}
async def clean_answer(message, *args, **kwargs):
    sent = await message.answer(*args, **kwargs)
    chat_id = sent.chat.id
    previous = _CLEAN_UI.get(chat_id)
    _CLEAN_UI[chat_id] = sent.message_id
    if len(_CLEAN_UI) > 10000:
        _CLEAN_UI.pop(next(iter(_CLEAN_UI)), None)
    if previous and previous != sent.message_id:
        try:
            await sent.bot.delete_message(chat_id, previous)
        except TelegramAPIError:
            pass
    return sent

async def clear_clean_ui(message):
    chat_id = message.chat.id
    previous = _CLEAN_UI.pop(chat_id, None)
    if previous:
        try:
            await message.bot.delete_message(chat_id, previous)
        except TelegramAPIError:
            pass


async def mobile_home(message, *, clear_keyboard=True):
    """Главное меню на inline-кнопках для всех режимов, включая compact.

    Скрываем ReplyKeyboard от предыдущих версий: она перекрывала половину
    экрана телефона. Старая цифровая навигация по сообщениям остаётся рабочей.
    """
    if clear_keyboard:
        await clean_answer(message, "💜 LUMI", reply_markup=ReplyKeyboardRemove())
    await clean_answer(message, 
        "💜 <b>LUMI</b>",
        reply_markup=mobile_home_keyboard(), parse_mode="HTML")



# Telegram photo/video captions are limited to 1024 characters AFTER HTML parsing.
# Keep the owner's card compact even when user-generated fields are long.
def ui_safe(value, limit=320):
    """Escape user content before interpolating it into Telegram HTML."""
    value = str(value or "").strip()
    if len(value) > limit:
        value = value[:limit - 1].rstrip() + "…"
    return html_escape(value, quote=False)


def quick_caption(profile):
    name, age, city, interests, _ = profile
    return ("💜 <b>Моя анкета</b>\n\n"
            f"<b>{ui_safe(name, 40)}, {age}, {ui_safe(city, 60)}</b> — "
            f"{ui_safe(interests, 420) or 'Пока без описания'}")


async def show_quick_menu(message, user_id=None):
    # Dismiss a previously visible oversized Telegram reply keyboard.
    if LUMI_UI_MODE == "inline":
        await clean_answer(message, "👤 Моя анкета", reply_markup=ReplyKeyboardRemove())
    profile = profile_of(user_id or message.from_user.id)
    if not profile:
        await message.answer("Сначала создай анкету 💜", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💜 Создать анкету", callback_data="ux:register")]]))
        return
    caption = quick_caption(profile)
    with connect_db() as db:
        if premium_active(db, user_id or message.from_user.id):
            caption = caption.replace("💜 <b>Моя анкета</b>", "👑 <b>Моя анкета · Premium</b>", 1)
    with connect_db() as db:
        caption += founder_badge(db, user_id or message.from_user.id)
    nickname = nickname_of(user_id or message.from_user.id)
    if nickname:
        caption = f"🎲 <b>Ник:</b> {ui_safe(nickname, 40)}\n\n" + caption
    with connect_db() as db:
        media = db.execute("SELECT video_id FROM profiles WHERE user_id=?", (user_id or message.from_user.id,)).fetchone()
    if media and media[0]:
        try:
            await message.answer_video(media[0], caption=caption, reply_markup=mobile_profile_keyboard(), protect_content=True, parse_mode="HTML")
            await clear_clean_ui(message)
            return
        except TelegramAPIError:
            logger.exception("Ошибка показа видео меню")
    if profile[4]:
        try:
            await message.answer_photo(profile[4], caption=caption, reply_markup=mobile_profile_keyboard(), protect_content=True, parse_mode="HTML")
            await clear_clean_ui(message)
            return
        except TelegramAPIError:
            logger.exception("Ошибка показа фото меню")
    await message.answer(caption, reply_markup=mobile_profile_keyboard(), parse_mode="HTML", protect_content=True)
    await clear_clean_ui(message)


class Registration(StatesGroup):
    name = State()
    nickname = State()
    age = State()
    city = State()
    interests = State()
    photo = State()
    gender = State()
    seeking = State()
    description = State()


class EditProfile(StatesGroup):
    photo = State()
    interests = State()
    voice = State()


class SearchSettings(StatesGroup):
    age_min = State()
    age_max = State()
    city = State()


# Развлекательная мини-викторина: не является измерением IQ.
QUIZ_INTERVAL = 30
QUIZ_QUESTIONS = [
    ("Что тяжелее: 1 кг пельменей или 1 кг кирпичей?", ("Пельмени", "Кирпичи", "Одинаково"), 2, "Килограмм всегда килограмм. Даже если это пельмени."),
    ("У трёх котов по четыре лапы. Сколько лап у одного кота?", ("3", "4", "12"), 1, "У одного кота четыре лапы. Если он не осьминог."),
    ("Что растёт, когда из него забирают?", ("Очередь", "Яма", "Пицца"), 1, "Чем больше копаешь, тем больше яма."),
    ("На берёзе росло 5 яблок. Два упали. Сколько осталось?", ("3", "5", "Ни одного"), 2, "На берёзе яблоки обычно не растут."),
    ("Какой месяц имеет 28 дней?", ("Февраль", "Все", "Только март"), 1, "У каждого месяца есть как минимум 28 дней."),
    ("Если ты обогнал второго бегуна, какое место занял?", ("Первое", "Второе", "Третье"), 1, "Ты занял место второго бегуна."),
    ("Сколько раз можно вычесть 10 из 100?", ("Один", "Десять", "Бесконечно"), 0, "После первого раза вычитаешь уже из 90."),
    ("Что можно увидеть с закрытыми глазами?", ("Сон", "Wi-Fi", "Пельмени"), 0, "Сны не требуют открытых глаз."),
    ("У кого есть шея, но нет головы?", ("У бутылки", "У стула", "У облака"), 0, "Горлышко бутылки — её шея."),
    ("На столе 4 яблока. Ты взял 2. Сколько яблок у тебя?", ("2", "4", "6"), 0, "У тебя два яблока — те, которые взял."),
    ("Какой рукой лучше размешивать чай?", ("Правой", "Левой", "Ложкой"), 2, "Ложкой удобнее. И пальцы целее."),
    ("Что мокнет, пока сушит?", ("Полотенце", "Фен", "Солнце"), 0, "Полотенце впитывает воду."),
]


def quiz_status(user_id):
    with connect_db() as db:
        return db.execute("SELECT viewed_count, pending_question FROM quiz_progress WHERE user_id=?", (user_id,)).fetchone() or (0, None)


async def send_quiz(message, user_id):
    _, question_id = quiz_status(user_id)
    if question_id is None:
        return False
    question, options, _, _ = QUIZ_QUESTIONS[question_id]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{i + 1}. {answer}", callback_data=f"quiz:{question_id}:{i}")]
        for i, answer in enumerate(options)
    ] + [[InlineKeyboardButton(text="Пропустить вопрос", callback_data=f"quiz:{question_id}:skip")]])
    await message.answer("LUMI · Минутка для мозга\n\n" + question + "\n\nЭто шуточная викторина, а не настоящий IQ-тест.", reply_markup=keyboard)
    return True


@dp.callback_query(F.data.startswith("quiz:"))
async def quiz_answer(callback: CallbackQuery):
    try:
        _, raw_id, choice = callback.data.split(":", 2)
        question_id = int(raw_id)
        if not 0 <= question_id < len(QUIZ_QUESTIONS):
            raise ValueError
        if choice != "skip" and choice not in {"0", "1", "2"}:
            raise ValueError
    except (ValueError, AttributeError):
        await callback.answer("Некорректный ответ", show_alert=True)
        return
    uid = callback.from_user.id
    with connect_db() as db:
        result = db.execute("UPDATE quiz_progress SET pending_question=NULL WHERE user_id=? AND pending_question=?", (uid, question_id))
    if result.rowcount == 0:
        await callback.answer("Этот вопрос уже завершён")
        return
    _, _, correct, explanation = QUIZ_QUESTIONS[question_id]
    if choice == "skip":
        verdict = "Вопрос пропущен."
    elif int(choice) == correct:
        verdict = "Верно!"
    else:
        verdict = "Почти!"
    await callback.answer(verdict)
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        await callback.message.answer(f"{verdict} {explanation}\n\nПродолжаем знакомства!")
        await show_next(callback.message, uid)


def connect_db():
    """Short-lived SQLite connection. WAL is configured once during init_db()."""
    from lumi_database_vault import connect_private
    db = connect_private(DB_PATH, timeout=10)
    try:
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA cache_size=-4096")  # 4 MiB per active connection
        return db
    except BaseException:
        db.close()
        raise


FOUNDER_LIMIT = 100


def founder_number(db, user_id):
    """No personal data beyond the internal Telegram user ID is stored."""
    row = db.execute("SELECT serial FROM lumi_founders WHERE user_id=?", (user_id,)).fetchone()
    return int(row[0]) if row else None


def founder_status(db):
    # AUTOINCREMENT keeps a monotonic, non-reusable ID even after deletion.
    # sqlite_sequence can be absent on a fresh database, but the table exists.
    row = db.execute("SELECT seq FROM sqlite_sequence WHERE name='lumi_founders'").fetchone()
    granted = int(row[0]) if row else 0
    return min(granted, FOUNDER_LIMIT), max(0, FOUNDER_LIMIT - granted)


def claim_founder(user_id):
    """Claim one of 100 non-transferable founder badges atomically.

    The event is for the first 100 *participants with completed profiles*,
    including existing members. No fabricated signups or backdating.
    """
    with connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = founder_number(db, user_id)
        if existing is not None:
            return existing, False
        registered = db.execute("SELECT 1 FROM profiles WHERE user_id=? AND age >= 18", (user_id,)).fetchone()
        if not registered:
            return None, False
        _, places = founder_status(db)
        if places <= 0:
            return None, False
        try:
            cursor = db.execute("INSERT INTO lumi_founders(user_id) VALUES (?)", (user_id,))
            return int(cursor.lastrowid), True
        except sqlite3.IntegrityError:
            # Preserve the same user's previous badge under double clicks.
            return founder_number(db, user_id), False


def founder_badge(db, user_id):
    serial = founder_number(db, user_id)
    return f"\n🏅 <b>Первопроходец LUMI · №{serial}</b>" if serial else ""


def init_admin_tables(db):
    """Additive migration. No existing user data or pet progress is overwritten."""
    db.execute("""CREATE TABLE IF NOT EXISTS support_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        category TEXT NOT NULL DEFAULT 'question', message TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open', reply TEXT,
        assigned_admin INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_support_status ON support_tickets(status, created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_support_user ON support_tickets(user_id, created_at)")
    db.execute("""CREATE TABLE IF NOT EXISTS support_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        sender TEXT NOT NULL CHECK(sender IN ('user','admin')),
        body TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_support_messages_ticket ON support_messages(ticket_id,id)")
    db.execute("""CREATE TABLE IF NOT EXISTS admin_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL,
        ref_id INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        delivered_at TEXT, attempts INTEGER NOT NULL DEFAULT 0
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_admin_events_queue ON admin_events(delivered_at,id)")
    db.execute("""CREATE TABLE IF NOT EXISTS report_reviews (
        report_id INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'open',
        moderator_id INTEGER, reviewed_at TEXT
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS moderation_holds (
        user_id INTEGER PRIMARY KEY, reason TEXT NOT NULL,
        moderator_id INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    if 'expires_at' not in {c[1] for c in db.execute('PRAGMA table_info(moderation_holds)')}:
        db.execute('ALTER TABLE moderation_holds ADD COLUMN expires_at TEXT')
    db.execute("""CREATE TABLE IF NOT EXISTS account_suspensions (
        user_id INTEGER PRIMARY KEY, reason TEXT NOT NULL,
        moderator_id INTEGER NOT NULL, expires_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")


def admin_event(db, event_type, ref_id=None):
    db.execute("INSERT INTO admin_events(type, ref_id) VALUES (?,?)", (event_type, ref_id))


from lumi_db_performance import install_indexes, moment_candidates


def init_db():
    # WAL lets readers continue while another connection is writing.
    # Do not remove -wal/-shm files while bot is running.
    with connect_db() as db:
        mode = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if mode.lower() != "wal":
            logger.warning("SQLite не перешла в WAL: %s", mode)
        db.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                age INTEGER NOT NULL,
                city TEXT NOT NULL,
                interests TEXT NOT NULL,
                photo_id TEXT
            )
        """)
        live_analytics.init(db)
        live_shop.init(db)
        clubs.init(db)
        init_referrals(db)
        init_daily_rewards(db)
        # LUMI: «Первые 100 сердец». AUTOINCREMENT guarantees that a deleted
        # account's place is never silently reassigned to a later participant.
        db.execute("""CREATE TABLE IF NOT EXISTS lumi_founders (
            serial INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            awarded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK(serial BETWEEN 1 AND 100)
        )""")
        columns = {row[1] for row in db.execute("PRAGMA table_info(profiles)")}
        if "photo_id" not in columns:
            db.execute("ALTER TABLE profiles ADD COLUMN photo_id TEXT")
        for column, ddl in (
            ("video_id", "TEXT"),
            ("nickname", "TEXT DEFAULT ''"),
            ("gender", "TEXT DEFAULT 'не указан'"),
            ("seeking", "TEXT DEFAULT 'все'"),
            ("share_contact", "INTEGER DEFAULT 0"),
            ("username", "TEXT"),
        ):
            if column not in columns:
                db.execute(f"ALTER TABLE profiles ADD COLUMN {column} {ddl}")
        init_media_identity(db)
        db.execute("""CREATE TABLE IF NOT EXISTS profile_extras (
            user_id INTEGER PRIMARY KEY, voice_id TEXT, verified INTEGER NOT NULL DEFAULT 0,
            verification_status TEXT NOT NULL DEFAULT 'none')""")
        db.execute("""CREATE TABLE IF NOT EXISTS verification_requests (
            user_id INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        # Храним только Telegram file_id до решения модератора; локальные видео не скачиваем.
        for column, ddl in (("challenge", "TEXT"), ("expires_at", "TEXT"),
                            ("video_note_id", "TEXT"), ("submitted_at", "TEXT"), ("review_id", "TEXT")):
            cols={r[1] for r in db.execute("PRAGMA table_info(verification_requests)")}
            if column not in cols:
                db.execute(f"ALTER TABLE verification_requests ADD COLUMN {column} {ddl}")
        # Legacy pending reviews cannot be tied to the original moderator buttons.
        db.execute("UPDATE profile_extras SET verification_status='none' WHERE verified=0 AND user_id IN (SELECT user_id FROM verification_requests WHERE status='review' AND review_id IS NULL)")
        db.execute("DELETE FROM verification_requests WHERE status='review' AND review_id IS NULL")
        db.execute("""CREATE TABLE IF NOT EXISTS mystery_queue (
            user_id INTEGER PRIMARY KEY, joined_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("""CREATE TABLE IF NOT EXISTS mystery_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_a INTEGER NOT NULL,
            user_b INTEGER NOT NULL, round INTEGER NOT NULL DEFAULT 0,
            answer_a INTEGER, answer_b INTEGER, reveal_a INTEGER,
            reveal_b INTEGER, status TEXT NOT NULL DEFAULT 'active')""")
        db.execute("""CREATE TABLE IF NOT EXISTS daily_moments (
            user_id INTEGER NOT NULL, day TEXT NOT NULL, target_id INTEGER NOT NULL,
            PRIMARY KEY(user_id, day))""")
        db.execute("""CREATE TABLE IF NOT EXISTS duo_adventures (
            user_a INTEGER NOT NULL, user_b INTEGER NOT NULL,
            step INTEGER NOT NULL DEFAULT 0, text_a TEXT, text_b TEXT,
            PRIMARY KEY(user_a,user_b))""")
        db.execute("""CREATE TABLE IF NOT EXISTS game_sessions (
            user_a INTEGER NOT NULL, user_b INTEGER NOT NULL,
            game_type TEXT NOT NULL, question_id INTEGER NOT NULL,
            answer_a INTEGER, answer_b INTEGER,
            PRIMARY KEY (user_a,user_b))""")
        db.execute("""
            CREATE TABLE IF NOT EXISTS quiz_progress (
                user_id INTEGER PRIMARY KEY,
                viewed_count INTEGER NOT NULL DEFAULT 0,
                pending_question INTEGER
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS search_settings (
                user_id INTEGER PRIMARY KEY,
                age_min INTEGER NOT NULL DEFAULT 18,
                age_max INTEGER NOT NULL DEFAULT 100,
                city TEXT NOT NULL DEFAULT ''
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS reactions (
                from_user INTEGER NOT NULL,
                to_user INTEGER NOT NULL,
                liked INTEGER NOT NULL,
                PRIMARY KEY (from_user, to_user)
            )
        """)
        # Premium — независимые таблицы, без изменения существующих анкет.
        db.execute("""CREATE TABLE IF NOT EXISTS premium_orders (
            payload TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
            price INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            created_at INTEGER NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS premium_payments (
            charge_id TEXT PRIMARY KEY, payload TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL, stars INTEGER NOT NULL,
            paid_at INTEGER NOT NULL, refunded INTEGER NOT NULL DEFAULT 0)""")
        db.execute("""CREATE TABLE IF NOT EXISTS premium_subscriptions (
            user_id INTEGER PRIMARY KEY, expires_at INTEGER NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS premium_superlikes (
            user_id INTEGER NOT NULL, day TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,day))""")
        db.execute("""CREATE TABLE IF NOT EXISTS premium_skips (
            user_id INTEGER PRIMARY KEY, target_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS lumi_like_teasers (
            user_id INTEGER PRIMARY KEY,
            last_sent INTEGER NOT NULL DEFAULT 0
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS premium_filters (
            user_id INTEGER PRIMARY KEY, verified_only INTEGER NOT NULL DEFAULT 0)""")
        # Keep last teaser phrase across restarts; no user text stored.
        db.execute("""CREATE TABLE IF NOT EXISTS lumi_teaser_phrase_history (
            user_id INTEGER PRIMARY KEY, phrase_index INTEGER NOT NULL)""")
        db.execute("""
            CREATE TABLE IF NOT EXISTS blocks (
                user_id INTEGER NOT NULL,
                blocked_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, blocked_id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS active_chats (
                user_id INTEGER PRIMARY KEY,
                peer_id INTEGER NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS contact_requests (
                requester_id INTEGER NOT NULL,
                recipient_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                PRIMARY KEY (requester_id, recipient_id)
            )
        """)
        db.execute("""CREATE TABLE IF NOT EXISTS lumi_pets (
            user_id INTEGER PRIMARY KEY, species TEXT NOT NULL DEFAULT 'lumik',
            name TEXT NOT NULL DEFAULT 'Лумик', level INTEGER NOT NULL DEFAULT 1,
            xp INTEGER NOT NULL DEFAULT 0, coins INTEGER NOT NULL DEFAULT 50,
            food INTEGER NOT NULL DEFAULT 80, mood INTEGER NOT NULL DEFAULT 80,
            color TEXT NOT NULL DEFAULT 'classic',
            last_daily TEXT, last_feed TEXT, last_play TEXT, last_care TEXT
        )""")
        # ARENA: новые таблицы, без изменения существующих анкет и питомцев.
        db.execute("""CREATE TABLE IF NOT EXISTS arena_heroes (
            user_id INTEGER PRIMARY KEY, hero_id INTEGER NOT NULL,
            level INTEGER NOT NULL DEFAULT 1, xp INTEGER NOT NULL DEFAULT 0,
            rating INTEGER NOT NULL DEFAULT 0, wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0, draws INTEGER NOT NULL DEFAULT 0,
            last_daily TEXT
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS arena_collection (
            user_id INTEGER NOT NULL, hero_id INTEGER NOT NULL,
            level INTEGER NOT NULL DEFAULT 1, xp INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(user_id,hero_id))""")
        db.execute("""CREATE TABLE IF NOT EXISTS arena_intro (
            user_id INTEGER PRIMARY KEY, shown_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("""CREATE TABLE IF NOT EXISTS arena_achievements (
            user_id INTEGER NOT NULL, code TEXT NOT NULL,
            unlocked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id,code))""")
        db.execute("""CREATE TABLE IF NOT EXISTS arena_battle_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, challenge_id INTEGER UNIQUE,
            winner INTEGER NOT NULL, loser INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("""CREATE TABLE IF NOT EXISTS arena_season_scores (
            season TEXT NOT NULL, user_id INTEGER NOT NULL,
            wins INTEGER NOT NULL DEFAULT 0, points INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(season,user_id))""")
        db.execute("""CREATE TABLE IF NOT EXISTS duo_quest_rewards (
            user_a INTEGER NOT NULL, user_b INTEGER NOT NULL,
            completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_a,user_b))""")
        # Однократная миграция прогресса старого активного героя.
        db.execute("""INSERT OR IGNORE INTO arena_collection(user_id,hero_id,level,xp)
            SELECT user_id,hero_id,level,xp FROM arena_heroes""")
        # Общее заработанное EXP аккаунта. Не уменьшается при смене героя.
        db.execute("""CREATE TABLE IF NOT EXISTS arena_account_progress (
            user_id INTEGER PRIMARY KEY, total_xp INTEGER NOT NULL DEFAULT 0
                CHECK(total_xp >= 0))""")
        # Исторический EXP переносится один раз. Ранее заработанные уровни не теряются.
        historical = db.execute("SELECT user_id,level,xp FROM arena_collection").fetchall()
        historical_totals = {}
        for hist_uid, hist_lvl, hist_xp in historical:
            hist_lvl = max(1, min(int(hist_lvl), 10000))
            earned = sum(50 + 25 * l + 5 * l * l for l in range(1, hist_lvl))
            historical_totals[hist_uid] = historical_totals.get(hist_uid, 0) + earned + max(0, int(hist_xp))
        for hist_uid, earned in historical_totals.items():
            db.execute("INSERT OR IGNORE INTO arena_account_progress(user_id,total_xp) VALUES (?,?)",
                       (hist_uid, earned))
        db.execute("""CREATE TABLE IF NOT EXISTS privacy_settings (
            user_id INTEGER PRIMARY KEY, discoverable INTEGER NOT NULL DEFAULT 1
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS profile_views (
            viewer_id INTEGER NOT NULL, target_id INTEGER NOT NULL,
            viewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(viewer_id,target_id)
        )""")
        db.execute("""CREATE INDEX IF NOT EXISTS idx_profile_views_expiry ON profile_views(viewed_at)""")
        # Отдельное ограничение массового просмотра анкет за UTC-день.
        db.execute("""CREATE TABLE IF NOT EXISTS browse_daily (
            user_id INTEGER NOT NULL, day TEXT NOT NULL, views INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(user_id,day))""")

        db.execute("""CREATE TABLE IF NOT EXISTS security_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, actor INTEGER, action TEXT NOT NULL,
            target INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("""CREATE INDEX IF NOT EXISTS idx_reactions_to ON reactions(to_user,liked)""")
        db.execute("""CREATE INDEX IF NOT EXISTS idx_blocks_target ON blocks(blocked_id,user_id)""")
        db.execute("""CREATE TABLE IF NOT EXISTS arena_challenges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            challenger INTEGER NOT NULL, defender INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_at TEXT
        )""")
        db.execute("""CREATE INDEX IF NOT EXISTS idx_arena_challenges_pair
            ON arena_challenges(challenger,defender,status)""")
        db.execute("""CREATE TABLE IF NOT EXISTS lumi_pet_colors (
            user_id INTEGER NOT NULL, color TEXT NOT NULL,
            PRIMARY KEY(user_id,color)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS lumi_pet_events (
            user_id INTEGER NOT NULL, event_key TEXT NOT NULL,
            PRIMARY KEY(user_id,event_key)
        )""")
        db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER NOT NULL,
                reported_id INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_reports_pair_time ON reports(reporter_id,reported_id,created_at)")
        init_admin_tables(db)
        init_ops(db)
        db.execute("CREATE INDEX IF NOT EXISTS idx_ops_metrics_day ON lumi_ops_daily(day,metric)")
        db.execute("""CREATE TABLE IF NOT EXISTS lumi_starter_daily (
            from_user INTEGER NOT NULL, to_user INTEGER NOT NULL, day TEXT NOT NULL,
            PRIMARY KEY(from_user,to_user,day))""")
        # Query-plan indexes for browsing, matches, seasonal boards and cleanup.
        # All are additive and safe for an existing database.
        for statement in (
            "CREATE INDEX IF NOT EXISTS idx_profiles_age_gender ON profiles(age, gender)",
            "CREATE INDEX IF NOT EXISTS idx_profiles_seeking_age ON profiles(seeking, age)",
            "CREATE INDEX IF NOT EXISTS idx_reactions_incoming ON reactions(to_user, liked, from_user)",
            "CREATE INDEX IF NOT EXISTS idx_arena_challenges_pending_time ON arena_challenges(status, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_arena_challenges_defender ON arena_challenges(defender, status)",
            "CREATE INDEX IF NOT EXISTS idx_verification_expiry ON verification_requests(status, expires_at)",
            "CREATE INDEX IF NOT EXISTS idx_security_audit_time ON security_audit(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_reports_reported ON reports(reported_id, created_at)",
        ):
            db.execute(statement)
        install_indexes(db)



def is_discoverable(db, uid):
    if db.execute("SELECT 1 FROM moderation_holds WHERE user_id=? AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)", (uid,)).fetchone():
        return False
    row = db.execute("SELECT discoverable FROM privacy_settings WHERE user_id=?", (uid,)).fetchone()
    return row is None or bool(row[0])


def can_access_profile(db, viewer, target):
    """For existing user-supplied buttons, allow only recently shown or mutual profiles."""
    if viewer == target:
        return True
    if db.execute("SELECT 1 FROM blocks WHERE (user_id=? AND blocked_id=?) OR (user_id=? AND blocked_id=?)",
                  (viewer,target,target,viewer)).fetchone():
        return False
    if not is_discoverable(db, target) and not is_match(db, viewer, target):
        return False
    if is_match(db,viewer,target):
        return True
    return db.execute("SELECT 1 FROM profile_views WHERE viewer_id=? AND target_id=? "
                      "AND viewed_at >= datetime('now','-24 hours')", (viewer,target)).fetchone() is not None


def mark_profile_view(db, viewer, target):
    db.execute("INSERT INTO profile_views(viewer_id,target_id,viewed_at) VALUES(?,?,CURRENT_TIMESTAMP) "
               "ON CONFLICT(viewer_id,target_id) DO UPDATE SET viewed_at=CURRENT_TIMESTAMP",(viewer,target))


def premium_expires_at(db, user_id):
    row = db.execute("SELECT expires_at FROM premium_subscriptions WHERE user_id=?", (user_id,)).fetchone()
    return int(row[0]) if row else 0


def premium_active(db, user_id):
    return premium_expires_at(db, user_id) > int(time.time())


def premium_accept_payment(db, user_id, payment):
    """Apply one Telegram-confirmed charge once; duplicate updates are safe."""
    if payment.currency != "XTR" or payment.total_amount != PREMIUM_STARS:
        return False
    payload = payment.invoice_payload
    charge = payment.telegram_payment_charge_id
    if not isinstance(payload, str) or not payload or not isinstance(charge, str) or not charge:
        return False
    order = db.execute("SELECT user_id,price,status FROM premium_orders WHERE payload=?", (payload,)).fetchone()
    if not order or order[0] != user_id or order[1] != PREMIUM_STARS:
        return False
    if order[2] != 'pending':
        return False
    now = int(time.time())
    inserted = db.execute(
        "INSERT OR IGNORE INTO premium_payments(charge_id,payload,user_id,stars,paid_at) VALUES(?,?,?,?,?)",
        (payment.telegram_payment_charge_id,payload,user_id,PREMIUM_STARS,now))
    if inserted.rowcount != 1:
        return False
    old = premium_expires_at(db,user_id)
    db.execute("INSERT INTO premium_subscriptions(user_id,expires_at) VALUES(?,?) "
               "ON CONFLICT(user_id) DO UPDATE SET expires_at=excluded.expires_at",
               (user_id,max(now,old)+PREMIUM_SECONDS))
    db.execute("UPDATE premium_orders SET status='paid' WHERE payload=?",(payload,))
    return True


def profile_of(user_id):
    with connect_db() as db:
        return db.execute(
            "SELECT name, age, city, interests, photo_id FROM profiles WHERE user_id=?",
            (user_id,),
        ).fetchone()


NICK_FIRST = ["Лорд", "Капитан", "Барон", "Мистер", "Генерал", "Принц", "Агент", "Король", "Профессор", "Магистр"]
NICK_SECOND = ["Пельмень", "Кряк", "Батон", "Огурец", "Кабачок", "Пингвин", "Чебурек", "Бублик", "Шашлык", "Тапочек"]


def random_nickname():
    return f"{random.choice(NICK_FIRST)} {random.choice(NICK_SECOND)}"


def nickname_of(user_id):
    with connect_db() as db:
        row = db.execute("SELECT nickname FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    return row[0] if row else ""


def nickname_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎲 Сгенерировать ник")],
        [KeyboardButton(text="Без ника")],
    ], resize_keyboard=True)


def profile_shared_context(profile, viewer_profile):
    """Only compare self-declared fields, never infer location or compatibility."""
    if not viewer_profile:
        return ""
    city = (profile[2] or "").strip().casefold()
    other_city = (viewer_profile[2] or "").strip().casefold()
    lines = []
    if city and city == other_city and city not in {"не указан", "не указано", "-", "—"}:
        lines.append("📍 Один город")
    common = interest_words(profile[3]) & interest_words(viewer_profile[3])
    if common:
        lines.append("✨ Есть общие слова в описаниях")
    return "\n\n" + " · ".join(lines) if lines else ""


def cosmetic_caption(db, user_id):
    if not user_id or not shop_enabled():
        return ""
    sku = live_shop.equipped(db, user_id)
    return "\n" + live_shop.LABELS[sku] if sku else ""


def profile_caption(profile, own=False, user_id=None, viewer_id=None):
    name, age, city, interests, _ = profile
    nickname = nickname_of(user_id) if user_id else ""
    with connect_db() as db:
        status = db.execute(
            "SELECT verified FROM profile_extras WHERE user_id=?", (user_id,)
        ).fetchone() if user_id else None

    title = "💜 <b>МОЯ АНКЕТА</b>" if own else "💜 <b>ЗНАКОМСТВА LUMI</b>"
    verified_line = "\n✅ <b>Фото проверено</b>" if status and status[0] else ""
    with connect_db() as db:
        premium_line = "\n👑 <b>ЗОЛОТАЯ АНКЕТА</b>  ·  ⭐ Premium" if user_id and premium_active(db, user_id) else ""
    nickname_line = f"\n🎲 {ui_safe(nickname, 40)}" if nickname else ""
    with connect_db() as db:
        founder_line = founder_badge(db, user_id) if user_id else ""
        referral_line = "\n💜 <b>Рамка героя «Сердце LUMI»</b>" if user_id and has_referral_frame(db, user_id) else ""
        cosmetic_line = cosmetic_caption(db, user_id)
    if not own:
        summary = f"<b>{ui_safe(' '.join(str(name or '').split()), 40)}, {age}, {ui_safe(' '.join(str(city or '').split()), 60)}</b> — {ui_safe(' '.join(str(interests or '').split()), 480) or 'Не указано'}"
        return (founder_line.strip() + "\n\n" if founder_line else "") + summary + verified_line + premium_line + nickname_line + referral_line + cosmetic_line
    return (
        f"{title}\n\n"
        f"<b>{ui_safe(name, 40)}, {age}</b>{verified_line}{premium_line}{nickname_line}{founder_line}{referral_line}{cosmetic_line}\n"
        f"📍 {ui_safe(city, 60)}\n\n"
        "<b>О себе</b>\n"
        f"{ui_safe(interests, 480) or 'Пока без описания'}"
        f"{profile_shared_context(profile, profile_of(viewer_id)) if viewer_id and not own and viewer_id != user_id else ''}"
    )


async def send_profile(message, profile, own=False, keyboard=None, user_id=None, viewer_id=None):
    caption = profile_caption(profile, own=own, user_id=user_id, viewer_id=viewer_id)
    markup = menu if own else keyboard
    if user_id:
        with connect_db() as db:
            media = db.execute("SELECT video_id FROM profiles WHERE user_id=?", (user_id,)).fetchone()
        if media and media[0]:
            try:
                await message.answer_video(media[0], caption=caption, reply_markup=markup, protect_content=True, parse_mode="HTML")
                return
            except TelegramAPIError:
                logger.exception("Не удалось отправить видео анкеты")
    if profile[4]:
        try:
            await message.answer_photo(photo=profile[4], caption=caption, reply_markup=markup, protect_content=True, parse_mode="HTML")
            return
        except TelegramAPIError:
            logger.exception("Не удалось отправить сохранённую фотографию")
    await message.answer(caption, reply_markup=markup, parse_mode="HTML", protect_content=True)


def interest_words(value):
    """Простые ключевые слова из добровольно указанного описания."""
    stop = {"и", "в", "на", "с", "а", "я", "ты", "мы", "мне", "для", "это", "не", "по", "или", "хочу", "ищу", "люблю", "очень", "как", "мой", "моя", "себе", "свой", "все", "нет", "указано"}
    return {word for word in re.findall(r"[^\W_]+", (value or "").casefold())
            if len(word) >= 3 and word not in stop}


ACTIVE_BROWSE_TARGET = RecentMap(5000)  # user_id -> (target_id, keyboard_message_id)
DEFERRED = RecentMap(2000)  # Анкеты, отложенные до следующего круга просмотра
SEEN_THIS_ROUND = RecentMap(2000)  # Уже показанные анкеты в текущем круге

class BrowsePanelGuard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user and user.id in ACTIVE_BROWSE_TARGET:
            if isinstance(event, Message):
                keep = event.text in {"❤️ Нравится", "👎 Пропустить"}
            else:
                keep = (event.data or "").startswith(("browse:more:", "browse:main:", "like:", "skip:", "super:", "letter:", "later:", "block:", "report:", "listen:"))
            if not keep:
                ACTIVE_BROWSE_TARGET.pop(user.id, None)
                chat_message = event if isinstance(event, Message) else event.message
                if chat_message:
                    await chat_message.answer("💜", reply_markup=ReplyKeyboardRemove())
        return await handler(event, data)


dp.message.outer_middleware(BrowsePanelGuard())
dp.callback_query.outer_middleware(BrowsePanelGuard())


def eligible_candidates(user_id):
    """Фильтры обязательны; рейтинг определяет порядок подходящих анкет."""
    with connect_db() as db:
        me = db.execute(
            "SELECT age, city, interests, gender, seeking FROM profiles WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not me or me[0] < 18:
            return [], None
        my_age, my_city, my_interests, my_gender, seeking = me
        settings = db.execute(
            "SELECT age_min, age_max, city FROM search_settings WHERE user_id=?",
            (user_id,),
        ).fetchone() or (18, 100, "")
        min_age, max_age, city_filter = settings
        filter_row=db.execute("SELECT verified_only FROM premium_filters WHERE user_id=?",(user_id,)).fetchone()
        verified_only=bool(filter_row and filter_row[0] and premium_active(db,user_id))
        # Исключаем несовершеннолетних, себя, уже оценённых и блокировки.
        rows = db.execute("""
            SELECT p.user_id, p.name, p.age, p.city, p.interests, p.photo_id,
                   p.gender, p.seeking
            FROM profiles p
            WHERE p.user_id != ? AND p.age BETWEEN ? AND ? AND p.age >= 18
              AND NOT EXISTS (SELECT 1 FROM privacy_settings ps WHERE ps.user_id=p.user_id AND ps.discoverable=0)
              AND NOT EXISTS (SELECT 1 FROM moderation_holds mh WHERE mh.user_id=p.user_id AND (mh.expires_at IS NULL OR mh.expires_at > CURRENT_TIMESTAMP))
              AND (? = 0 OR EXISTS (SELECT 1 FROM profile_extras pe WHERE pe.user_id=p.user_id AND pe.verified=1))
              AND (? = 'все' OR p.gender = ?)
              AND (p.seeking = 'все' OR p.seeking = ? OR ? = 'не указан')
              AND NOT EXISTS (
                  SELECT 1 FROM reactions r
                  WHERE r.from_user=? AND r.to_user=p.user_id AND r.liked=1
              )
              AND NOT EXISTS (
                  SELECT 1 FROM blocks b
                  WHERE (b.user_id=? AND b.blocked_id=p.user_id)
                     OR (b.user_id=p.user_id AND b.blocked_id=?)
              )
        """, (user_id, min_age, max_age, int(verified_only), seeking, seeking,
              my_gender, my_gender, user_id, user_id, user_id)).fetchall()

    city_filter = (city_filter or "").strip().casefold()
    if city_filter:
        rows = [r for r in rows if r[3].strip().casefold() == city_filter]
    return rows, me


def next_candidate(user_id):
    rows, me = eligible_candidates(user_id)
    if me is None:
        return None
    my_age, my_city, my_interests, my_gender, seeking = me
    if not rows:
        SEEN_THIS_ROUND.pop(user_id, None)
        DEFERRED.pop(user_id, None)
        return None

    # Сначала новые анкеты (без реакции), затем ранее пропущенные.
    # В рамках одного круга одна анкета не показывается дважды.
    with connect_db() as db:
        skipped = {r[0] for r in db.execute(
            "SELECT to_user FROM reactions WHERE from_user=? AND liked=0", (user_id,)
        )}
    seen = SEEN_THIS_ROUND.setdefault(user_id, RecentSet(1000))
    deferred = DEFERRED.get(user_id, set())
    available = [r for r in rows if r[0] not in seen and r[0] not in deferred]
    if not available:
        # Круг завершён: запускаем новый автоматически.
        seen.clear()
        DEFERRED.pop(user_id, None)
        available = list(rows)
    fresh = [r for r in available if r[0] not in skipped]
    rows = fresh or available

    mine = interest_words(my_interests)
    my_city_normalized = (my_city or "").strip().casefold()
    with connect_db() as db:
        boosted_ids={r[0] for r in db.execute(
            "SELECT user_id FROM premium_subscriptions WHERE expires_at>?",(int(time.time()),))}

    def compatibility(row):
        _, _, age, city, interests, _, _, _ = row
        if os.getenv("LUMI_MATCHING_EXPERIMENT", "0") == "1":
            return matching_score(my_city, my_interests, city, interests) + (4 if row[0] in boosted_ids else 0) + random.uniform(0, 3)
        theirs = interest_words(interests)
        common = len(mine & theirs)
        # Город и интересы важнее небольшой разницы в возрасте.
        city_bonus = 30 if city.strip().casefold() == my_city_normalized else 0
        interest_bonus = min(common, 5) * 12
        age_bonus = max(0, 20 - abs(age - my_age) * 2)
        visibility_bonus=4 if row[0] in boosted_ids else 0
        return city_bonus + interest_bonus + age_bonus + visibility_bonus + random.uniform(0, 3)

    best = max(rows, key=compatibility)
    SEEN_THIS_ROUND.setdefault(user_id, RecentSet(1000)).add(best[0])
    return best[:6]


def browse_keyboard(target_id: int, expanded: bool = False, has_voice: bool = False):
    """Mobile-first profile controls. Keep safety actions one tap away."""
    if not expanded:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💜 Лайк", callback_data=f"like:{target_id}"),
             InlineKeyboardButton(text="➡️ Пропустить", callback_data=f"skip:{target_id}")],
            [InlineKeyboardButton(text="⋯ Ещё", callback_data=f"browse:more:{target_id}"),
             InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")],
        ])
    rows = [
        [InlineKeyboardButton(text="⭐ Суперлайк", callback_data=f"super:{target_id}"),
         InlineKeyboardButton(text="💌 Симпатия", callback_data=f"letter:{target_id}")],
        [InlineKeyboardButton(text="💤 Позже", callback_data=f"later:{target_id}")],
    ]
    if has_voice:
        rows.append([InlineKeyboardButton(text="🎙 Слушать голос", callback_data=f"listen:{target_id}")])
    rows += [
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"block:{target_id}"),
         InlineKeyboardButton(text="⚠️ Пожаловаться", callback_data=f"report:{target_id}")],
        [InlineKeyboardButton(text="⬅️ К анкете", callback_data=f"browse:main:{target_id}"),
         InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def browse_navigation_keyboard(target_id):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⋯ Ещё", callback_data=f"browse:more:{target_id}"),
        InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")]])


def browse_reply_keyboard():
    """Нижняя панель выбора рядом со строкой ввода: только две главные реакции."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❤️ Нравится"), KeyboardButton(text="👎 Пропустить")]],
        resize_keyboard=True,
        is_persistent=False,
        input_field_placeholder="Выбери: нравится или пропустить",
    )


@dp.callback_query(F.data.startswith(("browse:more:", "browse:main:")))
async def browse_extra_actions(callback: CallbackQuery):
    try:
        _, mode, raw_id = callback.data.split(":", 2)
        target = int(raw_id)
        if target <= 0 or mode not in {"more", "main"}:
            raise ValueError
    except (AttributeError, ValueError):
        await callback.answer("Кнопка недоступна", show_alert=True)
        return
    uid = callback.from_user.id
    with connect_db() as db:
        allowed = bool(profile_of(uid)) and can_access_profile(db, uid, target)
        # A match alone does not grant permission to modify an old browse card.
        shown = db.execute("SELECT 1 FROM profile_views WHERE viewer_id=? AND target_id=? "
                           "AND viewed_at >= datetime('now','-24 hours')", (uid, target)).fetchone()
        voice = db.execute("SELECT voice_id FROM profile_extras WHERE user_id=?", (target,)).fetchone()
        # Once rated, old cards must not reopen the reaction controls.
        rated = db.execute("SELECT 1 FROM reactions WHERE from_user=? AND to_user=?",
                           (uid, target)).fetchone()
    if not allowed or not shown or rated:
        await callback.answer("Эта анкета уже недоступна. Открой поиск заново.", show_alert=True)
        return
    if not callback.message:
        await callback.answer("Сообщение недоступно", show_alert=True)
        return
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=browse_keyboard(
            target, expanded=(mode == "more"), has_voice=bool(voice and voice[0])) if mode == "more" or uid not in ACTIVE_BROWSE_TARGET else browse_navigation_keyboard(target))
    except TelegramAPIError:
        logger.info("Не удалось обновить действия анкеты")


# LUMI: обязательная проверка после первых 20 просмотров анкет.
# Счётчик постоянный в SQLite (quiz_progress), не сбрасывается при перезапуске.
VERIFY_GATE_AFTER = 20


def verification_gate_status(uid: int):
    with connect_db() as db:
        row = db.execute("SELECT viewed_count FROM quiz_progress WHERE user_id=?", (uid,)).fetchone()
        verified = db.execute("SELECT verified FROM profile_extras WHERE user_id=?", (uid,)).fetchone()
        request = db.execute("SELECT status FROM verification_requests WHERE user_id=?", (uid,)).fetchone()
    return (int(row[0]) if row else 0,
            bool(verified and verified[0]),
            request[0] if request else None)


def verification_gate_keyboard(is_review=False):
    rows = []
    if not is_review:
        rows.append([InlineKeyboardButton(text="🛡 Пройти проверку", callback_data="verifygate:start")])
    rows += [[InlineKeyboardButton(text="🆘 Поддержка", callback_data="ux:support"),
              InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_verification_gate(message, count=None, status=None):
    if count is None:
        count, _, status = verification_gate_status(message.from_user.id)
    if status == 'review':
        text = "Кружок уже отправлен модератору. После подтверждения просмотр снова станет доступен."
    elif status == 'challenge':
        text = "Задание уже выдано. Нажми кнопку ниже, чтобы увидеть его снова."
    else:
        text = ("Для дальнейшего просмотра нужно подтвердить сходство с фото анкеты: "
                "записать короткий видеокружок по заданию. Его проверит модератор.")
    await message.answer(
        "🛡 <b>Проверка анкеты LUMI</b>\n\n"
        f"Ты посмотрел(а) {count} анкет. После {VERIFY_GATE_AFTER} просмотров нужна проверка.\n\n"
        + text + "\n\n"
        "Видео не появляется в анкете, но будет отправлено модератору через Telegram. "
        "Это проверка сходства с фото, а не подтверждение возраста или личности по документам. "
        "Если не хочешь отправлять кружок, можешь продолжать пользоваться другими разделами LUMI.",
        parse_mode="HTML", reply_markup=verification_gate_keyboard(status == 'review')
    )


async def show_next(message, user_id):
    ACTIVE_BROWSE_TARGET.pop(user_id, None)
    try:
        await _show_next_profile(message, user_id)
    finally:
        if user_id not in ACTIVE_BROWSE_TARGET:
            await message.answer("Просмотр анкет приостановлен.", reply_markup=ReplyKeyboardRemove())


async def _show_next_profile(message, user_id):
    if not profile_of(user_id):
        await message.answer("Сначала создай свою анкету 💜", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💜 Создать анкету", callback_data="ux:register")], [InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")]]))
        return
    gate_count, gate_approved, gate_pending = verification_gate_status(user_id)
    if gate_count >= VERIFY_GATE_AFTER and not gate_approved:
        await show_verification_gate(message, gate_count, gate_pending)
        return
    # Лимит действует даже если пользователь медленно листает анкеты и не спамит кнопки.
    today_utc = datetime.now(timezone.utc).date().isoformat()
    try:
        daily_limit = max(10, min(500, int(os.getenv("LUMI_DAILY_PROFILE_LIMIT", "80"))))
    except ValueError:
        daily_limit = 80
    with connect_db() as db:
        viewed_today = db.execute("SELECT views FROM browse_daily WHERE user_id=? AND day=?",
                                  (user_id, today_utc)).fetchone()
    if viewed_today and viewed_today[0] >= daily_limit:
        await message.answer("На сегодня просмотры анкет закончились. Возвращайся завтра 💜", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")]]))
        return
    if await send_quiz(message, user_id):
        return
    candidate = next_candidate(user_id)
    if not candidate:
        await message.answer(
            "Пока нет доступных анкет по твоим фильтрам. Попробуй расширить настройки поиска.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔎 Настройки поиска", callback_data="ux:search")], [InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")]])
        )
        return
    candidate_id, *profile = candidate
    # Считаем показы, а не нажатия: каждая 30-я анкета запускает викторину.
    # Проверка ограничения непосредственно в SQL: параллельные нажатия не позволяют
    # получить 21-ю анкету без одобрения модератора.
    with connect_db() as db:
        db.execute("INSERT OR IGNORE INTO quiz_progress(user_id) VALUES (?)", (user_id,))
        updated = db.execute("""UPDATE quiz_progress SET viewed_count=viewed_count+1
            WHERE user_id=? AND (viewed_count < ? OR EXISTS (
                SELECT 1 FROM profile_extras WHERE user_id=? AND verified=1))""",
            (user_id, VERIFY_GATE_AFTER, user_id))
        count = db.execute("SELECT viewed_count FROM quiz_progress WHERE user_id=?", (user_id,)).fetchone()[0]
        gate_blocked = updated.rowcount == 0
        if not gate_blocked and count % QUIZ_INTERVAL == 0:
            db.execute("UPDATE quiz_progress SET pending_question=? WHERE user_id=?",
                       (random.randrange(len(QUIZ_QUESTIONS)), user_id))
    if gate_blocked:
        await show_verification_gate(message)
        return
    # LUMI 2.4: нижняя панель у поля ввода — только «Нравится» и «Пропустить».
    keyboard = browse_navigation_keyboard(candidate_id)
    with connect_db() as db:
        if not is_discoverable(db,candidate_id):
            await message.answer("Эта анкета больше недоступна.")
            return
        # Атомарное начисление просмотра. Несколько одновременных действий не обойдут лимит.
        db.execute("INSERT OR IGNORE INTO browse_daily(user_id,day,views) VALUES (?,?,0)",
                   (user_id,today_utc))
        updated = db.execute("UPDATE browse_daily SET views=views+1 WHERE user_id=? AND day=? AND views<?",
                             (user_id,today_utc,daily_limit))
        if not updated.rowcount:
            await message.answer("На сегодня просмотры анкет закончились. Возвращайся завтра 💜", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")]]))
            return
        mark_profile_view(db,user_id,candidate_id)
    await send_profile(message, profile, keyboard=keyboard, user_id=candidate_id, viewer_id=user_id)
    await clear_clean_ui(message)
    if count == VERIFY_GATE_AFTER:
        _, is_approved, state = verification_gate_status(user_id)
        if not is_approved:
            await show_verification_gate(message, count, state)
            return
    panel = await message.answer("\u2060", reply_markup=browse_reply_keyboard())
    ACTIVE_BROWSE_TARGET[user_id] = (candidate_id, panel.message_id)
    try:
        await panel.delete()
    except TelegramAPIError:
        pass


@dp.message(F.successful_payment)
async def premium_success(message: Message):
    payment=message.successful_payment
    with connect_db() as db:
        # SQLite transaction is committed only after the unique payment and subscription update.
        db.execute("BEGIN IMMEDIATE")
        result=premium_accept_payment(db,message.from_user.id,payment)
        until=premium_expires_at(db,message.from_user.id)
        duplicate=db.execute("SELECT 1 FROM premium_payments WHERE charge_id=? AND payload=? AND user_id=? AND stars=? AND refunded=0", (payment.telegram_payment_charge_id,payment.invoice_payload,message.from_user.id,payment.total_amount)).fetchone() if payment.currency=="XTR" else None
    if result:
        await message.answer(
            "✅ <b>Premium активирован!</b>\n\n"
            "Доступ до <b>"+datetime.fromtimestamp(until,timezone.utc).strftime("%d.%m.%Y %H:%M UTC")+"</b>.\n"
            "Открой /premium, чтобы пользоваться возможностями.",parse_mode="HTML")
    elif duplicate and until>int(time.time()):
        await message.answer("✅ Premium уже активен. Повторное начисление не выполнено.")
    else:
        logger.error("Платёж не сопоставлен с заказом: user_id=%s",message.from_user.id)
        await message.answer("⚠️ Платёж получен, но доступ не выдан автоматически. Напиши в /paysupport и приложи квитанцию.")


def premium_apply_refund(db, uid, refund):
    """Caller holds a write transaction; validate the original receipt."""
    if refund.currency != "XTR":
        return False
    row=db.execute("SELECT payload,stars FROM premium_payments WHERE charge_id=? AND user_id=? AND refunded=0",
                   (refund.telegram_payment_charge_id,uid)).fetchone()
    if not row or row[0]!=refund.invoice_payload or row[1]!=refund.total_amount:
        return False
    db.execute("UPDATE premium_payments SET refunded=1 WHERE charge_id=? AND user_id=?",(refund.telegram_payment_charge_id,uid))
    db.execute("UPDATE premium_orders SET status='refunded' WHERE payload=? AND user_id=?",(row[0],uid))
    remaining=db.execute("SELECT paid_at FROM premium_payments WHERE user_id=? AND refunded=0 ORDER BY paid_at,charge_id",(uid,)).fetchall()
    expiry=0
    for (paid_at,) in remaining:
        expiry=max(expiry,int(paid_at))+PREMIUM_SECONDS
    # Do not recreate a subscription that account deletion already removed.
    if expiry:
        db.execute("UPDATE premium_subscriptions SET expires_at=? WHERE user_id=?",(expiry,uid))
    else:
        db.execute("DELETE FROM premium_subscriptions WHERE user_id=?",(uid,))
    return True


@dp.message(F.refunded_payment)
async def premium_refund(message: Message):
    refund=message.refunded_payment
    uid=message.from_user.id
    with connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        applied=premium_apply_refund(db,uid,refund)
        duplicate=db.execute("SELECT 1 FROM premium_payments WHERE charge_id=? AND payload=? AND user_id=? AND stars=? AND refunded=1", (refund.telegram_payment_charge_id,refund.invoice_payload,uid,refund.total_amount)).fetchone() if refund.currency=="XTR" else None
    if applied or duplicate:
        await message.answer("ℹ️ Возврат Stars учтён. Текущий Premium пересчитан.")
    else:
        logger.warning("Не удалось сопоставить возврат Stars с платежом")
        await message.answer("⚠️ Возврат требует проверки. Обратись в /paysupport.")


@dp.message(Command("games"))
async def open_games(message: Message):
    if not LUMI_GAMES_URL:
        await message.answer("🎮 LUMI GAMES готовится к подключению.\n"
                             "Администратору нужно указать HTTPS-адрес LUMI_GAMES_URL в .env.")
        return
    await message.answer("🎮 <b>LUMI GAMES</b>\n\nАнкеты и совпадения остаются в чате. "
                         "Игры открываются отдельно 💜",
                         parse_mode="HTML",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[[game_button()]]))


@dp.callback_query(F.data == "games:not_configured")
async def games_not_configured(callback: CallbackQuery):
    await callback.answer("Игровая Mini App ещё не подключена. Нужен HTTPS-адрес.", show_alert=True)


def analytics_enabled():
    return os.getenv("LUMI_ANALYTICS_ENABLED", "0") == "1"


def analytics_record(uid):
    with connect_db() as db:
        live_analytics.record(db, uid, datetime.now(timezone.utc).date())


class AnalyticsActivityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if analytics_enabled() and user and not getattr(user, "is_bot", False):
            try:
                await asyncio.to_thread(analytics_record, user.id)
            except (sqlite3.Error, OSError, RuntimeError):
                logger.warning("Analytics activity unavailable")
        return await handler(event, data)


dp.message.outer_middleware(AnalyticsActivityMiddleware())
dp.callback_query.outer_middleware(AnalyticsActivityMiddleware())


@dp.message(Command("analytics_on"))
async def analytics_on(message: Message):
    if not analytics_enabled():
        await message.answer("Аналитика сейчас отключена.")
        return
    with connect_db() as db:
        enabled = live_analytics.opt_in(db, message.from_user.id)
    await message.answer("Аналитика включена: сохраняются только дни активности в течение 90 дней. /analytics_off удаляет эти записи." if enabled else "Сначала создай анкету.")


@dp.message(Command("analytics_off"))
async def analytics_off(message: Message):
    with connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        live_analytics.opt_out(db, message.from_user.id)
    await message.answer("Аналитика отключена, записи активности удалены из рабочей базы. Резервные копии могут сохраняться до истечения срока хранения.")


def shop_enabled():
    return os.getenv("LUMI_SHOP_DEMO", "0") == "1"


def shop_action(uid, sku=None, epoch=None):
    with connect_db() as db:
        return live_shop.act(db, uid, sku, epoch)


def shop_view(result):
    balance, epoch, owned, status = result
    names = {"aurora_frame": "Aurora Frame", "obsidian_glow": "Obsidian Glow", "violet_badge": "Violet Badge"}
    rows = [[InlineKeyboardButton(text=f"{names[sku]} · {price}", callback_data=f"shop:{epoch}:{sku}")]
            for sku, price in SHOP_CATALOG.items() if sku not in owned]
    text = f"LUMI · Demo Marketplace\nБаланс: {balance} тестовых кредитов\nИнвентарь: " + (", ".join(names[sku] for sku in owned) or "пуст")
    rows += [[InlineKeyboardButton(text=f"Надеть · {names[sku]}", callback_data=f"equip:{epoch}:{sku}")] for sku in owned if sku in names]
    if owned:
        rows.append([InlineKeyboardButton(text="Снять оформление", callback_data=f"equip:{epoch}:none")])
    text += "\nКредиты не имеют денежной ценности. Можно выбрать один значок оформления анкеты."
    return text, InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


@dp.message(Command("shop"))
async def demo_shop(message: Message):
    if not shop_enabled():
        await message.answer("Магазин пока недоступен.")
        return
    result = await asyncio.to_thread(shop_action, message.from_user.id)
    if result is None:
        await message.answer("Магазин недоступен для этого аккаунта.")
        return
    text, keyboard = shop_view(result)
    await message.answer(text, reply_markup=keyboard, parse_mode=None)


@dp.callback_query(F.data.startswith("shop:"))
async def demo_shop_purchase(callback: CallbackQuery):
    match = re.fullmatch(r"shop:([0-9a-f]{16}):([a-z_]+)", callback.data or "")
    if not shop_enabled() or not match or match[2] not in SHOP_CATALOG:
        await callback.answer("Магазин недоступен.", show_alert=True)
        return
    result = await asyncio.to_thread(shop_action, callback.from_user.id, match[2], match[1])
    if result is None:
        await callback.answer("Открой /shop заново.", show_alert=True)
        return
    await callback.answer({"owned": "Уже в инвентаре", "insufficient": "Недостаточно кредитов", "purchased": "Добавлено в инвентарь"}[result[3]], show_alert=True)
    if callback.message:
        text, keyboard = shop_view(result)
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=None)



def shop_equip_action(uid, sku, epoch):
    with connect_db() as db:
        return live_shop.equip(db, uid, sku, epoch)


@dp.callback_query(F.data.startswith("equip:"))
async def demo_shop_equip(callback: CallbackQuery):
    match = re.fullmatch(r"equip:([0-9a-f]{16}):([a-z_]+)", callback.data or "")
    if not shop_enabled() or not match or (match[2] != "none" and match[2] not in SHOP_CATALOG):
        await callback.answer("Оформление недоступно.", show_alert=True)
        return
    ok = await asyncio.to_thread(shop_equip_action, callback.from_user.id, None if match[2] == "none" else match[2], match[1])
    await callback.answer("Оформление обновлено." if ok else "Открой /shop заново или приобрети предмет.", show_alert=True)


def clubs_action(uid, action="view", club=None, epoch=None):
    with connect_db() as db:
        return clubs.act(db, uid, action, club, epoch)


def clubs_view(result, language_code=None):
    tr = locale_strings(language_code)
    epoch, owned, status = result
    rows = [[InlineKeyboardButton(text=(tr["leave"] if key in owned else tr["join"]) + tr[key],
             callback_data=f"club:{epoch}:{'leave' if key in owned else 'join'}:{key}")] for key, name in clubs.CLUBS.items()]
    rows.append([InlineKeyboardButton(text=tr["weekly"], callback_data=f"clubact:{epoch}:view")])
    return tr["title"] + "\n" + tr["mine"] + (", ".join(tr[k] for k in owned) or tr["none"]) + "\n" + tr["pilot"], InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(Command("clubs"))
async def demo_clubs(message: Message):
    lang = message.from_user.language_code if message.from_user else None
    tr = locale_strings(lang)
    if os.getenv("LUMI_CLUBS_DEMO", "0") != "1" or message.chat.type != "private" or not message.from_user:
        return
    result = await asyncio.to_thread(clubs_action, message.from_user.id)
    if result is None:
        await message.answer(tr["account"])
        return
    text, keyboard = clubs_view(result, lang)
    await message.answer(text, reply_markup=keyboard, parse_mode=None)


@dp.callback_query(F.data.startswith("club:"))
async def demo_club_action(callback: CallbackQuery):
    lang = callback.from_user.language_code
    tr = locale_strings(lang)
    match = re.fullmatch(r"club:([0-9a-f]{32}):(join|leave):([a-z]+)", callback.data or "")
    if (os.getenv("LUMI_CLUBS_DEMO", "0") != "1" or not match or match[3] not in clubs.CLUBS
            or not callback.message or callback.message.chat.type != "private" or callback.message.chat.id != callback.from_user.id):
        await callback.answer(tr["unavailable"], show_alert=True)
        return
    result = await asyncio.to_thread(clubs_action, callback.from_user.id, match[2], match[3], match[1])
    if result is None:
        await callback.answer(tr["reopen"], show_alert=True)
        return
    await callback.answer(tr[result[2]], show_alert=True)
    text, keyboard = clubs_view(result, lang)
    await callback.message.answer(text, reply_markup=keyboard, parse_mode=None)


def club_activity_action(uid, epoch, club=None, week=None):
    with connect_db() as db:
        return clubs.activities(db, uid, epoch, club, week)


@dp.callback_query(F.data.startswith("clubact:"))
async def demo_club_activity(callback: CallbackQuery):
    tr = locale_strings(callback.from_user.language_code)
    match = re.fullmatch(r"clubact:([0-9a-f]{32}):(view|[a-z]+:[0-9]{4}-[0-9]{2}-[0-9]{2})", callback.data or "")
    if (os.getenv("LUMI_CLUBS_DEMO", "0") != "1" or not match
            or not callback.message or callback.message.chat.type != "private" or callback.message.chat.id != callback.from_user.id):
        await callback.answer(tr["activity_unavailable"], show_alert=True)
        return
    club, week = (None, None) if match[2] == "view" else match[2].split(":")
    if club is not None and club not in clubs.CLUBS:
        await callback.answer(tr["activity_unavailable"], show_alert=True)
        return
    result = await asyncio.to_thread(club_activity_action, callback.from_user.id, match[1], club, week)
    if result is None:
        await callback.answer(tr["reopen"], show_alert=True)
        return
    current, owned, completed = result
    lines = [tr["activity_title"], tr["private"]]
    rows = []
    for key in owned:
        lines.append(tr[key] + ": " + tr["task_" + key] + (tr["done"] if key in completed else ""))
        if key not in completed:
            rows.append([InlineKeyboardButton(text=tr["mark"] + tr[key], callback_data=f"clubact:{match[1]}:{key}:{current}")])
    if not owned:
        lines.append(tr["empty"])
    await callback.answer()
    await callback.message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None, parse_mode=None)


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext = None):
    # Fixed allowlist for Mini App navigation. No arbitrary commands or user IDs.
    route = re.fullmatch(r"/start(?:@\w+)?\s+lumi_(home|gift|invite|profile|safety|notifications)\s*", message.text or "")
    if route:
        key = route.group(1)
        if key == "home":
            if state is not None:
                await lumi_navigation(message, state)
            else:
                await mobile_home(message)
        else:
            handlers = {"gift": daily4_command, "invite": referral_command, "profile": my_profile,
                        "safety": safety4_command, "notifications": notifications_menu}
            await handlers[key](message)
        return
    close_active_chat(message.from_user.id)
    # Telegram deep link: /start ref_<numeric id>; a click alone gives no reward.
    text = message.text or ""
    match = re.fullmatch(r"/start(?:@\w+)?\s+ref_(\d{1,20})\s*", text)
    if match:
        try:
            inviter_id = int(match.group(1))
            with connect_db() as db:
                register_referral(db, message.from_user.id, inviter_id)
        except (ValueError, sqlite3.Error):
            logger.exception("Referral attribution failed")
    # Стартовая иллюстрация: не меняет анкету, питомца или базу данных.
    welcome_image = Path(__file__).resolve().parent / "welcome.png"
    if welcome_image.is_file():
        await message.answer_photo(
            photo=FSInputFile(welcome_image),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Start", callback_data="welcome:begin")]
            ]),
        )
    else:
        logger.warning("Нет welcome.png рядом с bot.py")
        await mobile_home(message)


@dp.callback_query(F.data == "welcome:begin")
async def welcome_begin(callback: CallbackQuery):
    await callback.answer()
    await mobile_home(callback.message)


# Universal navigation works even during registration and other FSM steps.
# Avoid a global "go back" to the preceding registration state: previous answers
# may no longer be valid. Exiting a wizard leaves saved profiles untouched.
@dp.message(F.text.in_({"🏠 Домой", "⬅️ Назад"}))
@dp.message(Command("home"))
async def lumi_navigation(message: Message, state: FSMContext):
    close_active_chat(message.from_user.id)
    if message.text == "⬅️ Назад":
        await state.clear()
        await mobile_home(message)
    else:
        await state.clear()
        await mobile_home(message)


@dp.callback_query(F.data == "nav:home")
async def inline_go_home(callback: CallbackQuery, state: FSMContext):
    close_active_chat(callback.from_user.id)
    await callback.answer()
    await state.clear()
    await mobile_home(callback.message)


@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    close_active_chat(message.from_user.id)
    await state.clear()
    await mobile_home(message)


@dp.message(Command("register"))
@dp.message(F.text == "💜 Создать анкету")
async def create_profile(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Registration.age)
    await clean_answer(message, "💜 Сколько тебе лет? Только 18+. Для отмены /cancel", reply_markup=menu)


@dp.message(Registration.age)
async def get_age(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit() or not 18 <= int(message.text) <= 100:
        await clean_answer(message, "Укажи возраст цифрами от 18 до 100.")
        return
    await state.update_data(age=int(message.text))
    await state.set_state(Registration.gender)
    await clean_answer(message, "Как ты себя определяешь?", reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Я девушка"), KeyboardButton(text="Я парень")]], resize_keyboard=True))


@dp.message(Registration.gender)
async def get_gender(message: Message, state: FSMContext):
    gender = {"Я девушка": "девушка", "Я парень": "парень"}.get(message.text)
    if not gender:
        await clean_answer(message, "Выбери кнопку «Я девушка» или «Я парень».")
        return
    await state.update_data(gender=gender)
    await state.set_state(Registration.seeking)
    await clean_answer(message, "Кого показывать?", reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Девушки"), KeyboardButton(text="Парни"), KeyboardButton(text="Всё равно")]], resize_keyboard=True))


@dp.message(Registration.seeking)
async def get_seeking(message: Message, state: FSMContext):
    seeking = {"Девушки": "девушка", "Парни": "парень", "Всё равно": "все", "Все равно": "все"}.get(message.text)
    if not seeking:
        await clean_answer(message, "Выбери один из вариантов: «Девушки», «Парни» или «Всё равно».")
        return
    await state.update_data(seeking=seeking)
    await state.set_state(Registration.city)
    await clean_answer(message, "Из какого ты города? 🌆", reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Москва")]], resize_keyboard=True))


@dp.message(Registration.city)
async def get_city(message: Message, state: FSMContext):
    if not message.text or not 2 <= len(message.text.strip()) <= 60:
        await clean_answer(message, "Введи название города (2–60 символов).")
        return
    if not profile_text_allowed(message.text, getattr(message, "entities", None)):
        await clean_answer(message, "🛡 Убери ссылки, подозрительные просьбы или скрытые управляющие символы из анкеты.")
        return
    await state.update_data(city=message.text.strip())
    await state.set_state(Registration.name)
    name = (message.from_user.first_name or "").strip()
    buttons = [[KeyboardButton(text=name)]] if 2 <= len(name) <= 40 else []
    await clean_answer(message, "Как мне тебя называть?", reply_markup=ReplyKeyboardMarkup(
        keyboard=buttons or [[KeyboardButton(text="Пример: Алекс")]], resize_keyboard=True))


@dp.message(Registration.name)
async def get_name(message: Message, state: FSMContext):
    if not message.text or not 2 <= len(message.text.strip()) <= 40:
        await clean_answer(message, "Введи имя от 2 до 40 символов.")
        return
    if not profile_text_allowed(message.text, getattr(message, "entities", None)):
        await clean_answer(message, "🛡 Убери ссылки, подозрительные просьбы или скрытые управляющие символы из анкеты.")
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(Registration.nickname)
    await clean_answer(message, "🎲 Хочешь смешной ник для анкеты? Нажми «Сгенерировать ник» или «Без ника». Можно также написать свой ник.", reply_markup=nickname_keyboard())


@dp.message(Registration.nickname)
async def registration_nickname(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if value == "🎲 Сгенерировать ник":
        nickname = random_nickname()
        await state.update_data(nickname=nickname)
        await clean_answer(message, f"🎲 {nickname}\n\nНравится? Нажми «Оставить ник» или сгенерируй ещё.", reply_markup=ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="Оставить ник"), KeyboardButton(text="🎲 Сгенерировать ник")],
            [KeyboardButton(text="Без ника")],
        ], resize_keyboard=True))
        return
    if value == "Оставить ник":
        data = await state.get_data()
        if not data.get("nickname"):
            await clean_answer(message, "Сначала сгенерируй ник.")
            return
    elif value == "Без ника":
        await state.update_data(nickname="")
    elif 2 <= len(value) <= 40:
        if not profile_text_allowed(value, getattr(message, "entities", None)):
            await clean_answer(message, "🛡 Выбери ник без ссылок и подозрительных просьб.")
            return
        await state.update_data(nickname=value)
    else:
        await clean_answer(message, "Напиши ник от 2 до 40 символов или выбери кнопку.")
        return
    await state.set_state(Registration.description)
    await clean_answer(message, "💫 Расскажи о себе и кого хочешь найти. Можно пропустить.",
                         reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Пропустить")]], resize_keyboard=True))


@dp.message(Registration.description)
async def get_description(message: Message, state: FSMContext):
    if not message.text or not message.text.strip() or len(message.text.strip()) > 300:
        await clean_answer(message, "Описание должно быть текстом до 300 символов.")
        return
    description = "Не указано" if message.text == "Пропустить" else message.text.strip()
    if not profile_text_allowed(message.text, getattr(message, "entities", None)):
        await clean_answer(message, "🛡 Убери ссылки, подозрительные просьбы или скрытые управляющие символы из анкеты.")
        return
    await state.update_data(interests=description)
    await state.set_state(Registration.photo)
    choices = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Фото из Telegram", callback_data="regmedia:telegram")],
        [InlineKeyboardButton(text="💜 Оставить текущее", callback_data="regmedia:keep")],
    ])
    await clean_answer(message, 
        "📸 Пришли своё фото или видео до 15 секунд. Лицо должно быть видно.\n"
        "Можно использовать фото из профиля Telegram или оставить прежнее.\n"
        "Чужие фотографии и изображения из интернета не подходят.\n/cancel — отмена.",
        reply_markup=choices,
    )


async def save_registration(message: Message, state: FSMContext, photo_id=None, video_id=None, user=None, identity=None):
    data = await state.get_data()
    user = user or message.from_user
    with connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        previous_media=db.execute("SELECT photo_id,video_id,media_unique_id FROM profiles WHERE user_id=?",(user.id,)).fetchone()
        if identity is None and previous_media and previous_media[:2] == (photo_id, video_id):
            identity = previous_media[2]
        if not media_available(db, user.id, identity, photo_id, video_id):
            duplicate = True
        else:
            duplicate = False

            db.execute("""
                INSERT INTO profiles
                (user_id, name, age, city, interests, photo_id, video_id, gender, seeking, username, nickname)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    name=excluded.name, age=excluded.age, city=excluded.city,
                    interests=excluded.interests, photo_id=excluded.photo_id,
                    video_id=excluded.video_id, nickname=excluded.nickname, gender=excluded.gender,
                    seeking=excluded.seeking, username=excluded.username
            """, (user.id, data["name"], data["age"],
                  data["city"], data["interests"], photo_id, video_id,
                  data["gender"], data["seeking"], user.username, data.get("nickname", "")))
            db.execute("UPDATE profiles SET media_unique_id=? WHERE user_id=?", (identity, user.id))
            # Сброс проверки только при реальной замене фото/видео.
            if previous_media is None or previous_media[:2] != (photo_id, video_id):
                db.execute("UPDATE profile_extras SET verified=0,verification_status='none' WHERE user_id=?",(user.id,))
                db.execute("DELETE FROM verification_requests WHERE user_id=?",(user.id,))
    if duplicate:
        await message.answer("Это медиа уже используется в другой анкете. Отправь другое фото или видео.")
        return
    with connect_db() as db:
        referral_result = confirm_registration(db, user.id)
    if referral_result:
        inviter_id, count, newly_unlocked = referral_result
        try:
            if newly_unlocked:
                await message.bot.send_message(inviter_id,
                    "🎉 <b>Трое друзей создали анкеты!</b>\n\n"
                    "Тебе открыта эксклюзивная рамка <b>«💜 Сердце LUMI»</b> "
                    "— она отображается в карточке героя и твоей анкете.\n"
                    "Рамка косметическая и не влияет на битвы.", parse_mode="HTML")
            else:
                await message.bot.send_message(inviter_id,
                    f"💜 Друг создал анкету! Приглашений: <b>{count}/{REFERRAL_GOAL}</b>.", parse_mode="HTML")
        except TelegramAPIError:
            logger.info("Cannot notify referral inviter %s", inviter_id)
    founder_serial, is_new_founder = claim_founder(user.id)
    await state.clear()
    if is_new_founder:
        await message.answer(
            f"🎉 <b>Анкета сохранена!</b>\n\n"
            f"🏅 Ты стал участником события <b>«Первые 100 сердец LUMI»</b>!\n"
            f"Твой постоянный номер: <b>№{founder_serial}</b>. Значок уже в анкете.\n\n"
            "⚔️ Выбирай героя и знакомься!",
            reply_markup=ReplyKeyboardRemove(), parse_mode="HTML",
        )
    else:
        await message.answer("🎉 <b>Анкета сохранена!</b>\n\n⚔️ Выбери героя и знакомься!", reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")
    await show_quick_menu(message, user_id=user.id)


@dp.callback_query(Registration.photo, F.data.startswith("regmedia:"))
async def registration_media_choice(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":", 1)[1]
    photo_id, video_id = None, None
    identity = None
    if action == "keep":
        with connect_db() as db:
            row = db.execute("SELECT photo_id, video_id FROM profiles WHERE user_id=?",
                             (callback.from_user.id,)).fetchone()
        if row:
            photo_id, video_id = row
        if not photo_id and not video_id:
            await callback.answer("Пока нет сохранённого фото или видео", show_alert=True)
            return
    elif action == "telegram":
        try:
            photos = await callback.bot.get_user_profile_photos(callback.from_user.id, limit=1)
            if photos.total_count and photos.photos:
                if media_size_allowed(photos.photos[0][-1]):
                    photo_id = photos.photos[0][-1].file_id
                    identity = media_identity(photos.photos[0][-1])
        except TelegramAPIError:
            logger.info("Фото профиля Telegram недоступно для %s", callback.from_user.id)
        if not photo_id:
            await callback.answer("Фото Telegram недоступно. Пришли его вручную.", show_alert=True)
            return
    else:
        await callback.answer("Неизвестная кнопка")
        return
    await callback.answer()
    await save_registration(callback.message, state, photo_id, video_id, user=callback.from_user, identity=identity)


@dp.message(Registration.photo)
async def get_photo(message: Message, state: FSMContext):
    if not media_size_allowed(message.photo[-1] if message.photo else message.video):
        await message.answer("Файл слишком большой. Отправь медиа до 19 МБ.")
        return
    if message.photo:
        await save_registration(message, state, photo_id=message.photo[-1].file_id, identity=media_identity(message.photo[-1]))
    elif message.video and message.video.duration <= 15:
        await save_registration(message, state, video_id=message.video.file_id, identity=media_identity(message.video))
    elif message.video:
        await message.answer("Видео должно быть не длиннее 15 секунд.")
    else:
        await message.answer("Пришли фото или видео до 15 секунд, либо выбери кнопку выше.")




@dp.message(Command("nick"))
async def nickname_command(message: Message):
    if not profile_of(message.from_user.id):
        await message.answer("Сначала создай анкету 💜", reply_markup=menu)
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Новый случайный ник", callback_data="nick:roll")],
        [InlineKeyboardButton(text="🗑 Убрать ник", callback_data="nick:clear")],
    ])
    current = nickname_of(message.from_user.id) or "пока нет"
    await message.answer(f"🎲 Твой ник: {current}", reply_markup=keyboard)


@dp.callback_query(F.data.startswith("nick:"))
async def nickname_action(callback: CallbackQuery):
    if not profile_of(callback.from_user.id):
        await callback.answer("Сначала создай анкету", show_alert=True)
        return
    action = callback.data.split(":", 1)[1]
    if action == "roll":
        nick = random_nickname()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💜 Сохранить", callback_data=f"nicksave:{nick}")],
            [InlineKeyboardButton(text="🎲 Ещё вариант", callback_data="nick:roll")],
        ])
        await callback.message.answer(f"🎲 {nick}", reply_markup=keyboard)
    elif action == "clear":
        with connect_db() as db:
            db.execute("UPDATE profiles SET nickname='' WHERE user_id=?", (callback.from_user.id,))
        await callback.message.answer("Ник удалён из анкеты 💜")
    await callback.answer()


@dp.callback_query(F.data.startswith("nicksave:"))
async def nickname_save(callback: CallbackQuery):
    nick = callback.data.split(":", 1)[1]
    if not profile_of(callback.from_user.id) or len(nick) > 40:
        await callback.answer("Анкета недоступна", show_alert=True)
        return
    with connect_db() as db:
        db.execute("UPDATE profiles SET nickname=? WHERE user_id=?", (nick, callback.from_user.id))
    await callback.answer("Ник сохранён 💜")
    await callback.message.answer(f"🎲 Ник «{nick}» теперь виден в твоей анкете!")


@dp.message(Command("reset_skips"))
async def reset_skips(message: Message):
    """Повторно показывать пропущенные анкеты, но не лайкнутые."""
    with connect_db() as db:
        result = db.execute("DELETE FROM reactions WHERE from_user=? AND liked=0", (message.from_user.id,))
    DEFERRED.pop(message.from_user.id, None)
    SEEN_THIS_ROUND.pop(message.from_user.id, None)
    await message.answer(f"История пропусков очищена ({result.rowcount}). Анкеты и без этого повторяются автоматически.", reply_markup=quick_menu)

@dp.message(Command("myprofile"))
@dp.message(F.text == "👤 Мой профиль")
async def my_profile(message: Message):
    logger.info("Запрошен профиль пользователя %s", message.from_user.id)
    profile = profile_of(message.from_user.id)
    if not profile:
        await message.answer("💜 У тебя пока нет анкеты.", reply_markup=menu)
        return
    await show_quick_menu(message)


async def search_welcome(message: Message, user_id: int):
    """Show a one-time greeting when entering browse mode, never for each swipe."""
    with connect_db() as db:
        row = db.execute("SELECT gender FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        return
    gender = (row[0] or "").strip().casefold()
    if gender == "девушка":
        await message.answer("💜 Лови момент — возможно, новая симпатия уже рядом!")
    elif gender == "парень":
        await message.answer("💜 Лови момент — возможно, новая симпатия уже рядом!")


@dp.message(F.text == "❤️ Смотреть анкеты")
async def browse(message: Message):
    close_active_chat(message.from_user.id)
    await clean_answer(message, "❤️ Анкеты", reply_markup=ReplyKeyboardRemove())
    await show_next(message, message.from_user.id)


def teaser_is_safe(db, admirer_id: int, recipient_id: int) -> bool:
    """Показываем анонимный тизер только для реального невзаимного лайка."""
    return bool(
        admirer_id != recipient_id
        and db.execute("SELECT 1 FROM profiles WHERE user_id=?", (recipient_id,)).fetchone()
        and is_discoverable(db, admirer_id)
        and db.execute("SELECT 1 FROM reactions WHERE from_user=? AND to_user=? AND liked=1",
                       (admirer_id, recipient_id)).fetchone()
        and not db.execute("SELECT 1 FROM reactions WHERE from_user=? AND to_user=? AND liked=1",
                           (recipient_id, admirer_id)).fetchone()
        and not db.execute("SELECT 1 FROM blocks WHERE (user_id=? AND blocked_id=?) OR (user_id=? AND blocked_id=?)",
                           (admirer_id, recipient_id, recipient_id, admirer_id)).fetchone()
    )


def make_anonymous_teaser(photo_bytes: bytes) -> bytes:
    """Растеризуем и размываем САМ файл: никакого Telegram file_id оригинала."""
    from PIL import Image, ImageOps, ImageFilter, ImageDraw
    import io
    with Image.open(io.BytesIO(photo_bytes)) as original:
        if original.width * original.height > 22_000_000:
            raise ValueError("Слишком большое исходное изображение")
        clean = ImageOps.fit(original.convert("RGB"), (420, 520))
    # Очень низкое разрешение + сильный blur: поза/силуэт слегка видны,
    # мелкие особенности лица не различимы.
    clean = clean.resize((21, 26), Image.Resampling.BILINEAR)
    clean = clean.resize((420, 520), Image.Resampling.BICUBIC)
    clean = clean.filter(ImageFilter.GaussianBlur(radius=24))
    veil = Image.new("RGB", clean.size, (95, 55, 135))
    clean = Image.blend(clean, veil, .04)
    stream = io.BytesIO()
    clean.save(stream, format="JPEG", quality=83, optimize=True)  # EXIF не переносим
    return stream.getvalue()


async def send_like_teaser(bot: Bot, admirer_id: int, recipient_id: int):
    """Уведомление — только в личный чат и максимум раз в 24 ч."""
    now = int(time.time())
    with connect_db() as db:
        if not teaser_is_safe(db, admirer_id, recipient_id) or not can_notify(db, recipient_id, 'likes'):
            return
        # Атомарное ограничение, в том числе при параллельных лайках.
        changed = db.execute("INSERT INTO lumi_like_teasers(user_id,last_sent) VALUES(?,?) "
                             "ON CONFLICT(user_id) DO UPDATE SET last_sent=excluded.last_sent "
                             "WHERE lumi_like_teasers.last_sent <= ?",
                             (recipient_id, now, now - TEASER_COOLDOWN_SECONDS)).rowcount
        if changed != 1:
            return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👀 Кто это?", callback_data="teaser:reveal")],
        [InlineKeyboardButton(text="❤️ Смотреть анкеты", callback_data="ux:browse")],
    ])
    # Privacy by default: even blurred profile photos may identify someone.
    await bot.send_message(recipient_id, "💌 <b>Новая симпатия</b>\n\nМожет, познакомитесь? 💜",
                           reply_markup=keyboard, parse_mode="HTML", protect_content=True)


@dp.callback_query(F.data == "teaser:reveal")
async def reveal_teaser(callback: CallbackQuery):
    uid = callback.from_user.id
    with connect_db() as db:
        rows = db.execute("SELECT from_user FROM reactions WHERE to_user=? AND liked=1 ORDER BY from_user DESC", (uid,)).fetchall()
        has_like = any(teaser_is_safe(db, admirer, uid) for (admirer,) in rows)
        active = premium_active(db, uid)
    await callback.answer()
    if not has_like:
        await callback.message.answer("💜 Эта симпатия больше недоступна. Продолжай знакомиться!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❤️ Смотреть анкеты", callback_data="ux:browse")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")],
            ]))
        return
    if active:
        # Уже оплатившему человеку не продаём повторно подписку.
        await premium_choice_direct_likes(callback)
        return
    await callback.message.answer(
        "👀 <b>Интрига раскрывается…</b>\n\n"
        "Этот человек действительно поставил тебе лайк. 💜\n\n"
        "С <b>LUMI Premium</b> можно узнать, кто это, не дожидаясь взаимности.\n"
        "А можно продолжить искать совпадение бесплатно.\n\n"
        "⭐ <b>199 Stars / 30 дней</b> · без автопродления",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Открыть с Premium", callback_data="premium:activate")],
            [InlineKeyboardButton(text="❤️ Искать бесплатно", callback_data="ux:browse")],
            [InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")],
        ]),
    )


async def premium_choice_direct_likes(callback: CallbackQuery):
    """Показывает проверяемый список только действующему Premium-подписчику."""
    uid = callback.from_user.id
    with connect_db() as db:
        if not premium_active(db, uid):
            return
        rows = db.execute("SELECT p.user_id,p.name,p.age FROM reactions r "
                          "JOIN profiles p ON p.user_id=r.from_user "
                          "WHERE r.to_user=? AND r.liked=1 ORDER BY p.user_id DESC LIMIT 60", (uid,)).fetchall()
        visible = [(name, age) for pid, name, age in rows if teaser_is_safe(db, pid, uid)][:10]
    message = "👀 <b>Твои тайные симпатии</b>\n\n"
    message += "\n".join(f"• {ui_safe(name, 45)}, {age}" for name, age in visible) if visible else "Доступных симпатий пока нет."
    # Для просмотра карточки ниже нужен PID. Повторная проверка при нажатии обязательна.
    with connect_db() as db:
        choices = [(pid, name) for pid, name, age in rows if teaser_is_safe(db, pid, uid)][:10]
    buttons = [[InlineKeyboardButton(text=f"👤 {name[:28]}", callback_data=f"premium:view:{pid}")]
               for pid, name in choices]
    buttons.append([InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")])
    await callback.message.answer(message, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data.startswith("premium:view:"))
async def premium_open_liker(callback: CallbackQuery):
    try:
        pid = int(callback.data.rsplit(":",1)[1])
    except (ValueError, IndexError):
        await callback.answer("Недействительная кнопка", show_alert=True)
        return
    uid = callback.from_user.id
    with connect_db() as db:
        allowed = premium_active(db, uid) and teaser_is_safe(db, pid, uid)
        if allowed:
            mark_profile_view(db, uid, pid)
    if not allowed:
        await callback.answer("Анкета недоступна", show_alert=True)
        return
    profile = profile_of(pid)
    if not profile:
        await callback.answer("Анкета удалена", show_alert=True)
        return
    await callback.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❤️ Нравится", callback_data=f"like:{pid}")],
        [InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")],
    ])
    await send_profile(callback.message, profile, keyboard=kb, user_id=pid)


def record_reaction(db, user_id, target_id, liked):
    """Promote a previous skip to a like; never downgrade an existing like."""
    return db.execute(
        "INSERT INTO reactions(from_user,to_user,liked) VALUES(?,?,?) "
        "ON CONFLICT(from_user,to_user) DO UPDATE SET liked=1 "
        "WHERE reactions.liked=0 AND excluded.liked=1",
        (user_id, target_id, int(liked)),
    ).rowcount == 1


def new_match_keyboard(peer_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Начать разговор", callback_data=f"hello:menu:{peer_id}")],
        [InlineKeyboardButton(text="💌 Написать через LUMI", callback_data=f"chat:{peer_id}")],
        [InlineKeyboardButton(text="🎲 Игра для двоих", callback_data=f"games:{peer_id}")],
        [game_button()],
        [InlineKeyboardButton(text="⚔️ Битва героев", callback_data=f"arena:challenge:{peer_id}")],
        [InlineKeyboardButton(text="💞 Мои совпадения", callback_data="ux:matches")],
    ])


def commit_profile_reaction(user_id: int, target_id: int, action: str):
    if user_id == target_id or not profile_of(user_id) or not profile_of(target_id):
        return {"ok": False, "error": "Анкета недоступна"}
    with connect_db() as db:
        if not can_access_profile(db, user_id, target_id):
            return {"ok": False, "error": "Анкета недоступна или ссылка устарела"}
    new_like = False
    with connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        if not can_access_profile(db, user_id, target_id):
            return {"ok": False, "error": "Анкета недоступна или ссылка устарела"}
        if action == "later":
            DEFERRED.setdefault(user_id, RecentSet(1000)).add(target_id)
        elif action == "block":
            DEFERRED.get(user_id, set()).discard(target_id)
            isolate_pair(db, user_id, target_id)
        elif action == "report":
            DEFERRED.get(user_id, set()).discard(target_id)
            report_id = record_report_once(db, user_id, target_id)
            if report_id is not None:
                admin_event(db, 'report', report_id)
            isolate_pair(db, user_id, target_id)
        else:
            if action=="super":
                day=datetime.now(timezone.utc).date().isoformat()
                cap=5 if premium_active(db,user_id) else 1
                previous=db.execute("SELECT liked FROM reactions WHERE from_user=? AND to_user=?",(user_id,target_id)).fetchone()
                if previous is None or previous[0] == 0:
                    db.execute("INSERT OR IGNORE INTO premium_superlikes(user_id,day,used) VALUES(?,?,0)",(user_id,day))
                    used=db.execute("UPDATE premium_superlikes SET used=used+1 WHERE user_id=? AND day=? AND used<?",
                                    (user_id,day,cap))
                    if used.rowcount!=1:
                        return {"ok": False, "error": "Суперлайки на сегодня закончились. Открой /premium"}
            blocked = db.execute("""
                SELECT 1 FROM blocks
                WHERE (user_id=? AND blocked_id=?)
                   OR (user_id=? AND blocked_id=?)
            """, (user_id, target_id, target_id, user_id)).fetchone()
            if blocked:
                return {"ok": False, "error": "Анкета недоступна"}
            changed = record_reaction(db, user_id, target_id, action in {"like", "super", "letter"})
            new_like = action in {"like", "super", "letter"} and changed
            if action == "skip" and changed:
                db.execute("INSERT INTO premium_skips(user_id,target_id,created_at) VALUES(?,?,?) "
                           "ON CONFLICT(user_id) DO UPDATE SET target_id=excluded.target_id,created_at=excluded.created_at",
                           (user_id,target_id,int(time.time())))
        mutual = new_like and db.execute("""
            SELECT 1 FROM reactions
            WHERE from_user=? AND to_user=? AND liked=1
        """, (target_id, user_id)).fetchone() is not None
    ACTIVE_BROWSE_TARGET.pop(user_id, None)
    return {"ok": True, "new_like": new_like, "mutual": mutual}


@dp.callback_query(F.data.startswith(("like:", "super:", "letter:", "skip:", "later:", "block:", "report:")))
async def reaction(callback: CallbackQuery):
    try:
        action, raw_id = callback.data.split(":", 1)
        target_id = int(raw_id)
    except (ValueError, AttributeError):
        await callback.answer("Некорректная кнопка", show_alert=True)
        return
    user_id = callback.from_user.id
    result = commit_profile_reaction(user_id, target_id, action)
    if not result.get("ok"):
        await callback.answer(result["error"], show_alert=True)
        return
    new_like = result["new_like"]
    mutual = result["mutual"]
    await callback.answer("Отложено 💜" if action == "later" else "Готово 💜")
    if new_like and not mutual:
        with connect_db() as db:
            notify_allowed = can_notify(db,target_id,'likes')
        if notify_allowed and len(_teaser_tasks) < 32:
            task=asyncio.create_task(send_like_teaser(callback.bot,user_id,target_id))
            _teaser_tasks.add(task)
            task.add_done_callback(_teaser_finished)
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        if mutual:
            await callback.message.answer(
                "💞 <b>Это взаимно!</b>\n\nВы понравились друг другу. Начните разговор или сыграйте вместе 💜",
                parse_mode="HTML", reply_markup=new_match_keyboard(target_id)
            )
            try:
                with connect_db() as db:
                    allow_match_notice=can_notify(db,target_id,'matches')
                if allow_match_notice:
                    await callback.bot.send_message(
                        target_id,
                        "💞 <b>Это взаимно!</b>\n\nВы понравились друг другу. Начните разговор или сыграйте вместе 💜",
                        parse_mode="HTML", reply_markup=new_match_keyboard(user_id))
            except TelegramAPIError:
                logger.info("Не удалось уведомить пользователя %s", target_id)
        elif action == "report":
            await callback.message.answer("Жалоба сохранена. Анкета скрыта.")
        elif action == "block":
            await callback.message.answer("Анкета заблокирована.")
        await show_next(callback.message, user_id)


@dp.message(F.text.in_({"❤️ Нравится", "👎 Пропустить"}), lambda message: message.from_user.id in ACTIVE_BROWSE_TARGET)
async def reaction_from_bottom_bar(message: Message):
    user_id = message.from_user.id
    active = ACTIVE_BROWSE_TARGET.get(user_id)
    if not active:
        await message.answer("Открой раздел анкет, чтобы выбрать симпатию 💜", reply_markup=ReplyKeyboardRemove())
        return
    target_id, panel_id = active
    if message.message_id <= panel_id:
        return
    ACTIVE_BROWSE_TARGET.pop(user_id, None)
    action = "like" if message.text == "❤️ Нравится" else "skip"
    result = commit_profile_reaction(user_id, target_id, action)
    if not result.get("ok"):
        await message.answer(result["error"], reply_markup=ReplyKeyboardRemove())
        return
    new_like = result["new_like"]
    mutual = result["mutual"]
    if new_like and not mutual:
        with connect_db() as db:
            notify_allowed = can_notify(db, target_id, 'likes')
        if notify_allowed and len(_teaser_tasks) < 32:
            task = asyncio.create_task(send_like_teaser(message.bot, user_id, target_id))
            _teaser_tasks.add(task)
            task.add_done_callback(_teaser_finished)
    if mutual:
        await message.answer(
            "💞 <b>Это взаимно!</b>\n\nВы понравились друг другу. Начните разговор или сыграйте вместе 💜",
            parse_mode="HTML", reply_markup=new_match_keyboard(target_id)
        )
        try:
            with connect_db() as db:
                allow_match_notice = can_notify(db, target_id, 'matches')
            if allow_match_notice:
                await message.bot.send_message(
                    target_id,
                    "💞 <b>Это взаимно!</b>\n\nВы понравились друг другу. Начните разговор или сыграйте вместе 💜",
                    parse_mode="HTML", reply_markup=new_match_keyboard(user_id),
                )
        except TelegramAPIError:
            logger.info("Не удалось уведомить пользователя %s", target_id)
    await show_next(message, user_id)


def is_match(db, a, b):
    if a == b:
        return False
    return db.execute("""
        SELECT 1 FROM reactions r JOIN reactions s
          ON s.from_user=r.to_user AND s.to_user=r.from_user AND s.liked=1
        JOIN profiles p ON p.user_id=r.from_user
        JOIN profiles q ON q.user_id=r.to_user
        WHERE r.from_user=? AND r.to_user=? AND r.liked=1
          AND NOT EXISTS (SELECT 1 FROM blocks x WHERE
             (x.user_id=? AND x.blocked_id=?) OR
             (x.user_id=? AND x.blocked_id=?))
    """, (a,b,a,b,b,a)).fetchone() is not None


def match_keyboard(peer_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Подсказка для первого сообщения", callback_data=f"hello:menu:{peer_id}")],
        [InlineKeyboardButton(text="💬 Написать через LUMI", callback_data=f"chat:{peer_id}")],
        [InlineKeyboardButton(text="🔗 Обменяться Telegram", callback_data=f"exchange:{peer_id}")],
        [InlineKeyboardButton(text="⚔️ Битва героев", callback_data=f"arena:challenge:{peer_id}")],
        [InlineKeyboardButton(text="Начать разговор", callback_data=f"ice:{peer_id}"),
         InlineKeyboardButton(text="Играть вдвоём", callback_data=f"games:{peer_id}")],
        [game_button()],
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"blockmatch:{peer_id}")],
    ])


# LUMI MOBILE: одна страница совпадений вместо десятков сообщений.
MATCHES_PAGE_SIZE = 5


def matches_page_data(user_id: int, page: int = 0):
    with connect_db() as db:
        matches_rows = db.execute("""
            SELECT p.user_id, p.name, p.age, p.city
            FROM reactions a JOIN reactions b
              ON b.from_user=a.to_user AND b.to_user=a.from_user AND b.liked=1
            JOIN profiles p ON p.user_id=a.to_user
            WHERE a.from_user=? AND a.liked=1
            ORDER BY p.name, p.user_id
        """, (user_id,)).fetchall()
        matches_rows = [r for r in matches_rows if is_match(db, user_id, r[0])]
    total = len(matches_rows)
    page = max(0, min(page, max(0, (total - 1) // MATCHES_PAGE_SIZE)))
    return matches_rows[page * MATCHES_PAGE_SIZE:(page + 1) * MATCHES_PAGE_SIZE], total, page


def matches_page_keyboard(rows, total, page):
    buttons = [[InlineKeyboardButton(text=f"💜 {i + page * MATCHES_PAGE_SIZE + 1}. {name[:27]}",
                                     callback_data=f"matches:open:{uid}")]
               for i, (uid, name, age, city) in enumerate(rows)]
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"matches:page:{page-1}"))
    if (page + 1) * MATCHES_PAGE_SIZE < total:
        navigation.append(InlineKeyboardButton(text="Далее ▶️", callback_data=f"matches:page:{page+1}"))
    if navigation:
        buttons.append(navigation)
    buttons.append([InlineKeyboardButton(text="❤️ Анкеты", callback_data="ux:browse"), InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def show_matches_page(message, user_id: int, page: int = 0):
    rows, total, page = matches_page_data(user_id, page)
    if not rows:
        await message.answer("💞 <b>Совпадений пока нет.</b>\n\nСмотри анкеты: взаимная симпатия появится здесь 💜", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❤️ Смотреть анкеты", callback_data="ux:browse")], [InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")]]))
        return
    lines = [f"💞 <b>МОИ СОВПАДЕНИЯ</b>  ·  {total}", "", "Нажми на человека, чтобы открыть действия.", ""]
    for i, (_, name, age, city) in enumerate(rows, 1 + page * MATCHES_PAGE_SIZE):
        lines.append(f"<b>{i}. {ui_safe(name, 34)}, {age}</b>  ·  📍 {ui_safe(city, 45)}")
    lines += ["", f"<i>Страница {page + 1} из {(total + MATCHES_PAGE_SIZE-1) // MATCHES_PAGE_SIZE}</i>"]
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=matches_page_keyboard(rows, total, page))


@dp.message(F.text == "💞 Мои совпадения")
async def matches(message: Message):
    close_active_chat(message.from_user.id)
    if not profile_of(message.from_user.id):
        await message.answer("Сначала создай анкету 💜", reply_markup=menu)
        return
    await show_matches_page(message, message.from_user.id)


@dp.callback_query(F.data.startswith("matches:page:"))
async def matches_next_page(callback: CallbackQuery):
    await callback.answer()
    try:
        page = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        page = 0
    await show_matches_page(callback.message, callback.from_user.id, page)


@dp.callback_query(F.data.startswith("matches:open:"))
async def matches_open_person(callback: CallbackQuery):
    try:
        peer = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Неверная кнопка", show_alert=True)
        return
    with connect_db() as db:
        if not is_match(db, callback.from_user.id, peer):
            await callback.answer("Совпадение больше недоступно", show_alert=True)
            return
        name, age, city = db.execute("SELECT name, age, city FROM profiles WHERE user_id=?", (peer,)).fetchone()
    await callback.answer()
    await callback.message.answer(f"💜 <b>{ui_safe(name, 40)}, {age}</b>\n📍 {ui_safe(city, 45)}\n\nВыбери, что сделать дальше:",
                                  parse_mode="HTML", reply_markup=match_keyboard(peer))


def close_active_chat(uid):
    with connect_db() as db:
        db.execute("DELETE FROM active_chats WHERE user_id=?", (uid,))


def chat_reply_keyboard(peer):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить", callback_data=f"chat:{peer}")],
        [InlineKeyboardButton(text="💞 Совпадения", callback_data="ux:matches"),
         InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"blockmatch:{peer}")],
    ])


def chat_controls():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏹ Завершить переписку", callback_data="chatstop:now")],
        [InlineKeyboardButton(text="💞 Совпадения", callback_data="ux:matches")],
    ])


@dp.callback_query(F.data == "chatstop:now")
async def stop_chat_button(callback: CallbackQuery):
    close_active_chat(callback.from_user.id)
    await callback.answer("Переписка закрыта")
    await show_matches_page(callback.message, callback.from_user.id)


@dp.callback_query(F.data.startswith("chat:"))
async def begin_chat(callback: CallbackQuery, state: FSMContext):
    try:
        peer_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная кнопка", show_alert=True)
        return
    uid=callback.from_user.id
    with connect_db() as db:
        if not is_match(db,uid,peer_id):
            await callback.answer("Совпадение недоступно",show_alert=True)
            return
        db.execute("INSERT INTO active_chats(user_id,peer_id) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET peer_id=excluded.peer_id",(uid,peer_id))
        peer=db.execute("SELECT name FROM profiles WHERE user_id=?",(peer_id,)).fetchone()[0]
    await state.clear()
    await callback.answer()
    await callback.message.answer(f"Ты пишешь {peer} через LUMI. Можно отправлять текст, фото и голосовые. Для выхода — /stop. Не отправляй личные данные незнакомым людям.",reply_markup=chat_controls())


@dp.message(Command("stop"))
async def stop_chat(message: Message):
    with connect_db() as db:
        db.execute("DELETE FROM active_chats WHERE user_id=?",(message.from_user.id,))
    await message.answer("💜 Ты вышел из переписки. Для нового диалога открой «💞 Мои совпадения».",reply_markup=menu)


def contact_link(user_id: int, username: str | None) -> str:
    # Telegram may restrict opening numeric-ID links based on privacy settings.
    if username:
        return f"https://t.me/{username}"
    return f"tg://user?id={user_id}"


@dp.callback_query(F.data.startswith("exchange:"))
async def exchange_request(callback: CallbackQuery):
    try:
        peer_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная кнопка", show_alert=True)
        return
    uid = callback.from_user.id
    with connect_db() as db:
        if not is_match(db, uid, peer_id):
            await callback.answer("Совпадение недоступно", show_alert=True)
            return
        db.execute("UPDATE profiles SET username=? WHERE user_id=?",
                   (callback.from_user.username, uid))
        name = db.execute("SELECT name FROM profiles WHERE user_id=?", (uid,)).fetchone()[0]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Открыть мой профиль", callback_data=f"acceptcontact:{uid}")],
        [InlineKeyboardButton(text="🔒 Не открывать", callback_data=f"rejectcontact:{uid}")],
    ])
    try:
        await callback.bot.send_message(
            peer_id,
            f"🔗 {name} предлагает обменяться ссылками на Telegram-профили. "
            "Если согласишься, каждый получит ссылку на профиль другого. "
            "Это может раскрыть твой Telegram-аккаунт. "
            "Если нет @username, ссылка может не открываться из-за настроек Telegram. "
            "Можно отказаться и продолжить общение внутри LUMI.",
            reply_markup=keyboard,
        )
    except TelegramAPIError:
        await callback.answer("Не удалось доставить запрос", show_alert=True)
        return
    with connect_db() as db:
        if not is_match(db, uid, peer_id):
            await callback.answer("Совпадение больше недоступно", show_alert=True)
            return
        db.execute("""
            INSERT INTO contact_requests(requester_id, recipient_id, status)
            VALUES (?, ?, 'pending')
            ON CONFLICT(requester_id, recipient_id) DO UPDATE SET status='pending'
        """, (uid, peer_id))
    await callback.answer("Запрос отправлен 💜")
    if callback.message:
        await callback.message.answer("🔗 Запрос отправлен. Ждём согласия собеседника.")


@dp.callback_query(F.data.startswith(("acceptcontact:", "rejectcontact:")))
async def decide_exchange(callback: CallbackQuery):
    try:
        action, raw = callback.data.split(":", 1)
        requester = int(raw)
    except (ValueError, AttributeError):
        await callback.answer("Некорректная кнопка", show_alert=True)
        return
    uid = callback.from_user.id
    with connect_db() as db:
        row = db.execute("""
            SELECT status FROM contact_requests
            WHERE requester_id=? AND recipient_id=?
        """, (requester, uid)).fetchone()
        if not row or row[0] != 'pending' or not is_match(db, uid, requester):
            await callback.answer("Запрос уже обработан или недоступен", show_alert=True)
            return
        approved = action == 'acceptcontact'
        db.execute("""
            UPDATE contact_requests SET status=?
            WHERE requester_id=? AND recipient_id=?
        """, ('accepted' if approved else 'rejected', requester, uid))
        if approved:
            db.execute("UPDATE profiles SET username=? WHERE user_id=?",
                       (callback.from_user.username, uid))
            stored = db.execute("SELECT username FROM profiles WHERE user_id=?",
                                (requester,)).fetchone()
            requester_username = stored[0] if stored else None
    await callback.answer("Готово 💜")
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
    if not approved:
        if callback.message:
            await callback.message.answer("🔒 Обмен отклонён. Переписка через LUMI доступна.")
        try:
            await callback.bot.send_message(requester, "🔒 Собеседник отказался от обмена контактами.")
        except TelegramAPIError:
            pass
        return
    warning = ("\nЕсли ссылка не открывается, настройки Telegram не позволяют "
               "перейти к профилю. Продолжайте переписку через LUMI.")
    if callback.message:
        await callback.message.answer(
            f"💞 Вы оба согласились! Telegram собеседника: "
            f"{contact_link(requester, requester_username)}" + warning
        )
    try:
        await callback.bot.send_message(
            requester,
            f"💞 Вы оба согласились! Telegram собеседника: "
            f"{contact_link(uid, callback.from_user.username)}" + warning,
        )
    except TelegramAPIError:
        logger.warning("Не удалось отправить контакт %s", requester)


@dp.callback_query(F.data.startswith("blockmatch:"))
async def block_match(callback: CallbackQuery):
    try:
        peer=int(callback.data.split(":")[1])
    except (ValueError,IndexError):
        await callback.answer("Некорректная кнопка",show_alert=True)
        return
    uid=callback.from_user.id
    with connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        allowed = is_match(db, uid, peer)
        if allowed:
            isolate_pair(db, uid, peer)
    if not allowed:
        await callback.answer("Совпадение недоступно", show_alert=True)
        return
    await callback.answer("Заблокировано")
    await callback.message.answer("🚫 Пользователь заблокирован. Переписка остановлена.")


@dp.message(F.text == "🔎 Настройки поиска")
@dp.message(F.text == "🔎 Поиск")
async def search_settings(message: Message, state: FSMContext):
    if not profile_of(message.from_user.id):
        await clean_answer(message, "Сначала создай анкету 💜", reply_markup=menu)
        return
    await state.set_state(SearchSettings.age_min)
    await clean_answer(message, "🔎 Минимальный возраст для поиска? (18–100) /cancel")


@dp.message(SearchSettings.age_min)
async def search_min(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit() or not 18 <= int(message.text) <= 100:
        await clean_answer(message, "Введи число от 18 до 100.")
        return
    await state.update_data(age_min=int(message.text))
    await state.set_state(SearchSettings.age_max)
    await clean_answer(message, "Максимальный возраст для поиска? (18–100)")


@dp.message(SearchSettings.age_max)
async def search_max(message: Message, state: FSMContext):
    data = await state.get_data()
    if (not message.text or not message.text.isdigit()
            or not data["age_min"] <= int(message.text) <= 100):
        await clean_answer(message, f"Введи число от {data['age_min']} до 100.")
        return
    await state.update_data(age_max=int(message.text))
    await state.set_state(SearchSettings.city)
    await clean_answer(message, "Город для поиска? Напиши город или «Все».")


@dp.message(SearchSettings.city)
async def search_city(message: Message, state: FSMContext):
    if not message.text or len(message.text.strip()) > 60:
        await clean_answer(message, "Напиши название города или «Все».")
        return
    data = await state.get_data()
    city = "" if message.text.strip().casefold() == "все" else message.text.strip()
    with connect_db() as db:
        db.execute("""
            INSERT INTO search_settings (user_id, age_min, age_max, city)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                age_min=excluded.age_min, age_max=excluded.age_max, city=excluded.city
        """, (message.from_user.id, data["age_min"], data["age_max"], city))
    await state.clear()
    await clean_answer(message, "🔎 Фильтры сохранены! Теперь нажми «❤️ Смотреть анкеты».", reply_markup=menu)


@dp.message(F.text == "🔗 Контакт")
async def contact_settings(message: Message):
    if not profile_of(message.from_user.id):
        await message.answer("Сначала создай анкету 💜", reply_markup=menu)
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Разрешить", callback_data="contact:yes")],
        [InlineKeyboardButton(text="🔒 Запретить", callback_data="contact:no")],
    ])
    await message.answer(
        "🔗 Здесь можно сохранить предпочтение по обмену Telegram-контактами. "
        "Даже при разрешении ссылка не передаётся автоматически: "
        "потребуется отдельное согласие после совпадения. "
        "Без публичного @username Telegram может не открыть ссылку на профиль.",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data.startswith("contact:"))
async def set_contact(callback: CallbackQuery):
    permitted = callback.data == "contact:yes"
    with connect_db() as db:
        db.execute("UPDATE profiles SET share_contact=?, username=? WHERE user_id=?",
                   (int(permitted), callback.from_user.username, callback.from_user.id))
    await callback.answer("Настройка сохранена 💜")
    if callback.message:
        await callback.message.answer(
            "🔗 Предпочтение сохранено. Контакт передаётся только после отдельного взаимного согласия."
            if permitted else "🔒 Предпочтение сохранено: не делиться контактом.",
            reply_markup=menu,
        )


async def delete_remote_game_data(user_id: int) -> bool:
    """Signed service-to-service deletion. Never log the token, signature or user ID."""
    if not LUMI_GAMES_URL or not TOKEN:
        return False
    import hashlib
    import hmac
    import json
    import urllib.request
    from urllib.parse import urlsplit
    from urllib.error import URLError
    parsed = urlsplit(LUMI_GAMES_URL)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        return False
    uid = str(user_id)
    ts = int(time.time())
    signature = hmac.new(TOKEN.strip().encode(), f'lumi:delete:v1:{uid}:{ts}'.encode(), hashlib.sha256).hexdigest()
    endpoint = f'{parsed.scheme}://{parsed.netloc}/api/internal/delete-user'
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    def send():
        request = urllib.request.Request(endpoint, data=json.dumps({'uid': uid, 'ts': ts}).encode(), headers={'Content-Type': 'application/json', 'X-Lumi-Delete-Signature': signature}, method='POST')
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=8) as response:
                return response.status == 200 and json.loads(response.read(4096)).get('deleted') is True
        except (URLError, OSError, ValueError, AttributeError):
            return False
    return await asyncio.to_thread(send)


@dp.message(F.text == "🗑 Удалить анкету")
async def ask_delete(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да, удалить", callback_data="delete:yes"),
        InlineKeyboardButton(text="Отмена", callback_data="delete:no"),
    ]])
    await message.answer(
        "Удалить анкету, реакции, совпадения и игровые комнаты (в том числе общие)? Это нельзя отменить. "
        "Если действует модераторское ограничение, технический ID может "
        "сохраняться до 30 дней, чтобы предотвратить обход блокировки.",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data.startswith("delete:"))
async def delete_profile(callback: CallbackQuery, state: FSMContext):
    if callback.data == "delete:ask":
        await callback.answer()
        await ask_delete(callback.message.model_copy(update={"from_user":callback.from_user}))
        return
    if callback.data == "delete:yes":
        user_id = callback.from_user.id
        with connect_db() as db:
            db.execute("DELETE FROM active_chats WHERE user_id=? OR peer_id=?",(user_id,user_id))
            db.execute("DELETE FROM contact_requests WHERE requester_id=? OR recipient_id=?",(user_id,user_id))
            db.execute("DELETE FROM quiz_progress WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM privacy_settings WHERE user_id=?", (user_id,))
            # Minimal abuse-prevention record survives account deletion for at most 30 days.
            # Other profile and media data are removed below. Disclosed in deletion prompt.
            db.execute("UPDATE moderation_holds SET created_at=CURRENT_TIMESTAMP WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM profile_views WHERE viewer_id=? OR target_id=?", (user_id,user_id))
            db.execute("DELETE FROM browse_daily WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM lumi_notification_settings WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM lumi_return_activity WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM lumi_security_flags WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM lumi_starter_daily WHERE from_user=? OR to_user=?", (user_id,user_id))
            db.execute("DELETE FROM admin_events WHERE type='ticket' AND ref_id IN "
                       "(SELECT id FROM support_tickets WHERE user_id=?)", (user_id,))
            db.execute("DELETE FROM support_messages WHERE ticket_id IN (SELECT id FROM support_tickets WHERE user_id=?)", (user_id,))
            db.execute("DELETE FROM support_tickets WHERE user_id=?", (user_id,))
            from lumi_privacy import purge_admin_references
            purge_admin_references(db, user_id)
            db.execute("DELETE FROM report_reviews WHERE report_id IN "
                       "(SELECT id FROM reports WHERE reporter_id=? OR reported_id=?)", (user_id,user_id))
            db.execute("DELETE FROM profile_extras WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM verification_requests WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM game_sessions WHERE user_a=? OR user_b=?", (user_id,user_id))
            db.execute("DELETE FROM mystery_queue WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM mystery_sessions WHERE user_a=? OR user_b=?", (user_id,user_id))
            db.execute("DELETE FROM daily_moments WHERE user_id=? OR target_id=?", (user_id,user_id))
            db.execute("DELETE FROM duo_adventures WHERE user_a=? OR user_b=?", (user_id,user_id))
            db.execute("DELETE FROM arena_challenges WHERE challenger=? OR defender=?", (user_id,user_id))
            db.execute("DELETE FROM arena_heroes WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM arena_collection WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM arena_intro WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM arena_account_progress WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM arena_achievements WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM arena_battle_log WHERE winner=? OR loser=?", (user_id,user_id))
            db.execute("DELETE FROM arena_season_scores WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM duo_quest_rewards WHERE user_a=? OR user_b=?", (user_id,user_id))
            # Право на удаление: не оставляем игровой прогресс, журналы и медиа-ID.
            db.execute("DELETE FROM lumi_pets WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM lumi_pet_colors WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM lumi_pet_events WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM arena_heroes WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM arena_collection WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM arena_achievements WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM arena_season_scores WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM arena_challenges WHERE challenger=? OR defender=?", (user_id,user_id))
            db.execute("DELETE FROM arena_battle_log WHERE winner=? OR loser=?", (user_id,user_id))
            db.execute("DELETE FROM duo_quest_rewards WHERE user_a=? OR user_b=?", (user_id,user_id))
            db.execute("DELETE FROM security_audit WHERE actor=? OR target=?", (user_id,user_id))
            db.execute("DELETE FROM premium_skips WHERE user_id=?",(user_id,))
            db.execute("DELETE FROM premium_filters WHERE user_id=?",(user_id,))
            db.execute("DELETE FROM premium_superlikes WHERE user_id=?",(user_id,))
            db.execute("DELETE FROM lumi_like_teasers WHERE user_id=?",(user_id,))
            db.execute("DELETE FROM lumi_teaser_phrase_history WHERE user_id=?",(user_id,))
            db.execute("DELETE FROM premium_subscriptions WHERE user_id=?",(user_id,))
            db.execute("DELETE FROM premium_orders WHERE user_id=? AND status='pending'",(user_id,))
            delete_referral_data(db, user_id)
            db.execute("DELETE FROM lumi_daily_rewards WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM lumi_founders WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM profiles WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM search_settings WHERE user_id=?", (user_id,))
            db.execute(
                "DELETE FROM reactions WHERE from_user=? OR to_user=?",
                (user_id, user_id),
            )
            db.execute(
                "DELETE FROM blocks WHERE user_id=? OR blocked_id=?",
                (user_id, user_id),
            )
            db.execute(
                "DELETE FROM reports WHERE reporter_id=? OR reported_id=?",
                (user_id, user_id),
            )
        ACTIVE_BROWSE_TARGET.pop(user_id, None)
        DEFERRED.pop(user_id, None)
        SEEN_THIS_ROUND.pop(user_id, None)
        _CLEAN_UI.pop(user_id, None)
        await state.clear()
        remote_deleted = await delete_remote_game_data(user_id)
        text = ("Анкета и игровые записи удалены 💜. Для нового входа в Mini App подожди 2 минуты и открой приложение заново." if remote_deleted else
                "Анкета удалена. Удаление игровой базы не подтверждено. Повтори /deleteaccount или обратись в /support. ")
        text += " Копии сообщений в Telegram, резервные копии и необходимые записи платежей могут сохраняться."
    else:
        text = "Удаление отменено 💜"
    await callback.answer()
    if callback.message:
        await callback.message.answer(text, reply_markup=menu)


@dp.message(F.text.in_({"Меню", "🏠 Меню"}))
async def open_main_menu(message: Message, state: FSMContext):
    await state.clear()
    await mobile_home(message)


# Compact 1–4 mode commands; old named commands continue to work.
@dp.message(F.text == "2")
async def mobile_number_profile(message: Message):
    await my_profile(message)


@dp.message(F.text == "3")
async def mobile_number_heroes(message: Message):
    await arena_home(message)


@dp.message(F.text == "4")
async def mobile_number_more(message: Message):
    await clean_answer(message, "⋯ Ещё", reply_markup=mobile_more_keyboard(), parse_mode="HTML")


@dp.message(F.text == "1 🚀")
async def quick_browse(message: Message):
    await message.answer("❤️ <b>Знакомства</b>", reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")
    if profile_of(message.from_user.id):
        await search_welcome(message, message.from_user.id)
    await show_next(message, message.from_user.id)


@dp.message(F.text == "💜 Заполнить заново")
async def quick_restart(message: Message, state: FSMContext):
    await create_profile(message, state)


@dp.message(F.text == "📷 Изменить фото")
async def quick_edit_photo(message: Message, state: FSMContext):
    if not profile_of(message.from_user.id):
        await message.answer("Сначала создай анкету 💜", reply_markup=menu)
        return
    await state.set_state(EditProfile.photo)
    await clean_answer(message, "📷 Отправь новое фото или видео (до 15 секунд).\n\nОтмена — /cancel")


@dp.message(EditProfile.photo)
async def save_new_photo(message: Message, state: FSMContext):
    if not media_size_allowed(message.photo[-1] if message.photo else message.video):
        await message.answer("Файл слишком большой. Отправь медиа до 19 МБ.")
        return
    if not message.photo and not (message.video and message.video.duration <= 15):
        await message.answer("Отправь фото или видео до 15 секунд. /cancel — отмена")
        return
    media = message.photo[-1] if message.photo else message.video
    identity = media_identity(media)
    photo_id = media.file_id if message.photo else None
    video_id = media.file_id if not message.photo else None
    with connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        duplicate = not media_available(db, message.from_user.id, identity, photo_id, video_id)
        if not duplicate:
            db.execute("UPDATE profiles SET photo_id=?, video_id=?, media_unique_id=? WHERE user_id=?",
                       (photo_id, video_id, identity, message.from_user.id))
            db.execute("UPDATE profile_extras SET verified=0,verification_status='none' WHERE user_id=?",(message.from_user.id,))
            db.execute("DELETE FROM verification_requests WHERE user_id=?",(message.from_user.id,))
    if duplicate:
        await message.answer("Это медиа уже используется в другой анкете. Отправь другое фото или видео.")
        return
    await state.clear()
    await clean_answer(message, "✓ Фото сохранено")
    await show_quick_menu(message)
    await clear_clean_ui(message)


@dp.message(F.text == "✏️ Изменить описание")
async def quick_edit_text(message: Message, state: FSMContext):
    if not profile_of(message.from_user.id):
        await message.answer("Сначала создай анкету 💜", reply_markup=menu)
        return
    await state.set_state(EditProfile.interests)
    await clean_answer(message, "✏️ Напиши о себе (от 2 до 300 символов).\n\nОтмена — /cancel")


@dp.message(EditProfile.interests)
async def save_new_text(message: Message, state: FSMContext):
    if not message.text or not 2 <= len(message.text.strip()) <= 300:
        await message.answer("Напиши текст длиной от 2 до 300 символов.")
        return
    if not profile_text_allowed(message.text, getattr(message, "entities", None)):
        await message.answer("🛡 Убери ссылки, подозрительные просьбы или скрытые управляющие символы из анкеты.")
        return
    with connect_db() as db:
        db.execute("UPDATE profiles SET interests=? WHERE user_id=?",
                   (message.text.strip(), message.from_user.id))
    await state.clear()
    await clean_answer(message, "✓ Описание сохранено")
    await show_quick_menu(message)
    await clear_clean_ui(message)


def premium_keyboard(is_active):
    rows=[]
    if is_active:
        rows += [[InlineKeyboardButton(text="👀 Кто поставил лайк",callback_data="premium:likes")],
                 [InlineKeyboardButton(text="↩️ Вернуть пропуск",callback_data="premium:undo")],
                 [InlineKeyboardButton(text="🔎 Только проверенные анкеты",callback_data="premium:filter")]]
    rows.append([InlineKeyboardButton(text="⭐ Купить 30 дней · 199 Stars",callback_data="premium:activate")])
    rows.append([InlineKeyboardButton(text="🏠 Домой",callback_data="ux:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(Command("premium"))
@dp.message(F.text == "5")
@dp.message(F.text == "⭐ Premium")
async def quick_premium(message: Message):
    uid=message.from_user.id
    with connect_db() as db:
        until=premium_expires_at(db,uid)
    active=until>int(time.time())
    status=("✅ Активен до <b>"+datetime.fromtimestamp(until,timezone.utc).strftime("%d.%m.%Y %H:%M UTC")+"</b>"
            if active else "Бесплатный тариф")
    await clean_answer(message, 
        "👑 <b>LUMI PREMIUM · ЗОЛОТАЯ АНКЕТА</b>\n"
        "<i>Особая отметка в анкете для подписчиков</i>\n\n"+status+"\n\n"
        "👀 Кто поставил лайк — список доступных анкет\n"
        "⭐ До 5 суперлайков в день (без Premium — 1)\n"
        "↩️ Возврат последнего пропуска в течение 10 минут\n"
        "🔎 Фильтр: только анкеты с проверенным фото\n"
        "👑 Золотая отметка в анкете и небольшой бонус заметности\n\n"
        "<b>199 Telegram Stars за 30 дней</b>\n"
        "Без автоматического продления. Покупка продлит текущий срок на 30 дней.\n"
        "Обычные лайки, совпадения и переписка остаются бесплатными.",
        reply_markup=premium_keyboard(active),parse_mode="HTML")


@dp.callback_query(F.data.startswith("premium:"))
async def premium_choice(callback: CallbackQuery):
    action=callback.data.partition(":")[2]
    uid=callback.from_user.id
    if action=="activate":
        if not profile_of(uid):
            await callback.answer("Сначала создай анкету",show_alert=True)
            return
        payload="lumi_premium_"+secrets.token_urlsafe(16)
        with connect_db() as db:
            db.execute("INSERT INTO premium_orders(payload,user_id,price,status,created_at) VALUES(?,?,?,'pending',?)",
                       (payload,uid,PREMIUM_STARS,int(time.time())))
        await callback.answer()
        try:
            await callback.bot.send_invoice(
                chat_id=uid,title="LUMI Premium · 30 дней",
                description="Расширенные возможности знакомств на 30 дней, без автопродления",
                payload=payload,currency="XTR",prices=[LabeledPrice(label="LUMI Premium",amount=PREMIUM_STARS)],
                provider_token="",start_parameter="lumi-premium")
        except TelegramAPIError:
            logger.exception("Не удалось выставить счёт Stars")
            await callback.message.answer("Оплата временно недоступна. Попробуй позднее.")
        return
    if action=="later":
        await callback.answer("Продолжай знакомиться бесплатно 💜")
        return
    with connect_db() as db:
        active=premium_active(db,uid)
    if not active:
        await callback.answer("Для этого нужен действующий Premium",show_alert=True)
        return
    if action=="likes":
        with connect_db() as db:
            rows=db.execute("""SELECT p.user_id,p.name,p.age FROM reactions r
                JOIN profiles p ON p.user_id=r.from_user
                WHERE r.to_user=? AND r.liked=1 ORDER BY p.user_id DESC LIMIT 60""",(uid,)).fetchall()
            visible=[(person_id,name,age) for person_id,name,age in rows
                     if is_discoverable(db,person_id)
                     and not db.execute("SELECT 1 FROM blocks WHERE (user_id=? AND blocked_id=?) OR (user_id=? AND blocked_id=?)",
                                        (uid,person_id,person_id,uid)).fetchone()][:10]
        text="👀 <b>Кто поставил лайк</b>\n\n"
        text+=("\n".join(f"• {ui_safe(name,45)}, {age}" for _,name,age in visible)
               if visible else "Сейчас нет доступных анкет с новыми лайками.")
        await callback.answer()
        await callback.message.answer(text,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Домой",callback_data="ux:home")]]))
    elif action=="filter":
        with connect_db() as db:
            old=db.execute("SELECT verified_only FROM premium_filters WHERE user_id=?",(uid,)).fetchone()
            new=0 if old and old[0] else 1
            db.execute("INSERT INTO premium_filters(user_id,verified_only) VALUES(?,?) "
                       "ON CONFLICT(user_id) DO UPDATE SET verified_only=excluded.verified_only",(uid,new))
        await callback.answer("Фильтр сохранён")
        await callback.message.answer("🔎 Только анкеты с проверенным фото: "+("включено" if new else "выключено"))
    elif action=="undo":
        now=int(time.time())
        with connect_db() as db:
            skip=db.execute("SELECT target_id,created_at FROM premium_skips WHERE user_id=?",(uid,)).fetchone()
            if skip and now-skip[1]<=600 and is_discoverable(db,skip[0]):
                target=skip[0]
                valid=not db.execute("SELECT 1 FROM blocks WHERE (user_id=? AND blocked_id=?) OR (user_id=? AND blocked_id=?)",
                                     (uid,target,target,uid)).fetchone()
                if valid:
                    result=db.execute("DELETE FROM reactions WHERE from_user=? AND to_user=? AND liked=0",(uid,target))
                    valid=result.rowcount==1
                db.execute("DELETE FROM premium_skips WHERE user_id=?",(uid,))
            else:
                valid=False
        await callback.answer()
        if valid:
            SEEN_THIS_ROUND.get(uid,set()).discard(target)
            DEFERRED.get(uid,set()).discard(target)
            await callback.message.answer("↩️ Последний пропуск отменён. Анкета снова доступна в поиске.")
        else:
            await callback.message.answer("Не нашёл свежий пропуск за последние 10 минут.")
    else:
        await callback.answer("Кнопка недоступна",show_alert=True)


@dp.pre_checkout_query()
async def premium_pre_checkout(query: PreCheckoutQuery):
    with connect_db() as db:
        row=db.execute("""SELECT o.user_id,o.price,o.status,o.created_at FROM premium_orders o
            JOIN profiles p ON p.user_id=o.user_id
            WHERE o.payload=? AND NOT EXISTS (SELECT 1 FROM account_suspensions s
            WHERE s.user_id=o.user_id AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP))""",
            (query.invoice_payload,)).fetchone()
    valid=bool(row and row[0]==query.from_user.id and row[1]==PREMIUM_STARS
               and row[2]=='pending' and 0<=int(time.time())-row[3]<=3600
               and query.currency=='XTR' and query.total_amount==PREMIUM_STARS)
    await query.answer(ok=valid,error_message=None if valid else "Счёт недействителен или устарел. Открой Premium заново.")


@dp.message(Command("paysupport"))
async def premium_payment_support(message: Message):
    await message.answer("🆘 Если возник вопрос по оплате, открой /support. Не отправляй токены или банковские данные.")


@dp.message(Command("complaint"))
async def complaint_info(message: Message):
    await message.answer("🚫 Чтобы пожаловаться на анкету, открой просмотр и нажми «Пожаловаться» под ней.", reply_markup=menu)



# LUMI 10.0 — социальные функции. Проверка анкет только вручную администратором.
ICEBREAKERS = [
    "Какое самое странное сочетание еды тебе нравится?",
    "Если бы у тебя был бесплатный билет куда угодно, куда бы ты полетел(а)?",
    "Какой фильм ты готов(а) пересматривать бесконечно?",
    "Твоя суперспособность на один день — какая?",
    "Пицца с ананасами — преступление или искусство?",
    "Какую песню включишь в машине первой?",
    "Что смешнее: кот в галстуке или пёс в очках?",
    "Какой идеальный план для спонтанного выходного?",
]
PAIR_QUESTIONS = [
    ("Идеальный вечер?", ("Кино дома", "Гулять до ночи", "Пельмени и игры")),
    ("Что взять на необитаемый остров?", ("Книгу", "Гитару", "Надувного гуся")),
    ("Куда пойдём на первое свидание?", ("Кофейня", "Парк", "Музей странностей")),
    ("Выбери суперсилу", ("Телепортация", "Невидимость", "Всегда находить носки")),
    ("Какой питомец?", ("Кот", "Собака", "Капибара")),
    ("Чем заняться в дождь?", ("Сериал", "Танцы", "Собирать лужи")),
]


def pair_ids(a, b):
    return tuple(sorted((a, b)))


@dp.message(Command("features"))
@dp.message(F.text == "Возможности LUMI")
@dp.message(F.text == "✨ Возможности")
async def social_features(message: Message):
    await message.answer(
        "✨ Возможности LUMI\n\n"
        "🛡 Проверка после 20 просмотров анкет — автоматически\n"
        "🎤 /voice — голосовое приветствие\n"
        "🗑 /deletevoice — удалить голосовое\n"
        "💌 /admirers — тайные симпатии\n\n"
        "💞 В «Моих совпадениях» есть вопросы и игры для двоих.\n"
        "🔒 В «Приватности» можно скрыть анкету.",
        reply_markup=menu,
    )


@dp.message(Command("voice"))
async def voice_intro(message: Message, state: FSMContext):
    if not profile_of(message.from_user.id):
        await message.answer("Сначала создай анкету.")
        return
    await state.set_state(EditProfile.voice)
    await message.answer("Запиши голосовое приветствие до 15 секунд. Оно будет доступно при просмотре твоей анкеты. Для удаления — /deletevoice, для отмены — /cancel.")


@dp.message(Command("deletevoice"))
async def delete_voice(message: Message, state: FSMContext):
    with connect_db() as db:
        db.execute("UPDATE profile_extras SET voice_id=NULL WHERE user_id=?", (message.from_user.id,))
    await state.clear()
    await message.answer("Голосовое приветствие удалено.")


@dp.message(EditProfile.voice)
async def voice_save(message: Message, state: FSMContext):
    if not message.voice or message.voice.duration > 15 or not media_size_allowed(message.voice):
        await message.answer("Пришли голосовое сообщение длительностью до 15 секунд.")
        return
    with connect_db() as db:
        db.execute("INSERT INTO profile_extras(user_id,voice_id) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET voice_id=excluded.voice_id", (message.from_user.id,message.voice.file_id))
    await state.clear()
    await message.answer("Голосовое приветствие добавлено в анкету.")


@dp.callback_query(F.data.startswith("listen:"))
async def listen_profile(callback: CallbackQuery):
    try:
        target = int(callback.data.split(":",1)[1])
    except (ValueError,IndexError):
        await callback.answer("Некорректная кнопка")
        return
    with connect_db() as db:
        voice = db.execute("SELECT voice_id FROM profile_extras WHERE user_id=?",(target,)).fetchone()
        blocked = db.execute("SELECT 1 FROM blocks WHERE (user_id=? AND blocked_id=?) OR (user_id=? AND blocked_id=?)",(callback.from_user.id,target,target,callback.from_user.id)).fetchone()
    with connect_db() as db:
        access_allowed=can_access_profile(db,callback.from_user.id,target)
    if not profile_of(callback.from_user.id) or not profile_of(target) or blocked or not access_allowed or not voice or not voice[0]:
        await callback.answer("Запись недоступна",show_alert=True)
        return
    await callback.answer()
    await callback.message.answer_voice(voice[0],caption="Голосовое приветствие LUMI",protect_content=True)


@dp.message(Command("admirers"))
async def secret_admirers(message: Message):
    if not profile_of(message.from_user.id):
        await message.answer("Сначала создай анкету.")
        return
    with connect_db() as db:
        row = db.execute("""SELECT COUNT(*) FROM reactions r JOIN profiles p ON p.user_id=r.from_user
          WHERE r.to_user=? AND r.liked=1
          AND NOT EXISTS(SELECT 1 FROM reactions own WHERE own.from_user=? AND own.to_user=r.from_user AND own.liked=1)
          AND NOT EXISTS(SELECT 1 FROM blocks b WHERE (b.user_id=? AND b.blocked_id=r.from_user) OR (b.user_id=r.from_user AND b.blocked_id=?))
          AND NOT EXISTS(SELECT 1 FROM privacy_settings ps WHERE ps.user_id=r.from_user AND ps.discoverable=0)
          AND NOT EXISTS(SELECT 1 FROM moderation_holds mh WHERE mh.user_id=r.from_user AND (mh.expires_at IS NULL OR mh.expires_at > CURRENT_TIMESTAMP))""", (message.from_user.id,)*4).fetchone()
    count = row[0]
    await message.answer(f"Тайные симпатии: {count}.\nКто именно — узнаешь, когда симпатия станет взаимной. Открой просмотр анкет.")


# LUMI: одноразовая проверка сходства с фото через видеокружок.
# НЕ является проверкой возраста или документа. Доступ к видео — только администраторам.
VERIFICATION_ACTIONS = (
    "покажи два пальца возле лица и поверни голову вправо",
    "помаши правой рукой и поверни голову влево",
    "подними левую руку, затем слегка поверни голову вправо",
    "покажи большой палец и медленно поверни голову влево",
)


def utc_after(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')


def verification_valid(request) -> bool:
    return bool(request and request[2] and request[2] > datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'))


@dp.message(Command("verify"))
async def request_verification(message: Message):
    # Поддержка старой команды: раннюю ручную проверку не запускаем.
    if not profile_of(message.from_user.id):
        await message.answer("Сначала создай анкету 💜")
        return
    count, approved, status = verification_gate_status(message.from_user.id)
    if approved:
        await message.answer("✅ Твоя анкета уже проверена.")
    elif count < VERIFY_GATE_AFTER:
        await message.answer(f"🛡 Проверка появится автоматически после {VERIFY_GATE_AFTER} просмотров анкет. "
                             f"Сейчас: {count}/{VERIFY_GATE_AFTER}.",
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                 [InlineKeyboardButton(text="❤️ Смотреть анкеты", callback_data="ux:browse")],
                                 [InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")]]))
    else:
        await show_verification_gate(message, count, status)


@dp.callback_query(F.data == "verifygate:start")
async def verification_gate_begin(callback: CallbackQuery):
    count, approved, status = verification_gate_status(callback.from_user.id)
    if not profile_of(callback.from_user.id):
        await callback.answer("Сначала создай анкету", show_alert=True)
        return
    if approved:
        await callback.answer("Анкета уже проверена")
        await callback.message.answer("✅ Проверка пройдена! Продолжай смотреть анкеты.",
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                          [InlineKeyboardButton(text="❤️ Смотреть анкеты", callback_data="ux:browse")]]))
        return
    if count < VERIFY_GATE_AFTER:
        await callback.answer("Проверка станет доступна после 20 просмотров анкет", show_alert=True)
        return
    await callback.answer()
    await begin_verification(callback.from_user.id, callback.message)


async def begin_verification(uid: int, message):
    if not profile_of(uid):
        await message.answer("Сначала создай анкету с фотографией лица.")
        return
    if not ADMIN_IDS:
        await message.answer("Верификация временно недоступна: модераторы не настроены.")
        return
    with connect_db() as db:
        current_media=db.execute("SELECT photo_id,video_id FROM profiles WHERE user_id=?",(uid,)).fetchone()
    if not current_media or not any(current_media):
        await message.answer("Сначала добавь фото или короткое видео в анкету для сравнения лица.")
        return
    with connect_db() as db:
        media=db.execute("SELECT photo_id,video_id FROM profiles WHERE user_id=?",(uid,)).fetchone()
        info=db.execute("SELECT verified FROM profile_extras WHERE user_id=?",(uid,)).fetchone()
        if info and info[0]:
            await message.answer("✅ Фото в твоей анкете уже проверено.")
            return
        pending=db.execute("SELECT status,video_note_id,expires_at FROM verification_requests WHERE user_id=?",(uid,)).fetchone()
        if pending and pending[0]=='review' and pending[1]:
            await message.answer("Твой кружок уже ожидает ручной проверки модератором.")
            return
        if pending and pending[0]=='challenge' and verification_valid(pending):
            challenge=db.execute("SELECT challenge FROM verification_requests WHERE user_id=?",(uid,)).fetchone()[0] or 'помаши рукой перед камерой' 
            await message.answer(f"Твоё текущее задание: {challenge}\n\nОтправь видеокружок до 20 секунд в течение 10 минут. Для отмены /cancelverify")
            return
        challenge=secrets.choice(VERIFICATION_ACTIONS)
        db.execute("""INSERT INTO verification_requests(user_id,status,challenge,expires_at,video_note_id,submitted_at,created_at)
            VALUES (?, 'challenge', ?, ?, NULL, NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET status='challenge',challenge=excluded.challenge,
            expires_at=excluded.expires_at,video_note_id=NULL,submitted_at=NULL,review_id=NULL,created_at=CURRENT_TIMESTAMP""",
            (uid,challenge,utc_after(10)))
        db.execute("INSERT INTO profile_extras(user_id,verified,verification_status) VALUES (?,0,'challenge') ON CONFLICT(user_id) DO UPDATE SET verified=0,verification_status='challenge'",(uid,))
    await message.answer(
        "🛡 LUMI · Проверка сходства с фото\n\n"
        f"Задание: {challenge}\n\n"
        "Запиши НОВЫЙ видеокружок с лицом целиком. Выполни движение на камеру, "
        "не используй маски и фильтры. До 20 секунд, 10 минут на отправку.\n\n"
        "Кружок увидят только модераторы LUMI; другим пользователям он не показывается. "
        "Отправляя его, ты соглашаешься на ручное сравнение с фото анкеты. "
        "Отказаться можно: /cancelverify. Проверка не подтверждает возраст 18+.")


@dp.message(Command("cancelverify"))
async def cancel_verification(message: Message):
    uid=message.from_user.id
    with connect_db() as db:
        db.execute("DELETE FROM verification_requests WHERE user_id=? AND status IN ('challenge','review')",(uid,))
        db.execute("UPDATE profile_extras SET verification_status='none' WHERE user_id=? AND verified=0",(uid,))
    await message.answer("Запрос на проверку отменён. Данные кружка удалены из базы LUMI. Ранее отправленные модератору сообщения могут оставаться в Telegram.")


@dp.message(F.video_note)
async def verification_video_note(message: Message):
    uid=message.from_user.id
    if not media_size_allowed(message.video_note):
        await message.answer("Кружок слишком большой. Лимит 19 МБ.")
        return
    if getattr(message, "forward_origin", None) is not None or getattr(message, "is_automatic_forward", False):
        await message.answer("Пересланный кружок не подходит. Запиши новый прямо в Telegram после получения задания.")
        return
    with connect_db() as db:
        req=db.execute("SELECT status,challenge,expires_at FROM verification_requests WHERE user_id=?",(uid,)).fetchone()
        if not req or req[0]!='challenge':
            await message.answer("Для проверки нажми «🛡 Пройти проверку» после 20 просмотров. Обычные кружки не сохраняются.")
            return
        if not verification_valid(req):
            db.execute("DELETE FROM verification_requests WHERE user_id=?",(uid,))
            await message.answer("Время на запись истекло. Нажми «🛡 Пройти проверку» ещё раз в разделе поиска")
            return
        if message.video_note.duration > 20:
            await message.answer("Кружок должен быть не длиннее 20 секунд. Запиши ещё раз.")
            return
        if not profile_of(uid):
            await message.answer("Анкета не найдена.")
            return
        # Сразу меняем состояние: повторная отправка не создаёт новую очередь.
        review_id=new_review_id()
        result=db.execute("UPDATE verification_requests SET status='review',video_note_id=?,submitted_at=CURRENT_TIMESTAMP,expires_at=NULL,review_id=? WHERE user_id=? AND status='challenge' AND challenge=? AND expires_at=? AND expires_at>CURRENT_TIMESTAMP",(message.video_note.file_id,review_id,uid,req[1],req[2]))
        if not result.rowcount:
            await message.answer("Кружок уже получен.")
            return
        db.execute("UPDATE profile_extras SET verification_status='review' WHERE user_id=?",(uid,))
    # Telegram file_id is specific to the owning bot; copy media over Bot API in RAM only.
    # Never write verification clips to disk. If the admin bot is not configured, keep
    # the old, same-bot moderator workflow for compatibility.
    delivered = False
    moderator_token = os.getenv("LUMI_ADMIN_BOT_TOKEN", "").strip()
    review_bot = Bot(token=moderator_token) if moderator_token else message.bot
    try:
        with connect_db() as db:
            media = db.execute("SELECT photo_id,video_id FROM profiles WHERE user_id=?", (uid,)).fetchone()
        with connect_db() as db:
            identity=db.execute("SELECT name,username FROM profiles WHERE user_id=?", (uid,)).fetchone()
        display_name = (identity[0] or 'Без имени')[:45] if identity else 'Без имени'
        raw_username = (identity[1] or '') if identity else ''
        display_username = ('@' + raw_username.lstrip('@')) if re.fullmatch(r'[A-Za-z0-9_]{5,32}', raw_username.lstrip('@')) else 'не указан'
        for admin in ADMIN_IDS:
            try:
                if not media or not any(media):
                    raise ValueError("Нет материалов анкеты для сравнения")
                await review_bot.send_message(admin,
                    f"🛡 LUMI · Проверка фото\nИмя: {display_name}\nUsername: {display_username}\nTelegram ID: {uid}\n"
                    f"Задание: {req[1]}\n\n"
                    "Сравни лицо и выполнение задания с фото анкеты. "
                    "Кружок НЕ подтверждает возраст.", protect_content=True)
                if media and media[0]:
                    await transfer_review_media(message.bot, review_bot, admin, media[0], 'photo')
                elif media and media[1]:
                    await transfer_review_media(message.bot, review_bot, admin, media[1], 'video')
                await transfer_review_media(message.bot, review_bot, admin,
                                            message.video_note.file_id, 'video_note')
                await review_bot.send_message(admin, "Решение после просмотра:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"vcheck:yes:{uid}:{review_id}")],
                        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"vcheck:no:{uid}:{review_id}")],
                    ]), protect_content=True)
                delivered = True
            except (TelegramAPIError, OSError, ValueError):
                logger.exception("Не удалось передать заявку модератору")
    finally:
        if moderator_token:
            await review_bot.session.close()
    if delivered:
        with connect_db() as db:
            admin_event(db, 'verification', uid)
        await message.answer("✅ Видеокружок получен. Модератор проверит его вручную.")
    else:
        with connect_db() as db:
            removed=db.execute("DELETE FROM verification_requests WHERE user_id=? AND status='review' AND review_id=?", (uid,review_id))
            if removed.rowcount:
                db.execute("UPDATE profile_extras SET verification_status='none' WHERE user_id=? AND verified=0", (uid,))
        await message.answer("Не удалось передать кружок. Убедись, что модератор запустил "
                             "админ-бота, и повтори проверку из экрана поиска.")


async def transfer_review_media(source_bot, recipient_bot, admin_id, file_id, kind):
    """Bot-specific file IDs are converted in memory; no local video copies."""
    if recipient_bot is source_bot:
        media = file_id
    else:
        tg_file = await source_bot.get_file(file_id)
        if not tg_file.file_path:
            raise ValueError("Telegram file_path отсутствует")
        if not media_size_allowed(tg_file):
            raise ValueError("Медиа превышает лимит безопасной передачи")
        with BoundedMediaBuffer() as stream:
            await source_bot.download_file(tg_file.file_path, destination=stream)
            media = BufferedInputFile(stream.getvalue(), filename={
                'photo':'face.jpg','video':'profile.mp4','video_note':'proof.mp4'}[kind])
    if kind == 'photo':
        return await recipient_bot.send_photo(admin_id, media, protect_content=True)
    if kind == 'video':
        return await recipient_bot.send_video(admin_id, media, protect_content=True)
    return await recipient_bot.send_video_note(admin_id, media, protect_content=True)


@dp.callback_query(F.data.startswith('vcheck:'))
async def video_verification_review(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа",show_alert=True)
        return
    try:
        target,approved,review_id=parse_review_callback(callback.data)
    except (ValueError,AttributeError):
        await callback.answer("Некорректный запрос",show_alert=True);return
    with connect_db() as db:
        changed=decide_review(db,target,approved,callback.from_user.id,review_id)
    if not changed:
        await callback.answer("Проверка уже завершена или отменена",show_alert=True)
        return
    await callback.answer("Решение сохранено")
    try: await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError: pass
    try:
        await callback.bot.send_message(target,"✅ Твоё фото проверено! Теперь просмотр анкет снова доступен." if approved else "❌ Проверка не пройдена. Повтори её из экрана поиска.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❤️ Смотреть анкеты", callback_data="ux:browse")]]))
    except TelegramAPIError: pass


@dp.message(Command("approve", "reject"))
async def moderation_decision(message: Message):
    # Устаревший ручной обход запрещён: решение — только по отправленному видеокружку.
    await message.answer("Проверка доступна только по видеокружку после 20 просмотров. Открой «❤️ Смотреть анкеты».")


@dp.message(Command("ice"))
async def ice_help(message: Message):
    await message.answer("Открой «Мои совпадения» и нажми «Начать разговор» рядом с человеком.")


@dp.callback_query(F.data.startswith("ice:"))
async def icebreaker(callback: CallbackQuery):
    try:
        peer = int(callback.data.split(":",1)[1])
    except (ValueError,IndexError):
        await callback.answer("Некорректная кнопка")
        return
    uid = callback.from_user.id
    with connect_db() as db:
        valid = is_match(db,uid,peer)
    if not valid:
        await callback.answer("Совпадение недоступно",show_alert=True)
        return
    question = random.choice(ICEBREAKERS)
    try:
        await callback.bot.send_message(peer,"LUMI · Вопрос для знакомства:\n"+question)
    except TelegramAPIError:
        await callback.answer("Не удалось доставить вопрос",show_alert=True)
        return
    await callback.answer("Отправлено")
    await callback.message.answer("Вопрос отправлен обоим:\n"+question)


def reserve_pair_game(db, a, b, q):
    return db.execute("INSERT OR IGNORE INTO game_sessions(user_a,user_b,game_type,question_id,answer_a,answer_b) VALUES (?,?,'choose',?,NULL,NULL)", (a,b,q)).rowcount == 1


@dp.callback_query(F.data.startswith("games:"))
async def games_start(callback: CallbackQuery):
    try:
        peer=int(callback.data.split(":",1)[1])
    except (ValueError,IndexError):
        await callback.answer("Некорректная кнопка")
        return
    uid=callback.from_user.id
    with connect_db() as db:
        if not is_match(db,uid,peer):
            await callback.answer("Совпадение недоступно",show_alert=True)
            return
        a,b=pair_ids(uid,peer)
        q=random.randrange(len(PAIR_QUESTIONS))
        if not reserve_pair_game(db, a, b, q):
            await callback.answer("У вас уже есть незавершённая игра. Ответь на предыдущий вопрос.", show_alert=True)
            return
    title,options=PAIR_QUESTIONS[q]
    keyboard=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{i+1}. {opt}",callback_data=f"pair:{a}:{b}:{q}:{i}")] for i,opt in enumerate(options)])
    try:
        await callback.bot.send_message(peer,"LUMI · Игра для двоих\n"+title,reply_markup=keyboard)
    except TelegramAPIError:
        with connect_db() as db:
            db.execute("DELETE FROM game_sessions WHERE user_a=? AND user_b=?",(a,b))
        await callback.answer("Не удалось пригласить собеседника",show_alert=True)
        return
    await callback.answer("Игра началась")
    await callback.message.answer("LUMI · Игра для двоих\n"+title,reply_markup=keyboard)


@dp.callback_query(F.data.startswith("pair:"))
async def pair_answer(callback: CallbackQuery):
    try:
        _,sa,sb,sq,si=callback.data.split(":")
        a,b,q,choice=map(int,(sa,sb,sq,si))
        if not (a<b and 0<=q<len(PAIR_QUESTIONS) and 0<=choice<3):
            raise ValueError
    except (ValueError,AttributeError):
        await callback.answer("Некорректная кнопка",show_alert=True)
        return
    uid=callback.from_user.id
    if uid not in (a,b):
        await callback.answer("Это не твоя игра",show_alert=True)
        return
    with connect_db() as db:
        if not is_match(db,a,b):
            await callback.answer("Совпадение недоступно",show_alert=True)
            return
        row=db.execute("SELECT question_id,answer_a,answer_b FROM game_sessions WHERE user_a=? AND user_b=?",(a,b)).fetchone()
        if not row or row[0]!=q:
            await callback.answer("Игра уже завершена",show_alert=True)
            return
        if row[1 if uid==a else 2] is not None:
            await callback.answer("Ты уже ответил(а)")
            return
        db.execute("UPDATE game_sessions SET answer_a=? WHERE user_a=? AND user_b=?" if uid==a else "UPDATE game_sessions SET answer_b=? WHERE user_a=? AND user_b=?",(choice,a,b))
        row=db.execute("SELECT answer_a,answer_b FROM game_sessions WHERE user_a=? AND user_b=?",(a,b)).fetchone()
        complete=row[0] is not None and row[1] is not None
        if complete:
            db.execute("DELETE FROM game_sessions WHERE user_a=? AND user_b=?",(a,b))
    await callback.answer("Ответ принят")
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
    if not complete:
        await callback.message.answer("Ответ записан. Ждём второго игрока.")
        return
    opts=PAIR_QUESTIONS[q][1]
    result=(f"Игра завершена!\nИгрок 1: {opts[row[0]]}\nИгрок 2: {opts[row[1]]}\n" + ("Вы выбрали одно и то же!" if row[0]==row[1] else "У вас разные вкусы — есть о чём поговорить."))
    for person in (a,b):
        try:
            await callback.bot.send_message(person,result)
        except TelegramAPIError:
            pass


@dp.message(Command("language"))
async def language_info(message: Message):
    await message.answer("🌍 Сейчас LUMI доступен на русском языке.", reply_markup=menu)


# LUMI 11.0: добровольные знакомства вслепую, ежедневный выбор и Duo.
from datetime import date

MYSTERY_QUESTIONS = [
    ("Идеальный вечер?", ("Кино и плед", "Ночная прогулка", "Пельмени и мемы")),
    ("Твоя суперсила?", ("Телепорт", "Читать мысли котов", "Не терять носки")),
    ("Что важнее в знакомстве?", ("Юмор", "Забота", "Общие приключения")),
]
DUO_PROMPTS = [
    "Придумайте название вашему воображаемому кафе.",
    "Какой самый нелепый пункт будет в меню этого кафе?",
    "Куда вы отправитесь после закрытия кафе?",
]


def mystery_eligible(db, a, b):
    if a == b:
        return False
    x = db.execute("SELECT age,gender,seeking FROM profiles WHERE user_id=?", (a,)).fetchone()
    y = db.execute("SELECT age,gender,seeking FROM profiles WHERE user_id=?", (b,)).fetchone()
    if not x or not y or x[0] < 18 or y[0] < 18 or not is_discoverable(db,a) or not is_discoverable(db,b):
        return False
    if x[2] not in ('все', y[1]) or y[2] not in ('все', x[1]):
        return False
    return not db.execute("SELECT 1 FROM blocks WHERE (user_id=? AND blocked_id=?) OR (user_id=? AND blocked_id=?)", (a,b,b,a)).fetchone()


def mystery_buttons(sid, rnd):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{i+1}. {v}", callback_data=f"myanswer:{sid}:{rnd}:{i}")]
        for i,v in enumerate(MYSTERY_QUESTIONS[rnd][1])
    ] + [[InlineKeyboardButton(text="Завершить знакомство", callback_data=f"myexit:{sid}")]])


async def mystery_send_round(bot, sid, rnd, users):
    title, _ = MYSTERY_QUESTIONS[rnd]
    for uid in users:
        try:
            await bot.send_message(uid, f"LUMI Mystery · {rnd+1}/3\n\n{title}", reply_markup=mystery_buttons(sid,rnd))
        except TelegramAPIError:
            logger.info("Mystery: сообщение не доставлено %s", uid)


@dp.message(Command("mystery"))
@dp.message(F.text == "LUMI Mystery")
@dp.message(F.text == "🎭 Mystery")
async def mystery_join(message: Message):
    uid = message.from_user.id
    if not profile_of(uid):
        await message.answer("Сначала создай анкету.")
        return
    with connect_db() as db:
        active = db.execute("SELECT id FROM mystery_sessions WHERE status='active' AND (user_a=? OR user_b=?)", (uid,uid)).fetchone()
        if active:
            await message.answer("Знакомство вслепую уже началось. Ответь на вопрос или заверши его: /mysteryexit")
            return
        queue = db.execute("SELECT user_id FROM mystery_queue WHERE user_id!=? ORDER BY joined_at,user_id", (uid,)).fetchall()
        peer = next((r[0] for r in queue if mystery_eligible(db,uid,r[0]) and not db.execute(
            "SELECT 1 FROM mystery_sessions WHERE status='active' AND (user_a=? OR user_b=?)", (r[0],r[0])).fetchone()), None)
        if peer is None:
            db.execute("INSERT OR IGNORE INTO mystery_queue(user_id) VALUES (?)", (uid,))
            sid = None
        else:
            db.execute("DELETE FROM mystery_queue WHERE user_id IN (?,?)", (uid,peer))
            sid = db.execute("INSERT INTO mystery_sessions(user_a,user_b) VALUES (?,?)", (uid,peer)).lastrowid
    if sid is None:
        await message.answer("🎭 Ты в очереди Mystery.\n\nКогда найдётся подходящий человек, начнём знакомство с трёх вопросов.\n\nВыйти — /mysteryexit")
    else:
        await mystery_send_round(message.bot,sid,0,(uid,peer))


@dp.message(Command("mysteryexit"))
async def mystery_exit(message: Message):
    uid=message.from_user.id
    with connect_db() as db:
        db.execute("DELETE FROM mystery_queue WHERE user_id=?", (uid,))
        rows=db.execute("SELECT id,user_a,user_b FROM mystery_sessions WHERE status='active' AND (user_a=? OR user_b=?)",(uid,uid)).fetchall()
        db.execute("UPDATE mystery_sessions SET status='closed' WHERE status='active' AND (user_a=? OR user_b=?)",(uid,uid))
    for sid,a,b in rows:
        other=b if uid==a else a
        try:
            await message.bot.send_message(other,"Знакомство вслепую завершилось. Можно начать новое через /mystery.")
        except TelegramAPIError:
            pass
    await message.answer("Ты вышел(ла) из LUMI Mystery.")


@dp.callback_query(F.data.startswith("myexit:"))
async def mystery_exit_button(callback: CallbackQuery):
    await callback.answer()
    await mystery_exit(callback.message.model_copy(update={"from_user":callback.from_user}))


@dp.callback_query(F.data.startswith("myanswer:"))
async def mystery_answer(callback: CallbackQuery):
    try:
        _,sid,rnd,choice=callback.data.split(":")
        sid,rnd,choice=int(sid),int(rnd),int(choice)
    except (ValueError,AttributeError):
        await callback.answer("Некорректная кнопка",show_alert=True); return
    if rnd not in range(3) or choice not in range(3):
        await callback.answer("Некорректный ответ",show_alert=True); return
    uid=callback.from_user.id
    with connect_db() as db:
        row=db.execute("SELECT user_a,user_b,round,answer_a,answer_b FROM mystery_sessions WHERE id=? AND status='active'",(sid,)).fetchone()
        if not row or uid not in row[:2] or row[2]!=rnd:
            await callback.answer("Вопрос больше не активен",show_alert=True); return
        a,b,_,aa,ab=row
        if (aa if uid==a else ab) is not None:
            await callback.answer("Ответ уже принят"); return
        field='answer_a' if uid==a else 'answer_b'
        db.execute("UPDATE mystery_sessions SET answer_a=? WHERE id=?" if field=='answer_a' else "UPDATE mystery_sessions SET answer_b=? WHERE id=?",(choice,sid))
        updated=db.execute("SELECT answer_a,answer_b FROM mystery_sessions WHERE id=?",(sid,)).fetchone()
        complete=updated[0] is not None and updated[1] is not None
        if complete:
            db.execute("UPDATE mystery_sessions SET round=?,answer_a=NULL,answer_b=NULL WHERE id=?",(rnd+1,sid))
    await callback.answer("Ответ принят")
    if callback.message:
        try: await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError: pass
    if not complete:
        await callback.message.answer("Ответ записан. Ждём второго участника.")
    elif rnd<2:
        await mystery_send_round(callback.bot,sid,rnd+1,(a,b))
    else:
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Открыть анкеты",callback_data=f"myreveal:{sid}:1")],
            [InlineKeyboardButton(text="Завершить анонимно",callback_data=f"myreveal:{sid}:0")],
        ])
        for person in (a,b):
            try: await callback.bot.send_message(person,"Три вопроса пройдены! Открыть анкеты друг другу? Только если оба согласны.",reply_markup=kb)
            except TelegramAPIError: pass


@dp.callback_query(F.data.startswith("myreveal:"))
async def mystery_reveal(callback: CallbackQuery):
    try:
        _,sid,v=callback.data.split(":"); sid=int(sid); v=int(v)
    except (ValueError,AttributeError):
        await callback.answer("Некорректная кнопка",show_alert=True); return
    if v not in (0,1):
        await callback.answer("Некорректный ответ",show_alert=True); return
    uid=callback.from_user.id
    with connect_db() as db:
        row=db.execute("SELECT user_a,user_b,round,reveal_a,reveal_b FROM mystery_sessions WHERE id=? AND status='active'",(sid,)).fetchone()
        if not row or uid not in row[:2] or row[2]!=3:
            await callback.answer("Знакомство завершено",show_alert=True); return
        a,b,_,ra,rb=row
        field='reveal_a' if uid==a else 'reveal_b'
        if (ra if uid==a else rb) is not None:
            await callback.answer("Выбор уже сделан"); return
        db.execute("UPDATE mystery_sessions SET reveal_a=? WHERE id=?" if field=='reveal_a' else "UPDATE mystery_sessions SET reveal_b=? WHERE id=?",(v,sid))
        ra,rb=db.execute("SELECT reveal_a,reveal_b FROM mystery_sessions WHERE id=?",(sid,)).fetchone()
        done=(ra==0 or rb==0 or (ra==1 and rb==1))
        if done: db.execute("UPDATE mystery_sessions SET status='closed' WHERE id=?",(sid,))
    await callback.answer("Выбор сохранён")
    if callback.message:
        try: await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError: pass
    if not done:
        await callback.message.answer("Ждём решения второго участника."); return
    if ra==1 and rb==1:
        for person,other in ((a,b),(b,a)):
            prof=profile_of(other)
            with connect_db() as db:
                eligible = mystery_eligible(db,person,other)
            if prof and eligible:
                try:
                    caption = "Вы оба согласились!\n\n" + profile_caption(prof,user_id=other)
                    with connect_db() as db:
                        media = db.execute("SELECT video_id FROM profiles WHERE user_id=?",(other,)).fetchone()
                    if media and media[0]:
                        await callback.bot.send_video(person,media[0],caption=caption[:1024],protect_content=True)
                    elif prof[4]:
                        await callback.bot.send_photo(person,prof[4],caption=caption[:1024],protect_content=True)
                    else:
                        await callback.bot.send_message(person,caption)
                except TelegramAPIError:
                    logger.info("Не удалось показать анкету Mystery пользователю %s",person)
    else:
        for person in (a,b):
            try: await callback.bot.send_message(person,"Знакомство завершено без раскрытия анкет. Спасибо за игру!")
            except TelegramAPIError: pass


@dp.message(Command("moment"))
@dp.message(F.text == "LUMI Moment")
@dp.message(F.text == "💫 Moment")
async def daily_moment(message: Message):
    uid=message.from_user.id
    if not profile_of(uid):
        await message.answer("Сначала создай анкету."); return
    today=date.today().isoformat()  # дата сервера; для ежедневного лимита достаточно UTC/локальной даты сервера
    with connect_db() as db:
        old=db.execute("SELECT target_id FROM daily_moments WHERE user_id=? AND day=?",(uid,today)).fetchone()
        if old:
            target=old[0]
        else:
            me=db.execute("SELECT age,city,interests,gender,seeking FROM profiles WHERE user_id=?",(uid,)).fetchone()
            settings=db.execute("SELECT age_min,age_max,city FROM search_settings WHERE user_id=?",(uid,)).fetchone() or (18,100,'')
            candidates=moment_candidates(db,uid,settings)
            if not candidates:
                await message.answer("Сегодня пока нет подходящих анкет. Попробуй позже или расширь фильтры."); return
            def score(r):
                return 25*(r[2].casefold()==me[1].casefold())+10*len(interest_words(me[2])&interest_words(r[3]))-abs(me[0]-r[1])
            target=max(candidates,key=lambda r:(score(r),-r[0]))[0]
            db.execute("INSERT INTO daily_moments(user_id,day,target_id) VALUES (?,?,?)",(uid,today,target))
    prof=profile_of(target)
    if not prof:
        await message.answer("Анкета дня больше недоступна."); return
    with connect_db() as db:
        if not mystery_eligible(db,uid,target):
            await message.answer("Анкета дня больше недоступна."); return
    mine=profile_of(uid)
    shared=interest_words(mine[3]) & interest_words(prof[3])
    explanation=("Общие интересы: "+", ".join(sorted(shared)[:4])) if shared else ("Вы из одного города" if mine[2].casefold()==prof[2].casefold() else "Возможно, у вас найдётся что-то общее")
    await message.answer("LUMI Moment · знакомство дня\n"+explanation+"\n\nОдно предложение на день. Завтра появится новое.")
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Нравится",callback_data=f"like:{target}"),InlineKeyboardButton(text="Пропустить",callback_data=f"skip:{target}")]])
    with connect_db() as db:
        mark_profile_view(db,uid,target)
    await send_profile(message,prof,keyboard=kb,user_id=target)


@dp.message(Command("duo"))
@dp.message(F.text == "LUMI Duo")
@dp.message(F.text == "💑 Duo")
async def duo_menu(message: Message):
    await message.answer("💜 Новые приключения теперь в LUMI GAMES. "
                         "Если старое задание уже начато, его можно завершить через /duoanswer.",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[[game_button()]]))


@dp.callback_query(F.data.startswith("duostart:"))
async def duo_start(callback: CallbackQuery):
    await callback.answer()
    if callback.message:
        await duo_menu(callback.message)


@dp.message(Command("duoanswer"))
async def duo_answer(message: Message):
    uid=message.from_user.id
    text=(message.text or '').partition(' ')[2].strip()
    if not 1<=len(text)<=250:
        await message.answer("Напиши /duoanswer и ответ длиной до 250 символов."); return
    def transaction():
        with connect_db() as db:
            db.execute("BEGIN IMMEDIATE")
            sessions=db.execute("SELECT user_a,user_b,step,text_a,text_b FROM duo_adventures WHERE (user_a=? OR user_b=?) AND step<3",(uid,uid)).fetchall()
            sessions=[r for r in sessions if is_match(db,r[0],r[1]) and all(eligible_for_reward(db, person) for person in r[:2])]
            if len(sessions)!=1:
                return False, 'Нет одного доступного незавершённого задания Duo. Новые игры — /games.'
            a,b,step,ta,tb=sessions[0]
            if (ta if uid==a else tb) is not None:
                return False, 'Ты уже ответил(а). Ждём партнёра.'
            field='text_a' if uid==a else 'text_b'
            db.execute("UPDATE duo_adventures SET text_a=? WHERE user_a=? AND user_b=?" if field=='text_a' else "UPDATE duo_adventures SET text_b=? WHERE user_a=? AND user_b=?",(text,a,b))
            ta,tb=db.execute("SELECT text_a,text_b FROM duo_adventures WHERE user_a=? AND user_b=?",(a,b)).fetchone()
            ready=ta is not None and tb is not None
            if ready: db.execute("UPDATE duo_adventures SET step=step+1,text_a=NULL,text_b=NULL WHERE user_a=? AND user_b=?",(a,b))
            granted = False
            if ready and step == 2:
                # Completion and reward must commit or roll back together.
                granted = db.execute("INSERT OR IGNORE INTO duo_quest_rewards(user_a,user_b) VALUES (?,?)",(a,b)).rowcount
                if granted:
                    for person in (a,b):
                        if arena_get(db,person):
                            arena_add_xp(db,person,60)
                        arena_award(db,person,"duo1")
        return True, (a,b,step,ta,tb,ready,granted)
    ok, payload = await asyncio.to_thread(transaction)
    if not ok:
        await message.answer(payload)
        return
    a,b,step,ta,tb,ready,granted = payload
    if not ready:
        await message.answer("Ответ принят. Ждём партнёра."); return
    for person in (a,b):
        try:
            await message.bot.send_message(person,f"Задание {step+1}/3 завершено!\nОтвет первого: {ta}\nОтвет второго: {tb}")
            if step<2: await message.bot.send_message(person,f"Следующее задание: {DUO_PROMPTS[step+1]}\nОтветь: /duoanswer твой ответ")
            else: await message.bot.send_message(person,"💞 Вы прошли все три задания LUMI Duo!" + ("\n🎁 +60 EXP каждому герою и достижение!" if granted else "\nНаграда за эту пару уже получена."))
        except TelegramAPIError: pass


@dp.message(Command("duoreset"))
async def duo_reset(message: Message):
    uid=message.from_user.id
    with connect_db() as db:
        rows=db.execute("SELECT user_a,user_b FROM duo_adventures WHERE user_a=? OR user_b=?",(uid,uid)).fetchall()
        db.execute("DELETE FROM duo_adventures WHERE user_a=? OR user_b=?",(uid,uid))
    for a,b in rows:
        other=b if uid==a else a
        try: await message.bot.send_message(other,"Партнёр завершил приключение Duo. Новые игры — /games.")
        except TelegramAPIError: pass
    await message.answer("Приключения Duo сброшены.")



# LUMI PET 12.0 — игровая система, не влияет на поиск и реальные симпатии.
PET_COLORS = {
    "classic": ("Классический", 1, "Обычный"),
    "cloud": ("Облачный", 2, "Обычный"),
    "lavender": ("Лавандовый", 5, "Необычный"),
    "mint": ("Мятный", 8, "Необычный"),
    "star": ("Звёздный", 12, "Редкий"),
    "ice": ("Ледяной", 16, "Редкий"),
    "volcano": ("Вулканический", 20, "Эпический"),
    "forest": ("Лесной", 24, "Эпический"),
    "neon": ("Неоновый", 28, "Эпический"),
    "cosmos": ("Космический", 32, "Легендарный"),
    "sun": ("Солнечный", 36, "Легендарный"),
    "moon": ("Лунный", 40, "Легендарный"),
    "blackhole": ("Чёрная дыра", 45, "Секретный"),
}
PET_SPECIES = {"lumik": "Лумик", "ghost": "Призрак", "cat": "Котик", "slime": "Космический слизень"}
PET_RANKS = [(1,"Малыш"),(6,"Искатель"),(16,"Хранитель"),(31,"Легенда")]


def pet_now():
    return datetime.now(timezone.utc)


def pet_time(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def pet_ready(last, hours):
    previous=pet_time(last)
    return previous is None or pet_now()-previous >= timedelta(hours=hours)


def pet_get(db, uid):
    return db.execute("SELECT species,name,level,xp,coins,food,mood,color,last_daily,last_feed,last_play,last_care FROM lumi_pets WHERE user_id=?",(uid,)).fetchone()


def pet_level(db, uid, points):
    row=db.execute("SELECT level,xp FROM lumi_pets WHERE user_id=?",(uid,)).fetchone()
    if not row: return 0
    level,xp=row
    xp+=points
    gained=0
    while xp >= 40 + level*20:
        xp-=40+level*20
        level+=1
        gained+=1
    db.execute("UPDATE lumi_pets SET level=?,xp=?,coins=coins+? WHERE user_id=?",(level,xp,gained*20,uid))
    for color,(_,minimum,_) in PET_COLORS.items():
        if level>=minimum and color!="blackhole":
            db.execute("INSERT OR IGNORE INTO lumi_pet_colors(user_id,color) VALUES(?,?)",(uid,color))
    return gained


def pet_keyboard():
    """Telegram-native touch targets: two columns, short labels, no tiny icon-only actions."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍓 Покормить · 5", callback_data="pet:feed"),
         InlineKeyboardButton(text="💜 Погладить", callback_data="pet:care")],
        [InlineKeyboardButton(text="🎮 Поиграть", callback_data="pet:play"),
         InlineKeyboardButton(text="🎁 Награда дня", callback_data="pet:daily")],
        [InlineKeyboardButton(text="🎨 Окрасы", callback_data="pet:colors"),
         InlineKeyboardButton(text="✏️ Имя", callback_data="pet:rename")],
    ])


def pet_view(row):
    species, name, level, xp, coins, food, mood, color, *_ = row
    rank = next(title for min_level, title in reversed(PET_RANKS) if level >= min_level)
    needed = 40 + level * 20
    return (f"LUMI PET · {name}\n{PET_SPECIES.get(species, species)} · {rank} · уровень {level}\n"
            f"{PET_COLORS.get(color, PET_COLORS['classic'])[0]} · {coins} монет\n"
            f"Сытость {food}/100 · Настроение {mood}/100 · Опыт {xp}/{needed}")


PET_IMAGE_DIR = Path(__file__).resolve().parent / "pets"
PET_IMAGE_COLORS = {"classic", "star", "ice", "volcano", "cosmos", "blackhole"}
PET_ACCENTS = {
    "classic": (205, 108, 255), "cloud": (164, 196, 255),
    "lavender": (192, 145, 255), "mint": (91, 231, 192),
    "star": (245, 156, 255), "ice": (111, 206, 255),
    "volcano": (255, 112, 130), "forest": (112, 228, 151),
    "neon": (137, 255, 106), "cosmos": (142, 133, 255),
    "sun": (255, 202, 102), "moon": (169, 184, 255),
    "blackhole": (225, 117, 244),
}


def pet_art_path(species, color):
    """All species have art; non-dragon colors reuse base 3D art with a color treatment."""
    exact = PET_IMAGE_DIR / f"{species}_{color}.jpg"
    if exact.is_file():
        return exact
    base = PET_IMAGE_DIR / f"{species}_classic.jpg"
    return base if base.is_file() else None


def pet_card_image(image_path: Path, row) -> bytes:
    """LUMI PET 2026: original 3D pet artwork + live, mobile-friendly UI."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
    import math

    species, name, level, xp, coins, food, mood, color, *_ = row
    color = color if color in PET_COLORS else 'classic'
    rank = next(title for minimum, title in reversed(PET_RANKS) if level >= minimum)
    W, H, ART_H = 900, 1250, 720
    base = Image.new('RGB', (W, H), '#0D0820')
    with Image.open(image_path) as original:
        original = original.convert('RGB')
        # Preserve the existing 3D figure; crop only for the card's portrait format.
        if species == 'lumik' and original.height > original.width:
            original = original.crop((0, 0, original.width, int(original.height * .84)))
        art = ImageOps.fit(original, (W, ART_H), method=Image.Resampling.LANCZOS,
                           centering=(.5, .45))
    base.paste(art, (0, 0))
    # Darken the edges slightly, leaving the character untouched.
    fade = Image.new('RGBA', (W, ART_H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fade)
    for y in range(ART_H):
        top = int(115 * max(0, 1-y/170))
        bottom = int(250 * max(0, (y-(ART_H-180))/180))
        alpha = max(top, bottom)
        if alpha: fd.line((0,y,W,y), fill=(10,5,27,alpha))
    base.paste(fade,(0,0),fade)
    canvas=base.convert('RGBA')
    # The status section is an integrated part of the collectible card.
    panel=Image.new('RGBA',(W,H),(0,0,0,0)); pd=ImageDraw.Draw(panel)
    pd.rounded_rectangle((23,ART_H-15,W-23,H-22),radius=44,fill=(17,10,38,252),outline=(147,70,229,255),width=3)
    pd.rounded_rectangle((31,ART_H-7,W-31,H-30),radius=39,outline=(82,48,139,255),width=2)
    glow=panel.filter(ImageFilter.GaussianBlur(22))
    canvas=Image.alpha_composite(canvas,glow)
    canvas=Image.alpha_composite(canvas,panel)
    draw=ImageDraw.Draw(canvas)
    paths={
      'heavy':['C:/Windows/Fonts/arialbd.ttf','C:/Windows/Fonts/segoeuib.ttf',
               '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'],
      'regular':['C:/Windows/Fonts/segoeui.ttf','C:/Windows/Fonts/arial.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']}
    def font(size,weight='regular'):
        for path in paths[weight]:
            try:return ImageFont.truetype(path,size)
            except OSError:pass
        return ImageFont.load_default()
    def text_width(t,f):
        box=draw.textbbox((0,0),t,font=f);return box[2]-box[0]
    def fit(t,maximum,size,minimum=20):
        while size>minimum and text_width(t,font(size,'heavy'))>maximum:size-=2
        return font(size,'heavy')
    def gradient_text(t,x,y,f,left=(245,117,255),right=(116,204,255)):
        box=draw.textbbox((0,0),t,font=f,stroke_width=0)
        tw=max(1,box[2]-box[0]);th=max(1,box[3]-box[1])
        mask=Image.new('L',(tw+8,th+12),0);md=ImageDraw.Draw(mask)
        md.text((4-box[0],4-box[1]),t,font=f,fill=255)
        grad=Image.new('RGBA',mask.size);pixels=grad.load()
        for xx in range(grad.width):
            q=xx/max(1,grad.width-1)
            rgb=tuple(int(left[i]*(1-q)+right[i]*q) for i in range(3))
            for yy in range(grad.height):pixels[xx,yy]=(*rgb,255)
        canvas.paste(grad,(x-4,y+box[1]-4),mask)
    def rounded(xy,fill,radius=20,outline=None,width=2):
        draw.rounded_rectangle(xy,radius=radius,fill=fill,outline=outline,width=width)
    def coin(cx,cy,r):
        # Metallic stacked collectible coins, not a separate plain emoji.
        for dx,dy,scale in [(-22,18,.84),(20,13,.9),(0,-3,1.0)]:
            rr=int(r*scale);xx=cx+dx;yy=cy+dy
            draw.ellipse((xx-rr,yy-rr+10,xx+rr,yy+rr+10),fill='#9E3E1B',outline='#F9B448',width=4)
            draw.ellipse((xx-rr,yy-rr,xx+rr,yy+rr),fill='#F7A532',outline='#FFE79B',width=5)
            draw.ellipse((xx-rr+8,yy-rr+8,xx+rr-8,yy+rr-8),outline='#D9682E',width=4)
            # star polygon
            pts=[]
            for j in range(10):
                angle=-math.pi/2+j*math.pi/5;radius=rr*(.49 if j%2==0 else .23)
                pts.append((xx+math.cos(angle)*radius,yy+math.sin(angle)*radius))
            draw.polygon(pts,fill='#FFF0BA')
    # Art overlay labels
    draw.text((53,38),'LUMI',font=font(39,'heavy'),fill='#FFFFFF',stroke_width=1,stroke_fill='#C956FF')
    draw.text((55,89),'PET COLLECTION',font=font(18,'heavy'),fill='#E6B9FF')
    rounded((W-235,43,W-52,107),(25,13,56,226),32,(195,94,255,255),3)
    lvl=f'LVL {level}'
    draw.text((W-143,74),lvl,font=fit(lvl,153,33),anchor='mm',fill='#FFFFFF')
    # Primary name and coin balance
    petname=str(name).strip() or PET_SPECIES.get(species,'Лумик')
    if len(petname)>24:petname=petname[:23]+'…'
    nf=fit(petname.upper(),565,73,30)
    gradient_text(petname.upper(),65,ART_H+25,nf)
    rounded((624,ART_H+31,831,ART_H+118),(52,22,91,255),42,(217,100,250,255),3)
    coin(667,ART_H+72,27)
    amount=str(coins)
    draw.text((756,ART_H+73),amount,font=fit(amount,104,42,23),anchor='mm',fill='#FFFFFF')
    species_text=PET_SPECIES.get(species,species).upper()
    subtitle=f'{species_text}   /   {rank.upper()}   /   {PET_COLORS[color][0].upper()}'
    sf=fit(subtitle,760,22,15)
    draw.text((66,ART_H+120),subtitle,font=sf,fill='#C9B7E9')
    # High contrast bold labels and tabular values; simple rounded tracks.
    rows=[('СЫТОСТЬ',food,100,('#965BFF','#E2A1FF')),
          ('НАСТРОЕНИЕ',mood,100,('#EE59C6','#FFB4E7')),
          ('ОПЫТ',xp,40+level*20,('#38A6FF','#79E8FF'))]
    for idx,(label,value,maximum,colors) in enumerate(rows):
        y=ART_H+185+idx*111
        draw.text((66,y),label,font=font(28,'heavy'),fill='#F8F3FF')
        count=f'{value} / {maximum}'
        draw.text((832,y+1),count,font=font(29,'heavy'),anchor='ra',fill='#FFFFFF')
        left,right=66,832;by=y+53;bh=24
        rounded((left,by,right,by+bh),(62,42,89,255),12)
        frac=max(0,min(1,float(value)/max(1,maximum)))
        if frac:
            width=max(bh,round((right-left)*frac))
            rounded((left,by,left+width,by+bh),colors[0],12)
            draw.rounded_rectangle((left+4,by+3,left+width-4,by+9),radius=4,fill=colors[1]) if width>20 else None
    draw.line((67,H-57,831,H-57),fill=(102,61,155,255),width=2)
    draw.text((68,H-44),'LUMI  /  YOUR LITTLE UNIVERSE',font=font(18,'heavy'),fill='#C895ED')
    output=BytesIO();canvas.convert('RGB').save(output,format='JPEG',quality=92,optimize=True)
    return output.getvalue()


async def pet_send_card(message: Message, row, prefix=''):
    species, _, _, _, _, _, _, color, *_ = row
    image = pet_art_path(species,color)
    if image is not None:
        try:
            card=pet_card_image(image,row)
            await message.answer_photo(
                BufferedInputFile(card,filename='lumi_pet.jpg'),
                caption=prefix or None,reply_markup=pet_keyboard())
            return
        except (ImportError,OSError,ValueError,TelegramAPIError):
            logger.exception('Не удалось создать или отправить карточку питомца')
    caption=(prefix+'\n\n' if prefix else '')+pet_view(row)
    await message.answer(caption,reply_markup=pet_keyboard())


class PetRename(StatesGroup):
    name = State()


@dp.message(Command("pet"))
@dp.message(F.text == "Мой Лумик")
async def pet_home(message: Message):
    """Обратная совместимость: старый /pet открывает общую коллекцию героев."""
    await arena_home(message)


# Старые inline-кнопки питомцев могут оставаться в истории Telegram.
# Они открывают новую систему и больше не меняют устаревшую таблицу lumi_pets.
@dp.callback_query(F.data.startswith(("petchoose:", "pet:", "petcolor:")))
async def legacy_pet_button(callback: CallbackQuery):
    await callback.answer("Питомцы переехали в «⚔️ Мои герои»")
    if not profile_of(callback.from_user.id):
        await callback.message.answer("Сначала создай анкету LUMI.", reply_markup=menu)
        return
    await arena_show(callback.message, callback.from_user.id)


@dp.message(PetRename.name)
async def legacy_pet_rename(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Теперь персонажи живут в разделе «⚔️ Мои герои».", reply_markup=menu)
    await arena_home(message)


@dp.message(Command("petsecret"))
async def legacy_pet_secret(message: Message):
    await message.answer("Секретные окрасы старых питомцев сохранены, но теперь основная коллекция — 21 герой.")
    await arena_home(message)


# LUMI HEROES — основной раздел персонажей; старые питомцы сохранены в базе для совместимости.
# Файлы hero_01.png ... hero_21.png кладутся в папку heroes рядом с bot.py.
ARENA_HEROES = (
    ("Воин", "Воин"), ("Ниндзя", "Элита"), ("Ниндзя 2", "Мастер"),
    ("Маг", "Грандмастер"), ("Воительница", "Эпик"), ("Король", "Легенда"),
    ("Рыцарь-новичок", "Воин"), ("Синий рыцарь", "Элита"),
    ("Мечник", "Мастер"), ("Командир", "Грандмастер"),
    ("Золотой защитник", "Эпик"), ("Королевский паладин", "Легенда"),
    ("Мифический рыцарь", "Мифический"), ("Тигр-самурай", "Эпик"),
    ("Чёрный дракон", "Мифический"), ("Тёмная эльфийка", "Грандмастер"),
    ("Золотой грифон", "Эпик"), ("Единорожка-принцесса", "Легенда"),
    ("Волшебница с котиками", "Мифический"), ("Белый дракончик", "Легенда"),
    ("Снежный барсёнок", "Мастер"),
)
ARENA_RANKS = ((0, "Воин"), (100, "Элита"), (250, "Мастер"),
               (450, "Грандмастер"), (700, "Эпик"),
               (1050, "Легенда"), (1500, "Мифический"))
ARENA_HERO_DIR = Path(__file__).resolve().parent / "heroes"

# Финальная последовательность открытия, утверждённая для LUMI HEROES 2.0.
# Герои «Элита» открываются с Грандмастером, поскольку отдельного
# порога Элиты в выбранной последовательности нет.
HERO_UNLOCK_XP = {
    "Воин": 0, "Элита": 1500, "Грандмастер": 1500,
    "Эпик": 5000, "Легенда": 12000,
    "Мифический": 25000, "Мастер": 50000,
}
HERO_UNLOCK_STAGES = (
    (0, "Воин", 1),
    (1500, "Грандмастер (+ Элита)", 10),
    (5000, "Эпик", 20),
    (12000, "Легенда", 35),
    (25000, "Мифический", 50),
    (50000, "Мастер", 75),
)


def arena_account_xp(db, uid):
    row = db.execute("SELECT total_xp FROM arena_account_progress WHERE user_id=?", (uid,)).fetchone()
    return max(0, int(row[0])) if row else 0


def arena_unlocked(db, uid, hero_id):
    if not 1 <= hero_id <= len(ARENA_HEROES):
        return False
    # Сохраняем только активного персонажа у существующих пользователей;
    # исторический инвентарь не должен обходить новые замки.
    current = arena_get(db, uid)
    if current and current[0] == hero_id:
        return True
    return arena_account_xp(db, uid) >= HERO_UNLOCK_XP[ARENA_HEROES[hero_id-1][1]]


def arena_next_unlock(total):
    return next(((xp, title, lvl) for xp, title, lvl in HERO_UNLOCK_STAGES if xp > total), None)



def arena_rank(rating):
    return next(name for threshold, name in reversed(ARENA_RANKS) if rating >= threshold)


def arena_need(level):
    return 50 + 25 * level + 5 * level * level


def arena_get(db, uid):
    return db.execute("SELECT hero_id,level,xp,rating,wins,losses,draws,last_daily "
                      "FROM arena_heroes WHERE user_id=?", (uid,)).fetchone()


def arena_add_xp(db, uid, points):
    row = arena_get(db, uid)
    if row is None:
        return
    hero_id = row[0]
    db.execute("INSERT OR IGNORE INTO arena_collection(user_id,hero_id) VALUES (?,?)", (uid,hero_id))
    level, xp = db.execute("SELECT level,xp FROM arena_collection WHERE user_id=? AND hero_id=?",
                           (uid,hero_id)).fetchone()
    xp += points
    while xp >= arena_need(level):
        xp -= arena_need(level)
        level += 1
    db.execute("UPDATE arena_collection SET level=?,xp=? WHERE user_id=? AND hero_id=?",
               (level,xp,uid,hero_id))
    db.execute("UPDATE arena_heroes SET level=?,xp=? WHERE user_id=?", (level,xp,uid))
    db.execute("INSERT INTO arena_account_progress(user_id,total_xp) VALUES (?,?) "
               "ON CONFLICT(user_id) DO UPDATE SET total_xp=total_xp+excluded.total_xp",
               (uid, max(0, int(points))))
    arena_award(db, uid, "level10" if level >= 10 else "", level >= 10)
    arena_award(db, uid, "level25" if level >= 25 else "", level >= 25)


def arena_award(db, uid, code, condition=True):
    if code and condition:
        db.execute("INSERT OR IGNORE INTO arena_achievements(user_id,code) VALUES(?,?)",(uid,code))


def arena_season():
    # Сезоны по UTC-календарю: YYYY-MM.
    return datetime.now(timezone.utc).strftime("%Y-%m")


def arena_evolution(level):
    if level >= 50: return "👑 Королевская эволюция · сияющая аура"
    if level >= 30: return "✨ Эпическая эволюция · золотая рамка"
    if level >= 15: return "💎 Продвинутая эволюция · магическая аура"
    if level >= 5: return "⚔️ Первая эволюция · серебряная рамка"
    return "🌱 Базовая форма"


def arena_power(row):
    # Уровень даёт преимущество, но победа не гарантирована.
    return 100 + 15 * row[1] + min(row[3], 1500) // 20


@byte_cache(max_bytes=24 * 1024 * 1024, max_entries=96)
def _cached_arena_card_image(source_name: str, image_mtime_ns: int, tier: int) -> bytes:
    """Rendered card bytes; no user-specific values are cached."""
    from PIL import Image, ImageDraw
    source = Path(source_name)
    with Image.open(source) as original:
        img = original.convert("RGB")
        thickness = max(7, img.width // 38)
        colors = ((115, 93, 77), (188, 199, 220), (157, 117, 220), (225, 185, 73))
        canvas = Image.new("RGB", (img.width + thickness * 2, img.height + thickness * 2), colors[tier])
        canvas.paste(img, (thickness, thickness))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle(
            (thickness // 2, thickness // 2, canvas.width - thickness // 2 - 1,
             canvas.height - thickness // 2 - 1),
            outline=(255, 237, 190), width=max(2, thickness // 5),
        )
        out = BytesIO()
        canvas.save(out, format="PNG", optimize=False)
        return out.getvalue()


def arena_card_art(hero_id, level):
    """Return photo art; rendering is cached per hero, source version and frame tier."""
    source = ARENA_HERO_DIR / f"hero_{hero_id:02d}.png"
    if not source.is_file():
        return None
    tier = 3 if level >= 30 else (2 if level >= 15 else (1 if level >= 5 else 0))
    try:
        image = _cached_arena_card_image(str(source), source.stat().st_mtime_ns, tier)
        return BufferedInputFile(image, filename=f"hero_{hero_id:02d}_evolved.png")
    except (ImportError, OSError, ValueError):
        logger.exception("Не удалось создать рамку героя")
        return FSInputFile(source)


def arena_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Тренировка", callback_data="arena:daily")],
        [InlineKeyboardButton(text="🔄 Сменить героя", callback_data="arena:select:0"),
         InlineKeyboardButton(text="🖼 Все герои", callback_data="arena:gallery")],
        [InlineKeyboardButton(text="❔ Как играть", callback_data="arena:help")],
        [InlineKeyboardButton(text="🏆 Достижения", callback_data="arena:achievements"),
         InlineKeyboardButton(text="📅 Сезон", callback_data="arena:season")],
        [game_button()],
        [InlineKeyboardButton(text="💞 Мои совпадения", callback_data="arena:matches")],
        [InlineKeyboardButton(text="🏠 Домой", callback_data="nav:home")],
    ])


async def arena_show(message, uid, prefix=""):
    with connect_db() as db:
        row = arena_get(db, uid)
    if row is None:
        await arena_select(message)
        return
    hero_id, level, xp, rating, wins, losses, draws, _ = row
    name, rarity = ARENA_HEROES[hero_id - 1]
    with connect_db() as db:
        total_exp = arena_account_xp(db, uid)
        referral_frame = has_referral_frame(db, uid)
    upcoming = arena_next_unlock(total_exp)
    unlock_line = (f"🔓 <b>Следующий ранг:</b> {ui_safe(upcoming[1], 50)} — "
                   f"осталось {upcoming[0] - total_exp:,} EXP\n" if upcoming else
                   "🏆 <b>Открыты все ранги!</b>\n")
    top = f"{ui_safe(prefix, 160)}\n\n" if prefix else ""
    caption = (
        f"{top}⚔️ <b>МОЙ ГЕРОЙ</b>\n\n"
        f"<b>{ui_safe(name, 70)}</b>  ·  {ui_safe(rarity, 40)}\n"
        f"✨ <b>Уровень героя:</b> {level}\n\n"
        f"📈 <b>Опыт:</b> {xp} / {arena_need(level)} EXP\n"
        f"🌟 <b>Общий EXP:</b> {total_exp:,}\n"
        f"{unlock_line}"
        f"🏆 <b>Рейтинг:</b> {rating}\n"
        f"⚔️ <b>Победы:</b> {wins}  ·  <b>Поражения:</b> {losses}\n"
        + ("💜 <b>Эксклюзивная рамка: Сердце LUMI</b>\n" if referral_frame else "") +
        f"💎 <b>Эволюция:</b> {ui_safe(arena_evolution(level), 80)}\n\n"
        "<i>Прокачивай героя и открывай новые ранги.</i>"
    )
    art = ARENA_HERO_DIR / f"hero_{hero_id:02d}.png"
    if art.is_file():
        try:
            await message.answer_photo(await asyncio.to_thread(arena_card_art, hero_id, level), caption=caption, reply_markup=arena_keyboard(), parse_mode="HTML")
            return
        except TelegramAPIError:
            logger.exception("Не удалось отправить изображение героя %s", art)
    await message.answer(caption, reply_markup=arena_keyboard(), parse_mode="HTML")


async def arena_select(message, page=0, edit=False):
    page=max(0,min(page,(len(ARENA_HEROES)-1)//5))
    with connect_db() as db:
        uid=message.chat.id
        selected=arena_get(db,uid)
        total_exp=arena_account_xp(db,uid)
        access={i: arena_unlocked(db,uid,i) for i in range(1,len(ARENA_HEROES)+1)}
    start=page*5
    buttons=[[InlineKeyboardButton(text=f"{i:02d}. {name}" +
                                       (" ✅" if selected and selected[0]==i else
                                        " 🔒" if not access[i] else " 🔓"),
                          callback_data=f"arena:preview:{i}")]
             for i,(name,rarity) in enumerate(ARENA_HEROES,1) if start < i <= start+5]
    nav=[]
    if page>0: nav.append(InlineKeyboardButton(text="◀️",callback_data=f"arena:select:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{(len(ARENA_HEROES)+4)//5}",callback_data="arena:noop"))
    if start+5<len(ARENA_HEROES): nav.append(InlineKeyboardButton(text="▶️",callback_data=f"arena:select:{page+1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="🖼 Посмотреть всех на одном фото", callback_data="arena:gallery")])
    buttons.append([InlineKeyboardButton(text="❔ Как играть", callback_data="arena:help")])
    buttons.append([InlineKeyboardButton(text="⬅️ К моему герою", callback_data="arena:home"),
                    InlineKeyboardButton(text="🏠 Домой", callback_data="nav:home")])
    text = ("⚔️ <b>КОЛЛЕКЦИЯ ГЕРОЕВ</b>\n\n"
            "21 персонаж · у каждого свой EXP и уровень.\n"
            f"🌟 <b>Общий EXP:</b> {total_exp:,}\n"
            + (f"🔓 <b>Далее:</b> {ui_safe(arena_next_unlock(total_exp)[1], 50)} "
               f"через {arena_next_unlock(total_exp)[0]-total_exp:,} EXP\n\n"
               if arena_next_unlock(total_exp) else "🏆 Все ранги открыты!\n\n")
            + "<i>🔒 Закрыто · 🔓 Доступно · ✅ Выбрано. Нажми на героя.</i>")
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    if edit:
        try:
            await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
            return
        except TelegramAPIError as exc:
            if "message is not modified" in str(exc).lower():
                return
            logger.info("Не удалось обновить страницу коллекции: %s", exc)
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


@dp.message(Command("arena"))
@dp.message(Command("heroes"))
@dp.message(F.text == "LUMI ARENA")
@dp.message(F.text == "⚔️ Мои герои")
async def arena_home(message: Message):
    if not profile_of(message.from_user.id):
        await message.answer("Сначала создай анкету LUMI.", reply_markup=menu)
        return
    with connect_db() as db:
        first_visit = db.execute("INSERT OR IGNORE INTO arena_intro(user_id) VALUES (?)",
                                 (message.from_user.id,)).rowcount == 1
    if first_visit:
        await arena_send_gallery(message, intro=True)
        await arena_select(message, 0)
    else:
        await arena_show(message, message.from_user.id)


HERO_HELP = (
    "⚔️ <b>ЗАЧЕМ НУЖНЫ ГЕРОИ?</b>\n\n"
    "LUMI — это знакомства. Герои помогают превратить взаимную симпатию в весёлое общение. 💜\n\n"
    "<b>1. Выбери героя.</b> Посмотри всех 21 персонажа в галерее.\n"
    "<b>2. Прокачивай.</b> За ежедневную тренировку и участие в битвах получай EXP. "
    "У каждого персонажа свой уровень.\n"
    "<b>3. Найди взаимную симпатию.</b> После совпадения можешь пригласить человека на добровольную битву.\n"
    "<b>4. Общайся.</b> Победа не важнее знакомства: после боя можно начать разговор.\n\n"
    "<b>Как открывать героев:</b> Воин → Грандмастер → Эпик → Легенда → Мифический → Мастер. "
    "Элита открывается вместе с Грандмастером. "
    "Для этого накапливай общий EXP аккаунта; каждый герой тренируется отдельно.\n\n"
    "<i>Участие необязательно — знакомиться можно и без игры.</i>"
)


def hero_guide_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼 Посмотреть всех героев", callback_data="arena:gallery")],
        [InlineKeyboardButton(text="🔄 Выбрать персонажа", callback_data="arena:select:0")],
        [InlineKeyboardButton(text="⬅️ К моему герою", callback_data="arena:home")],
        [InlineKeyboardButton(text="🏠 Домой", callback_data="nav:home")],
    ])


async def arena_send_gallery(message, intro=False):
    path = ARENA_HERO_DIR / "all_heroes.jpg"
    caption = ("💜 <b>ПОЗНАКОМЬСЯ С ГЕРОЯМИ LUMI</b>\n\n"
               if intro else "🖼 <b>ВСЕ 21 ГЕРОЙ LUMI</b>\n\n")
    caption += ("В галерее можно посмотреть всех героев. Для выбора редких "
                "персонажей сначала накопи общий EXP аккаунта.\n"
                "А после взаимного лайка можно пригласить человека на дружескую битву!\n\n"
                "<i>Цифры на картинке соответствуют номерам в коллекции.</i>")
    if path.is_file():
        await message.answer_photo(FSInputFile(path), caption=caption,
                                   parse_mode="HTML", reply_markup=hero_guide_keyboard())
    else:
        await message.answer("Галерея временно недоступна. "
                             "Проверь файл heroes/all_heroes.jpg.\n\n" + caption,
                             parse_mode="HTML", reply_markup=hero_guide_keyboard())


@dp.message(Command("gallery"))
@dp.callback_query(F.data == "arena:gallery")
async def arena_gallery(event):
    if isinstance(event, CallbackQuery):
        await event.answer()
        if not profile_of(event.from_user.id):
            await event.message.answer("Сначала создай анкету LUMI.")
            return
        await arena_send_gallery(event.message)
    else:
        if not profile_of(event.from_user.id):
            await event.answer("Сначала создай анкету LUMI.")
            return
        await arena_send_gallery(event)


@dp.message(Command("howheroes"))
@dp.callback_query(F.data == "arena:help")
async def arena_guide(event):
    if isinstance(event, CallbackQuery):
        await event.answer()
        msg = event.message
    else:
        msg = event
    await msg.answer(HERO_HELP, parse_mode="HTML", reply_markup=hero_guide_keyboard())


@dp.callback_query(F.data == "arena:home")
async def arena_from_inline(callback: CallbackQuery):
    await callback.answer()
    if not profile_of(callback.from_user.id):
        await callback.message.answer("Сначала создай анкету LUMI.")
        return
    await arena_show(callback.message, callback.from_user.id)


@dp.callback_query(F.data == "arena:noop")
async def arena_noop(callback: CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data.startswith("arena:select"))
async def arena_select_callback(callback: CallbackQuery):
    await callback.answer()
    try: page=int(callback.data.rsplit(":",1)[1])
    except ValueError: page=0
    await arena_select(callback.message,page,edit=True)


@dp.callback_query(F.data.startswith("arena:preview:"))
async def arena_preview(callback: CallbackQuery):
    try: hero_id=int(callback.data.rsplit(":",1)[1])
    except ValueError:
        await callback.answer("Некорректный герой",show_alert=True)
        return
    if hero_id<1 or hero_id>len(ARENA_HEROES) or not profile_of(callback.from_user.id):
        await callback.answer("Герой недоступен",show_alert=True)
        return
    with connect_db() as db:
        old=db.execute("SELECT level,xp FROM arena_collection WHERE user_id=? AND hero_id=?",(callback.from_user.id,hero_id)).fetchone()
    name,rarity=ARENA_HEROES[hero_id-1]
    with connect_db() as db:
        available=arena_unlocked(db, callback.from_user.id, hero_id)
        total_exp=arena_account_xp(db, callback.from_user.id)
    required=HERO_UNLOCK_XP[rarity]
    lvl,xp=old or (1,0)
    await callback.answer()
    art=ARENA_HERO_DIR/f"hero_{hero_id:02d}.png"
    msg=(f"⚔️ <b>{ui_safe(name, 70)}</b>\n"
         f"💎 {ui_safe(rarity, 40)}  ·  <b>LVL {lvl}</b>\n"
         f"📈 EXP: {xp} / {arena_need(lvl)}\n\n"
         + ("<i>Герой доступен. Сделать его активным?</i>" if available else
          f"🔒 <b>Закрыто</b> · нужно {required:,} общего EXP.\n"
          f"Осталось: {max(0,required-total_exp):,} EXP."))
    rows=[]
    if available:
        rows.append([InlineKeyboardButton(text="✅ Выбрать героя",callback_data=f"arena:choose:{hero_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ К героям",callback_data=f"arena:select:{(hero_id-1)//5}")])
    rows.append([InlineKeyboardButton(text="🏠 Домой",callback_data="nav:home")])
    kb=InlineKeyboardMarkup(inline_keyboard=rows)
    if art.is_file(): await callback.message.answer_photo(FSInputFile(art),caption=msg,reply_markup=kb,parse_mode="HTML")
    else: await callback.message.answer(msg,reply_markup=kb,parse_mode="HTML")


@dp.callback_query(F.data.startswith("arena:choose:"))
async def arena_choose(callback: CallbackQuery):
    try:
        hero_id = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный герой", show_alert=True)
        return
    if not 1 <= hero_id <= len(ARENA_HEROES) or not profile_of(callback.from_user.id):
        await callback.answer("Герой недоступен", show_alert=True)
        return
    with connect_db() as db:
        uid = callback.from_user.id
        # Проверка на сервере: старые / поддельные callback_data не обходят замки.
        if not arena_unlocked(db, uid, hero_id):
            required = HERO_UNLOCK_XP[ARENA_HEROES[hero_id-1][1]]
            remain = max(0, required - arena_account_xp(db, uid))
            await callback.answer(f"🔒 Ранг закрыт. Осталось {remain:,} EXP.", show_alert=True)
            return
        db.execute("INSERT OR IGNORE INTO arena_collection(user_id,hero_id) VALUES (?,?)", (uid,hero_id))
        level,xp = db.execute("SELECT level,xp FROM arena_collection WHERE user_id=? AND hero_id=?", (uid,hero_id)).fetchone()
        db.execute("INSERT INTO arena_heroes(user_id,hero_id,level,xp) VALUES(?,?,?,?) "
                   "ON CONFLICT(user_id) DO UPDATE SET hero_id=excluded.hero_id,level=excluded.level,xp=excluded.xp",
                   (uid,hero_id,level,xp))
        count = db.execute("SELECT COUNT(*) FROM arena_collection WHERE user_id=?",(uid,)).fetchone()[0]
        arena_award(db,uid,"collector3",count>=3)
        arena_award(db,uid,"collector10",count>=10)
    await callback.answer("Герой выбран")
    await arena_show(callback.message, callback.from_user.id)


@dp.callback_query(F.data == "arena:daily")
async def arena_daily(callback: CallbackQuery):
    uid = callback.from_user.id
    with connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        if not eligible_for_reward(db, uid) or arena_get(db, uid) is None:
            status = None
        else:
            status = claim_training(db, uid)
            if status:
                arena_add_xp(db, uid, 10)
    if status is None:
        await callback.answer("Нужна действующая анкета 18+ и герой", show_alert=True)
        return
    await callback.answer("+10 EXP" if status else "Тренировка уже выполнена сегодня")
    await arena_show(callback.message, uid, "+10 EXP за тренировку!" if status else "Возвращайся завтра.")


@dp.callback_query(F.data == "arena:matches")
async def arena_matches(callback: CallbackQuery):
    await callback.answer()
    await show_matches_page(callback.message, callback.from_user.id)


@dp.callback_query(F.data.startswith("arena:challenge:"))
async def arena_challenge(callback: CallbackQuery):
    try:
        peer = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Неверный вызов", show_alert=True)
        return
    uid = callback.from_user.id
    def transaction():
        with connect_db() as db:
            db.execute("BEGIN IMMEDIATE")
            if not is_match(db, uid, peer) or not all(eligible_for_reward(db, person) for person in (uid, peer)):
                return False, 'Битва доступна только после взаимного лайка'
            if arena_get(db, uid) is None:
                return False, 'Сначала выбери героя в /arena'
            if arena_get(db, peer) is None:
                return False, 'У собеседника пока нет героя'
            db.execute("UPDATE arena_challenges SET status='expired',resolved_at=CURRENT_TIMESTAMP "
                       "WHERE status='pending' AND created_at < datetime('now','-24 hours')")
            # Не больше 3 рейтинговых боёв одной пары за UTC-сутки.
            count = pair_battles_today(db, uid, peer)
            if count >= 3:
                return False, 'Лимит: 3 боя с одним человеком в сутки'
            existing = db.execute("SELECT id FROM arena_challenges WHERE status='pending' "
                                  "AND ((challenger=? AND defender=?) OR (challenger=? AND defender=?))",
                                  (uid,peer,peer,uid)).fetchone()
            if existing:
                return False, 'Вызов уже ожидает ответа'
            cursor = db.execute("INSERT INTO arena_challenges(challenger,defender) VALUES(?,?)", (uid,peer))
            challenge_id = cursor.lastrowid
        return True, challenge_id
    ok, payload = await asyncio.to_thread(transaction)
    if not ok:
        await callback.answer(payload, show_alert=True)
        return
    challenge_id = payload
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Принять бой", callback_data=f"arena:accept:{challenge_id}")],
        [InlineKeyboardButton(text="Не сейчас", callback_data=f"arena:decline:{challenge_id}")],
    ])
    try:
        await callback.bot.send_message(peer, "LUMI ARENA · Тебя вызвали на битву!\n"
                                        "Сражение добровольное, результат не влияет на совпадение.",
                                        reply_markup=keyboard)
    except TelegramAPIError:
        with connect_db() as db:
            db.execute("UPDATE arena_challenges SET status='failed' WHERE id=?", (challenge_id,))
        await callback.answer("Не удалось отправить вызов", show_alert=True)
        return
    await callback.answer("Вызов отправлен")
    await callback.message.answer("Вызов отправлен. Ждём ответа!")


@dp.callback_query(F.data.startswith(("arena:accept:", "arena:decline:")))
async def arena_resolve(callback: CallbackQuery):
    try:
        _, action, raw = callback.data.split(":", 2)
        challenge_id = int(raw)
    except (ValueError, AttributeError):
        await callback.answer("Неверная кнопка", show_alert=True)
        return
    uid = callback.from_user.id
    def transaction():
        with connect_db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE arena_challenges SET status='expired',resolved_at=CURRENT_TIMESTAMP "
                       "WHERE status='pending' AND created_at < datetime('now','-24 hours')")
            challenge = db.execute("SELECT challenger,defender,status FROM arena_challenges WHERE id=?",
                                   (challenge_id,)).fetchone()
            if not challenge or challenge[1] != uid or challenge[2] != 'pending':
                return False, 'Вызов недоступен или уже обработан'
            challenger, defender, _ = challenge
            if not is_match(db, challenger, defender) or not all(eligible_for_reward(db, person) for person in (challenger, defender)):
                db.execute("UPDATE arena_challenges SET status='cancelled' WHERE id=?", (challenge_id,))
                return False, 'Совпадение больше недоступно'
            a, b = arena_get(db, challenger), arena_get(db, defender)
            if not a or not b:
                db.execute("UPDATE arena_challenges SET status='cancelled' WHERE id=?", (challenge_id,))
                return False, 'Один из героев недоступен'
            if action == "accept" and pair_battles_today(db, challenger, defender) >= 3:
                db.execute("UPDATE arena_challenges SET status='cancelled',resolved_at=CURRENT_TIMESTAMP WHERE id=?", (challenge_id,))
                return False, 'Лимит: 3 боя с одним человеком в сутки'
            updated = db.execute("UPDATE arena_challenges SET status=?,resolved_at=CURRENT_TIMESTAMP "
                                 "WHERE id=? AND status='pending'",
                                 ("completed" if action == "accept" else "declined", challenge_id))
            if not updated.rowcount:
                return False, 'Вызов уже обработан'
            if action == "decline":
                result = None
            else:
                # Вероятность ограничена 25–75%, уровень и рейтинг дают преимущество.
                chance_a = max(0.25, min(0.75, 0.5 + (arena_power(a) - arena_power(b)) / 1200))
                winner = challenger if secrets.SystemRandom().random() < chance_a else defender
                loser = defender if winner == challenger else challenger
                db.execute("UPDATE arena_heroes SET wins=wins+1,rating=rating+30 WHERE user_id=?", (winner,))
                db.execute("UPDATE arena_heroes SET losses=losses+1,rating=MAX(0,rating-10) WHERE user_id=?", (loser,))
                arena_add_xp(db, winner, 40)
                arena_add_xp(db, loser, 10)
                db.execute("INSERT OR IGNORE INTO arena_battle_log(challenge_id,winner,loser) VALUES (?,?,?)",(challenge_id,winner,loser))
                season = arena_season()
                db.execute("INSERT INTO arena_season_scores(season,user_id,wins,points) VALUES(?,?,1,30) "
                           "ON CONFLICT(season,user_id) DO UPDATE SET wins=wins+1,points=points+30",(season,winner))
                arena_award(db,winner,"firstwin")
                wins = db.execute("SELECT wins FROM arena_heroes WHERE user_id=?",(winner,)).fetchone()[0]
                arena_award(db,winner,"wins10",wins>=10)
                result = (winner, loser, a, b)
        return True, (challenger,result)
    ok, payload = await asyncio.to_thread(transaction)
    if not ok:
        await callback.answer(payload, show_alert=True)
        return
    challenger,result = payload
    await callback.answer("Бой завершён" if result else "Вызов отклонён")
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
    if result is None:
        await callback.message.answer("Ты отклонил(а) битву. Совпадение остаётся!")
        try:
            await callback.bot.send_message(challenger, "Собеседник пока не готов к битве. Можно просто пообщаться!")
        except TelegramAPIError:
            pass
        return
    winner, loser, a, b = result
    winner_name = ARENA_HEROES[(a if winner == challenger else b)[0] - 1][0]
    loser_name = ARENA_HEROES[(b if winner == challenger else a)[0] - 1][0]
    for player in (winner, loser):
        message = (f"⚔️ LUMI ARENA · Результат\n\n"
                   f"{winner_name} победил {loser_name}!\n"
                   f"{'Победа! +40 EXP, +30 рейтинга' if player == winner else 'Участие: +10 EXP, −10 рейтинга (минимум 0)'}\n\n"
                   "Совпадение остаётся — самое время написать друг другу.")
        try:
            await callback.bot.send_message(player, message)
        except TelegramAPIError:
            logger.info("Не доставлен результат битвы %s", player)


ACHIEVEMENT_NAMES = {
    "firstwin":"🥇 Первая победа", "wins10":"🏆 10 побед",
    "level10":"✨ Герой 10 уровня", "level25":"👑 Герой 25 уровня",
    "collector3":"🧩 Три героя", "collector10":"💎 Десять героев",
    "duo1":"💞 Первое совместное приключение",
}


@dp.message(Command("achievements"))
@dp.callback_query(F.data == "arena:achievements")
async def arena_achievements(event):
    uid = event.from_user.id
    if isinstance(event, CallbackQuery):
        await event.answer()
    with connect_db() as db:
        codes = {r[0] for r in db.execute("SELECT code FROM arena_achievements WHERE user_id=?",(uid,))}
    lines = [f"{'✅' if code in codes else '🔒'} {name}" for code,name in ACHIEVEMENT_NAMES.items()]
    await (event.message if isinstance(event,CallbackQuery) else event).answer("🏆 <b>ДОСТИЖЕНИЯ</b>\n\n"+"\n".join(lines),parse_mode="HTML")


@dp.message(Command("season"))
@dp.callback_query(F.data == "arena:season")
async def arena_season_board(event):
    if isinstance(event,CallbackQuery): await event.answer()
    season=arena_season()
    with connect_db() as db:
        rows=db.execute("SELECT s.user_id,s.wins,s.points,p.name FROM arena_season_scores s "
                        "JOIN profiles p ON p.user_id=s.user_id WHERE s.season=? "
                        "ORDER BY s.points DESC,s.wins DESC LIMIT 10",(season,)).fetchall()
    text="📅 <b>СЕЗОН АРЕНЫ</b>\n"+season+" (UTC)\n\n"
    text += "\n".join(f"{i}. Участник арены — {points} очков, {wins} побед" for i,(_,wins,points,name) in enumerate(rows,1)) if rows else "Пока нет побед в этом сезоне."
    text+="\n\nНовый сезон начинается первого числа каждого месяца. Рейтинг героев не обнуляется."
    await (event.message if isinstance(event,CallbackQuery) else event).answer(text, parse_mode="HTML")


@dp.message(Command("mydata"))
async def export_my_data(message: Message):
    """Прозрачность: какие персональные данные хранятся о пользователе."""
    if getattr(getattr(message, "chat", None), "type", None) != "private":
        return
    uid=message.from_user.id
    with connect_db() as db:
        profile=db.execute("SELECT name,age,city,interests,gender,seeking,share_contact,verified "
                           "FROM (SELECT p.*,COALESCE(x.verified,0) AS verified FROM profiles p "
                           "LEFT JOIN profile_extras x ON x.user_id=p.user_id) WHERE user_id=?",(uid,)).fetchone()
        reactions=db.execute("SELECT COUNT(*) FROM reactions WHERE from_user=?",(uid,)).fetchone()[0]
        reports=db.execute("SELECT COUNT(*) FROM reports WHERE reporter_id=?",(uid,)).fetchone()[0]
    if not profile:
        await message.answer("Анкеты пока нет. Данные можно удалить командой /deleteaccount.")
        return
    name,age,city,interests,gender,seeking,share,verified=profile
    await message.answer("🔒 Твои данные LUMI (только для тебя)\n\n"
                         f"Имя: {name}\nВозраст: {age}\nГород: {city}\n"
                         f"Описание: {interests}\nПол: {gender}\nПоиск: {seeking}\n"
                         f"Разрешение контактов: {'да' if share else 'нет'}\n"
                         f"Верификация: {'да' if verified else 'нет'}\n"
                         f"Оценённых анкет: {reactions}\nОтправленных жалоб: {reports}\n\n"
                         "Фото и видео хранятся как Telegram file_id.\n"
                         "Удалить данные: /deleteaccount", protect_content=True, parse_mode=None)

@dp.message(Command("deleteaccount"))
async def delete_account_command(message: Message):
    await ask_delete(message)

@dp.message(Command("duoquest"))
@dp.callback_query(F.data == "arena:duo")
async def arena_duo_quest(event):
    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            await duo_menu(event.message)
    else:
        await duo_menu(event)


@dp.message(Command("privacy"))
@dp.message(F.text == "🔒 Приватность")
async def privacy_menu(message: Message):
    if not profile_of(message.from_user.id):
        await clean_answer(message, "Сначала создай анкету 💜")
        return
    with connect_db() as db:
        visible=is_discoverable(db,message.from_user.id)
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Скрыть анкету" if visible else "🟢 Показывать анкету",
                              callback_data="privacy:hide" if visible else "privacy:show")],
        [InlineKeyboardButton(text="🗑 Удалить данные", callback_data="delete:ask")],
        [InlineKeyboardButton(text="⬅️ Моя анкета", callback_data="ux:profile")],
    ])
    await clean_answer(message, "🔒 Приватность LUMI\n\n"
                         + ("Твою анкету видят подходящие пользователи в поиске и Mystery."
                            if visible else "Анкета скрыта из поиска, Moment и новых знакомств Mystery.")
                         + "\n\nУже полученные пользователями сообщения и копии Telegram удаляются не автоматически.",
                         reply_markup=kb)


@dp.callback_query(F.data.startswith("privacy:"))
async def privacy_change(callback: CallbackQuery):
    if callback.data not in {"privacy:hide","privacy:show"} or not profile_of(callback.from_user.id):
        await callback.answer("Анкета недоступна",show_alert=True)
        return
    visible=callback.data=="privacy:show"
    with connect_db() as db:
        db.execute("INSERT INTO privacy_settings(user_id,discoverable) VALUES(?,?) "
                   "ON CONFLICT(user_id) DO UPDATE SET discoverable=excluded.discoverable",
                   (callback.from_user.id,int(visible)))
        if not visible:
            db.execute("DELETE FROM profile_views WHERE target_id=?",(callback.from_user.id,))
            db.execute("DELETE FROM mystery_queue WHERE user_id=?",(callback.from_user.id,))
            db.execute("UPDATE mystery_sessions SET status='closed' WHERE status='active' "
                       "AND (user_a=? OR user_b=?)",(callback.from_user.id,callback.from_user.id))
    await callback.answer("Настройка сохранена")
    await privacy_menu(callback.message.model_copy(update={"from_user":callback.from_user}))

class SupportForm(StatesGroup):
    message = State()


@dp.message(Command("support"))
@dp.message(F.text == "🆘 Поддержка")
async def support_start(message: Message, state: FSMContext):
    with connect_db() as db:
        init_admin_tables(db)
        row = db.execute("SELECT id FROM support_tickets WHERE user_id=? AND status='open' "
                         "ORDER BY id DESC LIMIT 1", (message.from_user.id,)).fetchone()
    await state.set_state(SupportForm.message)
    if row:
        await state.update_data(ticket_id=row[0])
        await message.answer(f"🆘 <b>Поддержка LUMI · №{row[0]}</b>\n\n"
                             "Можешь продолжить переписку. Отправь сообщение, "
                             "а модератор ответит здесь.\n\n"
                             "Закончить разговор — /endsupport.", parse_mode="HTML")
    else:
        await state.update_data(ticket_id=None)
        await message.answer("🆘 <b>Поддержка LUMI</b>\n\n"
                             "Расскажи о проблеме одним сообщением. "
                             "Не отправляй пароли, коды или чужие личные данные.\n\n"
                             "Выйти — /endsupport.", parse_mode="HTML")


@dp.message(Command("endsupport"))
async def end_support(message: Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data.get('ticket_id')
    if ticket_id:
        with connect_db() as db:
            db.execute("UPDATE support_tickets SET status='closed',updated_at=CURRENT_TIMESTAMP "
                       "WHERE id=? AND user_id=? AND status='open'", (ticket_id,message.from_user.id))
    await state.clear()
    await message.answer("✅ Диалог с поддержкой завершён. Если снова понадобится помощь — /support.",
                         reply_markup=mobile_home_keyboard())


@dp.message(F.text == "🛡 Проверить фото")
async def verify_menu_shortcut(message: Message):
    await request_verification(message)


@dp.message(SupportForm.message)
async def support_save(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    if not 1 <= len(txt) <= 1500 or txt.startswith('/'):
        await message.answer("Пришли текст до 1 500 символов. Выйти — /endsupport.")
        return
    uid = message.from_user.id
    data = await state.get_data()
    with connect_db() as db:
        init_admin_tables(db)
        # Recheck ownership and status server-side, regardless of FSM cache.
        row = db.execute("SELECT id FROM support_tickets WHERE user_id=? AND status='open' "
                         "ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        if row:
            ticket_id=row[0]
        else:
            recent = db.execute("SELECT COUNT(*) FROM support_tickets WHERE user_id=? AND "
                "created_at >= datetime('now','-24 hours')", (uid,)).fetchone()[0]
            if recent >= 3:
                await state.clear()
                await message.answer("Лимит новых обращений на сегодня достигнут. "
                                     "Ответ по существующим обращениям придёт сюда.")
                return
            cur=db.execute("INSERT INTO support_tickets(user_id,message) VALUES (?,?)", (uid,txt))
            ticket_id=cur.lastrowid
        db.execute("INSERT INTO support_messages(ticket_id,sender,body) VALUES (?,'user',?)",
                   (ticket_id,txt))
        db.execute("UPDATE support_tickets SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(ticket_id,))
        admin_event(db,'ticket',ticket_id)
    await state.update_data(ticket_id=ticket_id)
    await message.answer(f"✅ Сообщение отправлено в поддержку · <b>№{ticket_id}</b>.\n"
                         "Можешь написать ещё или выйти через /endsupport.",parse_mode="HTML")


@dp.message(Command("health"))
async def admin_health(message: Message):
    """Private administrator-only operational status. Never expose DB contents."""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Команда доступна только администратору.")
        return
    with connect_db() as db:
        integrity = db.execute("PRAGMA quick_check(1)").fetchone()[0]
        journal = db.execute("PRAGMA journal_mode").fetchone()[0]
        profiles = db.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        pending = db.execute("SELECT COUNT(*) FROM verification_requests WHERE status='review'").fetchone()[0]
        pending_battles = db.execute("SELECT COUNT(*) FROM arena_challenges WHERE status='pending'").fetchone()[0]
    uptime = int(time.monotonic() - LUMI_STARTED_MONOTONIC)
    size_mb = DB_PATH.stat().st_size / (1024 * 1024) if DB_PATH.is_file() else 0
    await message.answer(
        "🛡 <b>LUMI · Состояние системы</b>\n\n"
        f"Бот работает: <b>{uptime // 3600} ч {uptime % 3600 // 60} мин</b>\n"
        f"База: <b>{ui_safe(integrity, 24)}</b> · {ui_safe(journal, 12)} · {size_mb:.1f} МБ\n"
        f"Анкет: <b>{profiles}</b>\n"
        f"Проверок на рассмотрении: <b>{pending}</b>\n"
        f"Вызовов на битву: <b>{pending_battles}</b>\n\n"
        "Эта сводка доступна только администратору.", parse_mode="HTML",
    )


async def show_referral(message, uid):
    with connect_db() as db:
        registered = db.execute("SELECT 1 FROM profiles WHERE user_id=? AND age>=18", (uid,)).fetchone() is not None
        count = referral_count(db, uid)
        rewarded = has_referral_frame(db, uid)
    if not registered:
        await clean_answer(message, "🎁 <b>Приглашай друзей в LUMI</b>\n\nСначала создай анкету 18+.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💜 Создать анкету", callback_data="ux:register")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")]]))
        return
    me = await message.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{uid}"
    reward = "✅ <b>Рамка героя «Сердце LUMI» получена!</b>" if rewarded else f"Осталось друзей: <b>{max(0, REFERRAL_GOAL-count)}</b>"
    await clean_answer(message, 
        "🎁 <b>ПРИГЛАСИ 3 ДРУЗЕЙ</b>\n\n"
        "Друзья должны впервые перейти по твоей ссылке и завершить создание анкеты 18+. "
        "Один аккаунт учитывается один раз; самоприглашения не считаются.\n\n"
        f"<b>Подтверждено:</b> {count}/{REFERRAL_GOAL}\n{reward}\n\n"
        "🎨 Награда: эксклюзивная косметическая рамка героя, без бонусов к силе.\n\n"
        f"🔗 <code>{html_escape(link)}</code>", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")]]))


async def show_daily4(message, uid):
    if not profile_of(uid):
        await clean_answer(message, "💝 <b>Подарок дня</b>\n\nСначала создай анкету 18+.", parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💜 Создать анкету", callback_data="ux:register")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")]]))
        return
    with connect_db() as db:
        has_hero = arena_get(db, uid) is not None
        status = daily_reward_status(db, uid)
    title = "💝 <b>ТВОЙ ПОДАРОК ДНЯ</b>\n\n"
    if not has_hero:
        text = title + "Выбери героя, чтобы получать игровой опыт за ежедневное посещение."
        button = InlineKeyboardButton(text="⚔️ Выбрать героя", callback_data="ux:heroes")
    elif status['claimed_today']:
        text = title + f"✅ Сегодня подарок уже получен.\n🔥 Серия: <b>{status['streak']}</b> дн.\n\nВозвращайся завтра (по UTC)!"
        button = InlineKeyboardButton(text="⚔️ Мои герои", callback_data="ux:heroes")
    else:
        text = title + "Каждый день +15 EXP героя. На седьмой день подряд — +35 EXP!\n\nНаграда бесплатная, доступна один раз за день (UTC)."
        button = InlineKeyboardButton(text="💜 Забрать подарок", callback_data="daily4:claim")
    await clean_answer(message, text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [button], [InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")]]))


@dp.message(Command("gift"))
async def daily4_command(message: Message):
    await show_daily4(message, message.from_user.id)


@dp.callback_query(F.data == "daily4:open")
async def daily4_open(callback: CallbackQuery):
    await callback.answer()
    await show_daily4(callback.message, callback.from_user.id)


@dp.callback_query(F.data == "daily4:claim")
async def daily4_claim(callback: CallbackQuery):
    uid = callback.from_user.id
    if not profile_of(uid):
        await callback.answer("Сначала создай анкету", show_alert=True)
        return
    def transaction():
        with connect_db() as db:
            # Immediate write lock serializes double taps and concurrent updates.
            db.execute("BEGIN IMMEDIATE")
            if not eligible_for_reward(db, uid) or arena_get(db, uid) is None:
                return False, 'Нужна действующая анкета 18+ и герой'
            result = claim_daily_reward(db, uid)
            if result['awarded']:
                arena_add_xp(db, uid, result['xp'])
        return True, result
    ok, payload = await asyncio.to_thread(transaction)
    if not ok:
        await callback.answer(payload, show_alert=True)
        return
    result = payload
    if not result['awarded']:
        await callback.answer("Сегодня подарок уже получен 💜", show_alert=True)
    else:
        await callback.answer(f"+{result['xp']} EXP!", show_alert=True)
        await callback.message.answer(
            f"🎁 <b>Подарок получен!</b>\n\n⚔️ +{result['xp']} EXP\n🔥 Серия: {result['streak']} дн.\n\nДо завтра! 💜",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚔️ Мои герои", callback_data="ux:heroes")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")]]))


async def show_safety4(message, uid):
    with connect_db() as db:
        row = db.execute("SELECT share_contact FROM profiles WHERE user_id=?", (uid,)).fetchone()
        visible = is_discoverable(db, uid) if row else False
    if row is None:
        await message.answer("🛡 <b>Безопасность LUMI</b>\n\nСначала создай анкету 18+.", parse_mode="HTML")
        return
    contact = bool(row[0])
    text = ("🛡 <b>ЦЕНТР БЕЗОПАСНОСТИ LUMI</b>\n\n"
            f"👀 Поиск анкеты: <b>{'ВКЛ' if visible else 'ВЫКЛ'}</b>\n"
            f"🔗 Согласие на обмен контактами: <b>{'Разрешено' if contact else 'Запрещено'}</b>\n\n"
            "• Контакт передаётся только при дополнительном взаимном согласии.\n"
            "• Жалоба и блокировка доступны в анкете и переписке.\n"
            "• Не отправляй пароли, коды Telegram, деньги и личные документы незнакомцам.\n"
            "• Скрытие анкеты не удаляет уже отправленные сообщения и копии получателей.\n\n"
            "Твои данные: /mydata · Удаление: /deleteaccount · Поддержка: /support")
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙈 Скрыть анкету" if visible else "👀 Показать анкету",
                              callback_data="privacy:hide" if visible else "privacy:show")],
        [InlineKeyboardButton(text="🔒 Запретить контакт" if contact else "🔗 Разрешить контакт",
                              callback_data="safety4:contactoff" if contact else "safety4:contacton")],
        [InlineKeyboardButton(text="🆘 Поддержка", callback_data="ux:support"),
         InlineKeyboardButton(text="🗑 Удалить данные", callback_data="delete:ask")],
        [InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")]]))


@dp.message(Command("safety"))
async def safety4_command(message: Message):
    await show_safety4(message, message.from_user.id)


@dp.callback_query(F.data == "safety4:open")
async def safety4_open(callback: CallbackQuery):
    await callback.answer()
    await show_safety4(callback.message, callback.from_user.id)


@dp.callback_query(F.data.in_({"safety4:contactoff", "safety4:contacton"}))
async def safety4_contact(callback: CallbackQuery):
    uid = callback.from_user.id
    with connect_db() as db:
        cur = db.execute("UPDATE profiles SET share_contact=? WHERE user_id=?",
                         (int(callback.data == "safety4:contacton"), uid))
    if cur.rowcount == 0:
        await callback.answer("Сначала создай анкету", show_alert=True)
        return
    await callback.answer("Настройка сохранена 💜")
    await show_safety4(callback.message, uid)


@dp.message(Command("invite"))
async def referral_command(message: Message):
    await show_referral(message, message.from_user.id)


@dp.callback_query(F.data == "referral:open")
async def referral_open(callback: CallbackQuery):
    await callback.answer()
    if callback.message:
        await show_referral(callback.message, callback.from_user.id)


def founder_keyboard(registered):
    return InlineKeyboardMarkup(inline_keyboard=(
        [[InlineKeyboardButton(text="💜 Создать анкету", callback_data="ux:register")]] if not registered else
        [[InlineKeyboardButton(text="👤 Моя анкета", callback_data="ux:profile")]]
    ) + [[InlineKeyboardButton(text="🏠 Домой", callback_data="ux:home")]])


async def show_founder_event(message, uid):
    serial = None
    registered = profile_of(uid) is not None
    if registered:
        serial, _ = claim_founder(uid)
    with connect_db() as db:
        allocated, places = founder_status(db)
    if serial:
        body = (f"🏅 <b>Ты — первопроходец LUMI №{serial}!</b>\n\n"
                "Значок <b>«Первопроходец LUMI»</b> уже виден в твоей анкете. "
                "Он остаётся с тобой, пока существует анкета.")
    elif not registered and places:
        body = ("💜 <b>Стань одним из первых!</b>\n\n"
                "Создай анкету, и бот автоматически выдаст номер участника, пока места есть.")
    elif not registered:
        body = "Все 100 мест заняты. Но новые знакомства в LUMI открыты для всех! 💜"
    else:
        body = "Все 100 мест уже распределены. Продолжай знакомиться с LUMI! 💜"
    text = (
        "🏅 <b>ПЕРВЫЕ 100 СЕРДЕЦ LUMI</b>\n\n"
        "Событие для первых 100 участников с заполненной анкетой.\n"
        "<b>Награда:</b> постоянный значок в профиле и номер участника.\n"
        "Никаких платных преимуществ — только красивый статус.\n\n"
        f"<b>Занято:</b> {allocated} из 100\n"
        f"<b>Свободно:</b> {places}\n\n"
        + body
    )
    await clean_answer(message, text, parse_mode="HTML", reply_markup=founder_keyboard(registered))


@dp.message(Command("founder"))
async def founder_command(message: Message):
    await show_founder_event(message, message.from_user.id)


@dp.callback_query(F.data == "founder:open")
async def founder_open(callback: CallbackQuery):
    await callback.answer()
    if callback.message:
        await show_founder_event(callback.message, callback.from_user.id)


# Inline-first mobile navigation. Callback IDs are fixed strings, no user IDs.
@dp.callback_query(F.data.startswith("ux:"))
async def mobile_ux_action(callback: CallbackQuery, state: FSMContext):
    action = callback.data.partition(":")[2]
    if action not in {"home", "browse", "profile", "heroes", "matches", "more", "register",
                      "edit_photo", "edit_text", "privacy", "support", "verify", "search",
                      "premium", "features", "delete", "mystery", "moment", "duo", "contact"}:
        await callback.answer("Неизвестная кнопка", show_alert=True)
        return
    if not callback.message:
        await callback.answer("Сообщение недоступно", show_alert=True)
        return
    await callback.answer()
    message, uid = callback.message, callback.from_user.id
    close_active_chat(uid)
    if action == "home":
        await state.clear()
        await mobile_home(message)
    elif action == "more":
        await clean_answer(message, "⋯ Ещё", reply_markup=mobile_more_keyboard(), parse_mode="HTML")
    elif action == "browse":
        await state.clear()
        await clean_answer(message, "❤️ <b>Знакомства</b>", reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")
        await show_next(message, uid)
    elif action == "profile":
        await state.clear()
        await show_quick_menu(message, uid)
    elif action == "heroes":
        await state.clear()
        if not profile_of(uid):
            await message.answer("Сначала создай анкету 💜", reply_markup=mobile_home_keyboard())
        else:
            await arena_show(message, uid)
    elif action == "matches":
        await state.clear()
        if not profile_of(uid):
            await message.answer("Сначала создай анкету 💜", reply_markup=mobile_home_keyboard())
        else:
            await show_matches_page(message, uid)
    elif action == "register":
        await create_profile(message.model_copy(update={"from_user": callback.from_user}), state)
    elif action == "edit_photo":
        if not profile_of(uid):
            await message.answer("Сначала создай анкету 💜")
        else:
            await state.set_state(EditProfile.photo)
            await clean_answer(message, "📷 Пришли фото или видео до 15 секунд.", reply_markup=profile_back_keyboard())
    elif action == "edit_text":
        if not profile_of(uid):
            await message.answer("Сначала создай анкету 💜")
        else:
            await state.set_state(EditProfile.interests)
            await clean_answer(message, "✏️ Напиши о себе (2–300 символов).", reply_markup=profile_back_keyboard())
    elif action == "privacy":
        await state.clear()
        if not profile_of(uid):
            await message.answer("Сначала создай анкету 💜")
        else:
            await privacy_menu(message.model_copy(update={"from_user": callback.from_user}))
    elif action == "support":
        await support_start(message.model_copy(update={"from_user": callback.from_user}), state)
    elif action == "verify":
        await request_verification(message.model_copy(update={"from_user": callback.from_user}))
    elif action == "search":
        await search_settings(message.model_copy(update={"from_user": callback.from_user}), state)
    elif action == "premium":
        await quick_premium(message)
    elif action == "features":
        await social_features(message)
    elif action == "mystery":
        await mystery_join(message.model_copy(update={"from_user": callback.from_user}))
    elif action == "moment":
        await daily_moment(message.model_copy(update={"from_user": callback.from_user}))
    elif action == "duo":
        await duo_menu(message.model_copy(update={"from_user": callback.from_user}))
    elif action == "contact":
        await contact_settings(message.model_copy(update={"from_user": callback.from_user}))
    elif action == "delete":
        await ask_delete(message)


# LUMI 3.8 — opt-in notifications and message starters. All actions check mutuality.
STARTER_TEXTS = {
    'fun': 'У нас совпадение! 😄 Скажи, какая самая неожиданная вещь тебя рассмешила за последнее время?',
    'warm': 'Привет! 💜 Рад(а) нашему совпадению. Что сделало твой день лучше?',
    'simple': 'Привет! Мы совпали 😊 Чем любишь заниматься в свободное время?',
}


# Additive table; existing user data is untouched.
def init_return_reminders(db):
    db.execute("CREATE TABLE IF NOT EXISTS lumi_return_activity (user_id INTEGER PRIMARY KEY, last_seen INTEGER NOT NULL, stage INTEGER NOT NULL DEFAULT 0, last_sent INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 0)")


def reminder_stage(last_seen, stage, last_sent, now):
    due = sum(now-last_seen >= d*86400 for d in (1,3,7))
    return due if due > stage and now-last_sent >= 86400 else 0


class ReturnActivityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user:
            with connect_db() as db:
                db.execute("INSERT INTO lumi_return_activity(user_id,last_seen) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET last_seen=excluded.last_seen,stage=0", (user.id,int(time.time())))
        return await handler(event,data)


dp.message.outer_middleware(ReturnActivityMiddleware())
dp.callback_query.outer_middleware(ReturnActivityMiddleware())


def reminder_users(now):
    with connect_db() as db:
        return db.execute("SELECT a.user_id,a.last_seen,a.stage,a.last_sent FROM lumi_return_activity a JOIN profiles p ON p.user_id=a.user_id WHERE a.enabled=1 AND a.stage<3 AND a.last_seen<=? AND NOT EXISTS(SELECT 1 FROM account_suspensions s WHERE s.user_id=a.user_id AND (s.expires_at IS NULL OR s.expires_at>CURRENT_TIMESTAMP))",(now-86400,)).fetchall()


def claim_reminder(uid, seen, stage, due, now):
    rows, me = eligible_candidates(uid)
    if not rows or me is None:
        return 0
    with connect_db() as db:
        if not is_discoverable(db,uid) or not can_notify(db,uid,'likes'):
            return 0
        evaluated = {r[0] for r in db.execute("SELECT to_user FROM reactions WHERE from_user=?",(uid,))}
        count = sum(row[0] not in evaluated for row in rows)
        if not count:
            return 0
        changed = db.execute("UPDATE lumi_return_activity SET stage=?,last_sent=? WHERE user_id=? AND enabled=1 AND last_seen=? AND stage=?",(due,now,uid,seen,stage)).rowcount
    return count if changed else 0


async def return_reminder_pass(bot):
    now = int(time.time())
    users = await asyncio.to_thread(reminder_users, now)
    for uid, seen, stage, sent in users:
        due = reminder_stage(seen,stage,sent,now)
        if not due:
            continue
        count = await asyncio.to_thread(claim_reminder, uid, seen, stage, due, now)
        if count:
            try:
                await bot.send_message(uid,f"✨ Подходящих анкет, которые ты ещё не оценивал(а): {count}. Заглянешь в LUMI?",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❤️ Анкеты",callback_data="ux:browse")],[InlineKeyboardButton(text="🔕 Отключить напоминания",callback_data="return:off")]]))
            except TelegramAPIError:
                pass


async def return_reminder_loop(bot):
    while True:
        await asyncio.sleep(3600)
        try:
            await return_reminder_pass(bot)
        except (sqlite3.Error, TelegramAPIError):
            logger.exception("Ошибка напоминаний LUMI")


@dp.callback_query(F.data.in_({"return:on", "return:off"}))
async def return_reminder_setting(callback: CallbackQuery):
    with connect_db() as db:
        db.execute("UPDATE lumi_return_activity SET enabled=? WHERE user_id=?",(int(callback.data=="return:on"),callback.from_user.id))
    await notifications_menu(callback)


@dp.message(Command('notifications'))
@dp.callback_query(F.data == 'notify:menu')
async def notifications_menu(event):
    uid=event.from_user.id
    if isinstance(event, CallbackQuery):
        await event.answer()
    with connect_db() as db:
        init_ops(db)
        row=db.execute('SELECT likes,matches,quiet FROM lumi_notification_settings WHERE user_id=?',(uid,)).fetchone() or (1,1,0)
        reminder=db.execute('SELECT enabled FROM lumi_return_activity WHERE user_id=?',(uid,)).fetchone()
    enabled=bool(reminder and reminder[0])
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=('✅' if enabled else '❌')+' Напоминания об анкетах',callback_data='return:off' if enabled else 'return:on')],
        [InlineKeyboardButton(text=('✅' if row[0] else '❌')+' Тайные симпатии',callback_data='notify:likes')],
        [InlineKeyboardButton(text=('✅' if row[1] else '❌')+' Новые совпадения',callback_data='notify:matches')],
        [InlineKeyboardButton(text=('✅' if row[2] else '❌')+' Тихие часы 22:00–08:00 UTC',callback_data='notify:quiet')],
        [InlineKeyboardButton(text='🏠 Домой',callback_data='ux:home')]])
    info='🔔 <b>Уведомления LUMI</b>\n\nВыбери, что получать. Тихие часы указаны по UTC. Важные ответы поддержки не отключаются.'
    if isinstance(event, CallbackQuery):
        await clean_answer(event.message, info,parse_mode='HTML',reply_markup=kb)
    else:
        await clean_answer(event, info,parse_mode='HTML',reply_markup=kb)

@dp.callback_query(F.data.in_({'notify:likes','notify:matches','notify:quiet'}))
async def notification_change(callback: CallbackQuery):
    with connect_db() as db:
        toggle_notify(db,callback.from_user.id,callback.data.split(':')[1])
    await callback.answer('Настройка сохранена')
    await notifications_menu(callback)

@dp.callback_query(F.data.startswith('hello:'))
async def starter_hello(callback: CallbackQuery):
    parts=(callback.data or '').split(':')
    try:
        mode,peer=parts[1],int(parts[2])
    except (ValueError,IndexError):
        await callback.answer('Кнопка устарела',show_alert=True);return
    uid=callback.from_user.id
    with connect_db() as db:
        if not is_match(db,uid,peer):
            await callback.answer('Совпадение больше недоступно',show_alert=True);return
        peer_name=db.execute('SELECT name FROM profiles WHERE user_id=?',(peer,)).fetchone()[0]
        my_name=db.execute('SELECT name FROM profiles WHERE user_id=?',(uid,)).fetchone()[0]
    if mode=='menu':
        await callback.answer()
        await callback.message.answer('💬 <b>Как начать разговор?</b>\n\nВыбери готовую фразу. Она будет отправлена собеседнику от твоего имени через LUMI.',parse_mode='HTML',reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='😄 С юмором',callback_data=f'hello:fun:{peer}')],
            [InlineKeyboardButton(text='💜 Тепло',callback_data=f'hello:warm:{peer}')],
            [InlineKeyboardButton(text='👋 Просто',callback_data=f'hello:simple:{peer}')],
            [InlineKeyboardButton(text='⬅️ К совпадениям',callback_data='ux:matches')]]));return
    if mode not in STARTER_TEXTS:
        await callback.answer('Неизвестная фраза',show_alert=True);return
    with connect_db() as db:
        claim=db.execute("INSERT OR IGNORE INTO lumi_starter_daily(from_user,to_user,day) VALUES(?,?,date('now'))",(uid,peer))
        if claim.rowcount!=1:
            await callback.answer('Сегодня готовая фраза уже отправлена. Напиши своё сообщение через LUMI.',show_alert=True)
            return
    await callback.answer('Отправляю…')
    text=STARTER_TEXTS[mode]
    try:
        await callback.bot.send_message(peer,f'💬 <b>Сообщение от {html_escape(my_name[:40])} через LUMI:</b>\n\n{html_escape(text)}',parse_mode='HTML',protect_content=True,
            reply_markup=chat_reply_keyboard(uid))
    except TelegramAPIError:
        with connect_db() as db:
            db.execute("DELETE FROM lumi_starter_daily WHERE from_user=? AND to_user=? AND day=date('now')",(uid,peer))
        await callback.message.answer('Не удалось доставить сообщение. Возможно, собеседник ещё не открыл бота.');return
    await callback.message.answer(f'✅ Сообщение для {html_escape(peer_name[:40])} отправлено.\n\n{html_escape(text)}',parse_mode='HTML')

@dp.message()
async def fallback(message: Message):
    uid=message.from_user.id
    with connect_db() as db:
        row=db.execute("SELECT peer_id FROM active_chats WHERE user_id=?",(uid,)).fetchone()
        peer=row[0] if row else None
        if peer and not is_match(db,uid,peer):
            db.execute("DELETE FROM active_chats WHERE user_id=?",(uid,))
            peer=None
    if peer:
        if message.text and message.text.startswith("/"):
            await message.answer("Для выхода из переписки используй /stop.")
            return
        try:
            if message.text:
                await message.bot.send_message(peer,"💬 Сообщение через LUMI:\n"+message.text[:3800]+warning_for(message.text, message.entities),parse_mode=None,disable_web_page_preview=True,protect_content=True, reply_markup=chat_reply_keyboard(uid))
            elif message.photo:
                if not media_size_allowed(message.photo[-1]):
                    await message.answer("Фото слишком большое. Лимит 19 МБ.")
                    return
                await message.bot.send_photo(peer,message.photo[-1].file_id,caption="Фото через LUMI"+("\n"+message.caption[:800]+warning_for(message.caption, message.caption_entities) if message.caption else ""),parse_mode=None,protect_content=True, reply_markup=chat_reply_keyboard(uid))
            elif message.voice:
                if message.voice.duration > 60 or not media_size_allowed(message.voice):
                    await message.answer("Голосовое сообщение должно быть не длиннее 60 секунд.")
                    return
                await message.bot.send_voice(peer,message.voice.file_id,caption="Голосовое через LUMI",protect_content=True, reply_markup=chat_reply_keyboard(uid))
            else:
                await message.answer("Можно отправлять текст, фотографии и голосовые до 60 секунд.")
                return
            await message.answer("✅ Отправлено", reply_markup=chat_controls())
        except TelegramAPIError:
            logger.exception("Не удалось доставить сообщение")
            await message.answer("Не удалось доставить сообщение. Возможно, собеседник ещё не открыл бота.")
        return
    logger.debug("Получено сообщение, тип=%s",message.content_type)
    await message.answer("💜 Выбери раздел LUMI ниже.", reply_markup=mobile_home_keyboard())




def backup_database():
    """SQLite online backup before schema migrations; default only on first run per UTC day."""
    if not DB_PATH.is_file() or os.getenv("LUMI_AUTO_BACKUP", "1") == "0":
        return
    from lumi_backup_policy import create_daily_backup
    backup_dir = Path(os.getenv("LUMI_BACKUP_DIR", str(DB_PATH.parent.parent / "LUMI_backups")))
    key = os.getenv("LUMI_BACKUP_KEY", "").strip()
    if not key:
        raise RuntimeError("LUMI_BACKUP_KEY is required for encrypted backups")
    retention = int(os.getenv("LUMI_BACKUP_RETENTION_DAYS", "7"))
    create_daily_backup(DB_PATH, backup_dir, key, retention)


def cleanup_security_data():
    from lumi_data_lifecycle import expire_verification_material, purge_closed_support_events
    with connect_db() as db:
        live_analytics.prune(db, datetime.now(timezone.utc).date())
        expire_verification_material(db)
        purge_closed_support_events(db)
        db.execute("DELETE FROM admin_events WHERE created_at < datetime('now','-14 days')")
        db.execute("DELETE FROM support_messages WHERE ticket_id IN "
                   "(SELECT id FROM support_tickets WHERE status='closed' "
                   "AND updated_at < datetime('now','-90 days'))")
        db.execute("DELETE FROM support_tickets WHERE status='closed' "
                   "AND updated_at < datetime('now','-90 days')")
        # Expired restrictions no longer apply even before maintenance runs.
        db.execute("DELETE FROM moderation_holds WHERE expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP")
        db.execute("DELETE FROM account_suspensions WHERE expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP")
        # Remove orphaned moderation identifiers no later than 30 days after deletion.
        db.execute("DELETE FROM moderation_holds WHERE created_at < datetime('now','-30 days') "
                   "AND NOT EXISTS(SELECT 1 FROM profiles p WHERE p.user_id=moderation_holds.user_id)")
        db.execute("DELETE FROM profile_views WHERE viewed_at < datetime('now','-24 hours')")
        db.execute("DELETE FROM browse_daily WHERE day < date('now','-8 days')")
        db.execute("DELETE FROM lumi_starter_daily WHERE day < date('now','-8 days')")
        db.execute("DELETE FROM lumi_ops_daily WHERE day < date('now','-30 days')")
        db.execute("DELETE FROM lumi_security_flags WHERE last_alert_at < datetime('now','-30 days')")
        # Do not keep security metadata forever by default.
        audit_days = max(7, min(365, int(os.getenv("LUMI_AUDIT_RETENTION_DAYS", "30"))))
        db.execute("DELETE FROM security_audit WHERE created_at < datetime('now', ?)",
                   (f"-{audit_days} days",))
        db.execute("UPDATE arena_challenges SET status='expired', resolved_at=CURRENT_TIMESTAMP "
                   "WHERE status='pending' AND created_at < datetime('now','-24 hours')")
        db.execute("DELETE FROM verification_requests WHERE status='challenge' AND expires_at < CURRENT_TIMESTAMP")
        db.execute("UPDATE profile_extras SET verification_status='none' WHERE verified=0 AND verification_status='challenge' AND user_id NOT IN (SELECT user_id FROM verification_requests WHERE status='challenge')")


async def security_maintenance():
    """Автоматическая ежедневная копия и очистка просроченных заданий."""
    while True:
        await asyncio.sleep(3600)
        try:
            await asyncio.to_thread(backup_database)
        except (sqlite3.Error, OSError, ValueError, RuntimeError):
            logger.error("Ошибка резервного копирования LUMI")
        try:
            await asyncio.to_thread(cleanup_security_data)
        except (sqlite3.Error, OSError, ValueError):
            logger.error("Ошибка регламентной очистки LUMI")


@dp.errors()
async def capture_bot_error(event):
    """Record error type only, not message contents or user identifiers."""
    exc = getattr(event, 'exception', None)
    category = type(exc).__name__[:60] if exc else 'UnknownError'
    logger.error("LUMI обработчик завершился ошибкой: %s", category)
    LUMI_METRICS["errors"] += 1
    LUMI_METRICS["last_error_utc"] = datetime.now(timezone.utc).isoformat()
    try:
        with connect_db() as db:
            init_admin_tables(db)
            last = db.execute("SELECT created_at FROM admin_events WHERE type='error' "
                              "AND created_at > datetime('now','-5 minutes') LIMIT 1").fetchone()
            if not last:
                admin_event(db, 'error')
    except sqlite3.Error:
        logger.error("Не удалось записать событие об ошибке")
    return True


async def main():
    from lumi_preflight import validate
    validate("bot")
    print("LUMI BOT UX 3 — clean chat and reminders", flush=True)
    if not TOKEN:
        raise RuntimeError("Добавь BOT_TOKEN в файл .env")
    from lumi_database_vault import private_process_files
    private_process_files()
    boot_start=time.perf_counter()
    await asyncio.to_thread(backup_database)
    logger.info("Резервная копия: %.2f с",time.perf_counter()-boot_start)
    db_start=time.perf_counter()
    init_db()
    with connect_db() as db:
        init_return_reminders(db)
        from lumi_global_ban import init_sync
        init_sync(db)
    logger.info("Инициализация базы: %.2f с",time.perf_counter()-db_start)
    with connect_db() as db:
        integrity=db.execute("PRAGMA quick_check").fetchone()[0]
        if integrity!='ok':
            raise RuntimeError("Проверка целостности lumi.db не пройдена: "+str(integrity))
    with connect_db() as db:
        db.execute("DELETE FROM verification_requests WHERE status='challenge' AND expires_at < CURRENT_TIMESTAMP")
        db.execute("UPDATE profile_extras SET verification_status='none' WHERE verified=0 AND verification_status='challenge' AND user_id NOT IN (SELECT user_id FROM verification_requests WHERE status='challenge')")
    bot = Bot(token=TOKEN)
    from lumi_global_ban import sync_loop
    from lumi_supervisor import supervise, stop_workers
    ban_key=os.getenv("LUMI_BAN_SYNC_KEY", "").strip()
    sync_task=asyncio.create_task(supervise("ban-sync", lambda: sync_loop(connect_db,LUMI_GAMES_URL,ban_key), logger)) if LUMI_GAMES_URL and len(ban_key)>=32 else None
    if LUMI_GAMES_URL and not sync_task: logger.warning("Global ban sync not configured")
    maintenance_task = asyncio.create_task(supervise("maintenance", security_maintenance, logger))
    reminder_task = asyncio.create_task(supervise("reminders", lambda: return_reminder_loop(bot), logger))
    try:
        await bot.set_my_commands([
            BotCommand(command="founder", description="🏅 Первые 100 сердец"),
            BotCommand(command="invite", description="🎁 Пригласить друзей"),
            BotCommand(command="gift", description="💝 Подарок дня"),
            BotCommand(command="safety", description="🛡 Центр безопасности"),
            BotCommand(command="games", description="🎮 Мини-игры LUMI"),
            BotCommand(command="heroes", description="⚔️ Мои герои"),
            BotCommand(command="gallery", description="🖼 Все 21 героя"),
            BotCommand(command="howheroes", description="❔ Как играть с героями"),
            BotCommand(command="pet", description="Открыть моих героев"),
            BotCommand(command="arena", description="Арена и битвы героев"),
            BotCommand(command="achievements", description="Достижения"),
            BotCommand(command="season", description="Сезон арены"),

            BotCommand(command="support", description="🆘 Написать в поддержку"),
            BotCommand(command="endsupport", description="Завершить диалог с поддержкой"),
            BotCommand(command="home", description="🏠 Главное меню"),
            BotCommand(command="mydata", description="Мои сохранённые данные"),
            BotCommand(command="privacy", description="Скрыть или показать анкету"),
            BotCommand(command="deleteaccount", description="Удалить мои данные"),
            BotCommand(command="features", description="Возможности LUMI"),
            BotCommand(command="mystery", description="Знакомство вслепую"),
            BotCommand(command="mysteryexit", description="Выйти из Mystery"),
            BotCommand(command="moment", description="Знакомство дня"),

            BotCommand(command="voice", description="Записать голосовое приветствие"),
            BotCommand(command="cancelverify", description="Отменить проверку"),
            BotCommand(command="admirers", description="Тайные симпатии"),
            BotCommand(command="ice", description="Вопрос для знакомства"),
            BotCommand(command="start", description="💜 Главное меню"),
            BotCommand(command="myprofile", description="👤 Моя анкета"),
            BotCommand(command="premium", description="⭐ Premium"),
            BotCommand(command="paysupport", description="Помощь с оплатой"),
            BotCommand(command="notifications", description="🔔 Уведомления"),
            BotCommand(command="complaint", description="🚫 Пожаловаться"),
            BotCommand(command="language", description="🌍 Язык"),
            BotCommand(command="stop", description="💬 Завершить чат"),
            BotCommand(command="cancel", description="✖️ Отменить действие"),
        ])
        me = await bot.get_me()
        logger.info("LUMI запущен: @%s", me.username)
        await bot.delete_webhook(drop_pending_updates=False)
        await bounded_polling(dp, bot, "LUMI_POLLING_LIMIT", 32)
    finally:
        # Give outstanding privacy-safe image teasers a short chance to finish.
        if _teaser_tasks:
            await asyncio.wait(_teaser_tasks,timeout=3)
            pending = tuple(_teaser_tasks)
            for task in pending: task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        try:
            await stop_workers(sync_task, reminder_task, maintenance_task)
        finally:
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
