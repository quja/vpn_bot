from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .config import MOBILE_REFILL_PRICE

HAPP_WINDOWS_URL = 'https://github.com/Happ-proxy/happ-desktop/releases/latest'
HAPP_MAC_URL = 'https://apps.apple.com/us/app/happ-proxy-utility/id6504287215'
HAPP_IOS_URL = 'https://apps.apple.com/us/app/happ-proxy-utility/id6504287215'
HAPP_IOS_RU_URL = 'https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973'
HAPP_ANDROID_URL = 'https://play.google.com/store/apps/details?id=com.happproxy'
HAPP_APK_URL = 'https://github.com/Happ-proxy/happ-android/releases/latest'

def welcome_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🚀 Открыть меню', callback_data='menu:home')]])


def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text='💳 Тарифы', callback_data='menu:tariffs')],
        [InlineKeyboardButton(text='💰 Пополнить баланс', callback_data='menu:topup')],
        [InlineKeyboardButton(text='🎁 Пробный период 3 дня', callback_data='menu:trial')],
        [
            InlineKeyboardButton(text='📊 Мой профиль', callback_data='menu:status'),
            InlineKeyboardButton(text='📲 Инструкция', callback_data='menu:instruction'),
        ],
        [
            InlineKeyboardButton(text='🎟 Рефералы', callback_data='menu:referral'),
            InlineKeyboardButton(text='💰 Заработок', callback_data='menu:earnings'),
        ],
        [InlineKeyboardButton(text='🆘 Поддержка', callback_data='menu:support')],
        [InlineKeyboardButton(text='📚 Документация', callback_data='menu:documentation')],
    ]
    if is_admin:
        rows.insert(0, [InlineKeyboardButton(text='🛠 Админка', callback_data='admin:panel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def earnings_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text='🎟 Рефералы', callback_data='menu:referral')],
        [InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:home')],
    ]
    if is_admin:
        rows.insert(0, [InlineKeyboardButton(text='🛠 Админка', callback_data='admin:panel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tariffs_keyboard(prices: dict[str, int] | None = None) -> InlineKeyboardMarkup:
    prices = prices or {
        '1m': 200,
        '3m': 500,
        '6m': 950,
        '12m': 1700,
        'refill': MOBILE_REFILL_PRICE,
    }
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f'1 месяц — {prices["1m"]} ₽', callback_data='tariff:1m')],
        [InlineKeyboardButton(text=f'3 месяца — {prices["3m"]} ₽', callback_data='tariff:3m')],
        [InlineKeyboardButton(text=f'6 месяцев — {prices["6m"]} ₽', callback_data='tariff:6m')],
        [InlineKeyboardButton(text=f'12 месяцев — {prices["12m"]} ₽', callback_data='tariff:12m')],
        [InlineKeyboardButton(text='🔄 Продлить подписку', callback_data='tariff:renew_menu')],
        [InlineKeyboardButton(text='🎟 Промокоды', callback_data='menu:promo')],
        [InlineKeyboardButton(text='⬅️ Главное меню', callback_data='menu:home')],
    ])


def tariff_choice_keyboard(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🛒 Купить новую подписку', callback_data=f'buy:new:{code}')],
        [InlineKeyboardButton(text='⬅️ Назад к тарифам', callback_data='menu:tariffs')],
        [InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:home')],
    ])


def renew_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='➕ Докупить дни', callback_data='tariff:extend')],
        [InlineKeyboardButton(text='➕ Докупить трафик', callback_data='tariff:refill')],
        [InlineKeyboardButton(text='⬅️ Назад к тарифам', callback_data='menu:tariffs')],
        [InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:home')],
    ])


def purchase_confirm_keyboard(code: str, choice: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Подтвердить', callback_data=f'buy:confirm:{choice}:{code}')],
        [InlineKeyboardButton(text='❌ Отмена', callback_data=f'buy:cancel:{choice}:{code}')],
    ])


def documentation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📑 Публичная оферта', callback_data='menu:offer')],
        [InlineKeyboardButton(text='📜 Правила использования', callback_data='menu:rules')],
        [InlineKeyboardButton(text='🔒 Политика конфиденциальности', callback_data='menu:privacy')],
        [InlineKeyboardButton(text='⬅️ Главное меню', callback_data='menu:home')],
    ])


def support_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='support:cancel')]])


def withdraw_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🆘 Написать в поддержку', callback_data='menu:support')],
        [InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:home')],
    ])


def profile_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text='🔑 Мои ключи', callback_data='profile:keys')],
        [InlineKeyboardButton(text='💸 Вывести средства', callback_data='profile:withdraw')],
        [InlineKeyboardButton(text='🔄 Перевести на баланс оплаты', callback_data='profile:transfer')],
        [InlineKeyboardButton(text='⬅️ Главное меню', callback_data='menu:home')],
    ]
    if is_admin:
        rows.insert(0, [InlineKeyboardButton(text='🛠 Админка', callback_data='admin:panel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def referral_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:home')]]
    if is_admin:
        rows.insert(0, [InlineKeyboardButton(text='🛠 Админка', callback_data='admin:panel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_keys_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text='⬅️ В мой профиль', callback_data='menu:status')],
        [InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:home')],
    ]
    if is_admin:
        rows.insert(0, [InlineKeyboardButton(text='🛠 Админка', callback_data='admin:panel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_keys_list_keyboard(buttons: list[tuple[str, str]], is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=cb)] for label, cb in buttons]
    rows.append([InlineKeyboardButton(text='⬅️ В мой профиль', callback_data='menu:status')])
    rows.append([InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:home')])
    if is_admin:
        rows.insert(0, [InlineKeyboardButton(text='🛠 Админка', callback_data='admin:panel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_key_detail_keyboard(open_url: str | None, is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if open_url:
        rows.append([InlineKeyboardButton(text='🔗 Открыть в Hiddify / Happ', url=open_url)])
    rows.append([InlineKeyboardButton(text='⬅️ Назад к ключам', callback_data='profile:keys')])
    rows.append([InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:home')])
    if is_admin:
        rows.insert(0, [InlineKeyboardButton(text='🛠 Админка', callback_data='admin:panel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def refill_prompt_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Отмена', callback_data='refill:cancel')]])


def purchase_label_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='➡️ Пропустить', callback_data='buy:label_skip')],
        [InlineKeyboardButton(text='❌ Отмена', callback_data='buy:label_cancel')],
    ])


def refill_target_keyboard(options: list[tuple[int, str]], gb: int, amount: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=f'refill:target:{slot}:{gb}:{amount}')] for slot, label in options]
    rows.append([InlineKeyboardButton(text='❌ Отмена', callback_data='refill:cancel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def refill_confirm_keyboard(gb: int, amount: int, slot: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f'✅ Купить за {amount} ₽', callback_data=f'refill:confirm:{slot}:{gb}:{amount}')],
        [InlineKeyboardButton(text='❌ Отмена', callback_data='refill:cancel')],
    ])


def balance_topup_keyboard(payment_url: str | None = None, payment_id: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    if payment_url:
        rows.append([InlineKeyboardButton(text='💳 Оплатить', url=payment_url)])
    if payment_id:
        rows.append([InlineKeyboardButton(text='🔍 Проверить оплату', callback_data=f'paycheck:{payment_id}')])
    rows.append([InlineKeyboardButton(text='❌ Отмена', callback_data='menu:home')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def happ_keys_keyboard(happ_link: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    button_url = happ_link or ''
    if button_url:
        rows.append([InlineKeyboardButton(text='📲 Открыть в Happ', url=button_url)])
    rows.append([InlineKeyboardButton(text='📘 Инструкция', callback_data='menu:instruction')])
    rows.append([InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:home')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def happ_instruction_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Windows (GitHub)', url=HAPP_WINDOWS_URL), InlineKeyboardButton(text='Mac', url=HAPP_MAC_URL)],
        [InlineKeyboardButton(text='iOS (EN регион магазина)', url=HAPP_IOS_URL), InlineKeyboardButton(text='iOS (RU регион магазина)', url=HAPP_IOS_RU_URL)],
        [InlineKeyboardButton(text='Android', url=HAPP_ANDROID_URL), InlineKeyboardButton(text='APK (GitHub)', url=HAPP_APK_URL)],
        [InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:home')],
    ])


def insufficient_funds_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💰 Пополнить баланс', callback_data='menu:topup')],
        [InlineKeyboardButton(text='🎁 Перевести с реф. счёта', callback_data='profile:transfer')],
        [InlineKeyboardButton(text='❌ Отмена', callback_data='menu:tariffs')],
    ])


def trial_usage_low_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🆘 Поддержка', callback_data='menu:support')],
        [InlineKeyboardButton(text='❌ Отмена', callback_data='menu:home')],
    ])


def trial_usage_high_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💳 Тарифы', callback_data='menu:tariffs')],
        [InlineKeyboardButton(text='❌ Отмена', callback_data='menu:home')],
    ])


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='👥 Активные партнёры', callback_data='admin:partners_list:0')],
        [InlineKeyboardButton(text='👮 Активные админы', callback_data='admin:admins_list:0')],
        [InlineKeyboardButton(text='👥 Пользователи', callback_data='admin:clients_list:0')],
        [InlineKeyboardButton(text='🔎 Поиск пользователя', callback_data='admin:users_search')],
        [InlineKeyboardButton(text='📢 Написать всем клиентам', callback_data='admin:broadcast')],
        [InlineKeyboardButton(text='🧪 Тест уведомлений', callback_data='admin:test_subscription_notifications')],
        [InlineKeyboardButton(text='🎁 Рассылка пробного периода', callback_data='admin:trial_broadcast')],
        [InlineKeyboardButton(text='🧪 Тест без trial', callback_data='admin:test_no_trial_notification')],
        [InlineKeyboardButton(text='➕ Создать ключ', callback_data='admin:create_key')],
        [InlineKeyboardButton(text='🎟 Промокоды', callback_data='admin:promos')],
        [InlineKeyboardButton(text='👑 Выдать партнёра', callback_data='admin:partner_on')],
        [InlineKeyboardButton(text='🚫 Снять партнёра', callback_data='admin:partner_off')],
        [InlineKeyboardButton(text='👑 Выдать админа', callback_data='admin:admin_on')],
        [InlineKeyboardButton(text='🚫 Снять админа', callback_data='admin:admin_off')],
        [InlineKeyboardButton(text='⬅️ Главное меню', callback_data='menu:home')],
    ])


def _nav_row(prefix: str, page: int, total_pages: int, back_cb: str = 'admin:panel') -> list[InlineKeyboardButton]:
    buttons: list[InlineKeyboardButton] = []
    if page > 0:
        buttons.append(InlineKeyboardButton(text='⬅️', callback_data=f'{prefix}:{page - 1}'))
    buttons.append(InlineKeyboardButton(text=f'{page + 1}/{total_pages}', callback_data='noop'))
    if page + 1 < total_pages:
        buttons.append(InlineKeyboardButton(text='➡️', callback_data=f'{prefix}:{page + 1}'))
    buttons.append(InlineKeyboardButton(text='🏠 Меню', callback_data=back_cb))
    return buttons


def clients_list_keyboard(page: int, total_pages: int, clients: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=f'admin:client:{tg_id}:{page}') ] for tg_id, label in clients]
    rows.append(_nav_row('admin:clients_list', page, total_pages))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def partners_list_keyboard(page: int, total_pages: int, partners: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=f'admin:partner:{tg_id}:{page}') ] for tg_id, label in partners]
    rows.append(_nav_row('admin:partners_list', page, total_pages))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admins_list_keyboard(page: int, total_pages: int, admins: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=f'admin:client:{tg_id}:{page}') ] for tg_id, label in admins]
    rows.append(_nav_row('admin:admins_list', page, total_pages))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_detail_keyboard(tg_id: int, page: int, is_partner: bool, is_admin_user: bool, sub_slots: list[int]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text='➕ Баланс оплаты', callback_data=f'admin:client_paybalance_up:{tg_id}:{page}')],
        [InlineKeyboardButton(text='➖ Баланс оплаты', callback_data=f'admin:client_paybalance_down:{tg_id}:{page}')],
        [InlineKeyboardButton(text='➕ Реф. баланс', callback_data=f'admin:client_refbalance_up:{tg_id}:{page}')],
        [InlineKeyboardButton(text='➖ Реф. баланс', callback_data=f'admin:client_refbalance_down:{tg_id}:{page}')],
        [InlineKeyboardButton(text='➕ Рефералы', callback_data=f'admin:client_refcount_up:{tg_id}:{page}')],
        [InlineKeyboardButton(text='➖ Рефералы', callback_data=f'admin:client_refcount_down:{tg_id}:{page}')],
        [InlineKeyboardButton(text='🔎 Реф. средства', callback_data=f'admin:client_refcalc:{tg_id}:{page}')],
        [InlineKeyboardButton(text='♻️ Сбросить лимит', callback_data=f'admin:client_reset_limit:{tg_id}:{page}')],
    ]
    if is_partner:
        rows.append([InlineKeyboardButton(text='🚫 Снять партнёра', callback_data=f'admin:client_partner_off:{tg_id}:{page}')])
    else:
        rows.append([InlineKeyboardButton(text='👑 Выдать партнёра', callback_data=f'admin:client_partner_on:{tg_id}:{page}')])
    if is_admin_user:
        rows.append([InlineKeyboardButton(text='🚫 Снять админа', callback_data=f'admin:client_admin_off:{tg_id}:{page}')])
    else:
        rows.append([InlineKeyboardButton(text='👑 Выдать админа', callback_data=f'admin:client_admin_on:{tg_id}:{page}')])
    if sub_slots:
        rows.append([InlineKeyboardButton(text='❌ Деактивировать подписку', callback_data=f'admin:client_sub_disable:{tg_id}:{page}')])
        rows.append([InlineKeyboardButton(text='🔑 Подписки клиента', callback_data=f'admin:client_subs:{tg_id}:{page}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=f'admin:clients_list:{page}')])
    rows.append([InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:home')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def partner_detail_keyboard(tg_id: int, page: int, is_partner: bool, is_admin_user: bool, sub_slots: list[int]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text='➕ Баланс оплаты', callback_data=f'admin:partner_paybalance_up:{tg_id}:{page}')],
        [InlineKeyboardButton(text='➖ Баланс оплаты', callback_data=f'admin:partner_paybalance_down:{tg_id}:{page}')],
        [InlineKeyboardButton(text='➕ Реф. баланс', callback_data=f'admin:partner_refbalance_up:{tg_id}:{page}')],
        [InlineKeyboardButton(text='➖ Реф. баланс', callback_data=f'admin:partner_refbalance_down:{tg_id}:{page}')],
        [InlineKeyboardButton(text='➕ Рефералы', callback_data=f'admin:partner_refcount_up:{tg_id}:{page}')],
        [InlineKeyboardButton(text='➖ Рефералы', callback_data=f'admin:partner_refcount_down:{tg_id}:{page}')],
        [InlineKeyboardButton(text='➕ Добавить реферала', callback_data=f'admin:partner_add_ref:{tg_id}:{page}')],
    ]
    if is_partner:
        rows.append([InlineKeyboardButton(text='🚫 Снять партнёра', callback_data=f'admin:partner_off:{tg_id}:{page}')])
    else:
        rows.append([InlineKeyboardButton(text='👑 Выдать партнёра', callback_data=f'admin:partner_on:{tg_id}:{page}')])
    if is_admin_user:
        rows.append([InlineKeyboardButton(text='🚫 Снять админа', callback_data=f'admin:partner_admin_off:{tg_id}:{page}')])
    else:
        rows.append([InlineKeyboardButton(text='👑 Выдать админа', callback_data=f'admin:partner_admin_on:{tg_id}:{page}')])
    rows.append([InlineKeyboardButton(text='🧪 +30 тест рефералов', callback_data=f'admin:partner_test_refs:{tg_id}:{page}')])
    if sub_slots:
        rows.append([InlineKeyboardButton(text='❌ Деактивировать подписку', callback_data=f'admin:partner_sub_disable:{tg_id}:{page}')])
        rows.append([InlineKeyboardButton(text='🔑 Подписки партнёра', callback_data=f'admin:partner_subs:{tg_id}:{page}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=f'admin:partners_list:{page}')])
    rows.append([InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:home')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_list_keyboard(tg_id: int, page: int, subs: list[int], back_cb: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f'Подписка {slot}', callback_data=f'admin:sub:{tg_id}:{slot}:{page}')] for slot in subs]
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=back_cb)])
    rows.append([InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:home')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_manage_keyboard(tg_id: int, slot: int, page: int, back_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='➕ Продлить', callback_data=f'admin:sub_extend:{tg_id}:{slot}:{page}')],
        [InlineKeyboardButton(text='🔧 Новый лимит', callback_data=f'admin:sub_limit:{tg_id}:{slot}:{page}')],
        [InlineKeyboardButton(text='♻️ Сбросить лимит', callback_data=f'admin:sub_reset_limit:{tg_id}:{slot}:{page}')],
        [InlineKeyboardButton(text='🧪 Проверить трафик', callback_data=f'admin:sub_check:{tg_id}:{slot}:{page}')],
        [InlineKeyboardButton(text='🚫 Снять подписку', callback_data=f'admin:sub_disable:{tg_id}:{slot}:{page}')],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data=back_cb)],
        [InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:home')],
    ])


def promo_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='➕ Добавить промокод', callback_data='admin:promo_add')],
        [InlineKeyboardButton(text='🔄 Обновить список', callback_data='admin:promos')],
        [InlineKeyboardButton(text='⬅️ Админка', callback_data='admin:panel')],
    ])


def promo_single_use_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Да', callback_data='admin:promo_single_use:1')],
        [InlineKeyboardButton(text='❌ Нет', callback_data='admin:promo_single_use:0')],
        [InlineKeyboardButton(text='❌ Отмена', callback_data='admin:panel')],
    ])


def promo_manage_keyboard(code: str, promo_type: str = 'discount') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🗑 Удалить', callback_data=f'admin:promo_delete:{code}')],
        [InlineKeyboardButton(text='🔄 Обновить список', callback_data='admin:promos')],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data='admin:promos')],
    ])


def promo_trial_activation_keyboard(bot_username: str, code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🎁 Активировать пробный период', callback_data='menu:trial')],
    ])


def trial_invitation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🎁 Активировать пробный период', callback_data='menu:trial')],
    ])
