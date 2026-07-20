from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from time import monotonic
from typing import Any

from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from .config import settings

logger = logging.getLogger(__name__)


@dataclass
class _BucketConfig:
    min_interval: float = 0.28
    max_events: int = 20
    window_sec: float = 10.0
    callback_min_interval: float = 0.5


class AntiFloodMiddleware(BaseMiddleware):
    """Simple in-memory anti-flood guard for Telegram updates.

    It does not block the whole bot. It only drops bursts from one user/chat,
    which is enough to stop double-taps, spam callbacks and accidental floods.
    """

    def __init__(self, config: _BucketConfig | None = None) -> None:
        self.config = config or _BucketConfig()
        self._events: dict[int, deque[float]] = defaultdict(deque)
        self._last_seen: dict[tuple[int, str], float] = {}
        self._last_notice: dict[int, float] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _extract_user_id(event: Any, data: dict[str, Any]) -> int | None:
        user = data.get('event_from_user')
        if user and getattr(user, 'id', None):
            return int(user.id)
        for attr in ('from_user',):
            obj = getattr(event, attr, None)
            if obj and getattr(obj, 'id', None):
                return int(obj.id)
        message = getattr(event, 'message', None)
        if message and getattr(message, 'from_user', None) and getattr(message.from_user, 'id', None):
            return int(message.from_user.id)
        return None

    async def _block(self, event: Any, reason: str) -> None:
        if isinstance(event, CallbackQuery):
            with contextlib.suppress(Exception):
                await event.answer(reason, show_alert=False)
        elif isinstance(event, Message):
            chat = getattr(event, 'chat', None)
            if chat and getattr(chat, 'id', None):
                with contextlib.suppress(Exception):
                    await event.bot.send_message(chat.id, reason)

    async def _warn_support(self, event: Any, user_id: int, event_type: str, reason: str) -> None:
        # Intentionally disabled: антиспам не должен пересылать что-либо в support/admin chat.
        return None

    @staticmethod
    def _event_key(user_id: int, event: Any) -> tuple[int, str, str]:
        if isinstance(event, CallbackQuery):
            return (user_id, 'CallbackQuery', str(getattr(event, 'data', '') or ''))
        return (user_id, type(event).__name__, '')

    async def __call__(self, handler, event, data):  # type: ignore[override]
        user_id = self._extract_user_id(event, data)
        if not user_id:
            return await handler(event, data)

        support_chat_id = getattr(settings, 'support_chat_id', 0)
        if isinstance(event, Message) and support_chat_id and getattr(getattr(event, 'chat', None), 'id', None) == support_chat_id:
            return await handler(event, data)

        now = monotonic()
        event_type = type(event).__name__
        callback_heavy = isinstance(event, CallbackQuery)
        min_interval = self.config.callback_min_interval if callback_heavy else self.config.min_interval

        async with self._lock:
            key = self._event_key(user_id, event)
            last = self._last_seen.get(key)
            if last is not None and now - last < min_interval:
                logger.warning('AntiFlood blocked %s from user %s (cooldown)', event_type, user_id)
                await self._block(event, '⏳ Не спамьте. Подождите немного.')
                await self._warn_support(event, user_id, event_type, 'cooldown')
                return None

            bucket = self._events[user_id]
            while bucket and now - bucket[0] > self.config.window_sec:
                bucket.popleft()
            bucket.append(now)
            if len(bucket) > self.config.max_events:
                logger.warning('AntiFlood blocked user %s (burst=%s)', user_id, len(bucket))
                await self._block(event, '⏳ Не спамьте. Подождите немного.')
                await self._warn_support(event, user_id, event_type, f'burst={len(bucket)}')
                return None

            self._last_seen[key] = now

        return await handler(event, data)

