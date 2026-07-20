from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from .config import settings
from .remnawave_api import remnawave

logger = logging.getLogger(__name__)


def _get_setting(*names: str, default: Any = None) -> Any:
    for name in names:
        value = getattr(settings, name, None)
        if value not in (None, ""):
            return value
    return default


def get_wifi_squad_uuid() -> str:
    value = _get_setting(
        "remnawave_wifi_squad_uuid",
        "remnawave_squad_1_uuid",
        "remnawave_wifi_uuid",
    )
    if not value:
        raise RuntimeError("Wi-Fi squad UUID is not configured")
    return str(value)


def get_mobile_squad_uuid() -> str:
    value = _get_setting(
        "remnawave_mobile_squad_uuid",
        "remnawave_squad_2_uuid",
        "remnawave_mobile_uuid",
    )
    if not value:
        raise RuntimeError("Mobile squad UUID is not configured")
    return str(value)


def get_mobile_traffic_gb(default: int = 50) -> int:
    return int(
        _get_setting(
            "remnawave_mobile_traffic_gb",
            "remnawave_sub2_traffic_limit_gb",
            default=default,
        )
    )


def get_trial_mobile_traffic_gb(default: int = 10) -> int:
    return int(_get_setting("remnawave_trial_mobile_traffic_gb", default=default))


@dataclass
class IssuedPair:
    url: str
    username: str


def make_admin_test_order(tg_id: int, days: int = 30) -> dict[str, Any]:
    return {
        "payment_id": f"admin_test:{tg_id}:{uuid4().hex[:16]}",
        "tg_id": tg_id,
        "kind": "admin_test",
        "days": days,
        "amount": 0,
        "promo_code": None,
        "promo_discount": 0,
    }


async def issue_pair_for_order(order: dict[str, Any]) -> IssuedPair:
    tg_id = int(order["tg_id"])
    days = int(order.get("days") or 30)
    wifi_squad_uuid = get_wifi_squad_uuid()
    mobile_squad_uuid = get_mobile_squad_uuid()
    mobile_traffic_gb = int(order.get("mobile_traffic_gb") or get_mobile_traffic_gb())
    wifi_traffic_gb = int(order.get("wifi_traffic_gb") or 0)

    created = await remnawave.create_subscription_pair(
        telegram_id=tg_id,
        days=days,
        wifi_squad_uuid=wifi_squad_uuid,
        mobile_squad_uuid=mobile_squad_uuid,
        mobile_traffic_gb=mobile_traffic_gb,
        wifi_traffic_gb=wifi_traffic_gb,
        base_username=str(tg_id),
        description=f"TG {tg_id} access",
    )
    first = created[0]
    return IssuedPair(url=first.subscription_url, username=first.username)


async def deliver_paid_order(order: dict[str, Any], bot: Bot) -> bool:
    """
    Выдаёт 1 объединённый ключ и отправляет его пользователю.
    Если пользователь не начал чат с ботом, пишет ошибку админу.
    """
    tg_id = int(order["tg_id"])
    kind = str(order.get("kind") or "payment")
    logger.info(
        "Start delivery | payment_id=%s | tg_id=%s | kind=%s | days=%s",
        order.get("payment_id"),
        tg_id,
        kind,
        order.get("days"),
    )

    try:
        issued = await issue_pair_for_order(order)

        text = (
            f"✅ Оплата обработана.\n\n"
            f"Ключ доступа:\n{issued.url}"
        )
        await bot.send_message(chat_id=tg_id, text=text)
        logger.info(
            "Delivery success | tg_id=%s | username=%s",
            tg_id,
            issued.username,
        )
        return True

    except (TelegramForbiddenError, TelegramBadRequest) as e:
        logger.exception("Cannot message user | tg_id=%s | error=%s", tg_id, e)
        admin_id = int(getattr(settings, "admin_id", 0) or 0)
        if admin_id:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=(
                        "❌ Не удалось отправить подписки пользователю.\n\n"
                        f"TG ID: {tg_id}\n"
                        f"Ошибка: {type(e).__name__}: {e}"
                    ),
                )
            except Exception:
                logger.exception("Failed to notify admin about send error")
        return False

    except Exception as e:
        logger.exception("Delivery failed | tg_id=%s | error=%s", tg_id, e)
        admin_id = int(getattr(settings, "admin_id", 0) or 0)
        if admin_id:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=(
                        "❌ Ошибка при выдаче подписок.\n\n"
                        f"TG ID: {tg_id}\n"
                        f"Ошибка: {type(e).__name__}: {e}"
                    ),
                )
            except Exception:
                logger.exception("Failed to notify admin about generic error")
        return False
