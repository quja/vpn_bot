from __future__ import annotations

import asyncio
import contextlib
import base64
import html
import json
import logging
import secrets
from pathlib import Path

import httpx
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, FSInputFile

from .config import (
    DEFAULT_REF_PERCENT,
    MOBILE_REFILL_PRICE,
    MOBILE_TRAFFIC_GB,
    PARTNER_REF_PERCENT,
    PARTNER_TRAFFIC_GB,
    REF_BONUS_COUNT,
    TRIAL_TRAFFIC_GB,
    TRIAL_TRAFFIC_LIMIT_GB,
    settings,
)
from .db import (
    get_all_remnawave_subscriptions,
    adjust_user_balance,
    adjust_ref_paid_count,
    clear_user_promo,
    create_payment_order,
    delete_all_user_subscriptions,
    delete_user_subscriptions,
    delete_promo_code,
    deactivate_all_users_access,
    get_promo_trial_recipient,
    mark_promo_trial_recipient_activated,
    upsert_promo_trial_recipient,
    get_active_admins,
    get_active_clients,
    get_active_partners,
    get_all_remnawave_subscriptions,
    get_all_users,
    get_latest_active_subscription,
    get_trial_promo_broadcast_targets,
    get_no_trial_broadcast_targets,
    search_users,
    get_month_referral_count,
    get_next_subscription_slot,
    get_payment_order,
    get_pending_payment_orders,
    get_promo_code_row,
    get_referral_count,
    get_remnawave_subscription_by_user_slot,
    get_remnawave_subscriptions,
    get_user,
    get_user_id_by_support_message,
    get_meta_value,
    set_meta_value,
    get_user_subscriptions,
    get_user_subscriptions_by_kind,
    has_promo_redemption,
    increment_ref_paid_count,
    list_promo_codes,
    mark_promo_redemption,
    mark_payment_status,
    mark_trial_used,
    reserve_trial_access,
    save_remnawave_subscription,
    save_support_links,
    set_last_ref_bonus_date,
    set_partner_bonus_month,
    set_partner_month_state,
    set_promo_code_active,
    set_user_access,
    set_user_admin,
    set_user_partner,
    set_user_promo,
    transfer_user_balance,
    update_remnawave_subscription_fields,
    update_remnawave_subscription_identity,
    update_remnawave_subscription_limit,
    update_remnawave_subscription_reset_at,
    update_remnawave_subscription_usage,
    update_user_fields,
    upsert_promo_code,
    upsert_user,
    utc_in_days,
    utc_now,
    set_remnawave_subscription_mobile_disabled,
)
from .keyboards import (
    admin_keyboard,
    balance_topup_keyboard,
    client_detail_keyboard,
    admins_list_keyboard,
    clients_list_keyboard,
    documentation_keyboard,
    earnings_keyboard,
    insufficient_funds_keyboard,
    main_menu_keyboard,
    partner_detail_keyboard,
    partners_list_keyboard,
    profile_keyboard,
    profile_key_detail_keyboard,
    profile_keys_keyboard,
    profile_keys_list_keyboard,
    purchase_confirm_keyboard,
    purchase_label_keyboard,
    referral_keyboard,
    refill_confirm_keyboard,
    refill_prompt_keyboard,
    refill_target_keyboard,
    support_keyboard,
    tariff_choice_keyboard,
    tariffs_keyboard,
    happ_keys_keyboard,
    happ_instruction_keyboard,
    promo_admin_keyboard,
    promo_manage_keyboard,
    promo_single_use_keyboard,
    promo_trial_activation_keyboard,
    trial_invitation_keyboard,
    trial_usage_low_keyboard,
    trial_usage_high_keyboard,
    renew_menu_keyboard,
    withdraw_keyboard,
    welcome_keyboard,
    subscription_list_keyboard,
    subscription_manage_keyboard,
)
from .payments import create_payment, get_payment_status
from .remnawave_api import remnawave

router = Router()
logger = logging.getLogger(__name__)

TRIAL_DAYS = 3
PARTNER_BONUS_MIN_REFERRALS = 30
PARTNER_BONUS_AMOUNT = 2000
PARTNER_GRANT_DAYS = 365
PARTNER_ACCESS_TRAFFIC_GB = 50
REFERRAL_CASHBACK_PERCENT = 10
MOBILE_REFILL_DAYS = 30
ADMIN_TEST_AMOUNT = 200
ADMIN_TEST_DAYS = 30
TRIAL_USAGE_NOTIFY_THRESHOLD_BYTES = int(0.5 * 1024 * 1024 * 1024)
TRIAL_USAGE_NOTIFY_AFTER_HOURS = 4
EXPIRY_NOTIFY_INTERVAL_SEC = 300
NO_TRIAL_NOTIFY_AFTER_DAYS = 1

HAPP_INSTRUCTION_IMAGE_PATH = Path(__file__).resolve().parent / 'media' / 'instruction.png'
EARNINGS_IMAGE_PATH = Path(__file__).resolve().parent / 'media' / 'earnings.png'
HAPP_CRYPTO_API_URL = 'https://crypto.happ.su/api-v2.php'
HAPP_REDIRECT_BASE_URL = 'https://go.proxysocks.ru/'
HAPP_CRYPTO_CACHE: dict[str, str] = {}
HAPP_ACTION_CACHE: dict[int, dict[str, str]] = {}


class SupportForm(StatesGroup):
    waiting_for_message = State()


class PromoForm(StatesGroup):
    waiting_for_promo = State()


class PromoAdminForm(StatesGroup):
    waiting_for_code = State()
    waiting_for_discount = State()
    waiting_for_single_use = State()
    waiting_for_trial_code = State()
    waiting_for_broadcast_message = State()
    waiting_for_broadcast_confirm = State()


class RefillForm(StatesGroup):
    waiting_for_gb = State()
    waiting_for_target = State()


class ExtendForm(StatesGroup):
    waiting_for_target = State()
    waiting_for_days = State()


class PurchaseForm(StatesGroup):
    waiting_for_label = State()


class ProfileForm(StatesGroup):
    waiting_for_transfer_amount = State()


class AdminForm(StatesGroup):
    waiting_for_target = State()
    waiting_for_amount = State()
    waiting_for_confirm = State()
    waiting_for_days = State()
    waiting_for_limit = State()
    waiting_for_broadcast = State()
    waiting_for_trial_broadcast_message = State()
    waiting_for_trial_broadcast_confirm = State()
    waiting_for_create_key_target = State()
    waiting_for_create_key_days = State()
    waiting_for_create_key_limit = State()
    waiting_for_user_search = State()


TARIFFS = {
    '1m': {'amount': 200, 'days': 30, 'title': '1 месяц'},
    '3m': {'amount': 500, 'days': 90, 'title': '3 месяца'},
    '6m': {'amount': 950, 'days': 180, 'title': '6 месяцев'},
    '12m': {'amount': 1700, 'days': 365, 'title': '12 месяцев'},
    'refill': {'amount': MOBILE_REFILL_PRICE, 'days': MOBILE_REFILL_DAYS, 'title': 'Докупка трафика'},
}

EXTEND_DAY_OPTIONS = (5, 10, 15, 20, 30)

PROMO_CODES = {
    'FIRST15': {'discount': 15, 'single_use': False},
}


def row_value(row, *keys, default=None):
    if row is None:
        return default
    if hasattr(row, 'keys'):
        available = set(row.keys())
        for key in keys:
            if key in available:
                return row[key]
    elif isinstance(row, dict):
        for key in keys:
            if key in row:
                return row[key]
    return default




def callback_parts(callback: CallbackQuery) -> list[str]:
    return (callback.data or '').split(':')


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def parse_start_payload(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 and parts[1].strip() else None


def current_month_key(dt: datetime | None = None) -> str:
    return (dt or datetime.now(timezone.utc)).strftime('%Y-%m')


def _traffic_reset_due_at(row: Any) -> datetime | None:
    raw = row_value(row, 'traffic_reset_at')
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _next_traffic_reset_at(base: datetime | None = None) -> str:
    return ((base or datetime.now(timezone.utc)) + timedelta(days=30)).isoformat(timespec='seconds')


async def monthly_reset_status_text() -> str:
    return '🔄 Лимит трафика сбрасывается индивидуально раз в 30 дней после покупки или продления.'


def money(value: float | int) -> str:
    return f'{float(value):.2f}'


def human_timedelta(dt_value: str | None) -> str:
    if not dt_value:
        return '—'
    try:
        dt = datetime.fromisoformat(str(dt_value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if dt <= now:
            return 'истёк'
        delta = dt - now
        days = delta.days
        hours = delta.seconds // 3600
        if days <= 0:
            return f'{hours} ч.'
        return f'{days} д. {hours} ч.'
    except Exception:
        return '—'


def format_russian_dt(value: str | None) -> str:
    if not value:
        return '—'
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime('%d.%m.%Y %H:%M UTC')
    except Exception:
        return str(value)


def subscription_label(slot: int) -> str:
    if slot <= 0:
        return 'Ключ'
    return f'Ключ {slot}'


def subscription_display_name(sub: Any) -> str:
    name = str(row_value(sub, 'display_name') or '').strip()
    kind = str(row_value(sub, 'kind') or '').strip().lower()
    if kind == 'trial' and name.lower() in {'', 'trial', 'trial period', 'trial подписка', 'пробная'}:
        return 'Пробная'
    if name:
        return name
    slot = int(row_value(sub, 'slot', default=0) or 0)
    return subscription_label(slot)


def subscription_entry_title(sub: Any, index: int | None = None) -> str:
    slot = int(row_value(sub, 'slot', default=0) or 0)
    label = subscription_label(slot)
    kind = str(row_value(sub, 'kind') or '').strip().lower()
    display_name = str(row_value(sub, 'display_name') or '').strip()
    if not display_name:
        if kind == 'trial':
            display_name = 'Пробная'
        elif kind in {'balance_new', 'balance_renew', 'renew', 'payment'}:
            days = int(row_value(sub, 'days', default=0) or 0)
            display_name = f'{days} дней' if days > 0 else 'Подписка'
        elif kind == 'partner_grant':
            display_name = 'Партнёр'
        else:
            display_name = subscription_label(slot)
    title = f'{label} ({display_name})'
    return f'{index}. {title}' if index else title


def traffic_strategy_label(strategy: Any, traffic_limit_bytes: Any) -> str:
    strategy = str(strategy or '').upper()
    if strategy == 'NO_RESET' or (traffic_limit_bytes is not None and int(traffic_limit_bytes or 0) == 0):
        return 'никогда'
    if strategy == 'MONTH':
        return 'раз в месяц'
    if strategy == 'DAY':
        return 'раз в день'
    if strategy == 'WEEK':
        return 'раз в неделю'
    return '—'


def bytes_to_text(value: Any) -> str:
    try:
        n = int(value or 0)
    except Exception:
        n = 0
    if n <= 0:
        return '∞'
    gb = n / (1024 ** 3)
    if abs(gb - round(gb)) < 1e-9:
        return f'{int(round(gb))} ГБ'
    return f'{gb:.1f} ГБ'


def payment_status_text(status: str | None) -> str:
    raw = str(status or '').strip().lower()
    mapping = {
        'pending': '⏳ Ожидает оплаты',
        'waiting_for_capture': '⏳ Ожидает подтверждения',
        'succeeded': '✅ Оплачен',
        'canceled': '❌ Отменён',
        'cancelled': '❌ Отменён',
        'expired': '⌛ Истёк',
        'failed': '❌ Ошибка',
        'refunded': '↩️ Возврат',
        'authorized': '⏳ Авторизован',
        'refunded_partially': '↩️ Частичный возврат',
        'processing': '⏳ В обработке',
    }
    return mapping.get(raw, f'ℹ️ {raw or "unknown"}')


async def get_promo_definition(code: str) -> tuple[str, int, bool] | None:
    code = str(code or '').strip().upper()
    if not code:
        return None
    row = await get_promo_code_row(code)
    if row and int(row_value(row, 'is_active', default=0) or 0) == 1:
        promo_type = str(row_value(row, 'promo_type', default='discount') or 'discount').strip().lower()
        if promo_type != 'discount':
            return None
        single_use_raw = row_value(row, 'single_use', default=0)
        single_use = bool(int(single_use_raw) == 1 if single_use_raw is not None else False)
        return code, int(row_value(row, 'discount', default=0) or 0), single_use
    fallback = PROMO_CODES.get(code)
    if fallback:
        return code, int(fallback.get('discount', 0)), bool(fallback.get('single_use', False))
    return None


def promo_single_use_value(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    try:
        return int(value) == 1
    except Exception:
        text = str(value).strip().lower()
        if text in {'1', 'true', 'yes', 'да', 'одноразовый'}:
            return True
        if text in {'0', 'false', 'no', 'нет', 'многоразовый'}:
            return False
        return default


async def get_user_discount(user) -> tuple[str | None, int]:
    promo_code = str(row_value(user, 'promo_code') or '').strip().upper()
    promo_discount = int(row_value(user, 'promo_discount', default=0) or 0)
    if not promo_code or promo_discount <= 0:
        return None, 0
    promo = await get_promo_definition(promo_code)
    if not promo:
        return None, 0
    _, discount, _single_use = promo
    return promo_code, int(discount or promo_discount)


async def get_user_prices(user) -> tuple[dict[str, int], str | None, int]:
    promo_code, discount = await get_user_discount(user)
    prices = {code: int(data['amount']) for code, data in TARIFFS.items() if code != 'refill'}
    for code in list(prices):
        prices[code] = int(prices[code] * (100 - discount) / 100) if discount > 0 else prices[code]
    prices['refill'] = MOBILE_REFILL_PRICE
    return prices, promo_code, discount


def build_trial_promo_link(bot_username: str, code: str) -> str:
    clean_code = str(code or '').strip().upper()
    return f'https://t.me/{bot_username}?start=promo_{quote(clean_code)}'


async def activate_trial_promo_for_user(bot: Bot, tg_id: int, code: str) -> bool:
    promo_code = str(code or '').strip().upper()
    if not promo_code:
        return False

    row = await get_promo_code_row(promo_code)
    promo_type = str(row_value(row, 'promo_type', default='discount') or 'discount').strip().lower() if row else 'discount'
    if not row or int(row_value(row, 'is_active', default=0) or 0) != 1 or promo_type != 'trial':
        return False

    recipient = await get_promo_trial_recipient(promo_code, tg_id)
    if not recipient:
        await bot.send_message(
            tg_id,
            '❌ Этот пробный период доступен только из сообщения рассылки.',
            reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(tg_id)),
        )
        return True
    if str(row_value(recipient, 'activated_at') or '').strip():
        await bot.send_message(
            tg_id,
            'У вас уже активирован этот пробный период.',
            reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(tg_id)),
        )
        return True

    active_subs = _active_subscriptions(await get_user_subscriptions(tg_id))
    if any(str(row_value(sub, 'kind') or '').strip().lower() in PAID_SUBSCRIPTION_KINDS for sub in active_subs):
        await bot.send_message(
            tg_id,
            'Пробный период доступен только для пользователей без платной подписки.',
            reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(tg_id)),
        )
        return True
    if any(str(row_value(sub, 'kind') or '').strip().lower() == 'trial' for sub in active_subs):
        await bot.send_message(
            tg_id,
            'У вас уже есть активный пробный период.',
            reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(tg_id)),
        )
        return True

    trial_days = int(row_value(row, 'trial_days', default=TRIAL_DAYS) or TRIAL_DAYS)
    ok = await _create_internal_order_and_deliver(
        bot,
        tg_id,
        'promo_trial',
        0,
        trial_days,
        promo_code,
        subscription_name='Пробная',
    )
    if ok:
        await mark_trial_used(tg_id, utc_in_days(trial_days))
        await mark_promo_trial_recipient_activated(promo_code, tg_id)
        return True

    await bot.send_message(
        tg_id,
        '❌ Не удалось активировать пробный период.',
        reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(tg_id)),
    )
    return True


async def get_user_effective_subscription(user_tg_id: int):
    return await get_latest_active_subscription(user_tg_id)


def combined_internal_squads() -> list[str]:
    return [uuid for uuid in (str(settings.remnawave_squad_1_uuid or '').strip(), str(settings.remnawave_squad_2_uuid or '').strip()) if uuid]


def combined_key_username(tg_id: int, kind: str = 'sub', salt: str = '') -> str:
    import hashlib
    digest = hashlib.sha1(f'{tg_id}:{kind}:{salt}'.encode('utf-8')).hexdigest()[:6]
    username = f'tg{tg_id}_{digest}'
    return username[:35]


def subscription_limit_gb(sub: Any) -> int:
    return max(int(round(int(row_value(sub, 'traffic_limit_bytes', default=0) or 0) / (1024 ** 3))), 0)


def subscription_limit_bytes(sub: Any) -> int:
    return max(int(row_value(sub, 'traffic_limit_bytes', default=0) or 0), 0)


def subscription_button_label(sub: Any, index: int) -> str:
    kind = str(row_value(sub, 'kind') or '').strip().lower()
    display_name = str(row_value(sub, 'display_name') or '').strip()
    if kind == 'trial':
        return 'Пробный ключ'
    if display_name:
        return display_name
    return f'Ключ {index}'


def user_list_label(user: Any) -> str:
    tg_id = int(row_value(user, 'tg_id', default=0) or 0)
    username = str(row_value(user, 'username') or '').strip()
    first_name = str(row_value(user, 'first_name') or '').strip()
    parts = []
    if first_name:
        parts.append(first_name)
    if username:
        parts.append(f'@{username}')
    if not parts:
        parts.append(f'ID {tg_id}')
    else:
        parts.append(f'ID {tg_id}')
    return ' · '.join(parts)[:40]



async def _build_happ_redirect_link(subscription_url: str | None) -> str | None:
    url = str(subscription_url or '').strip()
    if not url:
        return None
    if url in HAPP_CRYPTO_CACHE:
        return HAPP_CRYPTO_CACHE[url]

    if url.startswith(HAPP_REDIRECT_BASE_URL):
        HAPP_CRYPTO_CACHE[url] = url
        return url

    if url.startswith('happ://crypt5/'):
        key = url.removeprefix('happ://crypt5/').strip()
        if key:
            redirect = f'{HAPP_REDIRECT_BASE_URL}?k={quote(key)}'
            HAPP_CRYPTO_CACHE[url] = redirect
            return redirect
        return None

    if not url.startswith(('http://', 'https://')):
        return None

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(HAPP_CRYPTO_API_URL, json={'url': url})
        response.raise_for_status()
        encrypted = ''
        try:
            data = response.json()
            if isinstance(data, str):
                encrypted = data
            elif isinstance(data, dict):
                for key in ('url', 'result', 'response', 'data', 'link', 'encrypted', 'encryptedUrl'):
                    value = data.get(key)
                    if isinstance(value, str) and value.strip():
                        encrypted = value.strip()
                        break
                if not encrypted and len(data) == 1:
                    value = next(iter(data.values()))
                    if isinstance(value, str):
                        encrypted = value.strip()
        except Exception:
            encrypted = response.text.strip()
        encrypted = encrypted.strip().strip('"').strip("'")
        if encrypted.startswith(HAPP_REDIRECT_BASE_URL):
            redirect = encrypted
        else:
            if encrypted.startswith('happ://crypt5/'):
                encrypted = encrypted.removeprefix('happ://crypt5/').strip()
            redirect = f'{HAPP_REDIRECT_BASE_URL}?k={quote(encrypted)}' if encrypted else None
        if redirect:
            HAPP_CRYPTO_CACHE[url] = redirect
            return redirect
    except Exception as exc:
        logger.warning('Failed to build Happ redirect link for %s: %s', url, exc)
    return None


def _build_happ_routing_profile() -> dict[str, Any]:
    return {
        'Name': 'NoirLatch RU',
        'GlobalProxy': True,
        'RouteOrder': 'block-proxy-direct',
        'RemoteDNSType': 'DoH',
        'RemoteDNSDomain': 'https://cloudflare-dns.com/dns-query',
        'RemoteDNSIP': '1.1.1.1',
        'DomesticDNSType': 'DoH',
        'DomesticDNSDomain': 'https://dns.google/dns-query',
        'DomesticDNSIP': '8.8.8.8',
        'Geoipurl': 'https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat',
        'Geositeurl': 'https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat',
        'LastUpdated': '',
        'DnsHosts': {
            'cloudflare-dns.com': '1.1.1.1',
            'dns.google': '8.8.8.8',
        },
        'DirectSites': ['geosite:ru', 'geoip:ru'],
        'DirectIp': [
            'geoip:ru',
            '10.0.0.0/8',
            '172.16.0.0/12',
            '192.168.0.0/16',
            '169.254.0.0/16',
            '224.0.0.0/4',
            '255.255.255.255',
        ],
        'ProxySites': [],
        'ProxyIp': [],
        'BlockSites': [],
        'BlockIp': [],
        'DomainStrategy': 'IPIfNonMatch',
        'FakeDNS': False,
        'UseChunkFiles': True,
    }


async def _build_happ_routing_link() -> str | None:
    try:
        payload = json.dumps(_build_happ_routing_profile(), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        encoded = base64.b64encode(payload).decode('ascii')
        return f'happ://routing/onadd/{encoded}'
    except Exception as exc:
        logger.warning('Failed to build Happ routing link: %s', exc)
        return None


def onboarding_text() -> str:
    return (
        '👋 Добро пожаловать в NoirLatch\n\n'
        '🔐 Надёжный и приватный доступ\n'
        '🛡 Максимальная анонимность и безопасность\n'
        '✨ Полная конфиденциальность без лишних данных\n'
        '💰 Вы можете не только пользоваться конфигуратором, но и зарабатывать вместе с сервисом.\n'
        '🎁 В боте проходят розыгрыши и промо-акции.\n\n'
        'Нажмите кнопку ниже, чтобы открыть меню.'
    )


def main_menu_text() -> str:
    return '🏠 Главное меню NoirLatch 😎\n\nВыберите нужный раздел ниже.'


def privacy_text() -> str:
    return '<b>ПОЛИТИКА КОНФИДЕНЦИАЛЬНОСТИ</b>\nсервиса NoirLatch (@noirlatch_bot)\n\n<b>Дата вступления в силу:</b> 01 мая 2026 года\n\n<b>1. Общие положения</b>\nМы уважаем вашу конфиденциальность и собираем только те данные, которые необходимы для предоставления Услуг.\n\n<b>2. Какие данные мы собираем</b>\n• Telegram ID, username, first_name\n• Данные об оплатах (через ЮKassa)\n• Информация о ваших подписках и использовании трафика\n• Реферальные данные (кто кого пригласил)\n\n<b>3. Цели обработки данных</b>\n• Предоставление и поддержка Услуг\n• Обработка платежей\n• Ведение реферальной и партнёрской программы\n• Улучшение работы бота\n• Выполнение требований законодательства РФ\n\n<b>4. Передача данных</b>\nМы не передаём ваши персональные данные третьим лицам, за исключением: платёжной системы ЮKassa (только данные, необходимые для платежа).\n\n<b>5. Хранение данных</b>\nВсе данные хранятся на защищённых серверах в течение срока, необходимого для оказания Услуг.\n\n<b>6. Ваши права</b>\nВы можете в любое время обратиться в поддержку бота с запросом на удаление ваших данных или получение информации о том, какие данные о вас хранятся.\n\n<b>7. Изменения Политики</b>\nМы можем обновлять Политику. Новая версия вступает в силу с момента публикации в разделе «📚 Документация» бота.\n\nИспользуя бот, вы соглашаетесь с настоящей Политикой конфиденциальности.'


def rules_text() -> str:
    return '<b>ПРАВИЛА ИСПОЛЬЗОВАНИЯ СЕРВИСА NOIRLATCH</b>\n\n<b>1. Общие положения</b>\nНастоящие Правила являются неотъемлемой частью публичной оферты и регулируют порядок использования Услуг.\n\n<b>2. Требования к Заказчику</b>\n• Заказчик обязан быть старше 18 лет.\n• Запрещается передавать свои учётные данные и ссылки-подписки третьим лицам.\n• Запрещается использовать Услуги для осуществления противоправной деятельности.\n\n<b>3. Лимиты трафика и подписки</b>\n• Подписки с припиской <b>«mobile»</b> имеют лимит трафика <b>50 ГБ</b> на весь период действия подписки.\n• При исчерпании лимита трафика доступ к Услугам автоматически приостанавливается.\n• <b>Продлить дни подписки</b> и <b>докупить дополнительный трафик</b> можно в любое время в разделе <b>«💳 Тарифы»</b> бота по кнопкам <b>«Продлить подписку»</b> и <b>«Докупить трафик»</b>.\n\n<b>4. Запрещённые действия</b>\n• Попытки обойти технические ограничения сервиса.\n• Распространение вредоносного ПО.\n• Любые действия, нарушающие законодательство РФ.\n\n<b>5. Поддержка</b>\nВсе вопросы решаются через кнопку <b>«🆘 Поддержка»</b> в главном меню бота.\n\nНарушение Правил может привести к блокировке аккаунта без возврата денежных средств.'


def offer_text() -> str:
    return '<b>ПУБЛИЧНАЯ ОФЕРТА</b>\nна заключение договора возмездного оказания услуг\nпо предоставлению доступа к информационно-телекоммуникационной сети\n\nг. Москва, Российская Федерация\nДата размещения: 01 мая 2026 года\n\n<b>1. Общие положения</b>\n1.1. Настоящий документ является публичной офертой Индивидуального предпринимателя (далее — Исполнитель) и содержит все существенные условия договора возмездного оказания услуг (далее — Договор).\n1.2. Акцептом оферты признаётся совершение Заказчиком любого из следующих действий: нажатие кнопки <b>«✅ Подтвердить»</b> в боте @noirlatch_bot, оплата тарифа или использование пробного периода.\n1.3. С момента акцепта оферты между Исполнителем и Заказчиком возникает Договор на условиях, изложенных в настоящей оферте.\n\n<b>2. Предмет Договора</b>\n2.1. Исполнитель обязуется оказать Заказчику услуги по предоставлению доступа к информационно-телекоммуникационной сети через выделенные серверы (далее — Услуги).\n2.2. Услуги оказываются в виде платных подписок (тарифных планов) различной продолжительности, а также возможности пополнения объёма трафика.\n2.3. Доступ предоставляется путём выдачи уникальной ссылки-подписки (subscription URL).\n\n<b>3. Порядок оказания услуг</b>\n3.1. Заказчик выбирает тариф в боте и производит оплату через платёжную систему ЮKassa.\n3.2. После успешной оплаты Исполнитель в течение 5 минут выдаёт Заказчику ссылку-подписку.\n3.3. Пробный период (3 дня) предоставляется один раз бесплатно при первом обращении.\n3.4. Срок действия подписки и объём доступного трафика указываются в выбранном тарифном плане.\n\n<b>4. Права и обязанности сторон</b>\n4.1. Заказчик вправе: пользоваться Услугами в пределах оплаченного тарифа; обращаться в поддержку бота по вопросам работы сервиса.\n4.2. Исполнитель вправе: приостанавливать доступ при превышении лимита трафика или нарушении Правил; изменять тарифы, предварительно уведомив пользователей через бота.\n\n<b>5. Стоимость и порядок оплаты</b>\n5.1. Стоимость Услуг указана в боте в разделе <b>«💳 Тарифы»</b>.\n5.2. Оплата производится в рублях РФ через ЮKassa.\n5.3. Денежные средства возврату не подлежат, кроме случаев, прямо предусмотренных законодательством РФ.\n\n<b>6. Ответственность сторон</b>\n6.1. Исполнитель не несёт ответственности за качество работы сети Интернет у Заказчика, а также за перерывы в предоставлении Услуг, вызванные действиями третьих лиц или обстоятельствами непреодолимой силы.\n6.2. Заказчик несёт полную ответственность за соблюдение законодательства РФ при использовании Услуг.\n\n<b>7. Заключительные положения</b>\n7.1. Настоящая оферта может быть изменена Исполнителем в любое время. Новая редакция вступает в силу с момента её публикации в боте.\n7.2. Все споры решаются путём переговоров, а при недостижении согласия — в суде по месту регистрации Исполнителя.\n7.3. Реквизиты Исполнителя доступны по запросу в поддержке бота.\n\nАкцептуя настоящую оферту, Заказчик подтверждает, что ознакомлен и согласен со всеми её условиями.'


def format_subscriptions_message(subs: list[dict], order) -> str:
    kind = str(row_value(order, 'kind', default='payment') or 'payment').strip().lower()
    title_map = {
        'trial': '✅ Пробная подписка активирована',
        'balance_new': '✅ Подписка активирована',
        'balance_renew': '✅ Подписка продлена',
        'renew': '✅ Подписка продлена',
        'refill': '✅ Докупка трафика оформлена',
        'admin_test': '🧪 Тестовая оплата выполнена',
        'partner_grant': '🏅 Партнёрская подписка активирована',
        'topup': '✅ Баланс оплаты пополнен',
        'admin_manual': '✅ Ключ создан администратором',
    }
    lines: list[str] = [title_map.get(kind, '✅ Оплата прошла успешно')]
    lines.append('')

    if kind == 'topup':
        lines.append(f'Сумма: {row_value(order, "amount")} ₽')
        return '\n'.join(lines).strip()

    if kind == 'trial':
        lines.append(f'Срок пробного периода: {row_value(order, "days")} дней')
    else:
        lines.append(f'Срок: {row_value(order, "days")} дней')
        amount_value = int(row_value(order, 'amount', default=0) or 0)
        if amount_value > 0:
            lines.append(f'Сумма: {amount_value} ₽')

    lines.append('')
    lines.append('ВАЖНО:')
    lines.append('')
    lines.append('• Ключ рассчитан на 2 девайса')
    lines.append('• Трафик распространяется только на серверы с припиской Mobile')
    lines.append('• Используйте Mobile только если серверы с припиской Wi-Fi не работают')
    lines.append('• Перед использованием прочитайте инструкцию')
    lines.append('')
    lines.append('Ваш ключ:')
    if subs:
        for idx, sub in enumerate(subs, start=1):
            lines.append(f'{idx}. {subscription_entry_title(sub)}')
            lines.append(f'   Название: {subscription_display_name(sub)}')
            lines.append(f'   Трафик: {_subscription_usage_text(sub)}')
            url = str(row_value(sub, "subscription_url") or '').strip()
            if url:
                lines.append(f'   URL: {url}')
            if idx != len(subs):
                lines.append('')
    else:
        lines.append('   Ключ будет отправлен отдельно после завершения обработки.')

    return '\n'.join(lines).strip()

def _usage_bytes_text(value: Any) -> str:

    try:
        n = int(value or 0)
    except Exception:
        n = 0
    if n <= 0:
        return '0'
    return bytes_to_text(n)


def _subscription_usage_text(sub: dict[str, Any]) -> str:
    used = int(row_value(sub, 'traffic_used_bytes', default=0) or 0)
    limit = subscription_limit_bytes(sub)
    if limit <= 0:
        return f'Mobile: {_usage_bytes_text(used)} / ∞'
    return f'Mobile: {_usage_bytes_text(used)} / {bytes_to_text(limit)}'


def _valid_happ_link(url: Any) -> str | None:
    value = str(url or '').strip()
    if value.startswith(('https://', 'http://', 'happ://', 'tg://')):
        return value
    return None


def _happ_redirect_url_from_link(link: str | None) -> str | None:
    value = str(link or '').strip()
    if not value:
        return None
    if value.startswith(HAPP_REDIRECT_BASE_URL):
        return value
    prefix = 'happ://crypt5/'
    if value.startswith(prefix):
        key = value[len(prefix):].strip()
        return f'{HAPP_REDIRECT_BASE_URL}?k={quote(key)}' if key else None
    if value.startswith(('https://', 'http://', 'tg://')):
        return None
    return f'{HAPP_REDIRECT_BASE_URL}?k={quote(value)}'




async def _register_start_user(bot: Bot, user_id: int, username: str | None, first_name: str | None, referrer_id: int | None) -> None:
    try:
        await upsert_user(user_id, username, first_name, referrer_id)
    except Exception as exc:
        logger.exception('Failed to register start user %s: %s', user_id, exc)


def subscription_card(sub: Any, index: int | None = None) -> str:
    display = subscription_entry_title(sub, index)
    header = display if index else subscription_entry_title(sub)
    return (
        f'{header}\n'
        f'Название: {subscription_display_name(sub)}\n'
        f'Лимит Mobile: {bytes_to_text(row_value(sub, "traffic_limit_bytes"))}\n'
        f'{_subscription_usage_text(sub)}\n'
        f'Сброс: {traffic_strategy_label(row_value(sub, "traffic_limit_strategy"), row_value(sub, "traffic_limit_bytes"))}\n'
        f'Действует до: {format_russian_dt(row_value(sub, "expire_at"))}\n'
        f'Осталось: {human_timedelta(row_value(sub, "expire_at"))}\n'
        f'URL: {row_value(sub, "subscription_url")}'
    )


def profile_subscription_lines(subs: list[dict]) -> list[str]:
    lines: list[str] = []
    for idx, sub in enumerate(subs, start=1):
        lines.extend([
            f'{idx}. {subscription_entry_title(sub)}',
            f'   Тег: {row_value(sub, "username") or "—"}',
            f'   Название: {subscription_display_name(sub)}',
            f'   Осталось: {human_timedelta(row_value(sub, "expire_at"))}',
            f'   Трафик: {_usage_bytes_text(row_value(sub, "traffic_used_bytes", default=0))} / {bytes_to_text(subscription_limit_bytes(sub))}',
        ])
        if idx != len(subs):
            lines.append('')
    return lines


def _active_subscriptions(subs: list[dict]) -> list[dict]:
    result = []
    for sub in subs:
        try:
            exp = row_value(sub, 'expire_at')
            if not exp:
                continue
            dt = datetime.fromisoformat(str(exp))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt > datetime.now(timezone.utc):
                result.append(sub)
        except Exception:
            result.append(sub)
    return result


def _refill_candidates(subs: list[dict]) -> list[dict]:
    candidates = []
    for sub in subs:
        kind = str(row_value(sub, 'kind') or '').strip().lower()
        if kind == 'trial':
            continue
        candidates.append(sub)
    return candidates


def _extend_candidates(subs: list[dict]) -> list[dict]:
    return [sub for sub in _active_subscriptions(subs) if str(row_value(sub, 'kind') or '').strip().lower() != 'trial']


def _extend_target_keyboard(options: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=f'extend:target:{slot}')] for slot, label in options]
    rows.append([InlineKeyboardButton(text='❌ Отмена', callback_data='extend:cancel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _extend_days_keyboard(slot: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f'+{days} дней', callback_data=f'extend:days:{slot}:{days}')] for days in EXTEND_DAY_OPTIONS]
    rows.append([InlineKeyboardButton(text='❌ Отмена', callback_data='extend:cancel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _extend_confirm_keyboard(slot: int, days: int, amount: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Подтвердить', callback_data=f'extend:confirm:{slot}:{days}:{amount}')],
        [InlineKeyboardButton(text='❌ Отмена', callback_data='extend:cancel')],
    ])


async def _is_admin_user(tg_id: int) -> bool:
    if tg_id == settings.admin_id:
        return True
    user = await get_user(tg_id)
    return bool(user and int(row_value(user, 'is_admin', default=0) or 0) == 1)


async def _send_admin_traceback(bot: Bot, title: str, exc: Exception, *, context: str = '') -> None:
    admin_id = int(getattr(settings, 'admin_id', 0) or 0)
    logger.exception('%s | %s', title, context)
    if not admin_id:
        return
    import traceback
    payload = f'❌ {title}\n'
    if context:
        payload += f'{context}\n'
    payload += f"{type(exc).__name__}: {exc}\n\n{''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}"
    for i in range(0, len(payload), 3500):
        try:
            await bot.send_message(admin_id, payload[i:i + 3500])
        except Exception:
            logger.exception('Failed to notify admin about %s', title)
            return


async def _safe_send_user_message(bot: Bot, tg_id: int, text: str, reply_markup=None) -> bool:
    try:
        await bot.send_message(tg_id, text, reply_markup=reply_markup)
        return True
    except TelegramBadRequest as exc:
        message = str(exc).lower()
        if 'chat not found' in message or 'bot was blocked by the user' in message or 'forbidden' in message:
            logger.warning('Could not deliver message to tg_id=%s: %s', tg_id, exc)
            return False
        raise


async def _notify_role_change(bot: Bot, tg_id: int, *, is_admin: bool, is_partner: bool | None = None) -> None:
    pieces = ['Ваши права в боте обновлены.']
    if is_admin:
        pieces.append('Теперь вам доступна админка.')
    elif is_partner is False:
        pieces.append('Статус партнёра снят.')
    elif is_partner is True:
        pieces.append('Статус партнёра выдан.')
    text = '\n'.join(pieces) + '\n\nГлавное меню NoirLatch 👇'
    await _safe_send_user_message(bot, tg_id, text, reply_markup=main_menu_keyboard(is_admin=is_admin))


async def _update_access_expiration(user_tg_id: int, days: int) -> None:
    user = await get_user(user_tg_id)
    base = datetime.now(timezone.utc)
    if user and row_value(user, 'access_until'):
        try:
            current_until = datetime.fromisoformat(str(row_value(user, 'access_until')))
            if current_until.tzinfo is None:
                current_until = current_until.replace(tzinfo=timezone.utc)
            if current_until > base:
                base = current_until
        except Exception:
            pass
    await set_user_access(user_tg_id, (base + timedelta(days=days)).isoformat(timespec='seconds'))


async def _ensure_partner_subscription(bot: Bot, tg_id: int) -> None:
    partner = await get_user(tg_id)
    if not partner:
        return
    existing = _active_subscriptions(await get_user_subscriptions_by_kind(tg_id, 'partner_grant'))
    if existing:
        first = existing[0]
        limit_ok = int(row_value(first, 'traffic_limit_bytes', default=0) or 0) == PARTNER_ACCESS_TRAFFIC_GB * 1024 * 1024 * 1024
        strategy_ok = str(row_value(first, 'traffic_limit_strategy') or '').upper() == 'MONTH'
        if limit_ok and strategy_ok:
            return
    await _create_internal_order_and_deliver(bot, tg_id, 'partner_grant', 0, PARTNER_GRANT_DAYS, 'partner_grant')


async def _reward_partner_for_new_referral(bot: Bot, partner_id: int) -> None:
    partner = await get_user(partner_id)
    if not partner or int(row_value(partner, 'is_partner', default=0) or 0) != 1:
        return
    month = current_month_key()
    count = await get_month_referral_count(partner_id, month)
    await set_partner_month_state(partner_id, month, count)
    bonus_month = row_value(partner, 'last_ref_bonus_date') or row_value(partner, 'partner_bonus_month')
    if count >= PARTNER_BONUS_MIN_REFERRALS and bonus_month != month:
        await adjust_user_balance(partner_id, 'referral_balance', PARTNER_BONUS_AMOUNT)
        await set_partner_bonus_month(partner_id, month)
        await set_last_ref_bonus_date(partner_id, month)
        try:
            await bot.send_message(partner_id, f'🏅 Партнёрский бонус: +{PARTNER_BONUS_AMOUNT} ₽ за {PARTNER_BONUS_MIN_REFERRALS}+ новых пользователей в месяц.')
        except Exception:
            logger.exception('Failed to notify partner about monthly bonus | partner_id=%s', partner_id)


async def _sync_user_access_from_subscriptions(tg_id: int) -> None:
    subscriptions = _active_subscriptions(await get_user_subscriptions(tg_id))
    if not subscriptions:
        await update_user_fields(tg_id, access_active=0, access_until=None, access_key=None)
        return

    def _parse_dt(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    expires = [_parse_dt(row_value(sub, 'expire_at')) for sub in subscriptions]
    expires = [dt for dt in expires if dt is not None]
    if not expires:
        await update_user_fields(tg_id, access_active=1, access_until=None, access_key=None)
        return
    await update_user_fields(tg_id, access_active=1, access_until=max(expires).isoformat(timespec='seconds'))


async def _delete_user_subscription_in_remnawave(bot: Bot, subs: list[dict[str, Any]]) -> None:
    uuids = [str(row_value(sub, 'user_uuid') or '').strip() for sub in subs if str(row_value(sub, 'user_uuid') or '').strip()]
    if not uuids:
        return
    try:
        await remnawave.bulk_delete_users(uuids)
    except Exception as exc:
        await _send_admin_traceback(bot, 'Не удалось удалить подписку в Remnawave', exc, context='\n'.join(uuids))


def _extract_mobile_usage_bytes(payload: Any, mobile_uuid: str | None = None) -> int:
    mobile_uuid = str(mobile_uuid or '').strip().lower()
    matched_names = {'mobile', 'mobile squad', 'мобильный', 'мобайл'}
    positive_key_parts = {'used', 'traffic', 'consum', 'download', 'upload', 'bytes'}
    blocked_key_parts = {'limit', 'quota', 'cap', 'allowance'}

    def parse_int(value: Any) -> int:
        try:
            if isinstance(value, bool):
                return 0
            if value is None:
                return 0
            return max(int(float(value)), 0)
        except Exception:
            return 0

    def key_matches(key: str) -> bool:
        k = key.strip().lower()
        if not k:
            return False
        if any(part in k for part in blocked_key_parts):
            return False
        return any(part in k for part in positive_key_parts)

    def node_matches_mobile(node: dict[str, Any]) -> bool:
        candidates = [
            node.get('squadUuid'),
            node.get('internalSquadUuid'),
            node.get('squad_uuid'),
            node.get('uuid'),
            node.get('id'),
            node.get('name'),
            node.get('title'),
            node.get('tag'),
            node.get('label'),
            node.get('description'),
        ]
        for value in candidates:
            if value is None:
                continue
            text = str(value).strip().lower()
            if not text:
                continue
            if mobile_uuid and (text == mobile_uuid or mobile_uuid in text):
                return True
            if any(name in text for name in matched_names):
                return True
        return False

    best_fallback = 0

    def extract_direct(node: dict[str, Any]) -> int:
        direct_values: list[int] = []
        for key, value in node.items():
            if key_matches(str(key)):
                direct_values.append(parse_int(value))
        if direct_values:
            direct_values = [value for value in direct_values if value > 0]
        if len(direct_values) >= 2 and any(k in node for k in ('downloadBytes', 'uploadBytes', 'downloadTrafficBytes', 'uploadTrafficBytes')):
            return sum(direct_values)
        return max(direct_values, default=0)

    def walk(node: Any) -> int:
        nonlocal best_fallback
        if isinstance(node, dict):
            used = extract_direct(node)
            if used > 0:
                if node_matches_mobile(node):
                    return used
                best_fallback = max(best_fallback, used)
            for key in ('squads', 'squadTraffic', 'trafficBySquad', 'internalSquads', 'userTraffic', 'response', 'data', 'items', 'rows', 'statistics', 'stats', 'result'):
                value = node.get(key)
                if value is None:
                    continue
                result = walk(value)
                if result > 0:
                    return result
            for value in node.values():
                result = walk(value)
                if result > 0:
                    return result
        elif isinstance(node, list):
            for item in node:
                result = walk(item)
                if result > 0:
                    return result
        return 0

    result = walk(payload)
    return result or best_fallback

def _extract_user_usage_bytes(user: Any) -> int:
    if not isinstance(user, dict):
        return 0
    candidates: list[int] = []
    for key in ('usedTrafficBytes', 'lifetimeUsedTrafficBytes', 'usedBytes', 'lifetimeUsedBytes', 'trafficUsedBytes', 'trafficUsedBytesTotal', 'downloadTrafficBytes', 'uploadTrafficBytes', 'downloadBytes', 'uploadBytes', 'totalBytes', 'consumedBytes', 'consumptionBytes'):
        value = user.get(key)
        try:
            n = int(float(value or 0))
        except Exception:
            n = 0
        if n > 0:
            candidates.append(n)
    traffic = user.get('userTraffic')
    if isinstance(traffic, dict):
        candidates.append(_extract_mobile_usage_bytes(traffic, mobile_uuid=str(user.get('tag') or user.get('username') or user.get('uuid') or '')))
        candidates.append(_extract_mobile_usage_bytes(traffic))
    return max(candidates, default=0)


async def _resolve_subscription_user_uuid(sub: dict[str, Any]) -> str:
    user_uuid = str(row_value(sub, 'user_uuid') or '').strip()
    tg_id = int(row_value(sub, 'user_tg_id', default=0) or 0)
    slot = int(row_value(sub, 'slot', default=0) or 0)
    username = str(row_value(sub, 'username') or '').strip()

    if user_uuid:
        try:
            user = await remnawave.get_user_by_uuid(user_uuid)
            if isinstance(user, dict) and str(user.get('uuid') or '').strip():
                return user_uuid
        except Exception:
            pass

    candidates: list[dict[str, Any]] = []
    if username:
        try:
            user = await remnawave.get_user_by_username(username)
            if isinstance(user, dict):
                candidates.append(user)
        except Exception:
            pass

    if candidates:
        candidate = candidates[0]
        resolved_uuid = str(candidate.get('uuid') or '').strip()
        resolved_username = str(candidate.get('username') or username or '').strip() or None
        if resolved_uuid:
            try:
                await update_remnawave_subscription_identity(tg_id, slot, user_uuid=resolved_uuid, username=resolved_username)
            except Exception:
                pass
            return resolved_uuid

    return user_uuid


async def _subscription_usage_bytes(sub: dict[str, Any]) -> tuple[int, int]:
    used = max(int(row_value(sub, 'traffic_used_bytes', default=0) or 0), 0)
    limit = subscription_limit_bytes(sub)
    mobile_uuid = str(row_value(sub, 'squad_uuid') or settings.remnawave_squad_2_uuid or '').strip()
    try:
        user_uuid = await _resolve_subscription_user_uuid(sub)
        if user_uuid:
            user = await remnawave.get_user_by_uuid(user_uuid)
            if isinstance(user, dict):
                used = max(used, _extract_user_usage_bytes(user))
                traffic = user.get('userTraffic') or {}
                used = max(used, _extract_mobile_usage_bytes(traffic, mobile_uuid=mobile_uuid))
        if used <= 0 and user_uuid:
            try:
                traffic = await remnawave.get_user_traffic(user_uuid, start='1970-01-01', end=date.today().isoformat())
            except Exception:
                traffic = None
            if traffic is not None:
                used = max(used, _extract_mobile_usage_bytes(traffic, mobile_uuid=mobile_uuid))
    except Exception:
        pass
    return used, limit


async def _sync_single_subscription_usage_once(bot: Bot, sub: Any, wifi_uuid: str, mobile_uuid: str, range_start: str, range_end: str, forced_used_bytes: int | None = None) -> dict[str, Any]:
    user_uuid = await _resolve_subscription_user_uuid(sub)
    tg_id = int(row_value(sub, 'user_tg_id', default=0) or 0)
    slot = int(row_value(sub, 'slot', default=0) or 0)
    if not user_uuid or tg_id <= 0:
        return {'status': 'skip'}

    limit = subscription_limit_bytes(sub)
    used = int(row_value(sub, 'traffic_used_bytes', default=0) or 0)
    if limit <= 0:
        await update_remnawave_subscription_usage(tg_id, slot, 0)
        return {'status': 'no_limit', 'used': 0, 'limit': 0, 'slot': slot, 'tg_id': tg_id}

    if forced_used_bytes is None:
        fetched_used, fetched_limit = await _subscription_usage_bytes(sub)
        used = max(used, fetched_used)
        if fetched_limit > 0:
            limit = fetched_limit
    else:
        used = max(int(forced_used_bytes), 0)
    await update_remnawave_subscription_usage(tg_id, slot, used)

    disabled = int(row_value(sub, 'mobile_disabled', default=0) or 0) == 1
    remote_needs_disable = False
    if disabled and mobile_uuid:
        with contextlib.suppress(Exception):
            remote = await remnawave.get_user_by_uuid(user_uuid)
            remote_needs_disable = mobile_uuid in _remnawave_active_squads(remote)

    if used >= limit and (not disabled or remote_needs_disable):
        confirmed = await _force_disable_mobile_squad(bot, sub, wifi_uuid, mobile_uuid, used, limit)
        if confirmed:
            await set_remnawave_subscription_mobile_disabled(tg_id, slot, 1)
            try:
                await bot.send_message(tg_id, f'⚠️ Для {subscription_display_name(sub)} достигнут лимит мобильного трафика. Mobile отключён.')
            except Exception:
                pass
        else:
            # Keep the flag clear so the next monitor tick retries the removal instead of assuming success.
            await set_remnawave_subscription_mobile_disabled(tg_id, slot, 0)
        return {'status': 'disabled', 'used': used, 'limit': limit, 'slot': slot, 'tg_id': tg_id}

    if used < limit and disabled:
        if remote_needs_disable:
            confirmed = await _force_disable_mobile_squad(bot, sub, wifi_uuid, mobile_uuid, used, limit)
            if confirmed:
                await set_remnawave_subscription_mobile_disabled(tg_id, slot, 1)
        return {'status': 'disabled', 'used': used, 'limit': limit, 'slot': slot, 'tg_id': tg_id}

    return {'status': 'ok', 'used': used, 'limit': limit, 'slot': slot, 'tg_id': tg_id}


async def _sync_mobile_usage_once(bot: Bot) -> dict[str, int]:
    subs = _active_subscriptions(await get_all_remnawave_subscriptions())
    wifi_uuid = str(settings.remnawave_squad_1_uuid or '').strip()
    mobile_uuid = str(settings.remnawave_squad_2_uuid or '').strip()
    range_start = '1970-01-01'
    range_end = date.today().isoformat()

    stats = {'checked': 0, 'disabled': 0, 'enabled': 0, 'skipped': 0, 'errors': 0}
    for sub in subs:
        try:
            await _sync_subscription_expire_from_remnawave(sub)
            result = await _sync_single_subscription_usage_once(bot, sub, wifi_uuid, mobile_uuid, range_start, range_end)
            stats['checked'] += 1
            status = str(result.get('status') or '')
            if status == 'disabled':
                stats['disabled'] += 1
            elif status == 'enabled':
                stats['enabled'] += 1
            elif status == 'skip':
                stats['skipped'] += 1
        except Exception as exc:
            stats['errors'] += 1
            logger.warning('Usage sync failed for tg_id=%s slot=%s: %s', row_value(sub, 'user_tg_id', default=0), row_value(sub, 'slot', default=0), exc)
    return stats


async def _subscription_snapshot_is_current(sub: Any) -> bool:
    tg_id = int(row_value(sub, 'user_tg_id', default=0) or 0)
    slot = int(row_value(sub, 'slot', default=0) or 0)
    if tg_id <= 0 or slot <= 0:
        return False
    current = await get_remnawave_subscription_by_user_slot(tg_id, slot)
    if not current:
        return False
    current_payment_id = str(row_value(current, 'payment_id') or '').strip()
    current_expire_at = str(row_value(current, 'expire_at') or '').strip()
    current_kind = str(row_value(current, 'kind') or '').strip().lower()
    snapshot_payment_id = str(row_value(sub, 'payment_id') or '').strip()
    snapshot_expire_at = str(row_value(sub, 'expire_at') or '').strip()
    snapshot_kind = str(row_value(sub, 'kind') or '').strip().lower()
    return (
        current_payment_id == snapshot_payment_id
        and current_expire_at == snapshot_expire_at
        and current_kind == snapshot_kind
    )


async def _force_disable_mobile_squad(bot: Bot, sub: Any, wifi_uuid: str, mobile_uuid: str, used: int, limit: int) -> bool:
    tg_id = int(row_value(sub, 'user_tg_id', default=0) or 0)
    slot = int(row_value(sub, 'slot', default=0) or 0)
    user_uuid = str(row_value(sub, 'user_uuid') or '').strip()
    if tg_id <= 0 or slot <= 0 or not user_uuid:
        return False

    desired_squads = [uuid for uuid in (wifi_uuid,) if uuid]
    expire_at = str(row_value(sub, 'expire_at') or utc_now())
    username = str(row_value(sub, 'username') or combined_key_username(tg_id, kind='mobile_off', salt=str(slot)))
    description = f'TG {tg_id} / mobile disabled / {subscription_display_name(sub)}'
    payload = {
        'uuid': user_uuid,
        'username': username,
        'telegramId': tg_id,
        'expireAt': expire_at,
        'status': 'ACTIVE',
        'trafficLimitStrategy': 'NO_RESET',
        'trafficLimitBytes': 0,
        'description': description,
        'activeInternalSquads': desired_squads,
        'tag': f'TG{tg_id % 100000000:08d}_{slot}'[:15],
    }

    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            await remnawave.update_user(payload)
        except Exception as exc:
            last_exc = exc
            logger.warning('Failed to disable mobile squad in Remnawave for tg_id=%s slot=%s attempt=%s: %s', tg_id, slot, attempt + 1, exc)
            continue

        with contextlib.suppress(Exception):
            remote = await remnawave.get_user_by_uuid(user_uuid)
            active_squads = _remnawave_active_squads(remote)
            if not mobile_uuid or mobile_uuid not in active_squads:
                return True

        # Retry with a minimal payload when the API keeps the old squad list.
        payload = {
            'uuid': user_uuid,
            'telegramId': tg_id,
            'status': 'ACTIVE',
            'activeInternalSquads': desired_squads,
            'expireAt': expire_at,
            'trafficLimitBytes': 0,
            'trafficLimitStrategy': 'NO_RESET',
        }

    if last_exc:
        logger.warning('Mobile squad removal did not fully confirm for tg_id=%s slot=%s: %s', tg_id, slot, last_exc)
    return False


async def _notify_subscription_expiry_once(bot: Bot) -> dict[str, int]:
    subs = _active_subscriptions(await get_all_remnawave_subscriptions())
    now = datetime.now(timezone.utc)
    stats = {'day': 0, 'two_hours': 0, 'ended': 0, 'errors': 0}
    for sub in subs:
        tg_id = int(row_value(sub, 'user_tg_id', default=0) or 0)
        slot = int(row_value(sub, 'slot', default=0) or 0)
        if tg_id <= 0 or slot <= 0:
            continue
        with contextlib.suppress(Exception):
            await _sync_subscription_expire_from_remnawave(sub)
        exp = _subscription_dt(row_value(sub, 'expire_at'))
        if not exp:
            continue
        try:
            sub_kind = str(row_value(sub, 'kind') or '').strip().lower()
            is_trial = sub_kind == 'trial'
            label = 'Пробная подписка' if is_trial else f'Подписка «{subscription_display_name(sub)}»'
            if exp <= now:
                if str(row_value(sub, 'expire_notified_end_at') or '').strip():
                    continue
                end_text = (
                    f'⚠️ {label} закончилась.\n\n'
                    f'Чтобы восстановить доступ, выберите подходящий тариф.'
                )
                await bot.send_message(
                    tg_id,
                    end_text,
                    reply_markup=tariffs_keyboard(),
                )
                await update_remnawave_subscription_fields(tg_id, slot, expire_notified_end_at=utc_now())
                stats['ended'] += 1
                continue

            remaining = exp - now
            if remaining <= timedelta(hours=2):
                if str(row_value(sub, 'expire_notified_2h_at') or '').strip():
                    continue
                if not await _subscription_snapshot_is_current(sub):
                    continue
                two_hours_text = (
                    '⏳ До окончания пробной подписки осталось 2 часа.\n\nВыберите подходящий тариф, чтобы не потерять доступ.'
                    if is_trial else
                    f'⏳ До окончания подписки «{subscription_display_name(sub)}» осталось 2 часа.\n\nВыберите подходящий тариф, чтобы не потерять доступ.'
                )
                await bot.send_message(
                    tg_id,
                    two_hours_text,
                    reply_markup=tariffs_keyboard(),
                )
                await update_remnawave_subscription_fields(tg_id, slot, expire_notified_2h_at=utc_now())
                stats['two_hours'] += 1
            elif remaining <= timedelta(days=1):
                if str(row_value(sub, 'expire_notified_1d_at') or '').strip():
                    continue
                if not await _subscription_snapshot_is_current(sub):
                    continue
                day_text = (
                    '⏳ Пробная подписка закончится через 1 день.\n\nВыберите подходящий тариф, чтобы не потерять доступ.'
                    if is_trial else
                    f'⏳ Подписка «{subscription_display_name(sub)}» закончится через 1 день.\n\nВыберите подходящий тариф, чтобы не потерять доступ.'
                )
                await bot.send_message(
                    tg_id,
                    day_text,
                    reply_markup=tariffs_keyboard(),
                )
                await update_remnawave_subscription_fields(tg_id, slot, expire_notified_1d_at=utc_now())
                stats['day'] += 1
        except Exception as exc:
            stats['errors'] += 1
            logger.warning('Expiry notification failed for tg_id=%s slot=%s: %s', tg_id, slot, exc)
    return stats


async def _notify_trial_usage_once(bot: Bot) -> dict[str, int]:
    subs = _active_subscriptions(await get_all_remnawave_subscriptions())
    now = datetime.now(timezone.utc)
    min_age = timedelta(hours=TRIAL_USAGE_NOTIFY_AFTER_HOURS)
    stats = {'sent': 0, 'skipped': 0, 'errors': 0}
    for sub in subs:
        tg_id = int(row_value(sub, 'user_tg_id', default=0) or 0)
        slot = int(row_value(sub, 'slot', default=0) or 0)
        if tg_id <= 0 or slot <= 0:
            continue
        with contextlib.suppress(Exception):
            await _sync_subscription_expire_from_remnawave(sub)
        if str(row_value(sub, 'kind') or '').strip().lower() != 'trial':
            continue
        if str(row_value(sub, 'trial_usage_notified_at') or '').strip():
            stats['skipped'] += 1
            continue
        started_at = _subscription_dt(row_value(sub, 'created_at')) or _subscription_dt(row_value(sub, 'updated_at'))
        if started_at and (now - started_at) < min_age:
            stats['skipped'] += 1
            continue
        if not await _subscription_snapshot_is_current(sub):
            stats['skipped'] += 1
            continue
        exp = _subscription_dt(row_value(sub, 'expire_at'))
        if exp and exp <= now:
            stats['skipped'] += 1
            continue
        used_bytes = max(int(row_value(sub, 'traffic_used_bytes', default=0) or 0), 0)
        is_low = used_bytes < TRIAL_USAGE_NOTIFY_THRESHOLD_BYTES
        text = (
            'Похоже, конфигуратор ещё не подключён или не пригодился 😢\n\n'
            'Если что-то не получилось подключить, то мы всегда поможем!'
            if is_low
            else
            'Видим, что наши услуги вам нравятся 😎\n\n'
            'Чтобы доступ не оборвался после пробника, можно продлить заранее — это займёт минуту.'
        )
        kb = trial_usage_low_keyboard() if is_low else trial_usage_high_keyboard()
        try:
            await bot.send_message(tg_id, text, reply_markup=kb)
            await update_remnawave_subscription_fields(tg_id, slot, trial_usage_notified_at=utc_now())
            stats['sent'] += 1
        except Exception as exc:
            stats['errors'] += 1
            logger.warning('Trial usage notification failed for tg_id=%s slot=%s: %s', tg_id, slot, exc)
    return stats


async def _notify_no_trial_once(bot: Bot) -> dict[str, int]:
    targets = await get_no_trial_broadcast_targets(days_old=NO_TRIAL_NOTIFY_AFTER_DAYS)
    stats = {'sent': 0, 'skipped': 0, 'errors': 0}
    for user in targets:
        tg_id = int(row_value(user, 'tg_id', default=0) or 0)
        if tg_id <= 0:
            continue
        try:
            await bot.send_message(
                tg_id,
                (
                    '🌟 Похоже, пробная подписка у вас ещё не была активирована.\n\n'
                    'Можно подключить пробный период в пару кликов и сразу проверить, как всё работает.\n'
                    'Если с запуском будут сложности — мы поможем.'
                ),
                reply_markup=trial_invitation_keyboard(),
            )
            await update_user_fields(tg_id, no_trial_notified_at=utc_now())
            stats['sent'] += 1
        except Exception as exc:
            stats['errors'] += 1
            logger.warning('No-trial notification failed for tg_id=%s: %s', tg_id, exc)
    return stats


async def _reset_single_subscription_traffic(bot: Bot, sub: Any) -> None:
    tg_id = int(row_value(sub, 'user_tg_id', default=0) or 0)
    slot = int(row_value(sub, 'slot', default=0) or 0)
    if tg_id <= 0 or slot <= 0:
        return
    now = utc_now()
    user_uuid = await _resolve_subscription_user_uuid(sub)
    if user_uuid:
        try:
            await remnawave.reset_user_traffic(user_uuid)
        except Exception as exc:
            logger.warning('Reset traffic failed for tg_id=%s slot=%s: %s', tg_id, slot, exc)
    try:
        await update_remnawave_subscription_usage(tg_id, slot, 0, checked_at=now)
        await set_remnawave_subscription_mobile_disabled(tg_id, slot, 0)
    except Exception as exc:
        logger.warning('Failed to store reset traffic for tg_id=%s slot=%s: %s', tg_id, slot, exc)
    if user_uuid:
        wifi_uuid = str(settings.remnawave_squad_1_uuid or '').strip()
        mobile_uuid = str(settings.remnawave_squad_2_uuid or '').strip()
        active_squads = [uuid for uuid in (wifi_uuid, mobile_uuid) if uuid]
        if active_squads:
            try:
                await remnawave.update_user({
                    'uuid': user_uuid,
                    'username': str(row_value(sub, 'username') or combined_key_username(tg_id, kind='reset', salt=str(slot))),
                    'telegramId': tg_id,
                    'expireAt': str(row_value(sub, 'expire_at') or utc_now()),
                    'status': 'ACTIVE',
                    'trafficLimitStrategy': str(row_value(sub, 'traffic_limit_strategy') or 'NO_RESET'),
                    'trafficLimitBytes': 0,
                    'description': f'TG {tg_id} / monthly reset / {subscription_display_name(sub)}',
                    'activeInternalSquads': active_squads,
                    'tag': f'TG{tg_id % 100000000:08d}_{slot}'[:15],
                })
            except Exception as exc:
                logger.warning('Failed to restore squads for tg_id=%s slot=%s: %s', tg_id, slot, exc)


async def _reset_monthly_traffic_once(bot: Bot) -> dict[str, Any]:
    subs = _active_subscriptions(await get_all_remnawave_subscriptions())
    wifi_uuid = str(settings.remnawave_squad_1_uuid or '').strip()
    mobile_uuid = str(settings.remnawave_squad_2_uuid or '').strip()
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat(timespec='seconds')
    touched_users: dict[int, list[str]] = {}
    reset_count = 0

    for sub in subs:
        tg_id = int(row_value(sub, 'user_tg_id', default=0) or 0)
        slot = int(row_value(sub, 'slot', default=0) or 0)
        if tg_id <= 0 or slot <= 0:
            continue
        due_at = _traffic_reset_due_at(sub)
        if due_at is None:
            try:
                base_raw = str(row_value(sub, 'updated_at') or row_value(sub, 'created_at') or '')
                base_dt = datetime.fromisoformat(base_raw) if base_raw else now_dt
                if base_dt.tzinfo is None:
                    base_dt = base_dt.replace(tzinfo=timezone.utc)
            except Exception:
                base_dt = now_dt
            with contextlib.suppress(Exception):
                await update_remnawave_subscription_reset_at(tg_id, slot, _next_traffic_reset_at(base_dt))
            continue
        if due_at > now_dt:
            continue

        mobile_disabled = int(row_value(sub, 'mobile_disabled', default=0) or 0) == 1
        user_uuid = await _resolve_subscription_user_uuid(sub)
        if user_uuid:
            try:
                await remnawave.reset_user_traffic(user_uuid)
            except Exception as exc:
                logger.warning('Monthly reset traffic failed for tg_id=%s slot=%s: %s', tg_id, slot, exc)
        try:
            await update_remnawave_subscription_usage(tg_id, slot, 0, checked_at=now)
            await set_remnawave_subscription_mobile_disabled(tg_id, slot, 0)
            await update_remnawave_subscription_identity(
                tg_id,
                slot,
                username=str(row_value(sub, 'username') or '').strip() or None,
            )
            await update_remnawave_subscription_reset_at(tg_id, slot, _next_traffic_reset_at(due_at))
        except Exception as exc:
            logger.warning('Failed to update local reset state for tg_id=%s slot=%s: %s', tg_id, slot, exc)
        if mobile_disabled and user_uuid and (wifi_uuid or mobile_uuid):
            active_squads = [uuid for uuid in (wifi_uuid, mobile_uuid) if uuid]
            if active_squads:
                try:
                    await remnawave.update_user({
                        'uuid': user_uuid,
                        'username': str(row_value(sub, 'username') or combined_key_username(tg_id, kind='reset', salt=str(slot))),
                        'telegramId': tg_id,
                        'expireAt': str(row_value(sub, 'expire_at') or utc_now()),
                        'status': 'ACTIVE',
                        'trafficLimitStrategy': str(row_value(sub, 'traffic_limit_strategy') or 'NO_RESET'),
                        'trafficLimitBytes': 0,
                        'description': f'TG {tg_id} / monthly reset / {subscription_display_name(sub)}',
                        'activeInternalSquads': active_squads,
                        'tag': f'TG{tg_id % 100000000:08d}_{slot}'[:15],
                    })
                except Exception as exc:
                    logger.warning('Failed to restore mobile squads for tg_id=%s slot=%s: %s', tg_id, slot, exc)
        touched_users.setdefault(tg_id, []).append(subscription_label(slot))
        reset_count += 1

    if touched_users:
        logger.info(
            'Monthly traffic reset applied for users=%s subscriptions=%s',
            len(touched_users),
            reset_count,
        )

    return {'reset': reset_count, 'users': len(touched_users), 'already_done': 0}



async def remnawave_usage_monitor(bot: Bot) -> None:
    interval = max(int(getattr(settings, 'remnawave_check_interval_sec', 1200) or 1200), 1200)
    tick = 0
    logger.info('Remnawave usage monitor started; interval=%s sec', interval)
    while True:
        tick += 1
        try:
            logger.info('Remnawave usage monitor tick %s started', tick)
            reset_stats = await _reset_monthly_traffic_once(bot)
            if reset_stats.get('already_done'):
                logger.info('Monthly traffic reset already applied for %s', current_month_key())
            elif reset_stats.get('reset', 0):
                logger.info(
                    'Monthly traffic reset done: subs=%s users=%s',
                    reset_stats.get('reset', 0),
                    reset_stats.get('users', 0),
                )
            stats = await _sync_mobile_usage_once(bot)
            logger.info(
                'Remnawave usage monitor tick %s done: checked=%s disabled=%s enabled=%s skipped=%s errors=%s',
                tick,
                stats.get('checked', 0),
                stats.get('disabled', 0),
                stats.get('enabled', 0),
                stats.get('skipped', 0),
                stats.get('errors', 0),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception('Remnawave usage monitor failed on tick %s: %s', tick, exc)
        await asyncio.sleep(interval)


async def subscription_notifications_monitor(bot: Bot) -> None:
    interval = max(int(EXPIRY_NOTIFY_INTERVAL_SEC or 300), 60)
    tick = 0
    logger.info('Subscription notifications monitor started; interval=%s sec', interval)
    await asyncio.sleep(interval)
    while True:
        tick += 1
        try:
            expiry_stats = await _notify_subscription_expiry_once(bot)
            trial_stats = await _notify_trial_usage_once(bot)
            logger.info(
                'Subscription notifications tick %s done: expiry_day=%s expiry_2h=%s expiry_end=%s trial_sent=%s trial_skipped=%s errors=%s',
                tick,
                expiry_stats.get('day', 0),
                expiry_stats.get('two_hours', 0),
                expiry_stats.get('ended', 0),
                trial_stats.get('sent', 0),
                trial_stats.get('skipped', 0),
                expiry_stats.get('errors', 0) + trial_stats.get('errors', 0),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception('Subscription notifications monitor failed on tick %s: %s', tick, exc)
        await asyncio.sleep(interval)


async def payment_orders_monitor(bot: Bot) -> None:
    interval = 15
    tick = 0
    logger.info('Payment monitor started; interval=%s sec', interval)
    while True:
        tick += 1
        try:
            logger.info('Payment monitor tick %s started', tick)
            await process_pending_orders(bot)
            logger.info('Payment monitor tick %s done', tick)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception('Payment monitor failed on tick %s: %s', tick, exc)
        await asyncio.sleep(interval)

async def _run_mobile_monitor_check(bot: Bot) -> str:
    logger.info('Manual monitor check started')
    stats = await _sync_mobile_usage_once(bot)
    logger.info(
        'Manual monitor check done: checked=%s disabled=%s enabled=%s skipped=%s errors=%s',
        stats.get('checked', 0),
        stats.get('disabled', 0),
        stats.get('enabled', 0),
        stats.get('skipped', 0),
        stats.get('errors', 0),
    )
    return (
        f"Проверка мониторинга завершена. Проверено: {stats['checked']}, "
        f"отключено Mobile: {stats['disabled']}, включено Mobile: {stats['enabled']}, "
        f"пропущено: {stats['skipped']}, ошибок: {stats['errors']}"
    )


async def _create_test_referrals_for_partner(bot: Bot, partner_id: int, count: int) -> int:
    partner = await get_user(partner_id)
    if not partner or int(row_value(partner, 'is_partner', default=0) or 0) != 1:
        return 0

    created = 0
    for _ in range(count):
        fake_tg_id = -(secrets.randbits(63) or 1)
        while await get_user(fake_tg_id):
            fake_tg_id = -(secrets.randbits(63) or 1)
        created += 1 if await upsert_user(fake_tg_id, None, None, partner_id) else 1
    if created:
        await _reward_partner_for_new_referral(bot, partner_id)
    return created


async def _apply_referral_earnings(order, bot: Bot) -> None:
    if str(row_value(order, 'kind', default='payment')) not in {'payment', 'refill', 'topup'}:
        return

    amount = int(row_value(order, 'amount', default=0) or 0)
    if amount <= 0:
        return

    buyer_id = int(row_value(order, 'tg_id'))
    buyer = await get_user(buyer_id)
    if buyer is None:
        return

    cashback = round(amount * REFERRAL_CASHBACK_PERCENT / 100, 2)
    if cashback > 0:
        await adjust_user_balance(buyer_id, 'payment_balance', cashback)

    first_payment_marked = int(row_value(buyer, 'referral_first_payment_marked', default=0) or 0) == 1
    if first_payment_marked:
        return

    if amount < 160:
        return

    now = utc_now()
    await update_user_fields(buyer_id, referral_first_payment_marked=1, referral_paid_at=now)

    referrer_id = row_value(buyer, 'referrer_id')
    if not referrer_id:
        return

    referrer = await get_user(int(referrer_id))
    if referrer is None:
        return

    ref_percent = PARTNER_REF_PERCENT if int(row_value(referrer, 'is_partner', default=0) or 0) == 1 else DEFAULT_REF_PERCENT
    commission = round(amount * ref_percent / 100, 2)
    if commission > 0:
        await adjust_user_balance(int(referrer_id), 'referral_balance', commission)

    paid_count = await increment_ref_paid_count(int(referrer_id))
    if paid_count % REF_BONUS_COUNT == 0:
        await _update_access_expiration(int(referrer_id), 30)
        try:
            await bot.send_message(int(referrer_id), '🎁 Бонус за 6 оплат рефералов: +1 месяц доступа.')
        except Exception:
            logger.exception('Failed to notify referrer about referral bonus | referrer_id=%s', referrer_id)


PAID_SUBSCRIPTION_KINDS = {'payment', 'balance_new', 'balance_renew', 'renew', 'admin_test', 'partner_grant'}
TRIAL_SUBSCRIPTION_KINDS = {'trial'}


def _subscription_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _remnawave_active_squads(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get('activeInternalSquads') or payload.get('active_internal_squads') or payload.get('squads') or payload.get('internalSquads')
    result: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                value = item.strip()
            elif isinstance(item, dict):
                value = str(item.get('uuid') or item.get('id') or item.get('squadUuid') or item.get('squad_uuid') or '').strip()
            else:
                value = str(item).strip()
            if value and value not in result:
                result.append(value)
    return result


async def _sync_subscription_expire_from_remnawave(sub: Any) -> bool:
    """Keep local expiry aligned with Remnawave."""
    user_uuid = str(row_value(sub, 'user_uuid') or '').strip()
    tg_id = int(row_value(sub, 'user_tg_id', default=0) or 0)
    slot = int(row_value(sub, 'slot', default=0) or 0)
    if not user_uuid or tg_id <= 0 or slot <= 0:
        return False

    try:
        remote = await remnawave.get_user_by_uuid(user_uuid)
    except Exception as exc:
        logger.warning('Failed to refresh Remnawave state for tg_id=%s slot=%s: %s', tg_id, slot, exc)
        return False

    if not isinstance(remote, dict) or not remote:
        return False

    now = datetime.now(timezone.utc)
    remote_exp = _subscription_dt(remote.get('expireAt') or remote.get('expire_at'))
    remote_status = str(remote.get('status') or '').strip().upper()
    local_exp = _subscription_dt(row_value(sub, 'expire_at'))

    updates: dict[str, Any] = {}
    if remote_exp and (local_exp is None or remote_exp < local_exp - timedelta(seconds=5)):
        updates['expire_at'] = remote_exp.isoformat(timespec='seconds')

    # If Remnawave says the user is no longer active, the local record must not stay live.
    if remote_status and remote_status not in {'ACTIVE', 'ENABLED'}:
        if remote_exp:
            updates['expire_at'] = remote_exp.isoformat(timespec='seconds')
        elif not updates.get('expire_at'):
            updates['expire_at'] = now.isoformat(timespec='seconds')

    if remote_exp and remote_exp <= now:
        updates['expire_at'] = remote_exp.isoformat(timespec='seconds')

    if updates:
        await update_remnawave_subscription_fields(tg_id, slot, **updates)
        return True
    return False


async def _sync_user_subscription_snapshots(tg_id: int) -> None:
    subs = await get_user_subscriptions(tg_id)
    for sub in subs:
        with contextlib.suppress(Exception):
            await _sync_subscription_expire_from_remnawave(sub)
    with contextlib.suppress(Exception):
        await _sync_user_access_from_subscriptions(tg_id)


def _pick_free_slot(existing_slots: set[int], preferred_slots: list[int]) -> int:
    for slot in preferred_slots:
        if slot > 0 and slot not in existing_slots:
            return slot
    slot = 1
    while slot in existing_slots:
        slot += 1
    return slot


def _pick_latest_subscription(subs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not subs:
        return None
    def key(sub: dict[str, Any]) -> tuple[datetime, datetime]:
        exp = _subscription_dt(row_value(sub, 'expire_at')) or datetime.min.replace(tzinfo=timezone.utc)
        updated = _subscription_dt(row_value(sub, 'updated_at')) or datetime.min.replace(tzinfo=timezone.utc)
        return exp, updated
    return max(subs, key=key)


async def _select_subscription_target_and_slot(tg_id: int, kind: str) -> tuple[dict[str, Any] | None, int, list[dict]]:
    subs = _active_subscriptions(await get_user_subscriptions(tg_id))
    existing_slots = {int(row_value(sub, 'slot', default=0) or 0) for sub in subs if int(row_value(sub, 'slot', default=0) or 0) > 0}
    kind = str(kind or '').strip()
    if kind in TRIAL_SUBSCRIPTION_KINDS:
        candidates = [sub for sub in subs if str(row_value(sub, 'kind') or '') in TRIAL_SUBSCRIPTION_KINDS]
        target = _pick_latest_subscription(candidates)
        slot = int(row_value(target, 'slot', default=0) or 0) if target else _pick_free_slot(existing_slots, [1, 2, 3, 4])
        return target, slot, subs

    candidates = [sub for sub in subs if str(row_value(sub, 'kind') or '') not in TRIAL_SUBSCRIPTION_KINDS]
    target = _pick_latest_subscription(candidates)
    slot = int(row_value(target, 'slot', default=0) or 0) if target else _pick_free_slot(existing_slots, [2, 1, 3, 4])
    return target, slot, subs


async def _issue_mobile_refill(tg_id: int, gb: int, bot: Bot, slot: int | None = None) -> list[dict]:
    subs = _active_subscriptions(await get_user_subscriptions(tg_id))
    if slot is not None:
        target = next((sub for sub in subs if int(row_value(sub, 'slot', default=0) or 0) == int(slot)), None)
    else:
        target = _pick_latest_subscription(_refill_candidates(subs))
    if not target:
        return []

    if str(row_value(target, 'kind') or '') == 'trial':
        return []

    current_limit = max(int(row_value(target, 'traffic_limit_bytes', default=0) or 0), 0)
    add_bytes = max(int(gb), 0) * 1024 * 1024 * 1024
    if add_bytes <= 0:
        return []

    new_limit = current_limit + add_bytes if current_limit > 0 else add_bytes
    target_slot = int(row_value(target, 'slot', default=0) or 0)
    await update_remnawave_subscription_limit(tg_id, target_slot, new_limit)
    await update_remnawave_subscription_reset_at(tg_id, target_slot, _next_traffic_reset_at())
    await set_remnawave_subscription_mobile_disabled(tg_id, target_slot, 0)

    wifi_uuid = str(settings.remnawave_squad_1_uuid or '').strip()
    mobile_uuid = str(settings.remnawave_squad_2_uuid or '').strip()
    if wifi_uuid and mobile_uuid:
        user_uuid = str(row_value(target, 'user_uuid') or '').strip()
        if user_uuid:
            try:
                await remnawave.update_user({
                    'uuid': user_uuid,
                    'telegramId': tg_id,
                    'status': 'ACTIVE',
                    'trafficLimitBytes': 0,
                    'activeInternalSquads': [wifi_uuid, mobile_uuid],
                    'description': f'TG {tg_id} / refill / {subscription_display_name(target)}',
                })
            except Exception:
                logger.exception('Failed to restore mobile squad after refill for tg_id=%s slot=%s', tg_id, target_slot)

    updated = await get_remnawave_subscription_by_user_slot(tg_id, target_slot)
    return [dict(updated)] if updated else [dict(target)]


async def _extend_existing_subscription(tg_id: int, slot: int, days: int, bot: Bot) -> list[dict]:
    sub = await get_remnawave_subscription_by_user_slot(tg_id, slot)
    if not sub or days <= 0:
        return []
    if str(row_value(sub, 'kind') or '') == 'trial':
        return []

    base = datetime.now(timezone.utc)
    current_exp = _subscription_dt(row_value(sub, 'expire_at'))
    if current_exp and current_exp > base:
        base = current_exp
    new_expire = (base + timedelta(days=days)).isoformat(timespec='seconds')

    wifi_uuid = str(settings.remnawave_squad_1_uuid or '').strip()
    mobile_uuid = str(settings.remnawave_squad_2_uuid or '').strip()
    user_uuid = str(row_value(sub, 'user_uuid') or '').strip()
    username = str(row_value(sub, 'username') or combined_key_username(tg_id, kind='extend', salt=f'{slot}:{days}'))
    display_name = subscription_display_name(sub)
    try:
        await remnawave.update_user({
            'uuid': user_uuid or None,
            'telegramId': tg_id,
            'username': username,
            'status': 'ACTIVE',
            'expireAt': new_expire,
            'trafficLimitBytes': 0,
            'activeInternalSquads': combined_internal_squads() or [u for u in (wifi_uuid, mobile_uuid) if u],
            'description': f'TG {tg_id} / extend / {display_name}',
        })
    except Exception:
        logger.exception('Failed to extend subscription in Remnawave | tg_id=%s slot=%s days=%s', tg_id, slot, days)
        raise

    await save_remnawave_subscription(
        payment_id=str(row_value(sub, 'payment_id') or f'extend:{tg_id}:{slot}'),
        user_tg_id=tg_id,
        slot=slot,
        kind=str(row_value(sub, 'kind') or 'payment'),
        user_uuid=user_uuid,
        username=username,
        subscription_url=str(row_value(sub, 'subscription_url') or ''),
        display_name=display_name,
        squad_uuid=str(row_value(sub, 'squad_uuid') or mobile_uuid or wifi_uuid),
        traffic_limit_bytes=int(row_value(sub, 'traffic_limit_bytes', default=0) or 0),
        traffic_limit_strategy=str(row_value(sub, 'traffic_limit_strategy') or 'NO_RESET'),
        expire_at=new_expire,
        traffic_reset_at=_next_traffic_reset_at(),
    )
    await set_remnawave_subscription_mobile_disabled(tg_id, slot, int(row_value(sub, 'mobile_disabled', default=0) or 0))
    await update_remnawave_subscription_usage(tg_id, slot, int(row_value(sub, 'traffic_used_bytes', default=0) or 0), str(row_value(sub, 'traffic_used_at') or utc_now()))
    await _sync_user_access_from_subscriptions(tg_id)
    updated = await get_remnawave_subscription_by_user_slot(tg_id, slot)
    return [dict(updated)] if updated else [dict(sub)]


async def _create_or_update_pair(tg_id: int, days: int, kind: str, choice: str, mobile_limit_gb: int, bot: Bot, display_name: str | None = None) -> list[dict]:
    slot = await get_next_subscription_slot(tg_id)
    wifi_uuid = str(settings.remnawave_squad_1_uuid or '').strip()
    mobile_uuid = str(settings.remnawave_squad_2_uuid or '').strip()
    active_squads = combined_internal_squads()

    final_name = (display_name or '').strip()
    if not final_name:
        if kind == 'trial':
            final_name = 'Пробная'
        elif kind == 'partner_grant':
            final_name = 'Партнёр'
        elif days > 0:
            final_name = f'{days} дней'
        else:
            final_name = 'Подписка'

    username = combined_key_username(tg_id, kind=kind, salt=f'{slot}:{kind}:{days}')
    user = await remnawave.create_or_update_subscription(
        telegram_id=tg_id,
        slot=slot,
        days=days,
        squad_uuid=mobile_uuid or wifi_uuid,
        traffic_limit_gb=0,
        base_username=username,
        description=f'TG {tg_id} / {kind} / {final_name}',
        traffic_limit_strategy='NO_RESET',
        active_internal_squads=active_squads,
        username=username,
        reuse_existing=False,
    )
    user_uuid = str(user.get('uuid') or '').strip()
    subscription_url = str(user.get('subscription_url') or user.get('subscriptionUrl') or '').strip()
    used_bytes = int(((user.get('userTraffic') or {}) if isinstance(user, dict) else {}).get('usedTrafficBytes') or ((user.get('userTraffic') or {}) if isinstance(user, dict) else {}).get('lifetimeUsedTrafficBytes') or 0)
    limit_bytes = max(int(mobile_limit_gb), 0) * 1024 * 1024 * 1024
    payment_id = f'{kind}:{tg_id}:{slot}'
    await save_remnawave_subscription(
        payment_id=payment_id,
        user_tg_id=tg_id,
        slot=slot,
        kind=kind,
        user_uuid=user_uuid,
        username=username,
        subscription_url=subscription_url,
        display_name=final_name,
        squad_uuid=mobile_uuid or wifi_uuid,
        traffic_limit_bytes=limit_bytes,
        traffic_limit_strategy='NO_RESET',
        expire_at=str(user.get('expireAt') or user.get('expire_at') or (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec='seconds')),
        traffic_reset_at=_next_traffic_reset_at(),
    )
    await update_remnawave_subscription_usage(tg_id, slot, used_bytes)
    await update_remnawave_subscription_limit(tg_id, slot, limit_bytes)
    await update_remnawave_subscription_reset_at(tg_id, slot, _next_traffic_reset_at())
    await set_remnawave_subscription_mobile_disabled(tg_id, slot, 0)
    await _update_access_expiration(tg_id, days)
    return [{
        'slot': slot,
        'user_uuid': user_uuid,
        'username': username,
        'subscription_url': subscription_url,
        'happ_crypto_link': str(((user.get('happ') or {}) if isinstance(user, dict) else {}).get('cryptoLink') or ''),
        'display_name': final_name,
        'kind': kind,
        'days': days,
        'squad_uuid': mobile_uuid or wifi_uuid,
        'traffic_limit_bytes': limit_bytes,
        'traffic_limit_strategy': 'NO_RESET',
        'expire_at': str(user.get('expireAt') or user.get('expire_at') or (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec='seconds')),
    }]


async def issue_remnawave_access(order, bot: Bot) -> list[dict]:
    tg_id = int(row_value(order, 'tg_id'))
    kind = str(row_value(order, 'kind', default='payment') or 'payment')
    days = int(row_value(order, 'days', default=30) or 30)
    if kind == 'topup':
        return []
    if kind == 'refill':
        gb = int(row_value(order, 'refill_gb', default=0) or 0)
        if gb <= 0:
            gb = max(int(round(int(row_value(order, 'amount', default=0) or 0) / 3)), 1)
        slot = int(row_value(order, 'refill_slot', default=0) or 0) or None
        return await _issue_mobile_refill(tg_id, gb, bot, slot)
    if kind in {'extend', 'balance_renew', 'renew'}:
        slot = int(row_value(order, 'extend_slot', default=0) or row_value(order, 'slot', default=0) or 0)
        if slot <= 0:
            _, slot, _ = await _select_subscription_target_and_slot(tg_id, kind)
        if slot <= 0:
            return []
        return await _extend_existing_subscription(tg_id, slot, days, bot)
    if kind == 'admin_manual':
        name = str(row_value(order, 'subscription_name') or '').strip() or f'{days} дней'
        limit_gb = int(row_value(order, 'mobile_limit_gb', default=0) or 0)
        return await _create_or_update_pair(tg_id, days, kind, 'new', limit_gb, bot, display_name=name)
    if kind in {'payment', 'balance_new'}:
        name = str(row_value(order, 'subscription_name') or '').strip() or f'{days} дней'
        return await _create_or_update_pair(tg_id, days, kind, 'new', MOBILE_TRAFFIC_GB, bot, display_name=name)
    if kind == 'trial':
        active_subs = _active_subscriptions(await get_user_subscriptions(tg_id))
        trial_subs = [sub for sub in active_subs if str(row_value(sub, 'kind') or '').strip().lower() == 'trial']
        if kind == 'trial':
            if bool(trial_subs):
                return []
        else:
            if any(str(row_value(sub, 'kind') or '').strip().lower() in PAID_SUBSCRIPTION_KINDS for sub in active_subs):
                return []
            if bool(trial_subs):
                return []
        return await _create_or_update_pair(tg_id, days, 'trial', 'new', TRIAL_TRAFFIC_LIMIT_GB, bot, display_name='Пробная')
    if kind == 'partner_grant':
        return await _create_or_update_pair(tg_id, days, kind, 'new', PARTNER_ACCESS_TRAFFIC_GB, bot, display_name='Партнёр')
    if kind == 'admin_test':
        return await _create_or_update_pair(tg_id, days, kind, 'new', TRIAL_TRAFFIC_LIMIT_GB, bot, display_name='Пробная')
    return await _create_or_update_pair(tg_id, days, kind, 'new', MOBILE_TRAFFIC_GB, bot, display_name=str(row_value(order, 'subscription_name') or '') or None)


async def deliver_paid_order(order, bot: Bot) -> bool:
    try:
        kind = str(row_value(order, 'kind', default='payment') or 'payment')
        amount = int(row_value(order, 'amount', default=0) or 0)
        tg_id = int(row_value(order, 'tg_id'))
        if kind == 'topup':
            await adjust_user_balance(tg_id, 'payment_balance', amount)
            await _apply_referral_earnings(order, bot)
            await mark_payment_status(str(row_value(order, 'payment_id')), 'succeeded', remnawave_done=1, notified_at=utc_now())
            user_after = await get_user(tg_id)
            cashback = round(amount * REFERRAL_CASHBACK_PERCENT / 100, 2)
            balance_after = float(row_value(user_after, 'payment_balance', default=0.0) or 0.0) if user_after else 0.0
            await bot.send_message(
                tg_id,
                (
                    f'✅ Баланс оплаты пополнен на {amount} ₽.\n'
                    f'Кэшбэк начислен: {money(cashback)} ₽\n'
                    f'Новый баланс оплаты: {money(balance_after)} ₽'
                ),
                reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(tg_id)),
            )
            return True

        subs = await issue_remnawave_access(order, bot)
        if not subs:
            if kind == 'trial':
                user_after = await get_user(tg_id)
                trial_subs = await get_user_subscriptions_by_kind(tg_id, 'trial')
                used = int(row_value(user_after, 'trial_used', default=0) or 0) == 1 if user_after else False
                if used or bool(trial_subs):
                    await mark_payment_status(str(row_value(order, 'payment_id')), 'succeeded', remnawave_done=1, notified_at=utc_now())
                    await bot.send_message(
                        tg_id,
                        '❌ Пробный период выдается только один раз на аккаунт.',
                        reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(tg_id)),
                    )
                    return True
            raise RuntimeError('Не удалось создать подписку')

        if kind in {'payment', 'refill', 'topup'}:
            await _apply_referral_earnings(order, bot)

        await mark_payment_status(str(row_value(order, 'payment_id')), 'succeeded', remnawave_done=1, notified_at=utc_now())
        link_url = None
        if subs:
            first = subs[0] if isinstance(subs[0], dict) else dict(subs[0])
            link_url = _happ_redirect_url_from_link(row_value(first, 'happ_crypto_link'))
            if not link_url:
                link_url = await _build_happ_redirect_link(row_value(first, 'subscription_url'))
            if not link_url:
                link_url = _happ_redirect_url_from_link(getattr(settings, 'happ_import_url', '') or None)
            HAPP_ACTION_CACHE[tg_id] = {
                'happ_link': link_url or '',
            }
        message_text = format_subscriptions_message(subs, order)
        if not isinstance(message_text, str) or not message_text.strip():
            message_text = '✅ Оплата прошла успешно.'
        await _safe_send_user_message(tg_id= tg_id, bot=bot, text=message_text, reply_markup=happ_keys_keyboard(link_url))
        await clear_user_promo(tg_id)
        return True
    except Exception as exc:
        await mark_payment_status(str(row_value(order, 'payment_id')), 'succeeded', remnawave_done=1, remnawave_error=str(exc))
        logger.exception('deliver_paid_order failed')
        return False


async def process_pending_orders(bot: Bot) -> None:
    orders = await get_pending_payment_orders()
    for order in orders:
        kind = str(row_value(order, 'kind', default='payment') or 'payment').strip().lower()
        payment_id = str(row_value(order, 'payment_id') or '')
        status = str(row_value(order, 'status', default='pending') or 'pending').strip().lower()
        remnawave_done = int(row_value(order, 'remnawave_done', default=0) or 0)
        remnawave_error = str(row_value(order, 'remnawave_error', default='') or '').strip()

        if remnawave_done == 1:
            continue

        # Legacy/internal orders are delivered only when they were already
        # finalized by the originating flow (status='succeeded'). Pending
        # leftovers must not be auto-issued on startup.
        if kind not in {'payment', 'topup', 'refill'} and status != 'succeeded':
            continue

        if remnawave_error:
            await mark_payment_status(payment_id, status, remnawave_done=1, remnawave_error=remnawave_error)
            continue

        if status != 'succeeded':
            status = await get_payment_status(payment_id)
            if status == 'succeeded':
                pass
            elif status in {'canceled', 'expired'}:
                await mark_payment_status(payment_id, status, remnawave_done=0)
                await clear_user_promo(int(row_value(order, 'tg_id')))
                continue
            else:
                continue

        await deliver_paid_order(order, bot)


async def _create_internal_order_and_deliver(bot: Bot, tg_id: int, tariff_code: str, amount: int, days: int, kind: str, **extra) -> bool:
    payment_id = f'{kind}:{tg_id}:{secrets.token_hex(8)}'
    await create_payment_order(
        payment_id,
        tg_id,
        tariff_code,
        amount,
        days,
        promo_code=None,
        promo_discount=0,
        kind=kind,
        status='succeeded',
        remnawave_done=1,
        refill_gb=extra.get('refill_gb'),
        refill_slot=extra.get('refill_slot'),
        subscription_name=extra.get('subscription_name'),
        mobile_limit_gb=extra.get('mobile_limit_gb'),
        extend_slot=extra.get('extend_slot'),
    )
    order = await get_payment_order(payment_id)
    return await deliver_paid_order(order, bot)


@router.message(Command('start'))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    payload = parse_start_payload(message.text)
    referrer_id = int(payload) if payload and payload.isdigit() else None
    if referrer_id == message.from_user.id:
        referrer_id = None

    await _register_start_user(
        message.bot,
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        referrer_id,
    )

    await message.answer(
        main_menu_text(),
        reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(message.from_user.id)),
    )

@router.callback_query(F.data == 'menu:home')
async def cb_home(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    user = await get_user(callback.from_user.id)
    await callback.message.answer(main_menu_text(), reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(callback.from_user.id)))


@router.callback_query(F.data == 'menu:instruction')
async def cb_instruction(callback: CallbackQuery):
    await callback.answer()
    caption = '<b>Инструкция по Happ</b>\n\nВыберите вашу платформу ниже.\nСсылки ведут на официальные страницы загрузки Happ.\n\nПосле установки откройте подписку из бота кнопкой <b>«Открыть в Happ»</b>.'
    await callback.message.answer_photo(
        FSInputFile(HAPP_INSTRUCTION_IMAGE_PATH),
        caption=caption,
        parse_mode='HTML',
        reply_markup=happ_instruction_keyboard(),
    )


@router.callback_query(F.data == 'menu:trial')
async def cb_trial(callback: CallbackQuery):
    await callback.answer()
    user = await get_user(callback.from_user.id)
    trial_subs = await get_user_subscriptions_by_kind(callback.from_user.id, 'trial')
    used = int(row_value(user, 'trial_used', default=0) or 0) == 1 if user else False
    is_admin = await _is_admin_user(callback.from_user.id)
    if (used or bool(trial_subs)) and not is_admin:
        await callback.message.answer('❌ Пробный период уже был использован на этом аккаунте.', reply_markup=main_menu_keyboard(is_admin=is_admin))
        return
    reserved = True
    trial_until = utc_in_days(TRIAL_DAYS)
    if not is_admin:
        reserved = await reserve_trial_access(callback.from_user.id, trial_until)
        if not reserved:
            await callback.message.answer('❌ Пробный период уже был использован на этом аккаунте.', reply_markup=main_menu_keyboard(is_admin=is_admin))
            return
    ok = await _create_internal_order_and_deliver(callback.message.bot, callback.from_user.id, 'trial', 0, TRIAL_DAYS, 'trial')
    if not ok:
        if reserved and not is_admin:
            await update_user_fields(callback.from_user.id, trial_used=0, trial_until=None, access_until=None, access_active=0)
        await callback.message.answer('❌ Не удалось выдать пробный период. Подробная причина уже отправлена в лог.', reply_markup=main_menu_keyboard(is_admin=is_admin))




@router.callback_query(F.data == 'happ:open')
async def cb_happ_open(callback: CallbackQuery):
    await callback.answer()
    data = HAPP_ACTION_CACHE.get(callback.from_user.id) or {}
    link = str(data.get('happ_link') or '').strip()
    if not link:
        subs = await get_latest_active_subscription(callback.from_user.id)
        if subs:
            first = subs[0] if isinstance(subs[0], dict) else dict(subs[0])
            link = _happ_redirect_url_from_link(row_value(first, 'happ_crypto_link')) or ''
            if not link:
                link = await _build_happ_redirect_link(row_value(first, 'subscription_url')) or ''
            if not link:
                link = _happ_redirect_url_from_link(row_value(first, 'subscription_url')) or ''
    if not link:
        await callback.message.answer('Ссылка Happ сейчас недоступна. Откройте инструкцию или попробуйте ещё раз.')
        return

    await callback.message.answer(
        (
            '📲 <b>Открыть в Happ</b>\n\n'
            'Нажмите кнопку ниже — Happ должен открыться автоматически и импортировать подписку.\n'
            'Если автопереход не сработал, скопируйте ключ, который выдала подписка, и вставьте его вручную в Happ.'
        ),
        parse_mode='HTML',
        reply_markup=happ_keys_keyboard(link),
    )

@router.callback_query(F.data == 'menu:tariffs')
async def cb_tariffs(callback: CallbackQuery):
    await callback.answer()
    user = await get_user(callback.from_user.id)
    prices, promo_code, discount = await get_user_prices(user)
    text = 'Выберите тариф 👇'
    if promo_code and discount > 0:
        text += f"\n\n🎟 Активен промокод {promo_code} со скидкой {discount}% — цены уже пересчитаны."
    await callback.message.answer(text, reply_markup=tariffs_keyboard(prices))


@router.callback_query(F.data == 'tariff:renew_menu')
async def cb_renew_menu(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer('Выберите, что нужно продлить:', reply_markup=renew_menu_keyboard())


@router.callback_query(F.data.startswith('tariff:'))
async def cb_tariff_detail(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    code = callback.data.split(':', 1)[1]
    user = await get_user(callback.from_user.id)
    prices, promo_code, discount = await get_user_prices(user)
    if code == 'extend':
        await state.clear()
        subs = _extend_candidates(await get_user_subscriptions(callback.from_user.id))
        if not subs:
            await callback.message.answer('У вас нет активных ключей для продления. Пробную подписку продлить нельзя.', reply_markup=renew_menu_keyboard())
            return
        if len(subs) == 1:
            slot = int(row_value(subs[0], 'slot', default=0) or 0)
            await state.set_state(ExtendForm.waiting_for_target)
            await state.update_data(extend_slot=slot)
            await callback.message.answer(
                f'Выберите срок продления для {subscription_entry_title(subs[0])}:',
                reply_markup=_extend_days_keyboard(slot),
            )
            return
        options = [(int(row_value(sub, 'slot', default=0) or 0), f'{subscription_entry_title(sub)} · {subscription_display_name(sub)}') for sub in subs]
        await state.set_state(ExtendForm.waiting_for_target)
        await callback.message.answer('Выберите, какой ключ продлить:', reply_markup=_extend_target_keyboard(options))
        return
    if code not in TARIFFS:
        await callback.message.answer('Тариф не найден.', reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(callback.from_user.id)))
        return
    if code == 'refill':
        await state.clear()
        await state.set_state(RefillForm.waiting_for_gb)
        await callback.message.answer(
            'Введите целое число ГБ, которое нужно добавить.\n\n1 ГБ = 3 ₽.\nПосле выбора подписки бот пересчитает стоимость и предложит покупку.',
            reply_markup=refill_prompt_keyboard(),
        )
        return
    final_amount = prices.get(code, TARIFFS[code]['amount'])
    text = f"💳 Тариф: {TARIFFS[code]['title']}\n\nЦена: {final_amount} ₽\nСрок: {TARIFFS[code]['days']} дней"
    if promo_code and discount > 0:
        text += f"\n\n🎟 Промокод: {promo_code}\nСкидка: {discount}%"
    await callback.message.answer(text, reply_markup=tariff_choice_keyboard(code))


@router.message(RefillForm.waiting_for_gb)
async def refill_amount_handler(message: Message, state: FSMContext):
    raw = (message.text or '').strip()
    if not raw.isdigit():
        await message.answer('Введите целое число ГБ.')
        return
    gb = int(raw)
    if gb <= 0:
        await message.answer('Введите число больше 0.')
        return
    amount = gb * 3
    user_subs = await get_user_subscriptions(message.from_user.id)
    candidates = _refill_candidates(user_subs)
    if not candidates:
        await state.clear()
        await message.answer('У вас нет активных ключей для покупки гб. В Пробную подписку купить гб нельзя.', reply_markup=tariffs_keyboard())
        return
    await state.update_data(refill_gb=gb, refill_amount=amount)
    if len(candidates) == 1:
        slot = int(row_value(candidates[0], 'slot', default=0) or 0)
        await state.update_data(refill_slot=slot)
        await message.answer(
            f'Докупка {gb} ГБ будет стоить {amount} ₽.\nПодтвердите покупку или отмените.',
            reply_markup=refill_confirm_keyboard(gb, amount, slot),
        )
        return
    options = []
    for sub in candidates:
        slot = int(row_value(sub, 'slot', default=0) or 0)
        title = subscription_display_name(sub)
        limit = bytes_to_text(subscription_limit_bytes(sub))
        options.append((slot, f'{title} ({limit})'))
    await state.set_state(RefillForm.waiting_for_target)
    await message.answer(
        f'Найдено несколько активных подписок. Выберите, к какой добавить {gb} ГБ за {amount} ₽:',
        reply_markup=refill_target_keyboard(options, gb, amount),
    )


@router.callback_query(F.data == 'refill:cancel')
async def refill_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer('Отменено')
    await state.clear()
    user = await get_user(callback.from_user.id)
    prices, _, _ = await get_user_prices(user)
    await callback.message.answer('Докупка трафика отменена.', reply_markup=tariffs_keyboard(prices))


@router.callback_query(F.data == 'extend:cancel')
async def extend_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer('Отменено')
    await state.clear()
    user = await get_user(callback.from_user.id)
    prices, _, _ = await get_user_prices(user)
    await callback.message.answer('Продление отменено.', reply_markup=tariffs_keyboard(prices))


@router.callback_query(F.data.startswith('extend:target:'))
async def extend_target(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    parts = callback.data.split(':')
    if len(parts) < 3 or not parts[2].isdigit():
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=tariffs_keyboard())
        return
    slot = int(parts[2])
    user = await get_user(callback.from_user.id)
    prices, _, _ = await get_user_prices(user)
    subs = _extend_candidates(await get_user_subscriptions(callback.from_user.id))
    sub = next((s for s in subs if int(row_value(s, 'slot', default=0) or 0) == slot), None)
    if not sub:
        await callback.message.answer('Ключ не найден или не подходит для продления.', reply_markup=tariffs_keyboard(prices))
        return
    await state.set_state(ExtendForm.waiting_for_days)
    await state.update_data(extend_slot=slot)
    await callback.message.answer(
        f'Выберите срок продления для {subscription_entry_title(sub)}:',
        reply_markup=_extend_days_keyboard(slot),
    )


@router.callback_query(F.data.startswith('extend:days:'))
async def extend_days(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    parts = callback.data.split(':')
    if len(parts) < 4 or not parts[2].isdigit() or not parts[3].isdigit():
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=tariffs_keyboard())
        return
    slot = int(parts[2])
    days = int(parts[3])
    if days not in EXTEND_DAY_OPTIONS:
        await callback.message.answer('Некорректный срок продления.', reply_markup=tariffs_keyboard())
        return
    user = await get_user(callback.from_user.id)
    prices, _, _ = await get_user_prices(user)
    base_price = int(prices.get('1m', TARIFFS['1m']['amount']))
    amount = max(1, round(base_price * days / 30))
    await state.update_data(extend_slot=slot, extend_days=days, extend_amount=amount)
    await state.set_state(ExtendForm.waiting_for_days)
    await callback.message.answer(
        f'Продлить ключ на {days} дн. за {amount} ₽?',
        reply_markup=_extend_confirm_keyboard(slot, days, amount),
    )


@router.callback_query(F.data.startswith('extend:confirm:'))
async def extend_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    parts = callback.data.split(':')
    if len(parts) < 5 or not parts[2].isdigit() or not parts[3].isdigit() or not parts[4].isdigit():
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=tariffs_keyboard())
        return
    slot = int(parts[2])
    days = int(parts[3])
    amount = int(parts[4])
    user = await get_user(callback.from_user.id)
    balance = float(row_value(user, 'payment_balance', default=0.0) or 0.0) if user else 0.0
    if balance < amount:
        await callback.message.answer(
            f'Недостаточно средств. Нужно {amount} ₽, на балансе {money(balance)} ₽.',
            reply_markup=insufficient_funds_keyboard(),
        )
        return
    sub = await get_remnawave_subscription_by_user_slot(callback.from_user.id, slot)
    if not sub or str(row_value(sub, 'kind') or '') == 'trial':
        await callback.message.answer('Продление доступно только для платных ключей.', reply_markup=tariffs_keyboard())
        return
    await adjust_user_balance(callback.from_user.id, 'payment_balance', -amount)
    ok = await _create_internal_order_and_deliver(
        callback.message.bot,
        callback.from_user.id,
        'extend',
        amount,
        days,
        'extend',
        extend_slot=slot,
    )
    await state.clear()
    if ok:
        await clear_user_promo(callback.from_user.id)
    else:
        await callback.message.answer('❌ Не удалось продлить ключ. Подробности уже отправлены админу.', reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(callback.from_user.id)))


@router.callback_query(F.data == 'menu:promo')
async def menu_promo(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user = await get_user(callback.from_user.id)
    current_code = str(row_value(user, 'promo_code') or '').strip().upper() if user else ''
    current_discount = int(row_value(user, 'promo_discount', default=0) or 0) if user else 0
    text = '🎟 Введите промокод одной строкой.\nПосле применения скидка автоматически отразится на тарифах.'
    if current_code and current_discount > 0:
        text += f'\n\nТекущий промокод: {current_code} ({current_discount}%)'
    await state.set_state(PromoForm.waiting_for_promo)
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='menu:home')]]))


@router.message(PromoForm.waiting_for_promo)
async def promo_code_handler(message: Message, state: FSMContext):
    code = (message.text or '').strip().upper()
    if not code:
        await message.answer('Введите промокод или нажмите «Отмена».')
        return

    row = await get_promo_code_row(code)
    user = await get_user(message.from_user.id)
    promo = await get_promo_definition(code)
    if not promo:
        await message.answer('Промокод не найден или уже неактивен.', reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(message.from_user.id)))
        return
    promo_code, discount, single_use = promo
    if single_use and await has_promo_redemption(message.from_user.id, promo_code):
        await message.answer('Этот одноразовый промокод уже использован на вашем аккаунте.', reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(message.from_user.id)))
        await state.clear()
        return
    await set_user_promo(message.from_user.id, promo_code, discount)
    if single_use:
        await mark_promo_redemption(message.from_user.id, promo_code)
    await state.clear()
    user = await get_user(message.from_user.id)
    prices, _, _ = await get_user_prices(user)
    await message.answer(
        f'✅ Промокод {promo_code} применён. Скидка {discount}% активна. Тарифы уже пересчитаны.',
        reply_markup=tariffs_keyboard(prices),
    )

@router.callback_query(F.data.startswith('refill:target:'))
async def refill_target(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    parts = callback.data.split(':')
    if len(parts) < 5 or not parts[2].isdigit() or not parts[3].isdigit() or not parts[4].isdigit():
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=tariffs_keyboard())
        return
    slot = int(parts[2])
    gb = int(parts[3])
    amount = int(parts[4])
    await state.update_data(refill_slot=slot, refill_gb=gb, refill_amount=amount)
    await callback.message.answer(
        f'Докупка {gb} ГБ будет стоить {amount} ₽.\nПодтвердите покупку или отмените.',
        reply_markup=refill_confirm_keyboard(gb, amount, slot),
    )


@router.callback_query(F.data.startswith('refill:confirm:'))
async def refill_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    gb = int(data.get('refill_gb') or 0)
    amount = int(data.get('refill_amount') or 0)
    slot = int(data.get('refill_slot') or 0)
    parts = callback.data.split(':')
    if len(parts) >= 5 and parts[2].isdigit() and parts[3].isdigit() and parts[4].isdigit():
        slot = int(parts[2])
        gb = int(parts[3])
        amount = int(parts[4])
    if gb <= 0 or amount <= 0:
        await state.clear()
        await callback.message.answer('Не удалось определить параметры докупки.', reply_markup=tariffs_keyboard())
        return
    user = await get_user(callback.from_user.id)
    balance = float(row_value(user, 'payment_balance', default=0.0) or 0.0) if user else 0.0
    if balance < amount:
        await state.clear()
        await callback.message.answer(
            f'Недостаточно средств. Нужно {amount} ₽, на балансе {money(balance)} ₽.',
            reply_markup=insufficient_funds_keyboard(),
        )
        return
    await adjust_user_balance(callback.from_user.id, 'payment_balance', -amount)
    ok = await _create_internal_order_and_deliver(
        callback.message.bot,
        callback.from_user.id,
        'refill',
        amount,
        MOBILE_REFILL_DAYS,
        'refill',
        refill_gb=gb,
        refill_slot=slot or None,
    )
    await state.clear()
    if ok:
        await clear_user_promo(callback.from_user.id)
    else:
        await callback.message.answer('❌ Не удалось оформить докупку трафика. Подробности уже отправлены админу.', reply_markup=tariffs_keyboard())


@router.callback_query(F.data.startswith('buy:new:'))
async def buy_new_choice(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    code = callback.data.split(':', 2)[2]
    if code not in TARIFFS:
        return
    await state.clear()
    await state.set_state(PurchaseForm.waiting_for_label)
    await state.update_data(buy_choice='new', buy_code=code)
    await callback.message.answer(
        f'Введите название для новой подписки "{TARIFFS[code]["title"]}".\nМожно написать любое удобное имя или нажать «Пропустить».',
        reply_markup=purchase_label_keyboard(),
    )


@router.callback_query(F.data == 'buy:label_skip')
async def buy_label_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    code = str(data.get('buy_code') or '')
    if code not in TARIFFS:
        await state.clear()
        return
    next_slot = await get_next_subscription_slot(callback.from_user.id)
    await state.update_data(subscription_name=f'Ключ {next_slot}')
    await callback.message.answer(
        f'Подтвердите покупку новой подписки: {TARIFFS[code]["title"]}.',
        reply_markup=purchase_confirm_keyboard(code, 'new'),
    )


@router.callback_query(F.data == 'buy:label_cancel')
async def buy_label_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer('Отменено')
    await state.clear()
    await clear_user_promo(callback.from_user.id)
    user = await get_user(callback.from_user.id)
    prices, _, _ = await get_user_prices(user)
    await callback.message.answer('Покупка отменена.', reply_markup=tariffs_keyboard(prices))


@router.message(PurchaseForm.waiting_for_label)
async def buy_label_message(message: Message, state: FSMContext):
    raw = (message.text or '').strip()
    if not raw:
        await message.answer('Введите название подписки или нажмите «Пропустить».', reply_markup=purchase_label_keyboard())
        return
    if raw.lower() in {'пропустить', 'skip'}:
        data = await state.get_data()
        code = str(data.get('buy_code') or '')
        if code not in TARIFFS:
            await state.clear()
            await message.answer('Тариф не найден.', reply_markup=tariffs_keyboard())
            return
        next_slot = await get_next_subscription_slot(message.from_user.id)
        await state.update_data(subscription_name=f'Ключ {next_slot}')
        await message.answer(
            f'Подтвердите покупку новой подписки: {TARIFFS[code]["title"]}.',
            reply_markup=purchase_confirm_keyboard(code, 'new'),
        )
        return
    data = await state.get_data()
    code = str(data.get('buy_code') or '')
    if code not in TARIFFS:
        await state.clear()
        await message.answer('Тариф не найден.', reply_markup=tariffs_keyboard())
        return
    await state.update_data(subscription_name=raw)
    await message.answer(
        f'Подтвердите покупку новой подписки: {TARIFFS[code]["title"]}.\nНазвание: {raw}',
        reply_markup=purchase_confirm_keyboard(code, 'new'),
    )


@router.callback_query(F.data.startswith('buy:renew:'))
async def buy_renew_choice(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    code = callback.data.split(':', 2)[2]
    if code not in TARIFFS:
        return
    target = _pick_latest_subscription(_extend_candidates(await get_user_subscriptions(callback.from_user.id)))
    if not target:
        await callback.message.answer('У вас нет активных ключей для продления.', reply_markup=renew_menu_keyboard())
        return
    await state.update_data(extend_slot=int(row_value(target, 'slot', default=0) or 0))
    await callback.message.answer(
        f'Подтвердите продление старой подписки: {TARIFFS[code]["title"]}.',
        reply_markup=purchase_confirm_keyboard(code, 'renew'),
    )


@router.callback_query(F.data.startswith('buy:confirm:'))
async def buy_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    _, _, choice, code = callback.data.split(':', 3)
    user = await get_user(callback.from_user.id)
    if code not in TARIFFS:
        await callback.message.answer('Тариф не найден.', reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(callback.from_user.id)))
        return
    prices, _, _ = await get_user_prices(user)
    amount = int(prices.get(code, TARIFFS[code]['amount']))
    balance = float(row_value(user, 'payment_balance', default=0.0) or 0.0)
    if balance < amount:
        await callback.message.answer(
            f'Недостаточно средств. Нужно {amount} ₽, на балансе {money(balance)} ₽.',
            reply_markup=insufficient_funds_keyboard(),
        )
        return
    await adjust_user_balance(callback.from_user.id, 'payment_balance', -amount)
    data = await state.get_data()
    subscription_name = str(data.get('subscription_name') or '').strip() if choice == 'new' else None
    extend_slot = int(data.get('extend_slot') or 0) if choice == 'renew' else None
    order_kind = 'extend' if choice == 'renew' else 'balance_new'
    try:
        ok = await _create_internal_order_and_deliver(
            callback.message.bot,
            callback.from_user.id,
            code,
            amount,
            TARIFFS[code]['days'],
            order_kind,
            subscription_name=subscription_name or None,
            extend_slot=extend_slot,
        )
    except Exception as exc:
        await adjust_user_balance(callback.from_user.id, 'payment_balance', amount)
        await _send_admin_traceback(callback.message.bot, 'Ошибка оформления покупки', exc, context=f'tg_id={callback.from_user.id}, code={code}, amount={amount}, kind={order_kind}')
        await state.clear()
        await callback.message.answer('❌ Не удалось оформить покупку. Баланс возвращён, попробуйте ещё раз.', reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(callback.from_user.id)))
        return
    await state.clear()
    if ok:
        await clear_user_promo(callback.from_user.id)
    else:
        await adjust_user_balance(callback.from_user.id, 'payment_balance', amount)
        await callback.message.answer('❌ Не удалось оформить покупку. Баланс возвращён, попробуйте ещё раз.', reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(callback.from_user.id)))


@router.callback_query(F.data.startswith('buy:cancel:'))
async def buy_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer('Отменено')
    await state.clear()
    await clear_user_promo(callback.from_user.id)
    user = await get_user(callback.from_user.id)
    prices, _, _ = await get_user_prices(user)
    await callback.message.answer('Покупка отменена.', reply_markup=tariffs_keyboard(prices))


@router.callback_query(F.data.startswith('paycheck:'))
async def cb_check_payment(callback: CallbackQuery):
    await callback.answer()
    payment_id = callback.data.split(':', 1)[1]
    order = await get_payment_order(payment_id)
    if not order:
        await callback.message.answer('Платёж не найден.', reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(callback.from_user.id)))
        return
    status = await get_payment_status(payment_id)
    if int(row_value(order, 'remnawave_done', default=0) or 0) == 1:
        await callback.message.answer('Платёж уже обработан и доступ выдан.')
        return
    if status == 'succeeded':
        await callback.message.answer('Платёж уже оплачен, выдаю доступ…')
        await deliver_paid_order(order, callback.message.bot)
    elif status in {'canceled', 'expired'}:
        await mark_payment_status(payment_id, status, remnawave_done=0)
        await clear_user_promo(callback.from_user.id)
        await callback.message.answer('Платёж не найден в статусе оплаты или уже завершён.')
    else:
        await callback.message.answer(payment_status_text(status))


@router.callback_query(F.data == 'menu:status')
@router.message(Command('profile'))
async def cmd_profile(callback_or_message):
    if isinstance(callback_or_message, CallbackQuery):
        await callback_or_message.answer()
        user = await get_user(callback_or_message.from_user.id)
        message = callback_or_message.message
    else:
        user = await get_user(callback_or_message.from_user.id)
        message = callback_or_message
    if user is None:
        await message.answer('Профиль не найден.', reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(callback_or_message.from_user.id)))
        return
    await _sync_user_subscription_snapshots(user['tg_id'])
    subscriptions = _active_subscriptions(await get_user_subscriptions(user['tg_id']))
    referral_count = await get_referral_count(user['tg_id'])
    access_until = row_value(user, 'access_until')
    if not access_until and subscriptions:
        access_until = max((row_value(sub, 'expire_at') for sub in subscriptions if row_value(sub, 'expire_at')), default=None)
    text_lines = [
        '📊 Мой профиль',
        '',
        f'👤 Username: @{row_value(user, "username") or "—"}',
        f'🆔 Telegram ID: {row_value(user, "tg_id")}',
        f'💰 Баланс оплаты: {money(row_value(user, "payment_balance", default=0.0) or 0.0)} ₽',
        f'🎁 Реферальный баланс: {money(row_value(user, "referral_balance", default=0.0) or 0.0)} ₽',
        f'👥 Рефералов: {referral_count}',
        f'⭐ Партнёр: {"Да" if int(row_value(user, "is_partner", default=0) or 0) == 1 else "Нет"}',
        f'📱 Подключённые ключи: {len(subscriptions)}',
    ]
    reset_status = await monthly_reset_status_text()
    text_lines.append(reset_status)
    if subscriptions:
        text_lines.extend(['', *profile_subscription_lines(subscriptions)])
    else:
        text_lines.extend(['', 'Ключей пока нет.'])
    text = '\n'.join(text_lines)
    await message.answer(text, reply_markup=profile_keyboard(is_admin=await _is_admin_user(callback_or_message.from_user.id)))

@router.callback_query(F.data == 'profile:keys')
async def profile_keys(callback: CallbackQuery):
    await callback.answer()
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.message.answer('Профиль не найден.')
        return
    await _sync_user_subscription_snapshots(user['tg_id'])
    subscriptions = _active_subscriptions(await get_user_subscriptions(user['tg_id']))
    is_admin = await _is_admin_user(callback.from_user.id)
    if not subscriptions:
        await callback.message.answer('Пока нет активных ключей.', reply_markup=profile_keys_keyboard(is_admin=is_admin))
        return
    buttons = []
    for idx, sub in enumerate(subscriptions, start=1):
        slot = int(row_value(sub, 'slot', default=0) or 0)
        buttons.append((subscription_button_label(sub, idx), f'profile:key:{slot}'))
    await callback.message.answer('🔑 Выберите ключ:', reply_markup=profile_keys_list_keyboard(buttons, is_admin=is_admin))


@router.callback_query(F.data.startswith('profile:key:'))
async def profile_key_detail(callback: CallbackQuery):
    await callback.answer()
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.message.answer('Профиль не найден.')
        return
    parts = callback_parts(callback)
    if len(parts) < 3 or not parts[2].isdigit():
        await callback.message.answer('Ключ не найден.', reply_markup=profile_keys_keyboard(is_admin=await _is_admin_user(callback.from_user.id)))
        return
    slot = int(parts[2])
    sub = await get_remnawave_subscription_by_user_slot(user['tg_id'], slot)
    if not sub:
        await callback.message.answer('Ключ не найден.', reply_markup=profile_keys_keyboard(is_admin=await _is_admin_user(callback.from_user.id)))
        return
    open_url = await _build_happ_redirect_link(row_value(sub, 'subscription_url'))
    if not open_url:
        open_url = _happ_redirect_url_from_link(row_value(sub, 'subscription_url')) or str(row_value(sub, 'subscription_url') or '').strip() or None
    lines = [
        '🔑 Карточка ключа',
        '',
        f'Название: {subscription_display_name(sub)}',
        f'Ключ: {subscription_entry_title(sub)}',
        f'Трафик: {_subscription_usage_text(sub)}',
        f'Лимит: {bytes_to_text(subscription_limit_bytes(sub))}',
        f'Сброс: {traffic_strategy_label(row_value(sub, "traffic_limit_strategy"), row_value(sub, "traffic_limit_bytes"))}',
        f'Действует до: {format_russian_dt(row_value(sub, "expire_at"))}',
        f'Осталось: {human_timedelta(row_value(sub, "expire_at"))}',
        await monthly_reset_status_text(),
    ]
    await callback.message.answer(
        '\n'.join(lines),
        reply_markup=profile_key_detail_keyboard(open_url, is_admin=await _is_admin_user(callback.from_user.id)),
    )


@router.callback_query(F.data == 'profile:transfer')
async def profile_transfer(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.message.answer('Профиль не найден.')
        return
    ref_balance = float(row_value(user, 'referral_balance', default=0.0) or 0.0)
    if ref_balance <= 0:
        await callback.message.answer('На реферальном балансе пока нет средств.', reply_markup=profile_keyboard(is_admin=await _is_admin_user(callback.from_user.id)))
        return
    await state.set_state(ProfileForm.waiting_for_transfer_amount)
    await callback.message.answer(
        f'Введите сумму для перевода на баланс оплаты.\nДоступно: {money(ref_balance)} ₽',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='profile:transfer_cancel')]]),
    )

@router.callback_query(F.data == 'profile:transfer_cancel')
async def profile_transfer_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer('Отменено')
    await state.clear()
    await callback.message.answer('Перевод отменён.', reply_markup=profile_keyboard(is_admin=await _is_admin_user(callback.from_user.id)))


@router.message(ProfileForm.waiting_for_transfer_amount)
async def profile_transfer_amount(message: Message, state: FSMContext):
    raw = (message.text or '').strip().replace(',', '.')
    try:
        amount = float(raw)
    except ValueError:
        await message.answer('Введите сумму числом.')
        return
    if amount < 50:
        await message.answer('Минимальная сумма пополнения — 50 ₽.')
        return
    user = await get_user(message.from_user.id)
    if not user:
        await state.clear()
        await message.answer('Профиль не найден.', reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(message.from_user.id)))
        return
    ref_balance = float(row_value(user, 'referral_balance', default=0.0) or 0.0)
    if amount > ref_balance:
        await message.answer(f'Недостаточно средств. Доступно {money(ref_balance)} ₽.')
        return
    moved = await transfer_user_balance(message.from_user.id, 'referral_balance', 'payment_balance', amount)
    if not moved:
        await message.answer('❌ Не удалось перевести средства. Попробуйте ещё раз.')
        return
    refreshed = await get_user(message.from_user.id)
    payment_balance = float(row_value(refreshed, 'payment_balance', default=0.0) or 0.0) if refreshed else 0.0
    referral_balance = float(row_value(refreshed, 'referral_balance', default=0.0) or 0.0) if refreshed else 0.0
    await state.clear()
    await message.answer(
        f'✅ {money(amount)} ₽ переведено на баланс оплаты.\n'
        f'Баланс оплаты: {money(payment_balance)} ₽\n'
        f'Реферальный баланс: {money(referral_balance)} ₽',
        reply_markup=profile_keyboard(is_admin=await _is_admin_user(message.from_user.id)),
    )


@router.callback_query(F.data == 'profile:withdraw')
async def profile_withdraw(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        '✅ Заявка на вывод отправлена.',
        reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(callback.from_user.id)),
    )
    chat_id = settings.support_chat_id or settings.admin_id
    if chat_id:
        try:
            await callback.message.bot.send_message(
                chat_id,
                (
                    '📩 Новое обращение\n\n'
                    f'От: {callback.from_user.first_name or "без имени"}\n'
                    f'Username: @{callback.from_user.username or "—"}\n'
                    f'ID: {callback.from_user.id}\n\n'
                    'Текст:\nХочу вывести средства.'
                ),
            )
        except Exception as exc:
            await _send_admin_traceback(callback.message.bot, 'Ошибка отправки заявки на вывод', exc, context=f'tg_id={callback.from_user.id}')

@router.callback_query(F.data == 'menu:referral')
async def cb_referral(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    me = await bot.get_me()
    user = await get_user(callback.from_user.id)
    is_partner = int(row_value(user, 'is_partner', default=0) or 0) == 1 if user else False
    percent = PARTNER_REF_PERCENT if is_partner else DEFAULT_REF_PERCENT
    ref_link = f'https://t.me/{me.username}?start={callback.from_user.id}'
    referral_balance = float(row_value(user, 'referral_balance', default=0.0) or 0.0) if user else 0.0
    text = (
        '🎟 Реферальная программа\n\n'
        f'Приглашайте друзей и зарабатывайте <b>{percent}%</b> с их оплат.\n'
        f'Ваша реферальная ссылка:\n{html.escape(ref_link)}\n\n'
        f'👥 Рефералов: {await get_referral_count(callback.from_user.id)}\n'
        f'🎁 Реферальный баланс: {money(referral_balance)} ₽\n'
        'Реферальный баланс можно переводить на баланс оплаты и выводить на вашу банковскую карту от 500 рублей.'
    )
    await callback.message.answer(text, parse_mode='HTML', reply_markup=referral_keyboard(is_admin=await _is_admin_user(callback.from_user.id)))


@router.message(Command('invite'))
async def cmd_invite(message: Message, bot: Bot):
    user = await get_user(message.from_user.id)
    me = await bot.get_me()
    is_partner = int(row_value(user, 'is_partner', default=0) or 0) == 1 if user else False
    percent = PARTNER_REF_PERCENT if is_partner else DEFAULT_REF_PERCENT
    ref_link = f'https://t.me/{me.username}?start={message.from_user.id}'
    referral_balance = float(row_value(user, 'referral_balance', default=0.0) or 0.0) if user else 0.0
    text = (
        '🎟 Реферальная программа\n\n'
        f'Приглашайте друзей и зарабатывайте <b>{percent}%</b> с их оплат.\n'
        f'Ваша реферальная ссылка:\n{html.escape(ref_link)}\n\n'
        f'👥 Рефералов: {await get_referral_count(message.from_user.id)}\n'
        f'🎁 Реферальный баланс: {money(referral_balance)} ₽\n'
        'Реферальный баланс можно переводить на баланс оплаты и выводить на вашу банковскую карту от 500 рублей.'
    )
    await message.answer(text, parse_mode='HTML', reply_markup=referral_keyboard(is_admin=await _is_admin_user(message.from_user.id)))


@router.callback_query(F.data == 'menu:earnings')
async def cb_earnings(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer_photo(
        FSInputFile(EARNINGS_IMAGE_PATH),
        reply_markup=earnings_keyboard(is_admin=await _is_admin_user(callback.from_user.id)),
    )



@router.callback_query(F.data == 'menu:documentation')
async def cb_documentation(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer('📚 Документация', reply_markup=documentation_keyboard())


@router.callback_query(F.data.in_({'menu:privacy', 'menu:rules', 'menu:offer'}))
async def cb_info_pages(callback: CallbackQuery):
    await callback.answer()
    if callback.data == 'menu:privacy':
        await callback.message.answer(privacy_text(), parse_mode='HTML', reply_markup=documentation_keyboard())
    elif callback.data == 'menu:rules':
        await callback.message.answer(rules_text(), parse_mode='HTML', reply_markup=documentation_keyboard())
    elif callback.data == 'menu:offer':
        await callback.message.answer(offer_text(), parse_mode='HTML', reply_markup=documentation_keyboard())


@router.callback_query(F.data == 'menu:support')
@router.message(Command('support'))
async def open_support(callback_or_message, state: FSMContext):
    if isinstance(callback_or_message, CallbackQuery):
        await callback_or_message.answer()
        message = callback_or_message.message
    else:
        message = callback_or_message
    await state.set_state(SupportForm.waiting_for_message)
    await message.answer('🆘 Напишите ваше сообщение в поддержку.\nМожно отправить текст, фото или файл.', reply_markup=support_keyboard())


@router.callback_query(F.data == 'support:cancel')
async def cb_support_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer('Отменено')
    await state.clear()
    await callback.message.answer('Обращение отменено.', reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(callback.from_user.id)))


@router.message(SupportForm.waiting_for_message)
async def support_send(message: Message, state: FSMContext, bot: Bot):
    chat_id = settings.support_chat_id or settings.admin_id
    if chat_id == 0:
        await message.answer('Поддержка пока не настроена.', reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(message.from_user.id)))
        return
    username = f"@{message.from_user.username}" if message.from_user.username else 'нет username'
    first_name = message.from_user.first_name or 'без имени'
    header = f"📩 Новое обращение\n\nОт: {first_name}\nUsername: {username}\nID: {message.from_user.id}\n\nОтветить можно через Reply"
    try:
        header_msg = await bot.send_message(chat_id=chat_id, text=header)
        await save_support_links([header_msg.message_id], message.from_user.id)
        if message.text:
            copied = await bot.send_message(chat_id=chat_id, text=f'Текст:\n{message.text}', reply_to_message_id=header_msg.message_id)
        else:
            copied = await bot.copy_message(chat_id=chat_id, from_chat_id=message.chat.id, message_id=message.message_id, reply_to_message_id=header_msg.message_id)
        await save_support_links([copied.message_id], message.from_user.id)
        await message.answer('✅ Сообщение отправлено в поддержку.', reply_markup=support_keyboard())
    except Exception as e:
        await message.answer(f'Ошибка отправки: {e}', reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(message.from_user.id)))


@router.message(StateFilter('*'), F.chat.id == settings.support_chat_id)
async def support_reply(message: Message, bot: Bot):
    if message.reply_to_message is None:
        return
    user_tg_id = await get_user_id_by_support_message(message.reply_to_message.message_id)
    if user_tg_id is None:
        return
    if message.text:
        await bot.send_message(chat_id=user_tg_id, text=f'Ответ поддержки:\n\n{message.text}')
    else:
        await bot.copy_message(chat_id=user_tg_id, from_chat_id=message.chat.id, message_id=message.message_id)


@router.callback_query(F.data == 'menu:topup')
async def cb_topup(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminForm.waiting_for_amount)
    await state.update_data(admin_action='topup_self')
    await callback.message.answer(
        'Введите сумму пополнения в рублях.\nМинимум для пополнения — 50 ₽.\nПосле оплаты деньги зачислятся на баланс оплаты.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='topup:cancel')]]),
    )


@router.message(StateFilter('*'), F.text == 'Отмена')
async def cancel_from_text(message: Message, state: FSMContext):
    current_state = await state.get_state()
    is_admin_flow = bool(current_state and current_state.startswith('AdminForm'))
    await state.clear()
    await message.answer('Действие отменено.', reply_markup=admin_keyboard() if is_admin_flow else main_menu_keyboard(is_admin=await _is_admin_user(message.from_user.id)))


@router.callback_query(F.data == 'topup:cancel')
async def topup_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer('Отменено')
    await state.clear()
    await callback.message.answer('Пополнение отменено.', reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(callback.from_user.id)))


@router.message(AdminForm.waiting_for_amount)
async def admin_amount_handler(message: Message, state: FSMContext):
    raw = (message.text or '').strip()
    if not raw.isdigit():
        await message.answer('Введите целое число рублей.')
        return
    amount = int(raw)
    data = await state.get_data()
    action = str(data.get('admin_action') or '')
    if action == 'topup_self' and amount < 50:
        await message.answer('Минимальная сумма пополнения — 50 ₽.')
        return
    if amount <= 0:
        await message.answer('Сумма должна быть больше 0.')
        return
    if action == 'topup_self':
        try:
            payment_data = await create_payment(message.from_user.id, 'topup', amount, 0)
            await create_payment_order(payment_data['payment_id'], message.from_user.id, 'topup', amount, 0, None, 0, kind='topup', status='pending')
        except Exception as exc:
            await _send_admin_traceback(message.bot, 'Не удалось создать платёж на пополнение', exc, context=f'tg_id={message.from_user.id}, amount={amount}')
            await message.answer('❌ Не удалось создать ссылку на оплату. Попробуйте ещё раз чуть позже.', reply_markup=main_menu_keyboard(is_admin=await _is_admin_user(message.from_user.id)))
            return
        await state.clear()
        await message.answer(
            f'💰 Пополнение на {amount} ₽\n\nПосле оплаты средства будут зачислены на баланс оплаты.',
            reply_markup=balance_topup_keyboard(payment_data['confirmation_url'], payment_data['payment_id']),
        )
        return
    target_id = int(data.get('target_id') or 0)
    if action in {'client_refcount_up', 'partner_refcount_up', 'client_refcount_down', 'partner_refcount_down'}:
        if target_id <= 0:
            await state.clear()
            await message.answer('Клиент не выбран.', reply_markup=admin_keyboard())
            return
        delta = amount if action.endswith('_up') else -amount
        new_value = await adjust_ref_paid_count(target_id, delta)
        await state.clear()
        await message.answer(f'✅ Пользователю {target_id} изменено количество рефералов. Теперь: {new_value}.', reply_markup=admin_keyboard())
        return
    if action == 'simulate_yookassa':
        if target_id <= 0:
            await state.clear()
            await message.answer('Клиент не выбран.', reply_markup=admin_keyboard())
            return
        user = await get_user(target_id)
        if not user:
            await state.clear()
            await message.answer('Пользователь не найден.', reply_markup=admin_keyboard())
            return
        ok = await _create_internal_order_and_deliver(message.bot, target_id, 'sim', amount, 0, 'topup')
        await state.clear()
        if ok:
            await message.answer(f'✅ Симуляция пополнения на {amount} ₽ для {target_id} выполнена.', reply_markup=admin_keyboard())
        else:
            await message.answer('❌ Симуляция оплаты не удалась.', reply_markup=admin_keyboard())
        return
    if target_id <= 0:
        await state.clear()
        await message.answer('Клиент не выбран.', reply_markup=admin_keyboard())
        return
    await state.update_data(amount=amount)
    await state.set_state(AdminForm.waiting_for_confirm)
    if action in {'paybalance_up', 'client_paybalance_up', 'partner_paybalance_up'}:
        text = f'Подтвердите начисление {amount} ₽ на баланс оплаты пользователя {target_id}.'
        confirm_data = 'admin:balance_confirm:up'
    elif action in {'paybalance_down', 'client_paybalance_down', 'partner_paybalance_down'}:
        text = f'Подтвердите списание {amount} ₽ с баланса оплаты пользователя {target_id}.'
        confirm_data = 'admin:balance_confirm:down'
    elif action in {'refbalance_up', 'client_refbalance_up', 'partner_refbalance_up', 'refbonus'}:
        text = f'Подтвердите начисление {amount} ₽ на реферальный баланс пользователя {target_id}.'
        confirm_data = 'admin:refbalance_confirm:up'
    elif action in {'refbalance_down', 'client_refbalance_down', 'partner_refbalance_down'}:
        text = f'Подтвердите списание {amount} ₽ с реферального баланса пользователя {target_id}.'
        confirm_data = 'admin:refbalance_confirm:down'
    else:
        text = f'Подтвердите действие на сумму {amount} ₽ для пользователя {target_id}.'
        confirm_data = 'admin:balance_confirm:up'
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Подтвердить', callback_data=confirm_data)],
        [InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')],
    ])
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == 'admin:cancel')
async def admin_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer('Отменено')
    await state.clear()
    await callback.message.answer('Действие отменено.', reply_markup=admin_keyboard())


@router.callback_query(F.data == 'admin:promos')
async def admin_promos(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    promos = await list_promo_codes(active_only=False)
    promos = [row for row in promos if str(row_value(row, 'promo_type', default='discount') or 'discount').strip().lower() == 'discount']
    if not promos:
        await callback.message.answer('Промокодов пока нет.', reply_markup=promo_admin_keyboard())
        return
    lines = ['🎟 Промокоды:']
    rows = []
    for row in promos:
        code = str(row_value(row, 'code') or '').upper()
        discount = int(row_value(row, 'discount', default=0) or 0)
        active = 'активен' if int(row_value(row, 'is_active', default=1) or 1) == 1 else 'неактивен'
        single_use = 'одноразовый' if promo_single_use_value(row_value(row, 'single_use', default=1), default=True) else 'многоразовый'
        lines.append(f'• {code}: {discount}% · {single_use} · {active}')
        rows.append([InlineKeyboardButton(text=f'⚙️ {code}', callback_data=f'admin:promo_manage:{code}')])
    rows.append([InlineKeyboardButton(text='➕ Добавить промокод', callback_data='admin:promo_add')])
    rows.append([InlineKeyboardButton(text='🏠 Админка', callback_data='admin:panel')])
    await callback.message.answer('\n'.join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith('admin:promo_manage:'))
async def admin_promo_manage(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    code = callback.data.split(':', 2)[2].strip().upper()
    row = await get_promo_code_row(code)
    if not row:
        await callback.message.answer('Промокод не найден.', reply_markup=promo_admin_keyboard())
        return
    promo_type = str(row_value(row, 'promo_type', default='discount') or 'discount').strip().lower()
    if promo_type != 'discount':
        await callback.message.answer('Пробные промокоды отключены.', reply_markup=promo_admin_keyboard())
        return
    active = 'активен' if int(row_value(row, 'is_active', default=1) or 1) == 1 else 'неактивен'
    discount = int(row_value(row, 'discount', default=0) or 0)
    single_use = 'одноразовый' if promo_single_use_value(row_value(row, 'single_use', default=1), default=True) else 'многоразовый'
    text = f'🎟 {code}\nСкидка: {discount}%\nТип: {single_use}\nСтатус: {active}'
    await callback.message.answer(text, reply_markup=promo_manage_keyboard(code, promo_type=promo_type))


@router.callback_query(F.data == 'admin:promo_add')
async def admin_promo_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    await state.clear()
    await state.set_state(PromoAdminForm.waiting_for_code)
    await callback.message.answer('Введите код нового промокода (например FIRST15):', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:panel')]]))


@router.message(PromoAdminForm.waiting_for_code)
async def admin_promo_code_step(message: Message, state: FSMContext):
    if not await _is_admin_user(message.from_user.id):
        return
    code = (message.text or '').strip().upper()
    if not code or ' ' in code:
        await message.answer('Код должен быть одним словом без пробелов.')
        return
    await state.update_data(promo_code=code)
    await state.set_state(PromoAdminForm.waiting_for_discount)
    await message.answer('Введите скидку в процентах, например 15:')


@router.message(PromoAdminForm.waiting_for_discount)
async def admin_promo_discount_step(message: Message, state: FSMContext):
    if not await _is_admin_user(message.from_user.id):
        return
    try:
        discount = int((message.text or '').strip())
    except Exception:
        await message.answer('Введите число от 1 до 99.')
        return
    if not 1 <= discount <= 99:
        await message.answer('Введите число от 1 до 99.')
        return
    await state.update_data(discount=discount)
    await state.set_state(PromoAdminForm.waiting_for_single_use)
    await message.answer('Сделать промокод одноразовым?', reply_markup=promo_single_use_keyboard())


@router.message(PromoAdminForm.waiting_for_single_use)
async def admin_promo_single_use_step(message: Message, state: FSMContext):
    if not await _is_admin_user(message.from_user.id):
        return
    raw = (message.text or '').strip().lower()
    if raw in {'да', 'yes', 'y', '1', 'true', 'одноразовый', 'один'}:
        single_use = True
    elif raw in {'нет', 'no', 'n', '0', 'false', 'многоразовый', 'много'}:
        single_use = False
    else:
        await message.answer('Нажмите кнопку Да или Нет.', reply_markup=promo_single_use_keyboard())
        return
    data = await state.get_data()
    code = str(data.get('promo_code') or '').strip().upper()
    discount = int(data.get('discount') or 0)
    if not code or discount <= 0:
        await state.clear()
        await message.answer('Не удалось создать промокод.', reply_markup=promo_admin_keyboard())
        return
    await upsert_promo_code(code, discount, single_use=single_use, is_active=True, promo_type='discount')
    await state.clear()
    await message.answer(f'✅ Промокод {code} создан: {discount}% · {"одноразовый" if single_use else "многоразовый"}.', reply_markup=promo_admin_keyboard())


@router.callback_query(PromoAdminForm.waiting_for_single_use, F.data.startswith('admin:promo_single_use:'))
async def admin_promo_single_use_choice(callback: CallbackQuery, state: FSMContext):
    if not await _is_admin_user(callback.from_user.id):
        await callback.answer('Нет доступа', show_alert=True)
        return
    await callback.answer()
    parts = callback.data.split(':')
    if len(parts) < 3:
        await callback.message.answer('Некорректный выбор.', reply_markup=promo_admin_keyboard())
        return
    single_use = parts[2] == '1'
    data = await state.get_data()
    code = str(data.get('promo_code') or '').strip().upper()
    discount = int(data.get('discount') or 0)
    if not code or discount <= 0:
        await state.clear()
        await callback.message.answer('Не удалось создать промокод.', reply_markup=promo_admin_keyboard())
        return
    await upsert_promo_code(code, discount, single_use=single_use, is_active=True, promo_type='discount')
    await state.clear()
    await callback.message.answer(f'✅ Промокод {code} создан: {discount}% · {"одноразовый" if single_use else "многоразовый"}.', reply_markup=promo_admin_keyboard())


@router.callback_query(F.data.startswith('admin:promo_broadcast:'))
async def admin_promo_broadcast(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    await callback.message.answer('Пробные промокоды отключены.', reply_markup=promo_admin_keyboard())
    return


@router.message(PromoAdminForm.waiting_for_broadcast_message)
async def admin_promo_broadcast_send(message: Message, state: FSMContext, bot: Bot):
    if not await _is_admin_user(message.from_user.id):
        return
    text = (message.text or '').strip()
    if not text:
        await message.answer('Введите текст сообщения для рассылки.')
        return
    data = await state.get_data()
    code = str(data.get('promo_broadcast_code') or '').strip().upper()
    row = await get_promo_code_row(code)
    if not row or str(row_value(row, 'promo_type', default='discount') or 'discount').strip().lower() != 'discount':
        await state.clear()
        await message.answer('Пробные промокоды отключены.', reply_markup=promo_admin_keyboard())
        return
    await state.update_data(promo_broadcast_message=text)
    await state.set_state(PromoAdminForm.waiting_for_broadcast_confirm)
    preview_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Подтвердить рассылку', callback_data='admin:promo_broadcast_confirm')],
        [InlineKeyboardButton(text='❌ Отмена', callback_data='admin:promo_broadcast_cancel')],
    ])
    await message.answer(
        f'Предпросмотр рассылки для trial-промокода {code}:\n\n{text}',
        reply_markup=preview_kb,
    )


@router.callback_query(PromoAdminForm.waiting_for_broadcast_confirm, F.data == 'admin:promo_broadcast_cancel')
async def admin_promo_broadcast_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer('Отменено')
    await state.clear()
    await callback.message.answer('Рассылка отменена.', reply_markup=promo_admin_keyboard())


@router.callback_query(PromoAdminForm.waiting_for_broadcast_confirm, F.data == 'admin:promo_broadcast_confirm')
async def admin_promo_broadcast_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    data = await state.get_data()
    code = str(data.get('promo_broadcast_code') or '').strip().upper()
    text = str(data.get('promo_broadcast_message') or '').strip()
    row = await get_promo_code_row(code)
    if not text or not row or str(row_value(row, 'promo_type', default='discount') or 'discount').strip().lower() != 'discount':
        await state.clear()
        await callback.message.answer('Пробные промокоды отключены.', reply_markup=promo_admin_keyboard())
        return
    targets = await get_trial_promo_broadcast_targets()
    if not targets:
        await state.clear()
        await callback.message.answer('Не нашёл пользователей, которым подходит эта рассылка.', reply_markup=promo_manage_keyboard(code, promo_type='discount'))
        return
    promo_button = trial_invitation_keyboard()
    sent = 0
    failed = 0
    for user in targets:
        tg_id = int(row_value(user, 'tg_id', default=0) or 0)
        if tg_id <= 0 or tg_id == settings.admin_id:
            continue
        try:
            await callback.message.bot.send_message(tg_id, text, reply_markup=promo_button)
            sent += 1
        except Exception as exc:
            failed += 1
            logger.warning('Trial promo broadcast failed for tg_id=%s: %s', tg_id, exc)
    await state.clear()
    await callback.message.answer(
        f'✅ Рассылка по trial-промокоду {code} завершена. Отправлено: {sent}, ошибок: {failed}.',
        reply_markup=promo_manage_keyboard(code, promo_type='discount'),
    )


@router.callback_query(F.data.startswith('admin:promo_delete:'))
async def admin_promo_delete(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    code = callback.data.split(':', 2)[2].strip().upper()
    await delete_promo_code(code)
    await callback.message.answer(f'🗑 Промокод {code} удалён.', reply_markup=promo_admin_keyboard())


@router.callback_query(F.data == 'admin:panel')

async def admin_panel(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        await callback.message.answer('Доступно только администратору.')
        return
    await callback.message.answer('🛠 Админка', reply_markup=admin_keyboard())


@router.callback_query(F.data == 'admin:create_key')
async def admin_create_key(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    await state.clear()
    await state.set_state(AdminForm.waiting_for_create_key_target)
    await state.update_data(admin_action='create_key')
    await callback.message.answer(
        'Введите Telegram ID клиента, для которого нужно создать ключ:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]),
    )


@router.message(AdminForm.waiting_for_create_key_target)
async def admin_create_key_target(message: Message, state: FSMContext):
    if not await _is_admin_user(message.from_user.id):
        return
    raw = (message.text or '').strip()
    if not raw.isdigit():
        await message.answer('Введите Telegram ID числом.')
        return
    tg_id = int(raw)
    user = await get_user(tg_id)
    if not user:
        await upsert_user(tg_id, None, None, None)
    await state.update_data(target_id=tg_id)
    await state.set_state(AdminForm.waiting_for_create_key_days)
    await message.answer('Введите срок ключа в днях (например 30):')


@router.message(AdminForm.waiting_for_create_key_days)
async def admin_create_key_days(message: Message, state: FSMContext):
    if not await _is_admin_user(message.from_user.id):
        return
    raw = (message.text or '').strip()
    if not raw.isdigit():
        await message.answer('Введите целое число дней.')
        return
    days = int(raw)
    if days <= 0:
        await message.answer('Срок должен быть больше 0.')
        return
    await state.update_data(days=days)
    await state.set_state(AdminForm.waiting_for_create_key_limit)
    await message.answer('Введите лимит Mobile на втором скваде в ГБ (0 = безлимит):')


@router.message(AdminForm.waiting_for_create_key_limit)
async def admin_create_key_limit(message: Message, state: FSMContext):
    if not await _is_admin_user(message.from_user.id):
        return
    raw = (message.text or '').strip()
    if not raw.isdigit():
        await message.answer('Введите целое число ГБ.')
        return
    limit_gb = int(raw)
    data = await state.get_data()
    tg_id = int(data.get('target_id') or 0)
    days = int(data.get('days') or 0)
    if tg_id <= 0 or days <= 0:
        await state.clear()
        await message.answer('Не удалось определить параметры ключа.', reply_markup=admin_keyboard())
        return
    ok = await _create_internal_order_and_deliver(message.bot, tg_id, 'admin_manual', 0, days, 'admin_manual', subscription_name=f'{days} дней', mobile_limit_gb=limit_gb)
    await state.clear()
    if ok:
        await message.answer(f'✅ Ключ создан для {tg_id}: {days} дн., лимит Mobile {limit_gb} ГБ.', reply_markup=admin_keyboard())
    else:
        await message.answer('❌ Не удалось создать ключ. Подробности уже отправлены админу.', reply_markup=admin_keyboard())


@router.callback_query(F.data == 'admin:admins_list:0')
@router.callback_query(F.data.startswith('admin:admins_list:'))
async def admin_admins_list(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    admins = await get_active_admins()
    per_page = 10
    total_pages = max(1, (len(admins) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = admins[page * per_page:(page + 1) * per_page]
    items = []
    for admin in chunk:
        tg_id = int(row_value(admin, 'tg_id'))
        username = row_value(admin, 'username')
        label = f'@{username}' if username else f'ID {tg_id}'
        items.append((tg_id, label))
    await callback.message.answer(f'👮 Активные админы (страница {page + 1}/{total_pages})', reply_markup=admins_list_keyboard(page, total_pages, items))


@router.callback_query(F.data == 'admin:yookassa_simulate')
async def admin_yookassa_simulate(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminForm.waiting_for_target)
    await state.update_data(admin_action='simulate_yookassa')
    await callback.message.answer('Введите Telegram ID клиента, для которого нужно симулировать успешное пополнение:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))


@router.callback_query(F.data == 'admin:partner_on')
async def admin_partner_on(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminForm.waiting_for_target)
    await state.update_data(admin_action='partner_on')
    await callback.message.answer('Введите Telegram ID клиента, которому нужно выдать статус партнёра:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))


@router.callback_query(F.data == 'admin:partner_off')
async def admin_partner_off(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminForm.waiting_for_target)
    await state.update_data(admin_action='partner_off')
    await callback.message.answer('Введите Telegram ID клиента, у которого нужно снять статус партнёра:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))


@router.callback_query(F.data == 'admin:admin_on')
async def admin_admin_on(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminForm.waiting_for_target)
    await state.update_data(admin_action='admin_on')
    await callback.message.answer('Введите Telegram ID клиента, которому нужно выдать статус админа:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))


@router.callback_query(F.data == 'admin:admin_off')
async def admin_admin_off(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminForm.waiting_for_target)
    await state.update_data(admin_action='admin_off')
    await callback.message.answer('Введите Telegram ID клиента, у которого нужно снять статус админа:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))


@router.callback_query(F.data.startswith('admin:partner_on:'))
async def admin_partner_on_selected(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s = parts[2]
    tg_id = int(tg_id_s)
    await set_user_partner(tg_id, True)
    await _reward_partner_for_new_referral(callback.message.bot, tg_id)
    await _ensure_partner_subscription(callback.message.bot, tg_id)
    await _notify_role_change(callback.message.bot, tg_id, is_admin=False, is_partner=True)
    await callback.message.answer(f'✅ Пользователю {tg_id} выдан статус партнёра.', reply_markup=admin_keyboard())

@router.callback_query(F.data.startswith('admin:partner_off:'))
async def admin_partner_off_selected(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s = parts[2]
    tg_id = int(tg_id_s)
    await set_user_partner(tg_id, False)
    await _deactivate_partner_access(callback.message.bot, tg_id)
    await _notify_role_change(callback.message.bot, tg_id, is_admin=False, is_partner=False)
    await callback.message.answer(f'✅ У пользователя {tg_id} снят статус партнёра.', reply_markup=admin_keyboard())

@router.callback_query(F.data.startswith('admin:partner_admin_on:'))
async def admin_partner_admin_on(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s = parts[2]
    tg_id = int(tg_id_s)
    await set_user_admin(tg_id, True)
    await _notify_role_change(callback.message.bot, tg_id, is_admin=True)
    await callback.message.answer(f'✅ Пользователю {tg_id_s} выдан статус админа.', reply_markup=admin_keyboard())

@router.callback_query(F.data.startswith('admin:partner_admin_off:'))
async def admin_partner_admin_off(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s = parts[2]
    if int(tg_id_s) == settings.admin_id:
        await callback.message.answer('Нельзя снять админку с главного администратора.', reply_markup=admin_keyboard())
        return
    tg_id = int(tg_id_s)
    await set_user_admin(tg_id, False)
    await _notify_role_change(callback.message.bot, tg_id, is_admin=False)
    await callback.message.answer(f'✅ У пользователя {tg_id_s} снят статус админа.', reply_markup=admin_keyboard())

@router.callback_query(F.data.startswith('admin:partner_test_refs:'))
async def admin_partner_test_refs(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    partner_id_s, page_s = parts[2], parts[3]
    partner_id = int(partner_id_s)
    created = await _create_test_referrals_for_partner(callback.message.bot, partner_id, 30)
    partner = await get_user(partner_id)
    subs = _active_subscriptions(await get_user_subscriptions(partner_id))
    await callback.message.answer(
        f'🧪 Для партнёра {partner_id} добавлено тестовых рефералов: {created}.\n'
        f'Рефералов в этом месяце: {await get_month_referral_count(partner_id, datetime.now(timezone.utc).strftime("%Y-%m"))}.\n'
        f'Реферальный баланс: {money(row_value(partner, "referral_balance", default=0.0) or 0.0)} ₽',
        reply_markup=partner_detail_keyboard(
            partner_id,
            int(page_s),
            bool(partner and int(row_value(partner, "is_partner", default=0) or 0) == 1),
            bool(partner and int(row_value(partner, "is_admin", default=0) or 0) == 1),
            [int(row_value(sub, "slot", default=0) or 0) for sub in subs],
        ),
    )

@router.callback_query(F.data.startswith('admin:client_sub_disable:'))
async def admin_client_sub_disable(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, page_s = parts[2], parts[3]
    tg_id = int(tg_id_s)
    subs = await get_user_subscriptions(tg_id)
    await _delete_user_subscription_in_remnawave(callback.message.bot, subs)
    await delete_user_subscriptions(tg_id)
    await update_user_fields(tg_id, access_active=0, access_until=None, access_key=None)
    client = await get_user(tg_id)
    subs = _active_subscriptions(await get_user_subscriptions(tg_id))
    await callback.message.answer(
        f'✅ Все подписки пользователя {tg_id} отключены и удалены из Remnawave и БД.',
        reply_markup=client_detail_keyboard(
            tg_id,
            int(page_s),
            bool(client and int(row_value(client, "is_partner", default=0) or 0) == 1),
            bool(client and int(row_value(client, "is_admin", default=0) or 0) == 1),
            [int(row_value(sub, "slot", default=0) or 0) for sub in subs],
        ),
    )

@router.callback_query(F.data.startswith('admin:partner_sub_disable:'))
async def admin_partner_sub_disable(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, page_s = parts[2], parts[3]
    tg_id = int(tg_id_s)
    subs = await get_user_subscriptions(tg_id)
    await _delete_user_subscription_in_remnawave(callback.message.bot, subs)
    await delete_user_subscriptions(tg_id)
    await update_user_fields(tg_id, access_active=0, access_until=None, access_key=None)
    partner = await get_user(tg_id)
    subs = _active_subscriptions(await get_user_subscriptions(tg_id))
    await callback.message.answer(
        f'✅ Все подписки пользователя {tg_id} отключены и удалены из Remnawave и БД.',
        reply_markup=partner_detail_keyboard(
            tg_id,
            int(page_s),
            bool(partner and int(row_value(partner, "is_partner", default=0) or 0) == 1),
            bool(partner and int(row_value(partner, "is_admin", default=0) or 0) == 1),
            [int(row_value(sub, "slot", default=0) or 0) for sub in subs],
        ),
    )


@router.message(AdminForm.waiting_for_target)
async def admin_target_handler(message: Message, state: FSMContext):
    raw = (message.text or '').strip()
    if not raw.isdigit():
        await message.answer('Введите только числовой Telegram ID.')
        return
    target_id = int(raw)
    data = await state.get_data()
    action = str(data.get('admin_action') or '')
    partner_id = int(data.get('partner_id') or data.get('target_id') or 0)
    await state.update_data(target_id=target_id)
    if action in {'partner_on', 'partner_off', 'admin_on', 'admin_off', 'partner_add_ref', 'refcalc', 'refbonus', 'simulate_yookassa', 'client_refcount_up', 'client_refcount_down', 'partner_refcount_up', 'partner_refcount_down'}:
        user = await get_user(target_id)
        if not user:
            await upsert_user(target_id, None, None, None)
            user = await get_user(target_id)
        if action == 'partner_add_ref':
            if partner_id <= 0:
                await state.clear()
                await message.answer('Партнёр не найден.', reply_markup=admin_keyboard())
                return
            await upsert_user(target_id, None, None, partner_id)
            await state.clear()
            await message.answer(f'✅ Реферал {target_id} привязан к партнёру {partner_id}.', reply_markup=admin_keyboard())
            return
        if action == 'refcalc':
            ref_balance = float(row_value(user, 'referral_balance', default=0.0) or 0.0)
            await state.clear()
            await message.answer(f'🎁 Реферальные средства пользователя {target_id}: {money(ref_balance)} ₽', reply_markup=admin_keyboard())
            return
        if action in {'client_refcount_up', 'client_refcount_down', 'partner_refcount_up', 'partner_refcount_down'}:
            await state.update_data(target_id=target_id)
            await state.set_state(AdminForm.waiting_for_amount)
            sign = 'добавить' if action.endswith('_up') else 'убавить'
            await message.answer(f'Введите количество рефералов, которое нужно {sign} пользователю {target_id}:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))
            return
        if action == 'refbonus':
            await state.update_data(target_id=target_id)
            await state.set_state(AdminForm.waiting_for_amount)
            await message.answer('Введите сумму в рублях, которую нужно добавить на реферальный баланс клиента:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))
            return
        if action == 'simulate_yookassa':
            await state.update_data(target_id=target_id)
            await state.set_state(AdminForm.waiting_for_amount)
            await message.answer('Введите сумму симуляции оплаты в рублях:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))
            return
        if action == 'partner_on':
            await set_user_partner(target_id, True)
            await _reward_partner_for_new_referral(message.bot, target_id)
            await _ensure_partner_subscription(message.bot, target_id)
            await _notify_role_change(message.bot, target_id, is_admin=False, is_partner=True)
            await state.clear()
            await message.answer(f'✅ Пользователю {target_id} выдан статус партнёра.', reply_markup=admin_keyboard())
            return
        if action == 'partner_off':
            await set_user_partner(target_id, False)
            await _deactivate_partner_access(message.bot, target_id)
            await _notify_role_change(message.bot, target_id, is_admin=False, is_partner=False)
            await state.clear()
            await message.answer(f'✅ У пользователя {target_id} снят статус партнёра.', reply_markup=admin_keyboard())
            return
        if action == 'admin_on':
            await set_user_admin(target_id, True)
            await _notify_role_change(message.bot, target_id, is_admin=True)
            await state.clear()
            await message.answer(f'✅ Пользователю {target_id} выдан статус админа.', reply_markup=admin_keyboard())
            return
        if action == 'admin_off':
            if target_id == settings.admin_id:
                await state.clear()
                await message.answer('Нельзя снять админку с главного администратора.', reply_markup=admin_keyboard())
                return
            await set_user_admin(target_id, False)
            await _notify_role_change(message.bot, target_id, is_admin=False)
            await state.clear()
            await message.answer(f'✅ У пользователя {target_id} снят статус админа.', reply_markup=admin_keyboard())
            return
    await message.answer('Неизвестное действие.')
    await state.clear()


async def _deactivate_partner_access(bot: Bot, tg_id: int) -> None:
    subs = await get_user_subscriptions_by_kind(tg_id, 'partner_grant')
    if not subs:
        return
    for sub in subs:
        try:
            user_uuid = str(row_value(sub, 'user_uuid', default='') or '')
            if user_uuid:
                try:
                    await remnawave.update_user({'uuid': user_uuid, 'status': 'DISABLED'})
                except Exception:
                    pass
        except Exception as exc:
            await _send_admin_traceback(bot, 'Не удалось деактивировать партнёрский ключ', exc, context=f'tg_id={tg_id}\nuser_uuid={row_value(sub, "user_uuid")}' )


async def _reply_with_balance_change(message: Message, target_id: int, field: str, delta: float, note: str) -> None:
    user = await get_user(target_id)
    if not user:
        await message.answer('Пользователь не найден.', reply_markup=admin_keyboard())
        return
    current = float(row_value(user, field, default=0.0) or 0.0)
    if delta < 0 and current < abs(delta):
        await message.answer('❌ Недостаточно средств у пользователя.', reply_markup=admin_keyboard())
        return
    await adjust_user_balance(target_id, field, delta)
    await message.answer(note, reply_markup=admin_keyboard())


@router.callback_query(F.data == 'admin:balance_confirm:up')
async def admin_balance_up_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    target_id = int(data.get('target_id') or 0)
    amount = int(data.get('amount') or 0)
    await _reply_with_balance_change(callback.message, target_id, 'payment_balance', amount, f'✅ На баланс оплаты пользователя {target_id} начислено {amount} ₽.')
    await state.clear()


@router.callback_query(F.data == 'admin:balance_confirm:down')
async def admin_balance_down_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    target_id = int(data.get('target_id') or 0)
    amount = int(data.get('amount') or 0)
    await _reply_with_balance_change(callback.message, target_id, 'payment_balance', -amount, f'✅ У пользователя {target_id} списано {amount} ₽ с баланса оплаты.')
    await state.clear()


@router.callback_query(F.data == 'admin:refbalance_confirm:up')
async def admin_refbalance_up_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    target_id = int(data.get('target_id') or 0)
    amount = int(data.get('amount') or 0)
    await _reply_with_balance_change(callback.message, target_id, 'referral_balance', amount, f'✅ На реферальный баланс пользователя {target_id} начислено {amount} ₽.')
    await state.clear()


@router.callback_query(F.data == 'admin:refbalance_confirm:down')
async def admin_refbalance_down_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    target_id = int(data.get('target_id') or 0)
    amount = int(data.get('amount') or 0)
    await _reply_with_balance_change(callback.message, target_id, 'referral_balance', -amount, f'✅ У пользователя {target_id} списано {amount} ₽ с реферального баланса.')
    await state.clear()


@router.callback_query(F.data == 'admin:clients_list:0')
@router.callback_query(F.data.startswith('admin:clients_list:'))
async def admin_clients_list(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    page = safe_int(parts[-1]) if parts and parts[-1].isdigit() else 0
    clients = await get_all_users()
    per_page = 10
    total_pages = max(1, (len(clients) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = clients[page * per_page:(page + 1) * per_page]
    if not chunk:
        await callback.message.answer('Пользователей нет.', reply_markup=admin_keyboard())
        return
    items = [(int(row_value(client, 'tg_id')), user_list_label(client)) for client in chunk]
    await callback.message.answer(f'📋 Пользователи (страница {page + 1}/{total_pages})', reply_markup=clients_list_keyboard(page, total_pages, items))


@router.callback_query(F.data == 'admin:users_search')
async def admin_users_search(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    await state.clear()
    await state.set_state(AdminForm.waiting_for_user_search)
    await callback.message.answer(
        'Введите Telegram ID, username или часть имени для поиска пользователя:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]),
    )


@router.message(AdminForm.waiting_for_user_search)
async def admin_users_search_result(message: Message, state: FSMContext):
    if not await _is_admin_user(message.from_user.id):
        return
    query = (message.text or '').strip()
    users = await search_users(query, limit=20)
    await state.clear()
    if not users:
        await message.answer('Ничего не найдено.', reply_markup=admin_keyboard())
        return
    items = [(int(row_value(user, 'tg_id')), user_list_label(user)) for user in users]
    await message.answer('🔎 Результаты поиска:', reply_markup=clients_list_keyboard(0, 1, items))


@router.callback_query(F.data.startswith('admin:client:'))
async def admin_client_detail(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, page_s = parts[2], parts[3]
    tg_id = int(tg_id_s)
    page = int(page_s)
    client = await get_user(tg_id)
    if not client:
        await callback.message.answer('Клиент не найден.', reply_markup=admin_keyboard())
        return
    subs = _active_subscriptions(await get_user_subscriptions(tg_id))
    referral_count = await get_referral_count(tg_id)
    is_partner = int(row_value(client, 'is_partner', default=0) or 0) == 1
    is_admin_user = int(row_value(client, 'is_admin', default=0) or 0) == 1
    lines = [
        '👤 Карточка клиента',
        '',
        f'ID: {tg_id}',
        f'Username: @{row_value(client, "username") or "—"}',
        f'Имя: {row_value(client, "first_name") or "—"}',
        f'Партнёр: {"Да" if is_partner else "Нет"}',
        f'Админ: {"Да" if is_admin_user else "Нет"}',
        f'Доступ до: {format_russian_dt(row_value(client, "access_until"))}',
        f'Баланс оплаты: {money(row_value(client, "payment_balance", default=0.0) or 0.0)} ₽',
        f'Реф. баланс: {money(row_value(client, "referral_balance", default=0.0) or 0.0)} ₽',
        f'Рефералов: {referral_count}',
        '',
        'Подписки:',
    ]
    for sub in subs:
        lines.append(subscription_card(sub))
        lines.append('')

    slots = [int(row_value(sub, 'slot', default=0) or 0) for sub in subs]
    await callback.message.answer('\n'.join(lines).rstrip(), reply_markup=client_detail_keyboard(tg_id, page, is_partner, is_admin_user, slots))


@router.callback_query(F.data.startswith('admin:client_reset_limit:'))
async def admin_client_reset_limit(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, page_s = parts[2], parts[3]
    tg_id = int(tg_id_s)
    page = int(page_s)
    subs = _active_subscriptions(await get_user_subscriptions(tg_id))
    if not subs:
        await callback.message.answer('У пользователя нет активных ключей.', reply_markup=admin_keyboard())
        return
    for sub in subs:
        await _reset_single_subscription_traffic(callback.message.bot, sub)
    client = await get_user(tg_id)
    await callback.message.answer(f'✅ Лимит трафика пользователя {tg_id} сброшен.', reply_markup=client_detail_keyboard(
        tg_id,
        page,
        bool(client and int(row_value(client, "is_partner", default=0) or 0) == 1),
        bool(client and int(row_value(client, "is_admin", default=0) or 0) == 1),
        [int(row_value(sub, "slot", default=0) or 0) for sub in subs],
    ))


@router.callback_query(F.data.startswith('admin:partner:'))

async def admin_partner_detail(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, page_s = parts[2], parts[3]
    tg_id = int(tg_id_s)
    page = int(page_s)
    partner = await get_user(tg_id)
    if not partner:
        await callback.message.answer('Партнёр не найден.', reply_markup=admin_keyboard())
        return
    subs = _active_subscriptions(await get_user_subscriptions(tg_id))
    referral_count = await get_referral_count(tg_id)
    is_partner = int(row_value(partner, 'is_partner', default=0) or 0) == 1
    is_admin_user = int(row_value(partner, 'is_admin', default=0) or 0) == 1
    lines = [
        '👑 Активный партнёр',
        '',
        f'ID: {tg_id}',
        f'Username: @{row_value(partner, "username") or "—"}',
        f'Партнёр с: {format_russian_dt(row_value(partner, "partner_since"))}',
        f'Процент: {PARTNER_REF_PERCENT}%',
        f'Рефералов: {referral_count}',
        f'Баланс оплаты: {money(row_value(partner, "payment_balance", default=0.0) or 0.0)} ₽',
        f'Реф. баланс: {money(row_value(partner, "referral_balance", default=0.0) or 0.0)} ₽',
        '',
        'Подписки:',
    ]
    for sub in subs:
        lines.append(subscription_card(sub))
        lines.append('')
    slots = [int(row_value(sub, 'slot', default=0) or 0) for sub in subs]
    await callback.message.answer('\n'.join(lines).rstrip(), reply_markup=partner_detail_keyboard(tg_id, page, is_partner, is_admin_user, slots))


@router.callback_query(F.data == 'admin:partners_list:0')
@router.callback_query(F.data.startswith('admin:partners_list:'))
async def admin_partners_list(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    page = safe_int(parts[-1]) if parts and parts[-1].isdigit() else 0
    partners = await get_active_partners()
    per_page = 5
    total_pages = max(1, (len(partners) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = partners[page * per_page:(page + 1) * per_page]
    if not chunk:
        await callback.message.answer('Активных партнёров нет.', reply_markup=admin_keyboard())
        return
    items = []
    for partner in chunk:
        tg_id = int(row_value(partner, 'tg_id'))
        username = row_value(partner, 'username')
        label = f'@{username}' if username else f'ID {tg_id}'
        if int(row_value(partner, 'is_admin', default=0) or 0) == 1:
            label += ' · админ'
        items.append((tg_id, label[:32]))
    await callback.message.answer(f'👑 Активные партнёры (страница {page + 1}/{total_pages})', reply_markup=partners_list_keyboard(page, total_pages, items))


@router.callback_query(F.data.startswith('admin:client_paybalance_up:'))
async def admin_client_paybalance_up(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, page_s = parts[2], parts[3]
    await state.set_state(AdminForm.waiting_for_amount)
    await state.update_data(admin_action='client_paybalance_up', target_id=int(tg_id_s), page=int(page_s))
    await callback.message.answer('Введите сумму в рублях, которую нужно добавить на баланс оплаты клиента:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))
@router.callback_query(F.data.startswith('admin:client_paybalance_down:'))
async def admin_client_paybalance_down(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, page_s = parts[2], parts[3]
    await state.set_state(AdminForm.waiting_for_amount)
    await state.update_data(admin_action='client_paybalance_down', target_id=int(tg_id_s), page=int(page_s))
    await callback.message.answer('Введите сумму в рублях, которую нужно снять с баланса оплаты клиента:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))
@router.callback_query(F.data.startswith('admin:client_refbalance_up:'))
async def admin_client_refbalance_up(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, page_s = parts[2], parts[3]
    await state.set_state(AdminForm.waiting_for_amount)
    await state.update_data(admin_action='client_refbalance_up', target_id=int(tg_id_s), page=int(page_s))
    await callback.message.answer('Введите сумму в рублях, которую нужно добавить на реферальный баланс клиента:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))
@router.callback_query(F.data.startswith('admin:client_refbalance_down:'))
async def admin_client_refbalance_down(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, page_s = parts[2], parts[3]
    await state.set_state(AdminForm.waiting_for_amount)
    await state.update_data(admin_action='client_refbalance_down', target_id=int(tg_id_s), page=int(page_s))
    await callback.message.answer('Введите сумму в рублях, которую нужно снять с реферального баланса клиента:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))
@router.callback_query(F.data.startswith('admin:client_refcalc:'))
async def admin_client_refcalc(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, page_s = parts[2], parts[3]
    tg_id = int(tg_id_s)
    page = int(page_s)
    client = await get_user(tg_id)
    if not client:
        await callback.message.answer('Клиент не найден.', reply_markup=admin_keyboard())
        return
    ref_balance = float(row_value(client, 'referral_balance', default=0.0) or 0.0)
    text = f'🎁 Реферальные средства клиента {tg_id}: {money(ref_balance)} ₽'
    await callback.message.answer(text, reply_markup=client_detail_keyboard(tg_id, page, int(row_value(client, "is_partner", default=0) or 0) == 1, int(row_value(client, "is_admin", default=0) or 0) == 1, [int(row_value(sub, "slot", default=0) or 0) for sub in await get_user_subscriptions(tg_id)]))
@router.callback_query(F.data.startswith('admin:partner_paybalance_up:'))
async def admin_partner_paybalance_up(callback: CallbackQuery, state: FSMContext):
    await admin_client_paybalance_up(callback, state)


@router.callback_query(F.data.startswith('admin:partner_paybalance_down:'))
async def admin_partner_paybalance_down(callback: CallbackQuery, state: FSMContext):
    await admin_client_paybalance_down(callback, state)


@router.callback_query(F.data.startswith('admin:partner_refbalance_up:'))
async def admin_partner_refbalance_up(callback: CallbackQuery, state: FSMContext):
    await admin_client_refbalance_up(callback, state)


@router.callback_query(F.data.startswith('admin:partner_refbalance_down:'))
async def admin_partner_refbalance_down(callback: CallbackQuery, state: FSMContext):
    await admin_client_refbalance_down(callback, state)


@router.callback_query(F.data.startswith('admin:client_refcount_up:'))
async def admin_client_refcount_up(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, page_s = parts[2], parts[3]
    await state.set_state(AdminForm.waiting_for_amount)
    await state.update_data(admin_action='client_refcount_up', target_id=int(tg_id_s), page=int(page_s))
    await callback.message.answer('Введите количество рефералов, которое нужно добавить пользователю:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))


@router.callback_query(F.data.startswith('admin:client_refcount_down:'))
async def admin_client_refcount_down(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, page_s = parts[2], parts[3]
    await state.set_state(AdminForm.waiting_for_amount)
    await state.update_data(admin_action='client_refcount_down', target_id=int(tg_id_s), page=int(page_s))
    await callback.message.answer('Введите количество рефералов, которое нужно убрать пользователю:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))


@router.callback_query(F.data.startswith('admin:partner_refcount_up:'))
async def admin_partner_refcount_up(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, page_s = parts[2], parts[3]
    await state.set_state(AdminForm.waiting_for_amount)
    await state.update_data(admin_action='partner_refcount_up', target_id=int(tg_id_s), page=int(page_s))
    await callback.message.answer('Введите количество рефералов, которое нужно добавить партнёру:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))


@router.callback_query(F.data.startswith('admin:partner_refcount_down:'))
async def admin_partner_refcount_down(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, page_s = parts[2], parts[3]
    await state.set_state(AdminForm.waiting_for_amount)
    await state.update_data(admin_action='partner_refcount_down', target_id=int(tg_id_s), page=int(page_s))
    await callback.message.answer('Введите количество рефералов, которое нужно убрать у партнёра:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))


@router.callback_query(F.data.startswith('admin:client_partner_on:'))
async def admin_client_partner_on(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s = parts[2]
    tg_id = int(tg_id_s)
    await set_user_partner(tg_id, True)
    await _reward_partner_for_new_referral(callback.message.bot, tg_id)
    await _ensure_partner_subscription(callback.message.bot, tg_id)
    await _notify_role_change(callback.message.bot, tg_id, is_admin=False, is_partner=True)
    await callback.message.answer(f'✅ Пользователю {tg_id} выдан статус партнёра.', reply_markup=admin_keyboard())
@router.callback_query(F.data.startswith('admin:client_partner_off:'))
async def admin_client_partner_off(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s = parts[2]
    tg_id = int(tg_id_s)
    await set_user_partner(tg_id, False)
    await _deactivate_partner_access(callback.message.bot, tg_id)
    await _notify_role_change(callback.message.bot, tg_id, is_admin=False, is_partner=False)
    await callback.message.answer(f'✅ У пользователя {tg_id} снят статус партнёра.', reply_markup=admin_keyboard())
@router.callback_query(F.data.startswith('admin:client_admin_on:'))
async def admin_client_admin_on(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s = parts[2]
    tg_id = int(tg_id_s)
    await set_user_admin(tg_id, True)
    await _notify_role_change(callback.message.bot, tg_id, is_admin=True)
    await callback.message.answer(f'✅ Пользователю {tg_id_s} выдан статус админа.', reply_markup=admin_keyboard())
@router.callback_query(F.data.startswith('admin:client_admin_off:'))
async def admin_client_admin_off(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s = parts[2]
    if int(tg_id_s) == settings.admin_id:
        await callback.message.answer('Нельзя снять админку с главного администратора.', reply_markup=admin_keyboard())
        return
    tg_id = int(tg_id_s)
    await set_user_admin(tg_id, False)
    await _notify_role_change(callback.message.bot, tg_id, is_admin=False)
    await callback.message.answer(f'✅ У пользователя {tg_id_s} снят статус админа.', reply_markup=admin_keyboard())
@router.callback_query(F.data.startswith('admin:partner_add_ref:'))
async def admin_partner_add_ref(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    partner_id_s, page_s = parts[2], parts[3]
    await state.set_state(AdminForm.waiting_for_target)
    await state.update_data(admin_action='partner_add_ref', partner_id=int(partner_id_s), page=int(page_s))
    await callback.message.answer('Введите Telegram ID нового реферала, которого нужно привязать к этому партнёру:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))



@router.callback_query(F.data.startswith('admin:sub:'))
async def admin_sub_detail(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 5:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, slot_s, page_s = parts[2], parts[3], parts[4]
    tg_id = int(tg_id_s)
    slot = int(slot_s)
    page = int(page_s)
    sub = await get_remnawave_subscription_by_user_slot(tg_id, slot)
    if not sub:
        await callback.message.answer('Подписка не найдена.', reply_markup=admin_keyboard())
        return
    lines = [
        '🔎 Подписка клиента',
        '',
        f'Клиент: ID {tg_id}',
        f'Ключ: {subscription_label(slot)}',
        f'Лимит: {bytes_to_text(row_value(sub, "traffic_limit_bytes"))}',
        f'Сброс: {traffic_strategy_label(row_value(sub, "traffic_limit_strategy"), row_value(sub, "traffic_limit_bytes"))}',
        f'Действует до: {format_russian_dt(row_value(sub, "expire_at"))}',
        f'Осталось: {human_timedelta(row_value(sub, "expire_at"))}',
        f'URL: {row_value(sub, "subscription_url")}',
    ]
    await callback.message.answer('\n'.join(lines), reply_markup=subscription_manage_keyboard(tg_id, slot, page, f'admin:client:{tg_id}:{page}'))


@router.callback_query(F.data.startswith('admin:client_subs:'))
async def admin_client_subs(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, page_s = parts[2], parts[3]
    tg_id = int(tg_id_s)
    page = int(page_s)
    subs = _active_subscriptions(await get_user_subscriptions(tg_id))
    if not subs:
        await callback.message.answer('Подписок нет.', reply_markup=admin_keyboard())
        return
    slots = [int(row_value(sub, 'slot', default=0) or 0) for sub in subs]
    await callback.message.answer(f'🔑 Подписки клиента {tg_id}', reply_markup=subscription_list_keyboard(tg_id, page, slots, f'admin:client:{tg_id}:{page}'))


@router.callback_query(F.data.startswith('admin:partner_subs:'))
async def admin_partner_subs(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 4:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, page_s = parts[2], parts[3]
    tg_id = int(tg_id_s)
    page = int(page_s)
    subs = _active_subscriptions(await get_user_subscriptions(tg_id))
    if not subs:
        await callback.message.answer('Подписок нет.', reply_markup=admin_keyboard())
        return
    slots = [int(row_value(sub, 'slot', default=0) or 0) for sub in subs]
    await callback.message.answer(f'🔑 Подписки партнёра {tg_id}', reply_markup=subscription_list_keyboard(tg_id, page, slots, f'admin:partner:{tg_id}:{page}'))


@router.callback_query(F.data.startswith('admin:sub_extend:'))
async def admin_sub_extend(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 5:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, slot_s, page_s = parts[2], parts[3], parts[4]
    await state.clear()
    await state.set_state(AdminForm.waiting_for_days)
    await state.update_data(admin_action='sub_extend', target_id=int(tg_id_s), target_slot=int(slot_s), page=int(page_s))
    await callback.message.answer(
        'Выберите срок продления:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='+5 дней', callback_data=f'admin:sub_extend_days:{tg_id_s}:{slot_s}:{page_s}:5')],
            [InlineKeyboardButton(text='+10 дней', callback_data=f'admin:sub_extend_days:{tg_id_s}:{slot_s}:{page_s}:10')],
            [InlineKeyboardButton(text='+15 дней', callback_data=f'admin:sub_extend_days:{tg_id_s}:{slot_s}:{page_s}:15')],
            [InlineKeyboardButton(text='+20 дней', callback_data=f'admin:sub_extend_days:{tg_id_s}:{slot_s}:{page_s}:20')],
            [InlineKeyboardButton(text='+30 дней', callback_data=f'admin:sub_extend_days:{tg_id_s}:{slot_s}:{page_s}:30')],
            [InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')],
        ]),
    )


@router.callback_query(F.data.startswith('admin:sub_extend_days:'))
async def admin_sub_extend_days(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback.data.split(':')
    if len(parts) < 6 or not parts[2].isdigit() or not parts[3].isdigit() or not parts[4].isdigit() or not parts[5].isdigit():
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    target_id = int(parts[2])
    slot = int(parts[3])
    page = int(parts[4])
    add_days = int(parts[5])
    await state.set_state(AdminForm.waiting_for_days)
    await state.update_data(admin_action='sub_extend', target_id=target_id, target_slot=slot, page=page, amount=add_days)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Подтвердить', callback_data='admin:sub_extend_confirm')],
        [InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')],
    ])
    await callback.message.answer(f'Подтвердите продление подписки пользователя {target_id} на {add_days} дн.', reply_markup=kb)


@router.callback_query(F.data.startswith('admin:sub_limit:'))
async def admin_sub_limit(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 5:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, slot_s, page_s = parts[2], parts[3], parts[4]
    await state.set_state(AdminForm.waiting_for_limit)
    await state.update_data(admin_action='sub_limit', target_id=int(tg_id_s), target_slot=int(slot_s), page=int(page_s))
    await callback.message.answer('Введите новый лимит в ГБ целым числом (0 = безлимит):', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))



@router.callback_query(F.data.startswith('admin:sub_reset_limit:'))
async def admin_sub_reset_limit(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 5:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, slot_s, page_s = parts[2], parts[3], parts[4]
    tg_id = int(tg_id_s)
    slot = int(slot_s)
    sub = await get_remnawave_subscription_by_user_slot(tg_id, slot)
    if not sub:
        await callback.message.answer('Подписка не найдена.', reply_markup=admin_keyboard())
        return
    await _reset_single_subscription_traffic(callback.message.bot, sub)
    page = int(page_s)
    client = await get_user(tg_id)
    subs = _active_subscriptions(await get_user_subscriptions(tg_id))
    await callback.message.answer(
        f'✅ Лимит трафика для пользователя {tg_id}, {subscription_label(slot)} сброшен.',
        reply_markup=client_detail_keyboard(
            tg_id,
            page,
            bool(client and int(row_value(client, "is_partner", default=0) or 0) == 1),
            bool(client and int(row_value(client, "is_admin", default=0) or 0) == 1),
            [int(row_value(sub, "slot", default=0) or 0) for sub in subs],
        ),
    )


@router.callback_query(F.data.startswith('admin:sub_disable:'))
async def admin_sub_disable(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 5:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, slot_s, page_s = parts[2], parts[3], parts[4]
    await state.update_data(admin_action='sub_disable', target_id=int(tg_id_s), target_slot=int(slot_s), page=int(page_s))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Подтвердить', callback_data=f'admin:sub_disable_confirm:{tg_id_s}:{slot_s}:{page_s}')],
        [InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')],
    ])
    await callback.message.answer('Подтвердите отключение подписки.', reply_markup=kb)


@router.callback_query(F.data.startswith('admin:sub_disable_confirm:'))
async def admin_sub_disable_confirm(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback_parts(callback)
    if len(parts) < 5:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id_s, slot_s, page_s = parts[2], parts[3], parts[4]
    tg_id = int(tg_id_s)
    slot = int(slot_s)
    sub = await get_remnawave_subscription_by_user_slot(tg_id, slot)
    if not sub:
        await callback.message.answer('Подписка не найдена.', reply_markup=admin_keyboard())
        return
    await _delete_user_subscription_in_remnawave(callback.message.bot, [sub])
    await delete_user_subscription_slot(tg_id, slot)
    await _sync_user_access_from_subscriptions(tg_id)
    client = await get_user(tg_id)
    subs = _active_subscriptions(await get_user_subscriptions(tg_id))
    await callback.message.answer(
        f'✅ Подписка пользователя {tg_id} отключена и удалена из Remnawave и БД.',
        reply_markup=client_detail_keyboard(
            tg_id,
            int(page_s),
            bool(client and int(row_value(client, "is_partner", default=0) or 0) == 1),
            bool(client and int(row_value(client, "is_admin", default=0) or 0) == 1),
            [int(row_value(sub, "slot", default=0) or 0) for sub in subs],
        ),
    )


@router.message(AdminForm.waiting_for_days)
async def admin_days_handler(message: Message, state: FSMContext):
    raw = (message.text or '').strip()
    if not raw.isdigit():
        await message.answer('Введите целое число дней.')
        return
    data = await state.get_data()
    target_id = int(data.get('target_id') or 0)
    slot = int(data.get('target_slot') or 0)
    page = int(data.get('page') or 0)
    sub = await get_remnawave_subscription_by_user_slot(target_id, slot)
    if not sub:
        await state.clear()
        await message.answer('Подписка не найдена.', reply_markup=admin_keyboard())
        return
    await state.update_data(amount=int(raw))
    await state.set_state(AdminForm.waiting_for_confirm)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Подтвердить', callback_data='admin:sub_extend_confirm')],
        [InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')],
    ])
    await message.answer(f'Подтвердите продление подписки пользователя {target_id} на {int(raw)} дн.', reply_markup=kb)


@router.message(AdminForm.waiting_for_limit)
async def admin_limit_handler(message: Message, state: FSMContext):
    raw = (message.text or '').strip()
    if not raw.isdigit():
        await message.answer('Введите целое число ГБ.')
        return
    data = await state.get_data()
    target_id = int(data.get('target_id') or 0)
    slot = int(data.get('target_slot') or 0)
    sub = await get_remnawave_subscription_by_user_slot(target_id, slot)
    if not sub:
        await state.clear()
        await message.answer('Подписка не найдена.', reply_markup=admin_keyboard())
        return
    await state.update_data(amount=int(raw))
    await state.set_state(AdminForm.waiting_for_confirm)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Подтвердить', callback_data='admin:sub_limit_confirm')],
        [InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')],
    ])
    await message.answer(f'Подтвердите установку лимита {int(raw)} ГБ для пользователя {target_id}.', reply_markup=kb)


@router.callback_query(F.data == 'admin:sub_extend_confirm')
async def admin_sub_extend_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    data = await state.get_data()
    target_id = int(data.get('target_id') or 0)
    slot = int(data.get('target_slot') or 0)
    page = int(data.get('page') or 0)
    add_days = int(data.get('amount') or 0)
    sub = await get_remnawave_subscription_by_user_slot(target_id, slot)
    if not sub:
        await state.clear()
        await callback.message.answer('Подписка не найдена.', reply_markup=admin_keyboard())
        return

    base = datetime.now(timezone.utc)
    try:
        exp = datetime.fromisoformat(str(row_value(sub, 'expire_at')))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp > base:
            base = exp
    except Exception:
        pass

    new_expire = (base + timedelta(days=add_days)).isoformat(timespec='seconds')
    username = str(row_value(sub, 'username') or combined_key_username(target_id, kind='admin_extend'))
    user = await remnawave.create_or_update_subscription(
        telegram_id=target_id,
        slot=slot,
        days=add_days,
        squad_uuid=str(row_value(sub, 'squad_uuid') or settings.remnawave_squad_2_uuid),
        traffic_limit_gb=0,
        base_username=username,
        description=f'TG {target_id} / admin extend / {subscription_label(slot).lower()}',
        traffic_limit_strategy='NO_RESET',
        existing_uuid=str(row_value(sub, 'user_uuid')),
        active_internal_squads=combined_internal_squads(),
        username=username,
        reuse_existing=True,
    )
    user_uuid = str(user.get('uuid') or row_value(sub, 'user_uuid') or '')
    await save_remnawave_subscription(
        payment_id=str(row_value(sub, 'payment_id')),
        user_tg_id=target_id,
        slot=slot,
        kind=str(row_value(sub, 'kind') or 'payment'),
        user_uuid=user_uuid,
        username=username,
        subscription_url=str(row_value(sub, 'subscription_url') or ''),
        squad_uuid=str(row_value(sub, 'squad_uuid') or ''),
        traffic_limit_bytes=int(row_value(sub, 'traffic_limit_bytes', default=0) or 0),
        traffic_limit_strategy='NO_RESET',
        expire_at=new_expire,
        traffic_reset_at=_next_traffic_reset_at(),
    )
    await _sync_user_access_from_subscriptions(target_id)
    client = await get_user(target_id)
    subs = _active_subscriptions(await get_user_subscriptions(target_id))
    await state.clear()
    await callback.message.answer(
        f'✅ Подписка пользователя {target_id} продлена на {add_days} дн.',
        reply_markup=client_detail_keyboard(
            target_id,
            page,
            bool(client and int(row_value(client, "is_partner", default=0) or 0) == 1),
            bool(client and int(row_value(client, "is_admin", default=0) or 0) == 1),
            [int(row_value(sub, "slot", default=0) or 0) for sub in subs],
        ),
    )


@router.callback_query(F.data == 'admin:sub_limit_confirm')
async def admin_sub_limit_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    data = await state.get_data()
    target_id = int(data.get('target_id') or 0)
    slot = int(data.get('target_slot') or 0)
    limit_gb = int(data.get('amount') or 0)
    sub = await get_remnawave_subscription_by_user_slot(target_id, slot)
    if not sub:
        await state.clear()
        await callback.message.answer('Подписка не найдена.', reply_markup=admin_keyboard())
        return
    limit_bytes = max(limit_gb, 0) * 1024 * 1024 * 1024
    await update_remnawave_subscription_limit(target_id, slot, limit_bytes)
    await callback.message.answer(f'✅ Локальный лимит подписки пользователя {target_id} установлен на {limit_gb} ГБ.', reply_markup=admin_keyboard())


@router.callback_query(F.data.startswith('admin:sub_check:'))
async def admin_sub_check(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback.data.split(':')
    if len(parts) < 5:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id = int(parts[2])
    slot = int(parts[3])
    page = int(parts[4])
    sub = await get_remnawave_subscription_by_user_slot(tg_id, slot)
    if not sub:
        await callback.message.answer('Подписка не найдена.', reply_markup=admin_keyboard())
        return
    result = await _sync_single_subscription_usage_once(callback.message.bot, sub, str(settings.remnawave_squad_1_uuid or '').strip(), str(settings.remnawave_squad_2_uuid or '').strip(), '1970-01-01', date.today().isoformat())
    used = bytes_to_text(result.get('used', 0))
    limit = bytes_to_text(result.get('limit', 0))
    status = result.get('status', 'ok')
    pretty = {'disabled': 'Mobile отключён', 'enabled': 'Mobile восстановлен', 'no_limit': 'Лимит не задан', 'ok': 'Проверка выполнена', 'skip': 'Пропуск'}.get(status, str(status))
    await callback.message.answer(
        f'🧪 Проверка трафика для пользователя {tg_id}, ключ {subscription_label(slot)}:\n'
        f'Статус: {pretty}\n'
        f'Трафик: {used} / {limit}',
        reply_markup=subscription_manage_keyboard(tg_id, slot, page, f'admin:client:{tg_id}:{page}'),
    )


@router.callback_query(F.data.startswith('admin:sub_simulate:'))
async def admin_sub_simulate(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    parts = callback.data.split(':')
    if len(parts) < 5:
        await callback.message.answer('Некорректные данные кнопки.', reply_markup=admin_keyboard())
        return
    tg_id = int(parts[2])
    slot = int(parts[3])
    page = int(parts[4])
    sub = await get_remnawave_subscription_by_user_slot(tg_id, slot)
    if not sub:
        await callback.message.answer('Подписка не найдена.', reply_markup=admin_keyboard())
        return
    limit = subscription_limit_bytes(sub)
    if limit <= 0:
        await callback.message.answer('У подписки нет лимита для симуляции.', reply_markup=admin_keyboard())
        return
    result = await _sync_single_subscription_usage_once(callback.message.bot, sub, str(settings.remnawave_squad_1_uuid or '').strip(), str(settings.remnawave_squad_2_uuid or '').strip(), '1970-01-01', date.today().isoformat(), forced_used_bytes=limit + 1)
    used = bytes_to_text(result.get('used', 0))
    pretty = {'disabled': 'Mobile отключён', 'enabled': 'Mobile восстановлен', 'no_limit': 'Лимит не задан', 'ok': 'Проверка выполнена', 'skip': 'Пропуск'}.get(result.get('status', 'ok'), str(result.get('status')))
    await callback.message.answer(
        f'🧪 Симуляция превышения для пользователя {tg_id}, ключ {subscription_label(slot)}:\n'
        f'Статус: {pretty}\n'
        f'Трафик: {used} / {bytes_to_text(limit)}',
        reply_markup=subscription_manage_keyboard(tg_id, slot, page, f'admin:client:{tg_id}:{page}'),
    )


@router.callback_query(F.data == 'admin:refcalc')

async def admin_refcalc(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    await state.set_state(AdminForm.waiting_for_target)
    await state.update_data(admin_action='refcalc')
    await callback.message.answer('Введите Telegram ID клиента для просмотра реферальных средств:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))


@router.callback_query(F.data == 'admin:refbonus')
async def admin_refbonus(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    await state.set_state(AdminForm.waiting_for_target)
    await state.update_data(admin_action='refbonus')
    await callback.message.answer('Введите Telegram ID клиента, которому нужно начислить реферальный баланс:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]))



async def _send_admin_subscription_test_notifications(bot: Bot) -> tuple[int, int]:
    sent = 0
    failed = 0
    samples = [
        (
            '⏳ Пробная подписка закончится через 1 день.\n\nВыберите подходящий тариф, чтобы не потерять доступ.',
            tariffs_keyboard(),
        ),
        (
            '⏳ До окончания пробной подписки осталось 2 часа.\n\nВыберите подходящий тариф, чтобы не потерять доступ.',
            tariffs_keyboard(),
        ),
        (
            '⚠️ Пробная подписка закончилась.\n\nЧтобы восстановить доступ, выберите подходящий тариф.',
            tariffs_keyboard(),
        ),
        (
            'Похоже, конфигуратор ещё не подключён или не пригодился 😢\n\nЕсли что-то не получилось подключить, то мы всегда поможем!',
            trial_usage_low_keyboard(),
        ),
        (
            'Видим, что наши услуги вам нравятся 😎\n\nЧтобы доступ не оборвался после пробника, можно продлить заранее — это займёт минуту.',
            trial_usage_high_keyboard(),
        ),
        (
            '🌟 Похоже, пробная подписка у вас ещё не была активирована.\n\nМожно подключить пробный период в пару кликов и сразу проверить, как всё работает. Если с запуском будут сложности — мы поможем.',
            trial_invitation_keyboard(),
        ),
    ]
    for text, kb in samples:
        try:
            await bot.send_message(settings.admin_id, text, reply_markup=kb)
            sent += 1
        except Exception as exc:
            failed += 1
            logger.warning('Admin test notification failed: %s', exc)
    return sent, failed


@router.callback_query(F.data == 'admin:test_subscription_notifications')
async def admin_test_subscription_notifications(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    sent, failed = await _send_admin_subscription_test_notifications(callback.message.bot)
    await callback.message.answer(
        f'🧪 Тест уведомлений отправлен только вам. Успешно: {sent}, ошибок: {failed}.',
        reply_markup=admin_keyboard(),
    )


@router.callback_query(F.data == 'admin:test_no_trial_notification')
async def admin_test_no_trial_notification(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    await callback.message.bot.send_message(
        settings.admin_id,
        '🌟 Похоже, пробная подписка у вас ещё не была активирована.\n\nМожно подключить пробный период в пару кликов и сразу проверить, как всё работает. Если с запуском будут сложности — мы поможем.',
        reply_markup=trial_invitation_keyboard(),
    )
    await callback.message.answer('🧪 Тест уведомления для пользователей без trial отправлен только вам.', reply_markup=admin_keyboard())


@router.callback_query(F.data == 'admin:purge_subscriptions')
async def admin_purge_subscriptions(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Подтвердить удаление', callback_data='admin:purge_subscriptions_confirm')],
        [InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')],
    ])
    await callback.message.answer('Подтвердите удаление ВСЕХ подписок из БД.', reply_markup=kb)


@router.callback_query(F.data == 'admin:purge_subscriptions_confirm')
async def admin_purge_subscriptions_confirm(callback: CallbackQuery):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    subs = await get_all_remnawave_subscriptions()
    await _delete_user_subscription_in_remnawave(callback.message.bot, subs)
    await delete_all_user_subscriptions()
    await deactivate_all_users_access()
    await callback.message.answer('✅ Все подписки удалены из БД и Remnawave, доступ у пользователей отключён.', reply_markup=admin_keyboard())


@router.callback_query(F.data == 'admin:trial_broadcast')
async def admin_trial_broadcast(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    await state.clear()
    await state.set_state(AdminForm.waiting_for_trial_broadcast_message)
    await callback.message.answer(
        'Введите текст сообщения для рассылки пробного периода:\nСообщение получат только пользователи, у которых был trial и которые не покупали подписку.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]),
    )


@router.message(AdminForm.waiting_for_trial_broadcast_message)
async def admin_trial_broadcast_send(message: Message, state: FSMContext):
    if not await _is_admin_user(message.from_user.id):
        return
    text = (message.text or '').strip()
    if not text:
        await message.answer('Введите текст сообщения для рассылки.')
        return
    await state.update_data(trial_broadcast_message=text)
    await state.set_state(AdminForm.waiting_for_trial_broadcast_confirm)
    preview_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Отправить', callback_data='admin:trial_broadcast_confirm')],
        [InlineKeyboardButton(text='❌ Отмена', callback_data='admin:trial_broadcast_cancel')],
    ])
    await message.answer(
        f'Предпросмотр рассылки пробного периода:\n\n{text}',
        reply_markup=preview_kb,
    )


@router.callback_query(AdminForm.waiting_for_trial_broadcast_confirm, F.data == 'admin:trial_broadcast_cancel')
async def admin_trial_broadcast_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer('Отменено')
    await state.clear()
    await callback.message.answer('Рассылка отменена.', reply_markup=admin_keyboard())


@router.callback_query(AdminForm.waiting_for_trial_broadcast_confirm, F.data == 'admin:trial_broadcast_confirm')
async def admin_trial_broadcast_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    data = await state.get_data()
    text = str(data.get('trial_broadcast_message') or '').strip()
    if not text:
        await state.clear()
        await callback.message.answer('Не удалось отправить рассылку.', reply_markup=admin_keyboard())
        return
    targets = await get_trial_promo_broadcast_targets()
    if not targets:
        await state.clear()
        await callback.message.answer('Не нашёл пользователей, которым подходит эта рассылка.', reply_markup=admin_keyboard())
        return
    sent = 0
    failed = 0
    for user in targets:
        tg_id = int(row_value(user, 'tg_id', default=0) or 0)
        if tg_id <= 0 or tg_id == settings.admin_id:
            continue
        try:
            await callback.message.bot.send_message(tg_id, text, reply_markup=trial_invitation_keyboard())
            sent += 1
        except Exception as exc:
            failed += 1
            logger.warning('Trial broadcast failed for tg_id=%s: %s', tg_id, exc)
    await state.clear()
    await callback.message.answer(
        f'✅ Рассылка пробного периода завершена. Отправлено: {sent}, ошибок: {failed}.',
        reply_markup=admin_keyboard(),
    )


@router.callback_query(F.data == 'admin:broadcast')
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await _is_admin_user(callback.from_user.id):
        return
    await state.set_state(AdminForm.waiting_for_broadcast)
    await callback.message.answer(
        '📢 Отправьте сообщение, которое нужно разослать всем клиентам.\nМожно текст, фото, видео, документ и подпись к нему.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]]),
    )


def _broadcast_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='admin:cancel')]])


@router.message(AdminForm.waiting_for_broadcast)
async def admin_broadcast_send(message: Message, state: FSMContext, bot: Bot):
    if not await _is_admin_user(message.from_user.id):
        return
    users = await get_all_users()
    if not users:
        await state.clear()
        await message.answer('В базе нет клиентов для рассылки.', reply_markup=admin_keyboard())
        return
    sent = 0
    failed = 0
    for user in users:
        tg_id = int(row_value(user, 'tg_id'))
        if tg_id <= 0 or tg_id == settings.admin_id:
            continue
        try:
            await bot.copy_message(chat_id=tg_id, from_chat_id=message.chat.id, message_id=message.message_id)
            sent += 1
        except Exception as exc:
            failed += 1
            logger.warning('Broadcast failed for tg_id=%s: %s', tg_id, exc)
    await state.clear()
    await message.answer(f'✅ Рассылка завершена. Отправлено: {sent}, ошибок: {failed}.', reply_markup=admin_keyboard())




@router.message(AdminForm.waiting_for_confirm)
async def admin_confirm_handler(message: Message, state: FSMContext):
    await message.answer('Используйте кнопки подтверждения.')


@router.message(StateFilter('*'), F.text == 'Отмена')
async def cancel_from_text(message: Message, state: FSMContext):
    current_state = await state.get_state()
    is_admin_flow = bool(current_state and current_state.startswith('AdminForm'))
    await state.clear()
    await message.answer('Действие отменено.', reply_markup=admin_keyboard() if is_admin_flow else main_menu_keyboard(is_admin=await _is_admin_user(message.from_user.id)))
