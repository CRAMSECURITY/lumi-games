"""LUMI Admin — private Telegram moderation & support bot.

Uses a DIFFERENT Telegram token and the same LOCAL lumi.db.
Run together with bot.py; never publish this DB as a web endpoint.
"""
import asyncio
from lumi_polling import bounded_polling
from lumi_verification import parse_review_callback, decide_review
import html
import logging
import os
import re
import sqlite3
from pathlib import Path

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (Message, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, BotCommand)
from dotenv import load_dotenv
from lumi_operations import init_ops, analytics

load_dotenv()
ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / 'lumi.db'
ADMIN_TOKEN = os.getenv('LUMI_ADMIN_BOT_TOKEN','').strip()
MAIN_TOKEN = os.getenv('BOT_TOKEN','').strip()
ADMINS = {int(x) for x in os.getenv('LUMI_ADMIN_IDS','').replace(' ','').split(',') if x.isdigit()}
logger = logging.getLogger('lumi.admin')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
from lumi_secrets import install_log_redaction
install_log_redaction()
dp = Dispatcher()


class AdminOnly(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, 'from_user', None)
        chat = getattr(event, 'chat', None) or getattr(getattr(event,'message',None),'chat',None)
        if not user or user.id not in ADMINS or getattr(chat,'type',None) != 'private':
            if isinstance(event, CallbackQuery):
                await event.answer('Доступ запрещён', show_alert=True)
            elif isinstance(event, Message) and getattr(chat,'type',None)=='private':
                await event.answer('Это закрытый служебный бот LUMI.')
            return
        return await handler(event,data)


dp.message.outer_middleware(AdminOnly())
dp.callback_query.outer_middleware(AdminOnly())


class ReplyState(StatesGroup):
    text = State()


class SanctionState(StatesGroup):
    reason = State()
    confirm = State()


def db_connect():
    from lumi_database_vault import connect_private
    db = connect_private(DB_PATH, timeout=10)
    try:
        db.execute('PRAGMA busy_timeout=10000')
        return db
    except BaseException:
        db.close()
        raise


def init_admin_schema():
    with db_connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            category TEXT NOT NULL DEFAULT 'question', message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open', reply TEXT,
            assigned_admin INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_support_status ON support_tickets(status,created_at)')
        db.execute("""CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            sender TEXT NOT NULL CHECK(sender IN ('user','admin')),
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_support_messages_ticket ON support_messages(ticket_id,id)")
        db.execute('''CREATE TABLE IF NOT EXISTS admin_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL,
            ref_id INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            delivered_at TEXT, attempts INTEGER NOT NULL DEFAULT 0)''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_admin_events_queue ON admin_events(delivered_at,id)')
        db.execute('''CREATE TABLE IF NOT EXISTS report_reviews (
            report_id INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'open',
            moderator_id INTEGER, reviewed_at TEXT)''')
        db.execute('''CREATE TABLE IF NOT EXISTS moderation_holds (
            user_id INTEGER PRIMARY KEY, reason TEXT NOT NULL,
            moderator_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('''CREATE TABLE IF NOT EXISTS admin_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER NOT NULL, action TEXT NOT NULL,
            target_id INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_admin_audit_time ON admin_audit(created_at)')

        columns = {r[1] for r in db.execute("PRAGMA table_info(moderation_holds)")}
        if 'expires_at' not in columns:
            db.execute("ALTER TABLE moderation_holds ADD COLUMN expires_at TEXT")
        db.execute("CREATE INDEX IF NOT EXISTS idx_moderation_expiry ON moderation_holds(expires_at)")
        db.execute("""CREATE TABLE IF NOT EXISTS moderation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL,
            action TEXT NOT NULL, reason TEXT,
            expires_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_mod_history_user ON moderation_history(user_id,created_at)")
        db.execute("""CREATE TABLE IF NOT EXISTS account_suspensions (
            user_id INTEGER PRIMARY KEY, reason TEXT NOT NULL,
            moderator_id INTEGER NOT NULL,
            expires_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_account_suspensions_expiry ON account_suspensions(expires_at)")


def apply_profile_hold(db, uid: int, actor_id: int, reason: str = 'manual_admin_review') -> str:
    """Hide a profile from discovery atomically; never delete the account.

    This is a temporary *profile visibility* restriction, not a global bot ban.
    The insert is idempotent across moderators and button retries.
    """
    if uid <= 0 or actor_id <= 0:
        return 'invalid'
    profile = db.execute('SELECT 1 FROM profiles WHERE user_id=?', (uid,)).fetchone()
    if not profile:
        return 'missing'
    result = db.execute(
        'INSERT OR IGNORE INTO moderation_holds(user_id,reason,moderator_id) VALUES (?,?,?)',
        (uid, reason, actor_id))
    if result.rowcount == 0:
        return 'already'
    audit(db, actor_id, 'hold_profile', uid)
    return 'created'




def sanction_duration(kind):
    """Return human-readable duration and relative SQLite expiry expression."""
    return {
        'day': ('24 часа', '+1 day'),
        'week': ('7 дней', '+7 days'),
        'forever': ('бессрочно', None),
    }.get(kind)


def apply_sanction(db, uid: int, actor_id: int, reason: str, kind: str, scope: str = 'profile'):
    """Apply a scoped sanction: profile visibility or bot account suspension.

    Existing indefinite restrictions are preserved.
    """
    if uid <= 0 or actor_id <= 0 or scope not in {'profile','account'} or not 5 <= len(reason.strip()) <= 300:
        return 'invalid'
    duration = sanction_duration(kind)
    if not duration:
        return 'invalid'
    if not db.in_transaction:
        db.execute('BEGIN IMMEDIATE')
    profile = db.execute('SELECT 1 FROM profiles WHERE user_id=?', (uid,)).fetchone()
    if not profile:
        return 'missing'
    table = 'moderation_holds' if scope=='profile' else 'account_suspensions'
    active = db.execute(f"SELECT 1 FROM {table} WHERE user_id=? "
                        "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)", (uid,)).fetchone()
    if active:
        return 'already'
    db.execute(f'DELETE FROM {table} WHERE user_id=?', (uid,))
    expires = db.execute("SELECT datetime('now', ?)", (duration[1],)).fetchone()[0] if duration[1] else None
    db.execute(f'INSERT INTO {table}(user_id,reason,moderator_id,expires_at) VALUES (?,?,?,?)',
               (uid, reason.strip(), actor_id, expires))
    db.execute('INSERT INTO moderation_history(user_id,moderator_id,action,reason,expires_at) VALUES (?,?,?,?,?)',
               (uid,actor_id,'restrict_'+scope,reason.strip(),expires))
    audit(db, actor_id, 'sanction_'+scope+'_'+kind, uid)
    return 'created'


def audit(db, actor_id, action, target_id=None):
    db.execute('INSERT INTO admin_audit(actor_id,action,target_id) VALUES (?,?,?)',
               (actor_id,action,target_id))


def admin_help():
    return ('<b>Управление LUMI</b>\n\n'
            '🆘 Обращения — ответы пользователям\n'
            '🚩 Жалобы — проверка и скрытие анкет\n'
            '🛡 Верификация — решения по кружкам\n'
            '⛔ Ограничения — скрытые модерацией анкеты\n'
            '🚫 Блокировки — временные и бессрочные ограничения аккаунтов\n'
            '📊 Статус — состояние базы и очередей\n\n'
            'Бот доступен только Telegram ID из LUMI_ADMIN_IDS.')


def safe(x, limit=500):
    return html.escape(str(x or '')[:limit], quote=False)


def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, callback_data=data) for text,data in row
    ] for row in rows])


def home_keyboard():
    return keyboard([
        [('🆘 Обращения','adm:tickets:0'), ('🚩 Жалобы','adm:reports:0')],
        [('🛡 Верификация','adm:verify:0'), ('⛔ Ограничения анкет','adm:holds:0')],
        [('🚫 Блокировки аккаунтов','adm:suspensions:0')],
        [('📈 Аналитика','adm:analytics'), ('📊 Статус','adm:status')],
        [('❔ Помощь','adm:help')],
        [('🔄 Обновить','adm:home')],
    ])


async def send_home(message):
    with db_connect() as db:
        tickets=db.execute("SELECT COUNT(*) FROM support_tickets WHERE status IN ('open','delivery_unknown')").fetchone()[0]
        reports=db.execute('''SELECT COUNT(*) FROM reports r LEFT JOIN report_reviews v ON v.report_id=r.id
                              WHERE v.status IS NULL OR v.status='open' ''').fetchone()[0]
        pending=db.execute("SELECT COUNT(*) FROM verification_requests WHERE status='review'").fetchone()[0]
        held=db.execute('SELECT COUNT(*) FROM moderation_holds WHERE expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP').fetchone()[0]
        banned=db.execute('SELECT COUNT(*) FROM account_suspensions WHERE expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP').fetchone()[0]
    await message.answer('💜 <b>LUMI · Панель модератора</b>\n\n'
                         f'🆘 Открытые обращения: <b>{tickets}</b>\n'
                         f'🚩 Жалобы: <b>{reports}</b>\n'
                         f'🛡 Видеопроверки: <b>{pending}</b>\n'
                         f'⛔ Скрытые анкеты: <b>{held}</b>\n'
                         f'🚫 Заблокированные аккаунты: <b>{banned}</b>\n\n'
                         'Выбери раздел ниже.', reply_markup=home_keyboard(), parse_mode='HTML')


@dp.message(CommandStart())
@dp.message(Command('admin'))
async def start(message: Message, state: FSMContext):
    await state.clear()
    await send_home(message)


@dp.message(F.text.in_({'🏠 Домой', '⬅️ Назад'}))
async def admin_navigation(message: Message, state: FSMContext):
    await state.clear()
    await send_home(message)


@dp.message(Command('cancel'))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer('Действие отменено. Возвращаю в панель.')
    await send_home(message)


def read_page(section, page):
    page=max(0,min(page,10000))
    with db_connect() as db:
        if section=='tickets':
            rows=db.execute("SELECT id,user_id,substr(message,1,65),created_at FROM support_tickets "
                            "WHERE status IN ('open','delivery_unknown') ORDER BY id DESC LIMIT 5 OFFSET ?",
                            (page*5,)).fetchall()
        elif section=='reports':
            rows=db.execute('''SELECT r.id,r.reporter_id,r.reported_id,r.created_at
                FROM reports r LEFT JOIN report_reviews v ON v.report_id=r.id
                WHERE v.status IS NULL OR v.status='open'
                ORDER BY r.id DESC LIMIT 5 OFFSET ?''',(page*5,)).fetchall()
        elif section=='suspensions':
            rows=db.execute('SELECT user_id,reason,created_at FROM account_suspensions WHERE expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP ORDER BY created_at DESC LIMIT 5 OFFSET ?', (page*5,)).fetchall()
        elif section=='holds':
            rows=db.execute('SELECT user_id,reason,created_at FROM moderation_holds WHERE expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP ORDER BY created_at DESC LIMIT 5 OFFSET ?',
                            (page*5,)).fetchall()
        else:
            rows=db.execute("SELECT user_id,challenge,created_at FROM verification_requests "
                            "WHERE status='review' ORDER BY created_at LIMIT 5 OFFSET ?",(page*5,)).fetchall()
    return rows


def user_label(db, uid):
    """Display registered name and public username; numeric Telegram ID is fallback.

    Do not use get_chat on a stranger: the admin bot might not have permission.
    """
    try:
        row = db.execute(
            "SELECT name, username FROM profiles WHERE user_id=?", (uid,)
        ).fetchone()
    except sqlite3.Error:
        row = None
    if not row:
        return f"Пользователь {uid}"
    name, username = row
    label = str(name or 'Без имени').strip()
    if username:
        clean = str(username).lstrip('@').strip()
        if re.fullmatch(r"[A-Za-z0-9_]{5,32}", clean):
            return f"{label} (@{clean})"
    return f"{label} · ID {uid}"


def user_detail(db, uid):
    try:
        row = db.execute('SELECT name, username FROM profiles WHERE user_id=?', (uid,)).fetchone()
    except sqlite3.Error:
        row = None
    name = row[0] if row else None
    username = row[1] if row else None
    output = f'👤 <b>{safe(name or "Пользователь", 70)}</b>\n'
    if username:
        clean = str(username).lstrip('@').strip()
        if re.fullmatch(r'[A-Za-z0-9_]{5,32}', clean):
            output += f'🔗 @{safe(clean, 32)}\n'
    else:
        output += '🔗 Username не указан\n'
    output += f'🆔 ID: <code>{uid}</code>'
    return output


async def show_list(message, section, page):
    rows=read_page(section,page)
    titles={'tickets':'🆘 Обращения','reports':'🚩 Жалобы','verify':'🛡 Видеопроверки','holds':'⛔ Ограничения','suspensions':'🚫 Блокировки аккаунтов'}
    buttons=[]
    for row in rows:
        ident=row[0]
        if section=='tickets':
            with db_connect() as db:
                who = user_label(db, row[1])
            label = f'№{ident} · {who}'
        elif section=='reports': label=f'№{ident} · на {row[2]}'
        elif section=='holds': label=f'Скрытая анкета {ident}'
        elif section=='suspensions': label=f'Аккаунт {ident}'
        else: label=f'Пользователь {ident}'
        buttons.append([(label,f'adm:{"ticket" if section=="tickets" else "report" if section=="reports" else "vitem" if section=="verify" else "sitem" if section=="suspensions" else "hitem"}:{ident}')])
    nav=[]
    if page>0: nav.append(('⬅️',f'adm:{section}:{page-1}'))
    if len(rows)==5: nav.append(('➡️',f'adm:{section}:{page+1}'))
    if nav: buttons.append(nav)
    buttons.append([('⬅️ Назад','adm:home'), ('🏠 Домой','adm:home')])
    await message.answer(f'<b>{titles[section]}</b> · страница {page+1}\n\n'
                         + ('Выбери запись:' if rows else 'Новых записей нет.'),
                         reply_markup=keyboard(buttons),parse_mode='HTML')


async def show_ticket(message, ticket_id):
    with db_connect() as db:
        row=db.execute('SELECT user_id,message,status,created_at,reply FROM support_tickets WHERE id=?',(ticket_id,)).fetchone()
        user_info = user_detail(db, row[0]) if row else None
        history=db.execute("SELECT sender,body,created_at FROM support_messages WHERE ticket_id=? "
                           "ORDER BY id DESC LIMIT 6", (ticket_id,)).fetchall()
    if not row:
        await message.answer('Обращение не найдено.');return
    uid,body,status,created,reply=row
    if history:
        transcript='\n\n'.join(f"<b>{'👤 Пользователь' if who=='user' else '🛡 Модератор'}</b> · {safe(at,22)}\n{safe(body,380)}"
                               for who,body,at in reversed(history))
    else:
        transcript=f'<b>👤 Пользователь</b>\n{safe(body,1200)}'
        if reply:transcript+=f'\n\n<b>🛡 Модератор</b>\n{safe(reply,600)}'
    await message.answer(f'🆘 <b>Обращение №{ticket_id}</b>\n'
                         f'{user_info}\nСтатус: <b>{safe(status)}</b>\n'
                         f'Дата: {safe(created)}\n\n{transcript}',
                         reply_markup=keyboard([
                             *([[('✉️ Ответить',f'adm:reply:{ticket_id}')]] if status=='open' else []),
                             *([[('⚠️ Повторить вручную',f'adm:retryconfirm:{ticket_id}')]] if status=='delivery_unknown' else []),
                             [('⛔ Назначить санкцию',f'adm:blockask:{uid}')],
                             [('✅ Закрыть',f'adm:close:{ticket_id}')],
                             [('⬅️ К обращениям','adm:tickets:0'), ('🏠 Домой','adm:home')]]),parse_mode='HTML',protect_content=True)


async def show_report(message, report_id):
    with db_connect() as db:
        row=db.execute('SELECT reporter_id,reported_id,created_at FROM reports WHERE id=?',(report_id,)).fetchone()
        reporter = user_label(db,row[0]) if row else None
        target = user_label(db,row[1]) if row else None
    if not row:
        await message.answer('Жалоба не найдена.');return
    await message.answer(f'🚩 <b>Жалоба №{report_id}</b>\n'
                         f'Автор: {safe(reporter,100)} · <code>{row[0]}</code>\n'
                         f'На анкету: {safe(target,100)} · <code>{row[1]}</code>\n'
                         f'Дата: {safe(row[2])}\n\n'
                         '<i>Жалоба не означает доказанное нарушение. Проверь сведения вручную.</i>',
                         reply_markup=keyboard([
                             [('✅ Отметить рассмотренной',f'adm:review:{report_id}')],
                             [('⛔ Назначить санкцию',f'adm:blockask:{row[1]}')],
                             [('⛔ Скрыть анкету',f'adm:hide:{report_id}')],
                             [('⬅️ К жалобам','adm:reports:0'), ('🏠 Домой','adm:home')]]),parse_mode='HTML',protect_content=True)


async def show_verification(message, user_id):
    with db_connect() as db:
        req=db.execute("SELECT status,challenge,created_at FROM verification_requests WHERE user_id=?",(user_id,)).fetchone()
        label=user_label(db,user_id)
    if not req or req[0]!='review':
        await message.answer('Нет заявки на проверку.');return
    await message.answer('🛡 <b>Видеопроверка анкеты</b>\n'
                         f'👤 <b>{safe(label,100)}</b>\n'
                         f'🆔 <code>{user_id}</code>\n'
                         f'Задание: {safe(req[1],160)}\n\n'
                         'Решение доступно только на кнопках, отправленных вместе с конкретным видеокружком.',
                         reply_markup=keyboard([
                             [('⛔ Назначить санкцию',f'adm:blockask:{user_id}')],
                             [('⬅️ К проверкам','adm:verify:0'), ('🏠 Домой','adm:home')]]),parse_mode='HTML',protect_content=True)


async def show_suspension(message, uid):
    with db_connect() as db:
        row=db.execute('SELECT reason,moderator_id,created_at,expires_at FROM account_suspensions '
                       'WHERE user_id=? AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)',(uid,)).fetchone()
        label=user_detail(db,uid)
    if not row:
        await message.answer('Блокировка уже снята или срок истёк.');return
    until=(safe(row[3],50)+' UTC') if row[3] else 'бессрочно'
    await message.answer('🚫 <b>Аккаунт ограничен</b>\n'+label+'\n\n'
                         f'Причина: {safe(row[0],300)}\n'
                         f'До: <b>{until}</b>\nМодератор: <code>{row[1]}</code>',
        parse_mode='HTML',protect_content=True,
        reply_markup=keyboard([[('🔓 Разблокировать',f'adm:unbanconfirm:{uid}')],
                               [('⬅️ К блокировкам','adm:suspensions:0'),('🏠 Домой','adm:home')]]))

async def show_hold(message, uid):
    with db_connect() as db:
        row=db.execute('SELECT reason,moderator_id,created_at,expires_at FROM moderation_holds WHERE user_id=? AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)',(uid,)).fetchone()
    if not row:
        await message.answer('Ограничение уже снято или запись удалена.');return
    expiration = (f'До: <b>{safe(row[3],50)} UTC</b>'
                  if row[3] else 'Срок: <b>бессрочно</b>')
    await message.answer(f'⛔ <b>Анкета скрыта модерацией</b>\n'
                         f'ID: <code>{uid}</code>\nПричина: {safe(row[0],300)}\n'
                         f'Модератор: <code>{row[1]}</code>\nДата: {safe(row[2],50)}\n'
                         f'{expiration}\n\n'
                         'Проверь обращение пользователя перед снятием ограничения.',
                         reply_markup=keyboard([
                             [('🔓 Снять ограничение',f'adm:unhideconfirm:{uid}')],
                             [('⬅️ К ограничениям','adm:holds:0'), ('🏠 Домой','adm:home')]]),
                         parse_mode='HTML',protect_content=True)


async def show_unhide_confirmation(message,uid):
    with db_connect() as db:
        exists=db.execute('SELECT 1 FROM moderation_holds WHERE user_id=? AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)',(uid,)).fetchone()
    if not exists:
        await message.answer('Ограничение уже снято.');return
    await message.answer(f'Снять модераторскую блокировку анкеты <code>{uid}</code>?\n'
                         'После этого анкета снова сможет появляться в поиске, '
                         'если сам пользователь не скрыл её.',
                         reply_markup=keyboard([
                             [('✅ Подтвердить снятие',f'adm:unhide:{uid}')],
                             [('⬅️ Отмена',f'adm:hitem:{uid}')]]),parse_mode='HTML',protect_content=True)


@dp.callback_query(F.data.startswith('adm:'))
async def admin_callbacks(c: CallbackQuery, state: FSMContext):
    parts=c.data.split(':')
    action=parts[1] if len(parts)>1 else ''
    arg=parts[2] if len(parts)>2 else ''
    await c.answer()
    if action not in ('reply','blockask','scope','sanctiontime','sanctionconfirm'):
        await state.clear()
    if action=='home':
        await state.clear()
        await send_home(c.message);return
    if action=='help':
        await c.message.answer(admin_help(),parse_mode='HTML',reply_markup=keyboard([[('🏠 Домой','adm:home')]]));return
    if action=='analytics':
        with db_connect() as db:
            init_ops(db)
            stats=analytics(db)
        text=('📈 <b>LUMI · Аналитика</b>\n\n'
              f'👤 Анкет: <b>{stats["profiles"]}</b>\n'
              f'🔒 Скрыто пользователями: {stats["hidden"]}\n'
              f'❤️ Лайков всего: {stats["likes"]}\n'
              f'💞 Взаимных пар: {stats["matches"]}\n'
              f'👀 Просмотров сегодня (UTC): {stats["views_today"]}\n'
              f'🆘 Открытых обращений: {stats["tickets_open"]}\n'
              f'🛡 Видеопроверок ожидает: {stats["verification_pending"]}\n'
              f'⭐ Активных Premium: {stats["premium_active"]}\n'
              f'💳 Оплаченных операций: {stats["paid_orders"]}\n'
              f'⚠️ Ошибок сегодня*: {stats["errors_today"]}\n'
              f'🐢 Медленных ответов сегодня*: {stats["slow_today"]}\n\n'
              '<i>* Телеметрия записывается раз в минуту. Сводка не содержит персональных данных. '
              'Лайки и оплаты — накопленные показатели, не статистика за сутки.</i>')
        await c.message.answer(text,parse_mode='HTML',reply_markup=keyboard([[('🔄 Обновить','adm:analytics')],[('🏠 Домой','adm:home')]]));return
    if action=='status':
        with db_connect() as db:
            result=db.execute('PRAGMA quick_check(1)').fetchone()[0]
            count=db.execute('SELECT COUNT(*) FROM profiles').fetchone()[0]
            events=db.execute('SELECT COUNT(*) FROM admin_events WHERE delivered_at IS NULL').fetchone()[0]
        await c.message.answer(f'📊 <b>Статус LUMI</b>\nБаза: <b>{safe(result,40)}</b>\n'
                               f'Анкет: <b>{count}</b>\nНеотправленных уведомлений: {events}',
                               parse_mode='HTML', reply_markup=keyboard([[('⬅️ Назад', 'adm:home'), ('🏠 Домой', 'adm:home')]]));return
    if action=='blockask':
        try:
            uid=int(arg)
            if uid<=0: raise ValueError
        except (ValueError,TypeError):
            await c.message.answer('Некорректный ID анкеты.');return
        with db_connect() as db:
            exists=db.execute('SELECT 1 FROM profiles WHERE user_id=?',(uid,)).fetchone()
            active=db.execute("SELECT 1 FROM moderation_holds WHERE user_id=? AND "
                              "(expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)",(uid,)).fetchone()
            label=user_detail(db,uid) if exists else None
        if not exists:
            await c.message.answer('Анкета уже удалена.');return
        if uid in ADMINS:
            await c.message.answer('Нельзя ограничить аккаунт администратора.');return
        # An existing profile restriction does not prevent a separate account sanction.
        await state.update_data(sanction_user=uid)
        await c.message.answer('⛔ <b>Выбери тип санкции</b>\n\n'+label+'\n\n'
                               'Скрытие анкеты убирает её из поиска.\n'
                               'Блокировка аккаунта запрещает основные функции LUMI, '
                               'но оставляет поддержку и удаление данных.',
            parse_mode='HTML',protect_content=True,
            reply_markup=keyboard([
                [('👁 Скрыть анкету',f'adm:scope:{uid}:profile')],
                [('🚫 Заблокировать аккаунт',f'adm:scope:{uid}:account')],
                [('❌ Отмена','adm:home')]]))
        return
    if action=='scope':
        try:
            uid=int(arg); scope=parts[3]
            if uid<=0 or scope not in ('profile','account'):raise ValueError
        except (ValueError,IndexError):
            await c.message.answer('Некорректный тип санкции.');return
        data=await state.get_data()
        if data.get('sanction_user')!=uid:
            await c.message.answer('Старый выбор. Открой анкету заново.');return
        await state.update_data(sanction_scope=scope)
        await c.message.answer('Выбери срок ограничения:',reply_markup=keyboard([
            [('⏳ 24 часа',f'adm:sanctiontime:{uid}:day'),('📅 7 дней',f'adm:sanctiontime:{uid}:week')],
            [('⛔ Бессрочно',f'adm:sanctiontime:{uid}:forever')],
            [('❌ Отмена','adm:home')]]))
        return
    if action=='sanctiontime':
        try:
            uid=int(arg)
            kind=parts[3]
            if uid<=0 or not sanction_duration(kind): raise ValueError
        except (IndexError, ValueError):
            await c.message.answer('Некорректный срок.');return
        # Only allow proceeding after current moderator initiated sanction flow.
        data=await state.get_data()
        if data.get('sanction_user')!=uid or data.get('sanction_scope') not in ('profile','account'):
            await c.message.answer('Выбор устарел. Открой анкету заново.');return
        await state.update_data(sanction_kind=kind)
        await state.set_state(SanctionState.reason)
        await c.message.answer(f'✍️ <b>Причина ограничения · {sanction_duration(kind)[0]}</b>\n\n'
                               'Напиши причину своими словами (5–300 символов). '
                               'Я покажу её пользователю. Не включай личные данные заявителя.\n\n'
                               '/cancel — отмена.',parse_mode='HTML',protect_content=True)
        return
    if action=='sanctionconfirm':
        data=await state.get_data()
        if await state.get_state()!=SanctionState.confirm.state or not data.get('sanction_user'):
            await c.message.answer('Подтверждение устарело. Начни снова.');return
        uid=data['sanction_user']; reason=data['sanction_reason']; kind=data['sanction_kind']; scope=data.get('sanction_scope','profile')
        with db_connect() as db:
            result=apply_sanction(db,uid,c.from_user.id,reason,kind,scope)
        await state.clear()
        if result=='created':
            await c.message.answer('✅ Ограничение применено. Причина и срок сохранены в журнале.',
                                   reply_markup=keyboard([[('⛔ Ограничения','adm:holds:0'),('🏠 Домой','adm:home')]]))
            duration=sanction_duration(kind)[0]
            sent=await try_user_message(uid,'🛡 <b>LUMI · Решение модерации</b>\n\n'
                                        f"{'Твой аккаунт ограничен. Доступ к знакомствам и играм закрыт.' if scope=='account' else 'Твоя анкета скрыта из поиска.'}\n"
                                        f'Срок: <b>{safe(duration,30)}</b>\n'
                                        f'Причина: {safe(reason,300)}\n\n'
                                        'Если считаешь решение ошибочным, напиши /support.',
                                        parse_mode='HTML')
            if not sent:
                await c.message.answer('⚠️ Не получилось доставить уведомление пользователю. '
                                       'Ограничение сохранено; попробуй связаться через поддержку.')
        else:
            await c.message.answer('Не применено: анкета удалена или уже ограничена.')
        return
    if action in ('tickets','reports','verify','holds','suspensions'):
        try: page=int(arg or 0)
        except ValueError:
            await c.message.answer('Некорректная страница.');return
        await show_list(c.message,action,page);return
    if action in ('ticket','report','vitem','hitem','sitem','unbanconfirm','unban','unhideconfirm','unhide','retryconfirm','retry','reply','close','review','hide'):
        try: obj=int(arg)
        except (ValueError,TypeError):
            await c.message.answer('Некорректный номер.');return
        if action=='ticket': await show_ticket(c.message,obj);return
        if action=='report': await show_report(c.message,obj);return
        if action=='vitem': await show_verification(c.message,obj);return
        if action=='hitem': await show_hold(c.message,obj);return
        if action=='sitem': await show_suspension(c.message,obj);return
        if action=='unbanconfirm':
            await c.message.answer('Разблокировать аккаунт? Это восстановит доступ к функциям LUMI.',reply_markup=keyboard([[('✅ Разблокировать',f'adm:unban:{obj}')],[('❌ Отмена',f'adm:sitem:{obj}')]]));return
        if action=='unban':
            with db_connect() as db:
                result=db.execute('DELETE FROM account_suspensions WHERE user_id=?',(obj,))
                if result.rowcount:
                    audit(db,c.from_user.id,'unban_account',obj)
                    db.execute('INSERT INTO moderation_history(user_id,moderator_id,action) VALUES (?,?,?)',(obj,c.from_user.id,'unban_account'))
            await c.message.answer('✅ Аккаунт разблокирован.' if result.rowcount else 'Ограничение уже снято.')
            if result.rowcount:
                await try_user_message(obj,'🛡 LUMI: блокировка аккаунта снята. Ты снова можешь пользоваться ботом.')
            return
        if action=='unhideconfirm': await show_unhide_confirmation(c.message,obj);return
        if action=='unhide':
            with db_connect() as db:
                result=db.execute('DELETE FROM moderation_holds WHERE user_id=?',(obj,))
                if result.rowcount:
                    audit(db,c.from_user.id,'unhide_profile',obj)
                    db.execute('INSERT INTO moderation_history(user_id,moderator_id,action) VALUES (?,?,?)',(obj,c.from_user.id,'lift'))
            await c.message.answer('✅ Ограничение снято.' if result.rowcount else 'Ограничение уже снято.',
                                   reply_markup=keyboard([[('⬅️ К ограничениям','adm:holds:0'),('🏠 Домой','adm:home')]]))
            if result.rowcount:
                await try_user_message(obj,'🛡 Ограничение модерации снято. Если анкета скрыта в настройках приватности, её можно открыть самостоятельно.')
            return
        if action=='retryconfirm':
            await c.message.answer('⚠️ <b>Доставка не подтверждена</b>\n\n'
                                   'Перед повторным ответом проверь, не получил ли человек сообщение. '
                                   'При сбое Telegram сообщение могло отправиться, но не подтвердиться.',
                                   parse_mode='HTML',reply_markup=keyboard([
                                       [('Я проверил(а), открыть повторно',f'adm:retry:{obj}')],
                                       [('⬅️ Отмена',f'adm:ticket:{obj}')]]))
            return
        if action=='retry':
            with db_connect() as db:
                res=db.execute("UPDATE support_tickets SET status='open',updated_at=CURRENT_TIMESTAMP "
                               "WHERE id=? AND status='delivery_unknown'",(obj,))
                if res.rowcount:audit(db,c.from_user.id,'retry_unknown_ticket',obj)
            await c.message.answer('Обращение снова открыто.' if res.rowcount else 'Статус уже изменён.')
            return
        if action=='reply':
            with db_connect() as db:
                existing=db.execute("SELECT 1 FROM support_tickets WHERE id=? AND status='open'",(obj,)).fetchone()
            if not existing:
                await c.message.answer('Обращение уже закрыто.');return
            await state.set_state(ReplyState.text)
            await state.update_data(ticket_id=obj)
            await c.message.answer(f'✉️ Напиши ответ на обращение №{obj} одним сообщением.\n/cancel — отмена, /admin — домой.',
                                   reply_markup=keyboard([[('⬅️ К обращению',f'adm:ticket:{obj}'),('🏠 Домой','adm:home')]]))
            return
        if action=='close':
            with db_connect() as db:
                closed=db.execute("UPDATE support_tickets SET status='closed',updated_at=CURRENT_TIMESTAMP "
                           "WHERE id=? AND status='open'",(obj,))
                if closed.rowcount:audit(db,c.from_user.id,'close_ticket',obj)
            await c.message.answer('Обращение закрыто.' if closed.rowcount else 'Обращение уже закрыто.');return
        if action=='hide':
            with db_connect() as db:
                target=db.execute('SELECT reported_id FROM reports WHERE id=?',(obj,)).fetchone()
            if not target:
                await c.message.answer('Жалоба уже удалена.');return
            await state.update_data(sanction_user=target[0],sanction_scope='profile')
            await c.message.answer('Выбери срок санкции и напиши причину:',reply_markup=keyboard([
                [('⏳ 24 часа',f'adm:sanctiontime:{target[0]}:day'),('📅 7 дней',f'adm:sanctiontime:{target[0]}:week')],
                [('⛔ Бессрочно',f'adm:sanctiontime:{target[0]}:forever')],
                [('❌ Отмена',f'adm:report:{obj}')]]))
            return
        with db_connect() as db:
            row=db.execute('SELECT reported_id FROM reports WHERE id=?',(obj,)).fetchone()
            if not row:
                await c.message.answer('Жалоба удалена.');return
            already=db.execute('SELECT status FROM report_reviews WHERE report_id=?',(obj,)).fetchone()
            if already and already[0]!='open':
                await c.message.answer('Жалоба уже обработана.');return
            if action=='hide':
                # Private moderation flag. Account cannot undo this by toggling /privacy.
                db.execute('INSERT OR REPLACE INTO moderation_holds(user_id,reason,moderator_id) VALUES (?,?,?)',
                           (row[0],'manual_report_review',c.from_user.id))
            db.execute("INSERT INTO report_reviews(report_id,status,moderator_id,reviewed_at) "
                       "VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(report_id) DO UPDATE SET "
                       "status=excluded.status,moderator_id=excluded.moderator_id,reviewed_at=CURRENT_TIMESTAMP",
                       (obj,'hidden' if action=='hide' else 'reviewed',c.from_user.id))
            audit(db,c.from_user.id,'hide_profile' if action=='hide' else 'review_report',row[0])
        if action=='hide':
            await c.message.answer('Анкета скрыта из поиска модератором. Данные не удалены.')
            await try_user_message(row[0], '🛡 Твоя анкета временно скрыта модерацией. '
                                        'Напиши /support, если считаешь это ошибкой.')
        else:
            await c.message.answer('Жалоба отмечена как рассмотренная.')
        return
    await c.message.answer('Неизвестная команда.')


async def try_user_message(user_id, text, parse_mode=None):
    try:
        async with Bot(token=MAIN_TOKEN) as user_bot:
            await user_bot.send_message(user_id,text,protect_content=True,parse_mode=parse_mode)
        return True
    except TelegramAPIError:
        logger.warning('Не удалось доставить сообщение пользователю %s',user_id)
        return False



@dp.message(SanctionState.reason)
async def sanction_reason_message(message: Message, state: FSMContext):
    reason=(message.text or '').strip()
    if reason.startswith('/') or not 5 <= len(reason) <= 300:
        await message.answer('Напиши причину от 5 до 300 символов. /cancel — отмена.')
        return
    data=await state.get_data()
    uid=data.get('sanction_user'); kind=data.get('sanction_kind'); scope=data.get('sanction_scope')
    if not uid or scope not in ('profile','account') or not sanction_duration(kind):
        await state.clear()
        await message.answer('Действие устарело. Открой анкету снова.');return
    await state.update_data(sanction_reason=reason)
    await state.set_state(SanctionState.confirm)
    await message.answer('⛔ <b>Проверка решения</b>\n\n'
                         f'ID: <code>{uid}</code>\n'
                         f'Тип: <b>{"Блокировка аккаунта" if scope=="account" else "Скрытие анкеты"}</b>\n'
                         f'Срок: <b>{safe(sanction_duration(kind)[0])}</b>\n'
                         f'Причина для пользователя: {safe(reason,300)}\n\n'
                         'Проверь текст. После подтверждения ограничение вступит в силу.',
                         reply_markup=keyboard([
                             [('⛔ Подтвердить санкцию','adm:sanctionconfirm')],
                             [('❌ Отмена','adm:home')]]),parse_mode='HTML',protect_content=True)

@dp.message(SanctionState.confirm)
async def sanction_confirm_text(message: Message):
    await message.answer('Подтверди или отмени решение кнопкой выше. /cancel — отмена.')

@dp.message(ReplyState.text)
async def save_reply(message: Message, state: FSMContext):
    text=(message.text or '').strip()
    if not 1 <= len(text) <= 2000 or text.startswith('/'):
        await message.answer('Ответ должен быть текстом до 2 000 символов. /cancel — отмена.');return
    data=await state.get_data()
    ticket_id=data.get('ticket_id')
    # Claim the ticket BEFORE sending. Prevents two moderators from sending two replies.
    with db_connect() as db:
        result=db.execute("UPDATE support_tickets SET status='sending',assigned_admin=?,"
                          "updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='open'",
                          (message.from_user.id,ticket_id))
        row=db.execute('SELECT user_id FROM support_tickets WHERE id=?',(ticket_id,)).fetchone()
    if not result.rowcount or not row:
        await state.clear()
        await message.answer('Обращение уже обрабатывается или закрыто.');return
    uid=row[0]
    try:
        async with Bot(token=MAIN_TOKEN) as user_bot:
            await user_bot.send_message(uid,f'💜 <b>Поддержка LUMI · №{ticket_id}</b>\n\n'
                                        f'{safe(text,2000)}',parse_mode='HTML',protect_content=True)
    except (TelegramAPIError,OSError,TimeoutError):
        with db_connect() as db:
            db.execute("UPDATE support_tickets SET status='delivery_unknown',updated_at=CURRENT_TIMESTAMP "
                       "WHERE id=? AND status='sending' AND assigned_admin=?",
                       (ticket_id,message.from_user.id))
            audit(db,message.from_user.id,'delivery_unknown',ticket_id)
        await state.clear()
        await message.answer('⚠️ Telegram не подтвердил доставку. Возможно, ответ дошёл. '
                             'Обращение помечено для ручной проверки в панели, не отправляй второй ответ вслепую.')
        return
    with db_connect() as db:
        db.execute("INSERT INTO support_messages(ticket_id,sender,body) VALUES (?,'admin',?)",
                   (ticket_id,text))
        db.execute("UPDATE support_tickets SET reply=?,status='open',updated_at=CURRENT_TIMESTAMP "
                   "WHERE id=? AND status='sending' AND assigned_admin=?",
                   (text,ticket_id,message.from_user.id))
        audit(db,message.from_user.id,'reply_ticket',ticket_id)
    await state.clear()
    await message.answer(f'✅ Ответ доставлен. Диалог №{ticket_id} остаётся открытым.',
                         reply_markup=keyboard([[('✉️ Ответить ещё',f'adm:reply:{ticket_id}')],
                                                [('✅ Закрыть',f'adm:close:{ticket_id}')],
                                                [('🏠 Домой','adm:home')]]))



@dp.callback_query(F.data.startswith('vcheck:'))
async def verify_decision(c: CallbackQuery):
    if c.from_user.id not in ADMINS:
        await c.answer('Доступ запрещён',show_alert=True);return
    try:
        uid,approved,review_id=parse_review_callback(c.data)
    except (ValueError,TypeError,AttributeError):
        await c.answer('Некорректная или устаревшая кнопка',show_alert=True);return
    with db_connect() as db:
        changed=decide_review(db,uid,approved,c.from_user.id,review_id)
        if changed:
            audit(db,c.from_user.id,'approve_video' if approved else 'reject_video',uid)
    if not changed:
        await c.answer('Заявка уже закрыта или отменена',show_alert=True);return
    await c.answer('Решение сохранено')
    try:
        await c.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await try_user_message(uid,'✅ Твоё фото проверено модератором LUMI!' if approved
                           else '❌ Проверка не пройдена. Можешь отправить новый кружок: /verify')


def pending_admin_events():
    with db_connect() as db:
        expired=db.execute('SELECT user_id,moderator_id FROM moderation_holds WHERE expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP').fetchall()
        for uid,actor in expired:
            db.execute('INSERT INTO moderation_history(user_id,moderator_id,action) VALUES (?,?,?)',(uid,actor,'expired'))
        db.execute('DELETE FROM moderation_holds WHERE expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP')
        expired_accounts=db.execute('SELECT user_id,moderator_id FROM account_suspensions WHERE expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP').fetchall()
        for uid,actor in expired_accounts:
            db.execute('INSERT INTO moderation_history(user_id,moderator_id,action) VALUES (?,?,?)',(uid,actor,'account_expired'))
        db.execute('DELETE FROM account_suspensions WHERE expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP')
        return db.execute('SELECT id,type,ref_id FROM admin_events '
                          'WHERE delivered_at IS NULL AND attempts<5 ORDER BY id LIMIT 12').fetchall()


def mark_admin_event(event_id, delivered):
    with db_connect() as db:
        db.execute("UPDATE admin_events SET attempts=attempts+1,"
                   "delivered_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE delivered_at END WHERE id=?",
                   (int(delivered),event_id))


async def dispatch_events(bot):
    """Use same database as durable queue; never include full profile data in alerts."""
    while True:
        try:
            events = await asyncio.to_thread(pending_admin_events)
            for event_id,kind,ref in events:
                content={
                    'ticket':f'🆘 Новое обращение №{ref}',
                    'report':f'🚩 Новая жалоба №{ref}',
                    'verification':f'🛡 Новая заявка на проверку · пользователь {ref}',
                    'error':'⚠️ LUMI: зарегистрирована ошибка обработчика. Проверь журнал.',
                    'slow':'🐢 LUMI: зафиксированы медленные ответы. Проверь /health и нагрузку.',
                    'guard':f'🛡 LUMI GUARD: подозрительно высокая частота действий · ID {ref}. Проверь вручную, без автоматической блокировки.',
                }.get(kind,'🔔 Служебное событие LUMI')
                delivered=False
                for moderator in sorted(ADMINS):
                    try:
                        markup=keyboard([[('Открыть в панели', f'adm:{"ticket" if kind=="ticket" else "report" if kind=="report" else "vitem" if kind=="verification" else "status"}' + (f':{ref}' if kind in ('ticket','report','verification') else ''))]])
                        await bot.send_message(moderator,content,reply_markup=markup,protect_content=True)
                        delivered=True
                    except TelegramAPIError:
                        logger.warning('Администратор %s недоступен — нажми /start в админ-боте',moderator)
                await asyncio.to_thread(mark_admin_event, event_id, delivered)
        except (sqlite3.Error, TelegramAPIError):
            logger.exception('Ошибка очереди уведомлений администрации')
        await asyncio.sleep(12)


@dp.message()
async def fallback(message: Message):
    await message.answer('Открой /admin или нажми кнопку на панели.')


async def main():
    from lumi_preflight import validate
    validate("admin")
    from lumi_database_vault import private_process_files
    private_process_files()
    if not ADMIN_TOKEN or not MAIN_TOKEN or not ADMINS:
        raise RuntimeError('Настрой BOT_TOKEN, LUMI_ADMIN_BOT_TOKEN и LUMI_ADMIN_IDS в .env')
    if ADMIN_TOKEN==MAIN_TOKEN:
        raise RuntimeError('У админ-бота должен быть собственный токен от BotFather')
    if not DB_PATH.exists():
        raise RuntimeError('lumi.db не найден: запусти сначала основной bot.py')
    init_admin_schema()
    with db_connect() as db:
        init_ops(db)
    # A crash during Telegram send cannot prove if a message was delivered.
    # Leave such tickets in a visible manual-review state, not automatically resend.
    with db_connect() as db:
        db.execute("UPDATE support_tickets SET status='delivery_unknown' WHERE status='sending'")
    with db_connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS moderation_holds (
            user_id INTEGER PRIMARY KEY,reason TEXT NOT NULL,moderator_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    bot=Bot(token=ADMIN_TOKEN)
    from lumi_supervisor import supervise, stop_workers
    task=asyncio.create_task(supervise("admin-events", lambda: dispatch_events(bot), logger))
    try:
        await bot.set_my_commands([
            BotCommand(command='admin',description='Панель LUMI'),
            BotCommand(command='cancel',description='Отменить ответ'),
        ])
        await bot.delete_webhook(drop_pending_updates=False)
        await bounded_polling(dp, bot, "LUMI_ADMIN_POLLING_LIMIT", 8)
    finally:
        try:
            await stop_workers(task)
        finally:
            await bot.session.close()


if __name__=='__main__':
    asyncio.run(main())
