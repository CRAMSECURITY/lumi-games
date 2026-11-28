"""LUMI: cooperative two-player Telegram quest. No extra dependencies.

Each player uses their own private chat with the bot; progress is stored in SQLite.
This module intentionally does not change existing Duo Quest tables or rewards.
"""
import secrets
import sqlite3
from datetime import datetime, timezone
from urllib.parse import quote

from aiogram import F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

QUESTIONS = (
    ("🌌 Вы нашли портал в другой мир. Куда идём?", ("🏰 В таинственный замок", "🌲 В волшебный лес", "🚀 На далёкую планету")),
    ("🗝 Перед вами три ключа. Какой возьмёте?", ("🔥 Огненный", "💧 Водяной", "✨ Звёздный")),
    ("🐉 Дракон охраняет мост. Что предпримете?", ("🤝 Подружимся", "🧩 Разгадаем загадку", "🛡 Найдём обход")),
    ("🎁 Вам достался один сундук. Что внутри?", ("💎 Кристалл удачи", "📜 Древняя карта", "🐣 Маленький питомец")),
    ("🌠 Ваше финальное желание?", ("💜 Всегда быть командой", "🌍 Новые приключения", "✨ Исполнение мечты")),
)


def init_friend_quest(db):
    db.execute('''CREATE TABLE IF NOT EXISTS friend_quest_rooms (
        token TEXT PRIMARY KEY,
        host_id INTEGER NOT NULL,
        guest_id INTEGER,
        step INTEGER NOT NULL DEFAULT 0,
        host_choice INTEGER,
        guest_choice INTEGER,
        score INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'waiting' CHECK(status IN ('waiting','playing','finished')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_fq_host ON friend_quest_rooms(host_id,status)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_fq_guest ON friend_quest_rooms(guest_id,status)')


def share_keyboard(link):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💌 Отправить другу', url=f'https://t.me/share/url?url={quote(link, safe="")}')],
        [InlineKeyboardButton(text='🏠 Главное меню', callback_data='ux:home')],
    ])


def choices_keyboard(token, step):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f'fq:{token}:{step}:{i}')]
        for i, label in enumerate(QUESTIONS[step][1])
    ])


async def safe_send(bot, uid, text, **kwargs):
    try:
        await bot.send_message(uid, text, **kwargs)
        return True
    except Exception:
        # Player may have blocked the bot; the other player's progress remains intact.
        return False


async def send_step(bot, uid, token, step, score):
    text = (f'🎮 LUMI · ПРИКЛЮЧЕНИЕ ВДВОЁМ\n\n'
            f'Этап {step + 1}/{len(QUESTIONS)} · 💜 Единство: {score}\n\n'
            f'{QUESTIONS[step][0]}\n\n'
            'Выбери ответ. Когда друг тоже ответит, откроется следующий этап!')
    await safe_send(bot, uid, text, reply_markup=choices_keyboard(token, step))


def register_friend_quest(dp, connect_db):
    """Register before polling, alongside other aiogram handlers."""

    async def create_game(message, uid):
        token = secrets.token_urlsafe(9)  # only letters/numbers/-/_; fits callback_data
        with connect_db() as db:
            init_friend_quest(db)
            db.execute('INSERT INTO friend_quest_rooms(token,host_id) VALUES (?,?)', (token, uid))
        me = await message.bot.get_me()
        link = f'https://t.me/{me.username}?start=fq_{token}'
        await message.answer('🎮 LUMI · ПРИКЛЮЧЕНИЕ ВДВОЁМ\n\n'
                             'Вы вместе выбираете путь в волшебном мире!\n'
                             '5 этапов, два телефона, общий финал. 💜\n\n'
                             'Пригласи одного друга — как только он зайдёт, начнётся игра.\n\n'
                             f'Ссылка: {link}', reply_markup=share_keyboard(link))

    @dp.message(Command('friendgame'))
    async def create_game_command(message):
        await create_game(message, message.from_user.id)

    @dp.callback_query(F.data == 'fq:new')
    async def create_game_button(callback):
        await callback.answer()
        await create_game(callback.message, callback.from_user.id)

    @dp.callback_query(F.data.startswith('fq:'))
    async def choose(callback):
        parts = (callback.data or '').split(':')
        if len(parts) != 4:
            await callback.answer('Некорректная кнопка', show_alert=True)
            return
        _, token, step_raw, choice_raw = parts
        if not step_raw.isdigit() or not choice_raw.isdigit():
            await callback.answer('Некорректная кнопка', show_alert=True)
            return
        step, choice = int(step_raw), int(choice_raw)
        if not (0 <= step < len(QUESTIONS) and 0 <= choice < 3):
            await callback.answer('Некорректная кнопка', show_alert=True)
            return
        uid = callback.from_user.id
        with connect_db() as db:
            db.execute('BEGIN IMMEDIATE')
            room = db.execute('SELECT host_id,guest_id,step,host_choice,guest_choice,score,status '
                              'FROM friend_quest_rooms WHERE token=?', (token,)).fetchone()
            if not room or uid not in room[:2] or room[6] != 'playing' or room[2] != step:
                result = 'Этот этап уже недоступен.'
                updates = None
            else:
                host, guest, _, hchoice, gchoice, score, _ = room
                field = 'host_choice' if uid == host else 'guest_choice'
                if (hchoice if uid == host else gchoice) is not None:
                    result = 'Ты уже ответил(а). Ждём друга!'
                    updates = None
                else:
                    db.execute(f'UPDATE friend_quest_rooms SET {field}=? WHERE token=?', (choice, token))
                    hchoice = choice if uid == host else hchoice
                    gchoice = choice if uid == guest else gchoice
                    if hchoice is not None and gchoice is not None:
                        both_same = hchoice == gchoice
                        new_score = score + int(both_same)
                        final = step == len(QUESTIONS) - 1
                        db.execute('UPDATE friend_quest_rooms SET step=?,host_choice=NULL,guest_choice=NULL,'
                                   'score=?,status=? WHERE token=?',
                                   (step+1, new_score, 'finished' if final else 'playing', token))
                        result = 'Вы оба ответили!'
                        updates = (host, guest, step, hchoice, gchoice, new_score, final, both_same)
                    else:
                        result = 'Ответ сохранён. Ждём друга!'
                        updates = None
        await callback.answer(result)
        if callback.message:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
        if updates:
            host, guest, idx, hchoice, gchoice, score, final, same = updates
            answers = QUESTIONS[idx][1]
            recap = (f'✨ Этап {idx+1}/{len(QUESTIONS)} завершён!\n\n'
                     f'Первый игрок: {answers[hchoice]}\n'
                     f'Второй игрок: {answers[gchoice]}\n\n'
                     + ('💞 Вы выбрали одинаково! +1 к единству.' if same
                        else '🌈 Разные решения — тоже отличная команда!'))
            for player in (host, guest):
                await safe_send(callback.bot, player, recap)
            if final:
                title = ('🌟 Легендарная команда' if score >= 4 else
                         '💜 Команда приключенцев' if score >= 2 else
                         '🪄 Дуэт противоположностей')
                text = (f'🏆 ПРИКЛЮЧЕНИЕ ЗАВЕРШЕНО!\n\n{title}\n'
                        f'Совпавших решений: {score}/{len(QUESTIONS)}\n\n'
                        'Вы прошли все испытания вместе! Это развлекательная игра, а не тест дружбы.\n\n'
                        'Хотите снова? /friendgame')
                for player in (host, guest):
                    await safe_send(callback.bot, player, text)
            else:
                for player in (host, guest):
                    await send_step(callback.bot, player, token, idx+1, score)

    async def join_game(message, token):
        uid = message.from_user.id
        with connect_db() as db:
            init_friend_quest(db)
            db.execute('BEGIN IMMEDIATE')
            room = db.execute('SELECT host_id,guest_id,status,created_at FROM friend_quest_rooms '
                              'WHERE token=?', (token,)).fetchone()
            if room is None:
                status = 'Ссылка на игру не найдена.'
                players = None
            elif room[0] == uid:
                status = 'Это твоя комната! Отправь ссылку другу.'
                players = None
            elif room[1] is not None or room[2] != 'waiting':
                status = 'Эта комната уже занята. Создай свою: /friendgame'
                players = None
            else:
                age_seconds = (datetime.now(timezone.utc) - datetime.strptime(
                    room[3], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)).total_seconds()
                if age_seconds > 48*3600:
                    status = 'Ссылка устарела. Попроси друга создать новую игру.'
                    players = None
                else:
                    db.execute("UPDATE friend_quest_rooms SET guest_id=?,status='playing' "
                               "WHERE token=? AND guest_id IS NULL AND status='waiting'", (uid, token))
                    players = (room[0], uid)
                    status = '💜 Ты в игре! Начинаем совместное приключение.'
        await message.answer(status)
        if players:
            for player in players:
                await safe_send(message.bot, player, '🎉 Оба игрока присоединились! Ваше приключение начинается.')
                await send_step(message.bot, player, token, 0, 0)
        return True

    return join_game
