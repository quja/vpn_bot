import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

from .config import settings
from .db import init_db
from .antiflood import AntiFloodMiddleware
from .handlers import payment_orders_monitor, remnawave_usage_monitor, subscription_notifications_monitor, router


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('app.remnawave_api').setLevel(logging.WARNING)

    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN пустой. Заполни файл .env")

    await init_db()
    session = AiohttpSession()
    bot = Bot(token=settings.bot_token, session=session)
    dp = Dispatcher(storage=MemoryStorage())
    flood = AntiFloodMiddleware()
    router.message.middleware(flood)
    router.callback_query.middleware(flood)
    dp.include_router(router)

    await bot.delete_my_commands(scope=BotCommandScopeDefault())
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="profile", description="Мой профиль"),
            BotCommand(command="invite", description="Пригласить друга"),
            BotCommand(command="support", description="Поддержка"),
        ],
        scope=BotCommandScopeDefault(),
    )

    intro_text = (
        '👋 Добро пожаловать в NoirLatch\n\n'
        '🔐 Надёжный и приватный доступ\n'
        '🛡 Максимальная анонимность и безопасность\n'
        '✨ Полная конфиденциальность без лишних данных\n'
        '💰 Вы можете не только пользоваться конфигуратором, но и зарабатывать вместе с сервисом.\n'
        '🎁 В боте проходят розыгрыши и промо-акции.\n\n'
        'Нажмите кнопку ниже, чтобы открыть меню.'
    )
    try:
        await bot.set_my_short_description(short_description='👋 Добро пожаловать в NoirLatch')
    except Exception:
        pass
    try:
        await bot.set_my_description(description=intro_text)
    except Exception:
        pass


    print("✅ Бот успешно запущен")
    print("Меню бота обновлено: /start, /profile, /invite, /support, /earnings")

    usage_monitor_task = asyncio.create_task(remnawave_usage_monitor(bot))
    notification_monitor_task = asyncio.create_task(subscription_notifications_monitor(bot))
    payment_monitor_task = asyncio.create_task(payment_orders_monitor(bot))
    try:
        await dp.start_polling(bot)
    finally:
        for task in (usage_monitor_task, notification_monitor_task, payment_monitor_task):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
