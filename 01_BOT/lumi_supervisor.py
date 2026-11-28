"""Restart failed long-running background loops without logging private payloads."""
import asyncio
import time


async def supervise(name, factory, logger, *, sleep=asyncio.sleep, clock=time.monotonic):
    delay = 5
    while True:
        started = clock()
        try:
            await factory()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error('Background loop %s stopped: %s', name, type(exc).__name__)
        else:
            logger.error('Background loop %s returned unexpectedly', name)
        if clock() - started >= 300:
            delay = 5
        await sleep(delay)
        delay = min(120, delay * 2)


async def stop_workers(*tasks):
    active = tuple(task for task in tasks if task is not None)
    for task in active:
        task.cancel()
    await asyncio.gather(*active, return_exceptions=True)
