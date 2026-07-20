from uuid import uuid4
import asyncio

from yookassa import Configuration, Payment
from yookassa.domain.exceptions import NotFoundError

from .config import settings

Configuration.account_id = settings.yookassa_shop_id
Configuration.secret_key = settings.yookassa_secret_key


def _payment_payload(tg_id: int, tariff_code: str, amount: int, days: int, promo_code: str | None = None, promo_discount: int = 0) -> dict:
    description = f'Оплата {tariff_code} для пользователя {tg_id}'
    if promo_code and promo_discount:
        description += f' (промокод {promo_code}, скидка {promo_discount}%)'

    return {
        'amount': {'value': str(amount), 'currency': 'RUB'},
        'confirmation': {'type': 'redirect', 'return_url': 'https://t.me/noirlatch_bot'},
        'capture': True,
        'description': description,
        'payment_method_data': {'type': 'sbp'},
        'metadata': {
            'tg_id': str(tg_id),
            'tariff': tariff_code,
            'days': str(days),
            'promo_code': promo_code or '',
            'promo_discount': str(promo_discount),
        },
    }


async def create_payment(tg_id: int, tariff_code: str, amount: int, days: int, promo_code: str | None = None, promo_discount: int = 0) -> dict:
    payload = _payment_payload(tg_id, tariff_code, amount, days, promo_code, promo_discount)

    def _create():
        return Payment.create(payload, str(uuid4()))

    payment = await asyncio.to_thread(_create)
    return {
        'payment_id': payment.id,
        'confirmation_url': payment.confirmation.confirmation_url,
        'amount': amount,
        'days': days,
    }


async def get_payment_status(payment_id: str) -> str:
    if ':' in payment_id and not payment_id.startswith('payment:') and not payment_id.startswith('refill:'):
        return 'succeeded'

    def _find():
        try:
            return Payment.find_one(payment_id)
        except NotFoundError:
            return None

    payment = await asyncio.to_thread(_find)
    if payment is None:
        return ''
    return getattr(payment, 'status', '') or ''
