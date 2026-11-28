"""Bound the number of Telegram update tasks before they are created."""
import inspect
import os


def polling_limit(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 3:
        raise RuntimeError(f'{name}: expected integer between 1 and 256')
    limit = int(raw)
    if not 1 <= limit <= 256:
        raise RuntimeError(f'{name}: expected integer between 1 and 256')
    return limit


async def bounded_polling(dispatcher, bot, name: str, default: int):
    # Older aiogram releases accept arbitrary kwargs without enforcing this limit.
    if 'tasks_concurrency_limit' not in inspect.signature(dispatcher.start_polling).parameters:
        raise RuntimeError('Upgrade aiogram to >=3.20.0.post0 before polling')
    await dispatcher.start_polling(bot, handle_as_tasks=True,
                                   tasks_concurrency_limit=polling_limit(name, default))
