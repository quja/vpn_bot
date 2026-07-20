import os
import contextlib
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from .config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def utc_in_days(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec='seconds')


async def _table_columns(db: aiosqlite.Connection, table: str) -> set[str]:
    cursor = await db.execute(f'PRAGMA table_info({table})')
    rows = await cursor.fetchall()
    return {row[1] for row in rows}


async def _add_column_if_missing(db: aiosqlite.Connection, table: str, column_def: str) -> None:

    column_name = column_def.split()[0]
    columns = await _table_columns(db, table)
    if column_name not in columns:
        await db.execute(f'ALTER TABLE {table} ADD COLUMN {column_def}')




async def _ensure_users_promo_columns(db: aiosqlite.Connection) -> None:
    columns = await _table_columns(db, 'users')
    if 'promo_code' not in columns:
        await db.execute('ALTER TABLE users ADD COLUMN promo_code TEXT')
    if 'promo_discount' not in columns:
        await db.execute('ALTER TABLE users ADD COLUMN promo_discount INTEGER NOT NULL DEFAULT 0')
    if 'no_trial_notified_at' not in columns:
        await db.execute('ALTER TABLE users ADD COLUMN no_trial_notified_at TEXT')


async def _ensure_users_referral_payment_columns(db: aiosqlite.Connection) -> None:
    columns = await _table_columns(db, 'users')
    if 'referral_first_payment_marked' not in columns:
        await db.execute('ALTER TABLE users ADD COLUMN referral_first_payment_marked INTEGER NOT NULL DEFAULT 0')
    if 'referral_paid_at' not in columns:
        await db.execute('ALTER TABLE users ADD COLUMN referral_paid_at TEXT')


async def _ensure_promo_code_columns(db: aiosqlite.Connection) -> None:
    columns = await _table_columns(db, 'promo_codes')
    if 'promo_type' not in columns:
        await db.execute("ALTER TABLE promo_codes ADD COLUMN promo_type TEXT NOT NULL DEFAULT 'discount'")
    if 'trial_days' not in columns:
        await db.execute('ALTER TABLE promo_codes ADD COLUMN trial_days INTEGER NOT NULL DEFAULT 3')


async def _ensure_remnawave_subscription_columns(db: aiosqlite.Connection) -> None:
    columns = await _table_columns(db, 'remnawave_subscriptions')
    if 'mobile_disabled' not in columns:
        await db.execute('ALTER TABLE remnawave_subscriptions ADD COLUMN mobile_disabled INTEGER NOT NULL DEFAULT 0')
    if 'traffic_used_bytes' not in columns:
        await db.execute('ALTER TABLE remnawave_subscriptions ADD COLUMN traffic_used_bytes INTEGER NOT NULL DEFAULT 0')
    if 'traffic_used_at' not in columns:
        await db.execute('ALTER TABLE remnawave_subscriptions ADD COLUMN traffic_used_at TEXT')
    if 'traffic_reset_month' not in columns:
        await db.execute('ALTER TABLE remnawave_subscriptions ADD COLUMN traffic_reset_month TEXT')
    if 'traffic_reset_at' not in columns:
        await db.execute('ALTER TABLE remnawave_subscriptions ADD COLUMN traffic_reset_at TEXT')


async def _ensure_remnawave_subscription_notification_columns(db: aiosqlite.Connection) -> None:
    columns = await _table_columns(db, 'remnawave_subscriptions')
    for column_def in (
        'expire_notified_1d_at TEXT',
        'expire_notified_2h_at TEXT',
        'expire_notified_end_at TEXT',
        'trial_usage_notified_at TEXT',
    ):
        column_name = column_def.split()[0]
        if column_name not in columns:
            await db.execute(f'ALTER TABLE remnawave_subscriptions ADD COLUMN {column_def}')


async def _migrate_legacy_trial_users(db: aiosqlite.Connection) -> None:
    """Mark legacy trial holders as already used so trial stays one-time per account."""
    try:
        await db.execute(
            """
            UPDATE users
            SET trial_used = 1, updated_at = ?
            WHERE tg_id IN (
                SELECT DISTINCT user_tg_id
                FROM remnawave_subscriptions
                WHERE kind = 'trial' AND user_tg_id IS NOT NULL
            )
            """,
            (utc_now(),),
        )
    except Exception:
        pass


async def _purge_legacy_trial_subscriptions(db: aiosqlite.Connection) -> None:
    try:
        await db.execute("DELETE FROM remnawave_subscriptions WHERE kind = 'trial'")
    except Exception:
        pass


async def _ensure_subscription_reset_schedule(db: aiosqlite.Connection) -> None:
    try:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, COALESCE(updated_at, created_at) AS base_at
            FROM remnawave_subscriptions
            WHERE traffic_reset_at IS NULL OR traffic_reset_at = ''
            """
        )
        rows = await cursor.fetchall()
        for row in rows:
            base_raw = row['base_at']
            try:
                base_dt = datetime.fromisoformat(str(base_raw)) if base_raw else datetime.now(timezone.utc)
            except Exception:
                base_dt = datetime.now(timezone.utc)
            if base_dt.tzinfo is None:
                base_dt = base_dt.replace(tzinfo=timezone.utc)
            next_reset = (base_dt + timedelta(days=30)).isoformat(timespec='seconds')
            await db.execute(
                'UPDATE remnawave_subscriptions SET traffic_reset_at = ?, updated_at = ? WHERE id = ?',
                (next_reset, utc_now(), int(row['id'])),
            )
    except Exception:
        pass


async def init_db() -> None:
    db_dir = os.path.dirname(settings.db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL UNIQUE,
                username TEXT,
                first_name TEXT,
                referrer_id INTEGER,
                referral_marked_at TEXT,
                ref_balance REAL NOT NULL DEFAULT 0,
                payment_balance REAL NOT NULL DEFAULT 0,
                referral_balance REAL NOT NULL DEFAULT 0,
                trial_used INTEGER NOT NULL DEFAULT 0,
                trial_until TEXT,
                access_until TEXT,
                access_key TEXT,
                access_active INTEGER NOT NULL DEFAULT 0,
                promo_used INTEGER NOT NULL DEFAULT 0,
                promo_code TEXT,
                promo_discount INTEGER NOT NULL DEFAULT 0,
                is_partner INTEGER NOT NULL DEFAULT 0,
                is_admin INTEGER NOT NULL DEFAULT 0,
                partner_since TEXT,
                ref_paid_count INTEGER NOT NULL DEFAULT 0,
                referral_first_payment_marked INTEGER NOT NULL DEFAULT 0,
                partner_month TEXT,
                partner_month_ref_count INTEGER NOT NULL DEFAULT 0,
                partner_bonus_month TEXT,
                last_ref_bonus_date TEXT,
                referral_paid_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            '''
        )
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS payment_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id TEXT NOT NULL UNIQUE,
                tg_id INTEGER NOT NULL,
                tariff_code TEXT NOT NULL,
                amount INTEGER NOT NULL,
                days INTEGER NOT NULL,
                promo_code TEXT,
                promo_discount INTEGER NOT NULL DEFAULT 0,
                refill_gb INTEGER,
                refill_slot INTEGER,
                extend_slot INTEGER,
                mobile_limit_gb INTEGER,
                subscription_name TEXT,
                kind TEXT NOT NULL DEFAULT 'payment',
                status TEXT NOT NULL DEFAULT 'pending',
                remnawave_done INTEGER NOT NULL DEFAULT 0,
                notified_at TEXT,
                remnawave_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            '''
        )
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS remnawave_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_tg_id INTEGER,
                payment_id TEXT NOT NULL,
                slot INTEGER NOT NULL,
                kind TEXT NOT NULL DEFAULT 'payment',
                user_uuid TEXT NOT NULL,
                username TEXT NOT NULL,
                subscription_url TEXT NOT NULL,
                display_name TEXT,
                squad_uuid TEXT NOT NULL,
                traffic_limit_bytes INTEGER,
                traffic_limit_strategy TEXT,
                mobile_disabled INTEGER NOT NULL DEFAULT 0,
                expire_at TEXT,
                traffic_reset_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(payment_id, slot)
            )
            '''
        )
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS support_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                support_message_id INTEGER NOT NULL UNIQUE,
                user_tg_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            '''
        )
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            '''
        )
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS promo_redemptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                promo_code TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(tg_id, promo_code)
            )
            '''
        )
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                discount INTEGER NOT NULL DEFAULT 0,
                single_use INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                promo_type TEXT NOT NULL DEFAULT 'discount',
                trial_days INTEGER NOT NULL DEFAULT 3,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            '''
        )
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS promo_trial_recipients (
                code TEXT NOT NULL,
                tg_id INTEGER NOT NULL,
                activated_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(code, tg_id)
            )
            '''
        )

        await _add_column_if_missing(db, 'users', 'payment_balance REAL NOT NULL DEFAULT 0')
        await _ensure_users_promo_columns(db)
        await _ensure_promo_code_columns(db)
        await _add_column_if_missing(db, 'users', 'referral_marked_at TEXT')
        await _add_column_if_missing(db, 'users', 'referral_balance REAL NOT NULL DEFAULT 0')
        await _add_column_if_missing(db, 'users', 'is_partner INTEGER NOT NULL DEFAULT 0')
        await _add_column_if_missing(db, 'users', 'is_admin INTEGER NOT NULL DEFAULT 0')
        await _add_column_if_missing(db, 'users', 'partner_since TEXT')
        await _add_column_if_missing(db, 'users', 'ref_paid_count INTEGER NOT NULL DEFAULT 0')
        await _ensure_users_referral_payment_columns(db)
        await _add_column_if_missing(db, 'users', 'partner_month TEXT')
        await _add_column_if_missing(db, 'users', 'partner_month_ref_count INTEGER NOT NULL DEFAULT 0')
        await _add_column_if_missing(db, 'users', 'partner_bonus_month TEXT')
        await _add_column_if_missing(db, 'users', 'last_ref_bonus_date TEXT')
        await _add_column_if_missing(db, 'payment_orders', 'refill_gb INTEGER')
        await _add_column_if_missing(db, 'payment_orders', 'refill_slot INTEGER')
        await _add_column_if_missing(db, 'payment_orders', 'extend_slot INTEGER')
        await _add_column_if_missing(db, 'payment_orders', 'mobile_limit_gb INTEGER')
        await _add_column_if_missing(db, 'payment_orders', 'subscription_name TEXT')
        await _add_column_if_missing(db, 'payment_orders', "kind TEXT NOT NULL DEFAULT 'payment'")
        await _add_column_if_missing(db, 'remnawave_subscriptions', 'user_tg_id INTEGER')
        await _add_column_if_missing(db, 'remnawave_subscriptions', 'display_name TEXT')
        await _add_column_if_missing(db, 'remnawave_subscriptions', "kind TEXT NOT NULL DEFAULT 'payment'")
        await _add_column_if_missing(db, 'remnawave_subscriptions', 'traffic_limit_strategy TEXT')
        await _add_column_if_missing(db, 'remnawave_subscriptions', 'expire_at TEXT')
        await _add_column_if_missing(db, 'users', 'referral_paid_at TEXT')
        await _ensure_remnawave_subscription_columns(db)
        await _ensure_remnawave_subscription_notification_columns(db)
        await _migrate_legacy_trial_users(db)
        await _ensure_subscription_reset_schedule(db)
        await db.execute(
            """
            UPDATE payment_orders
            SET remnawave_done = 1, updated_at = ?
            WHERE status = 'succeeded'
              AND remnawave_done = 0
              AND COALESCE(remnawave_error, '') <> ''
            """,
            (utc_now(),),
        )


        await db.execute(
            """
            UPDATE users
            SET referral_first_payment_marked = 1, updated_at = ?
            WHERE referral_first_payment_marked = 0
              AND EXISTS (
                  SELECT 1
                  FROM payment_orders po
                  WHERE po.tg_id = users.tg_id
                    AND po.status = 'succeeded'
                    AND po.kind IN ('payment', 'refill', 'topup')
              )
            """,
            (utc_now(),),
        )
        await db.execute('CREATE INDEX IF NOT EXISTS idx_payment_orders_status ON payment_orders(status, remnawave_done)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_subscriptions_user_slot ON remnawave_subscriptions(user_tg_id, slot)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_subscriptions_user_kind ON remnawave_subscriptions(user_tg_id, kind, updated_at DESC, id DESC)')
        await db.commit()


async def get_user(tg_id: int):
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM users WHERE tg_id = ?', (tg_id,))
        return await cursor.fetchone()


async def upsert_user(tg_id: int, username: str | None, first_name: str | None, referrer_id: int | None = None) -> bool:
    now = utc_now()
    created = False
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_users_promo_columns(db)
        columns = await _table_columns(db, 'users')
        has_promo_discount = 'promo_discount' in columns
        cursor = await db.execute('SELECT tg_id, referrer_id FROM users WHERE tg_id = ?', (tg_id,))
        existing = await cursor.fetchone()

        if existing is None:
            created = True
            safe_referrer_id = referrer_id if referrer_id and referrer_id != tg_id else None
            if has_promo_discount:
                await db.execute(
                    '''
                    INSERT INTO users (tg_id, username, first_name, referrer_id, created_at, updated_at, promo_used, promo_discount, referral_first_payment_marked, referral_paid_at)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, NULL)
                    ''',
                    (tg_id, username, first_name, safe_referrer_id, now, now),
                )
            else:
                await db.execute(
                    '''
                    INSERT INTO users (tg_id, username, first_name, referrer_id, created_at, updated_at, promo_used, referral_first_payment_marked, referral_paid_at)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 0, NULL)
                    ''',
                    (tg_id, username, first_name, safe_referrer_id, now, now),
                )
        else:
            await db.execute('UPDATE users SET username = ?, first_name = ?, updated_at = ? WHERE tg_id = ?', (username, first_name, now, tg_id))
            if existing['referrer_id'] is None and referrer_id and referrer_id != tg_id:
                await db.execute('UPDATE users SET referrer_id = ?, referral_marked_at = ?, updated_at = ? WHERE tg_id = ?', (referrer_id, now, now, tg_id))
        await db.commit()
    return created


async def update_user_fields(tg_id: int, **fields: Any) -> None:
    if not fields:
        return
    now = utc_now()
    fields = dict(fields)
    fields['updated_at'] = now
    clauses = []
    values: list[Any] = []
    for key, value in fields.items():
        clauses.append(f'{key} = ?')
        values.append(value)
    values.append(tg_id)
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT 1 FROM users WHERE tg_id = ? LIMIT 1', (tg_id,))
        existing = await cursor.fetchone()
        if existing is None:
            await db.execute(
                'INSERT INTO users (tg_id, created_at, updated_at) VALUES (?, ?, ?)',
                (tg_id, now, now),
            )
        await db.execute(f"UPDATE users SET {', '.join(clauses)} WHERE tg_id = ?", tuple(values))
        await db.commit()


async def adjust_user_balance(tg_id: int, field: str, delta: float) -> None:
    if field not in {'payment_balance', 'referral_balance'}:
        raise ValueError(f'Invalid balance field: {field}')
    now = utc_now()
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            f'UPDATE users SET {field} = COALESCE({field}, 0) + ?, updated_at = ? WHERE tg_id = ?',
            (delta, now, tg_id),
        )
        await db.commit()


async def transfer_user_balance(tg_id: int, from_field: str, to_field: str, amount: float) -> bool:
    if from_field not in {'ref_balance', 'payment_balance', 'referral_balance'} or to_field not in {'ref_balance', 'payment_balance', 'referral_balance'}:
        raise ValueError('Invalid balance field')
    if from_field == to_field:
        return True
    now = utc_now()
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(f'SELECT {from_field} AS source_balance FROM users WHERE tg_id = ? LIMIT 1', (tg_id,))
        row = await cursor.fetchone()
        source = float(row['source_balance'] or 0) if row else 0.0
        if source < amount:
            return False
        await db.execute(
            f'UPDATE users SET {from_field} = COALESCE({from_field}, 0) - ?, {to_field} = COALESCE({to_field}, 0) + ?, updated_at = ? WHERE tg_id = ?',
            (amount, amount, now, tg_id),
        )
        await db.commit()
    return True


async def set_user_partner(tg_id: int, is_partner: bool) -> None:
    fields: dict[str, Any] = {'is_partner': 1 if is_partner else 0}
    if is_partner:
        fields['partner_since'] = utc_now()
    else:
        fields['partner_since'] = None
        fields['partner_bonus_month'] = None
        fields['partner_month'] = None
        fields['partner_month_ref_count'] = 0
    await update_user_fields(tg_id, **fields)


async def set_user_admin(tg_id: int, is_admin: bool) -> None:
    await update_user_fields(tg_id, is_admin=1 if is_admin else 0)


async def mark_trial_used(tg_id: int, trial_until: str) -> None:
    await update_user_fields(tg_id, trial_used=1, trial_until=trial_until, access_until=trial_until, access_active=1)


async def reserve_trial_access(tg_id: int, trial_until: str) -> bool:
    now = utc_now()
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        try:
            await db.execute('BEGIN IMMEDIATE')
            cursor = await db.execute('SELECT COALESCE(trial_used, 0) AS trial_used FROM users WHERE tg_id = ? LIMIT 1', (tg_id,))
            user = await cursor.fetchone()
            if not user or int(user['trial_used'] or 0) == 1:
                await db.execute('ROLLBACK')
                return False
            cursor = await db.execute("SELECT 1 FROM remnawave_subscriptions WHERE user_tg_id = ? AND kind = 'trial' LIMIT 1", (tg_id,))
            if await cursor.fetchone():
                await db.execute('ROLLBACK')
                return False
            await db.execute(
                'UPDATE users SET trial_used = 1, trial_until = ?, access_until = ?, access_active = 1, updated_at = ? WHERE tg_id = ?',
                (trial_until, trial_until, now, tg_id),
            )
            await db.commit()
            return True
        except Exception:
            with contextlib.suppress(Exception):
                await db.execute('ROLLBACK')
            raise


async def set_user_access(tg_id: int, access_until: str, access_active: int = 1) -> None:
    await update_user_fields(tg_id, access_until=access_until, access_active=access_active)


async def increment_ref_paid_count(tg_id: int) -> int:
    user = await get_user(tg_id)
    current = int(user['ref_paid_count'] or 0) if user else 0
    new_value = current + 1
    await update_user_fields(tg_id, ref_paid_count=new_value)
    return new_value


async def adjust_ref_paid_count(tg_id: int, delta: int) -> int:
    user = await get_user(tg_id)
    current = int(user['ref_paid_count'] or 0) if user else 0
    new_value = max(0, current + int(delta))
    await update_user_fields(tg_id, ref_paid_count=new_value)
    return new_value


async def set_partner_month_state(tg_id: int, month: str, count: int) -> None:
    await update_user_fields(tg_id, partner_month=month, partner_month_ref_count=count)


async def set_partner_bonus_month(tg_id: int, month: str) -> None:
    await update_user_fields(tg_id, partner_bonus_month=month)


async def set_last_ref_bonus_date(tg_id: int, month_key: str) -> None:
    await update_user_fields(tg_id, last_ref_bonus_date=month_key)


async def clear_user_promo(tg_id: int) -> None:
    now = utc_now()
    async with aiosqlite.connect(settings.db_path) as db:
        await _ensure_users_promo_columns(db)
        await db.execute('UPDATE users SET promo_code = NULL, promo_discount = 0, updated_at = ? WHERE tg_id = ?', (now, tg_id))
        await db.commit()


async def set_user_promo(tg_id: int, promo_code: str, promo_discount: int) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await _ensure_users_promo_columns(db)
    await update_user_fields(tg_id, promo_code=promo_code, promo_discount=promo_discount)


async def has_promo_redemption(tg_id: int, promo_code: str) -> bool:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT 1 FROM promo_redemptions WHERE tg_id = ? AND promo_code = ? LIMIT 1', (tg_id, promo_code))
        return await cursor.fetchone() is not None


async def mark_promo_redemption(tg_id: int, promo_code: str) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute('INSERT OR IGNORE INTO promo_redemptions (tg_id, promo_code, created_at) VALUES (?, ?, ?)', (tg_id, promo_code, utc_now()))
        await db.commit()


async def list_promo_codes(active_only: bool = False):
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        if active_only:
            cursor = await db.execute('SELECT * FROM promo_codes WHERE is_active = 1 ORDER BY updated_at DESC, code ASC')
        else:
            cursor = await db.execute('SELECT * FROM promo_codes ORDER BY is_active DESC, updated_at DESC, code ASC')
        return await cursor.fetchall()


async def get_promo_code_row(code: str):
    code = str(code or '').strip().upper()
    if not code:
        return None
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM promo_codes WHERE code = ? LIMIT 1', (code,))
        return await cursor.fetchone()


async def upsert_promo_code(code: str, discount: int = 0, single_use: bool = False, is_active: bool = True, promo_type: str = 'discount', trial_days: int = 3) -> None:
    code = str(code or '').strip().upper()
    if not code:
        raise ValueError('Promo code is empty')
    now = utc_now()
    promo_type = str(promo_type or 'discount').strip().lower() or 'discount'
    async with aiosqlite.connect(settings.db_path) as db:
        await _ensure_promo_code_columns(db)
        await db.execute(
            '''
            INSERT INTO promo_codes (code, discount, single_use, is_active, promo_type, trial_days, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                discount = excluded.discount,
                single_use = excluded.single_use,
                is_active = excluded.is_active,
                promo_type = excluded.promo_type,
                trial_days = excluded.trial_days,
                updated_at = excluded.updated_at
            '''
            ,
            (code, int(discount), 1 if single_use else 0, 1 if is_active else 0, promo_type, int(trial_days), now, now),
        )
        await db.commit()


async def set_promo_code_active(code: str, is_active: bool) -> None:
    code = str(code or '').strip().upper()
    if not code:
        return
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute('UPDATE promo_codes SET is_active = ?, updated_at = ? WHERE code = ?', (1 if is_active else 0, utc_now(), code))
        await db.commit()


async def delete_promo_code(code: str) -> None:
    code = str(code or '').strip().upper()
    if not code:
        return
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute('DELETE FROM promo_codes WHERE code = ?', (code,))
        await db.execute('DELETE FROM promo_trial_recipients WHERE code = ?', (code,))
        await db.commit()


async def upsert_promo_trial_recipient(code: str, tg_id: int) -> None:
    code = str(code or '').strip().upper()
    if not code or int(tg_id or 0) <= 0:
        return
    now = utc_now()
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            '''
            INSERT INTO promo_trial_recipients (code, tg_id, activated_at, created_at, updated_at)
            VALUES (?, ?, NULL, ?, ?)
            ON CONFLICT(code, tg_id) DO UPDATE SET
                updated_at = excluded.updated_at
            '''
            ,
            (code, int(tg_id), now, now),
        )
        await db.commit()


async def get_promo_trial_recipient(code: str, tg_id: int):
    code = str(code or '').strip().upper()
    if not code or int(tg_id or 0) <= 0:
        return None
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM promo_trial_recipients WHERE code = ? AND tg_id = ? LIMIT 1', (code, int(tg_id)))
        return await cursor.fetchone()


async def mark_promo_trial_recipient_activated(code: str, tg_id: int) -> None:
    code = str(code or '').strip().upper()
    if not code or int(tg_id or 0) <= 0:
        return
    now = utc_now()
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute('UPDATE promo_trial_recipients SET activated_at = COALESCE(activated_at, ?), updated_at = ? WHERE code = ? AND tg_id = ?', (now, now, code, int(tg_id)))
        await db.commit()


async def create_payment_order(
    payment_id: str,
    tg_id: int,
    tariff_code: str,
    amount: int,
    days: int,
    promo_code: str | None,
    promo_discount: int,
    kind: str = 'payment',
    status: str = 'pending',
    remnawave_done: int = 0,
    refill_gb: int | None = None,
    refill_slot: int | None = None,
    extend_slot: int | None = None,
    mobile_limit_gb: int | None = None,
    subscription_name: str | None = None,
) -> None:
    now = utc_now()
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            '''
            INSERT OR REPLACE INTO payment_orders
            (payment_id, tg_id, tariff_code, amount, days, promo_code, promo_discount, refill_gb, refill_slot, extend_slot, mobile_limit_gb, subscription_name, kind, status, remnawave_done, notified_at, remnawave_error, created_at, updated_at)
            VALUES (:payment_id, :tg_id, :tariff_code, :amount, :days, :promo_code, :promo_discount, :refill_gb, :refill_slot, :extend_slot, :mobile_limit_gb, :subscription_name, :kind, :status, :remnawave_done, :notified_at, :remnawave_error, :created_at, :updated_at)
            ''',
            {
                'payment_id': payment_id,
                'tg_id': tg_id,
                'tariff_code': tariff_code,
                'amount': amount,
                'days': days,
                'promo_code': promo_code,
                'promo_discount': promo_discount,
                'refill_gb': refill_gb,
                'refill_slot': refill_slot,
                'extend_slot': extend_slot,
                'mobile_limit_gb': mobile_limit_gb,
                'subscription_name': subscription_name,
                'kind': kind,
                'status': status,
                'remnawave_done': remnawave_done,
                'notified_at': None,
                'remnawave_error': None,
                'created_at': now,
                'updated_at': now,
            },
        )
        await db.commit()


async def get_payment_order(payment_id: str):
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM payment_orders WHERE payment_id = ? LIMIT 1', (payment_id,))
        return await cursor.fetchone()


async def get_pending_payment_orders():
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            '''
            SELECT * FROM payment_orders
            WHERE kind IN ('payment', 'topup', 'refill')
              AND (
                    status = 'pending'
                 OR (status = 'succeeded' AND remnawave_done = 0)
              )
            ORDER BY id ASC
            '''
        )
        return await cursor.fetchall()


async def mark_payment_status(
    payment_id: str,
    status: str,
    remnawave_done: int | None = None,
    remnawave_error: str | None = None,
    notified_at: str | None = None,
) -> None:
    now = utc_now()
    fields = ['status = ?', 'updated_at = ?']
    values: list[Any] = [status, now]

    if remnawave_done is not None:
        fields.append('remnawave_done = ?')
        values.append(remnawave_done)
    if remnawave_error is not None:
        fields.append('remnawave_error = ?')
        values.append(remnawave_error)
    if notified_at is not None:
        fields.append('notified_at = ?')
        values.append(notified_at)

    values.append(payment_id)
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(f"UPDATE payment_orders SET {', '.join(fields)} WHERE payment_id = ?", tuple(values))
        await db.commit()


async def save_remnawave_subscription(
    payment_id: str,
    user_tg_id: int,
    slot: int,
    user_uuid: str,
    username: str,
    subscription_url: str,
    squad_uuid: str,
    traffic_limit_bytes: int | None,
    kind: str = 'payment',
    display_name: str | None = None,
    traffic_limit_strategy: str | None = None,
    expire_at: str | None = None,
    traffic_reset_at: str | None = None,
) -> None:
    now = utc_now()
    if traffic_reset_at is None:
        traffic_reset_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(timespec='seconds')
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            'SELECT id FROM remnawave_subscriptions WHERE user_tg_id = ? AND slot = ? LIMIT 1',
            (user_tg_id, slot),
        )
        existing = await cursor.fetchone()
        if existing:
            await db.execute(
                '''
                UPDATE remnawave_subscriptions
                SET payment_id = :payment_id, kind = :kind, user_uuid = :user_uuid, username = :username, subscription_url = :subscription_url, display_name = :display_name, squad_uuid = :squad_uuid, traffic_limit_bytes = :traffic_limit_bytes, traffic_limit_strategy = :traffic_limit_strategy, expire_at = :expire_at, traffic_reset_at = :traffic_reset_at, expire_notified_1d_at = NULL, expire_notified_2h_at = NULL, expire_notified_end_at = NULL, trial_usage_notified_at = NULL, updated_at = :updated_at
                WHERE id = :id
                '''
                ,
                {
                    'payment_id': payment_id,
                    'kind': kind,
                    'user_uuid': user_uuid,
                    'username': username,
                    'subscription_url': subscription_url,
                    'display_name': display_name,
                    'squad_uuid': squad_uuid,
                    'traffic_limit_bytes': traffic_limit_bytes,
                    'traffic_limit_strategy': traffic_limit_strategy,
                    'expire_at': expire_at,
                    'traffic_reset_at': traffic_reset_at,
                    'updated_at': now,
                    'id': existing['id'],
                },
            )
        else:
            await db.execute(
                '''
                INSERT INTO remnawave_subscriptions
                (user_tg_id, payment_id, slot, kind, user_uuid, username, subscription_url, display_name, squad_uuid, traffic_limit_bytes, traffic_limit_strategy, expire_at, traffic_reset_at, expire_notified_1d_at, expire_notified_2h_at, expire_notified_end_at, trial_usage_notified_at, created_at, updated_at)
                VALUES (:user_tg_id, :payment_id, :slot, :kind, :user_uuid, :username, :subscription_url, :display_name, :squad_uuid, :traffic_limit_bytes, :traffic_limit_strategy, :expire_at, :traffic_reset_at, :expire_notified_1d_at, :expire_notified_2h_at, :expire_notified_end_at, :trial_usage_notified_at, :created_at, :updated_at)
                '''
                ,
                {
                    'user_tg_id': user_tg_id,
                    'payment_id': payment_id,
                    'slot': slot,
                    'kind': kind,
                    'user_uuid': user_uuid,
                    'username': username,
                    'subscription_url': subscription_url,
                    'display_name': display_name,
                    'squad_uuid': squad_uuid,
                    'traffic_limit_bytes': traffic_limit_bytes,
                    'traffic_limit_strategy': traffic_limit_strategy,
                    'expire_at': expire_at,
                    'traffic_reset_at': traffic_reset_at,
                    'expire_notified_1d_at': None,
                    'expire_notified_2h_at': None,
                    'expire_notified_end_at': None,
                    'trial_usage_notified_at': None,
                    'created_at': now,
                    'updated_at': now,
                },
            )
        await db.commit()


async def update_remnawave_subscription_usage(tg_id: int, slot: int, used_bytes: int, checked_at: str | None = None) -> None:
    now = checked_at or utc_now()
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            'UPDATE remnawave_subscriptions SET traffic_used_bytes = ?, traffic_used_at = ?, updated_at = ? WHERE user_tg_id = ? AND slot = ?',
            (used_bytes, now, now, tg_id, slot),
        )
        await db.commit()


async def update_remnawave_subscription_limit(tg_id: int, slot: int, traffic_limit_bytes: int) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            'UPDATE remnawave_subscriptions SET traffic_limit_bytes = ?, updated_at = ? WHERE user_tg_id = ? AND slot = ?',
            (traffic_limit_bytes, utc_now(), tg_id, slot),
        )
        await db.commit()


async def update_remnawave_subscription_reset_at(tg_id: int, slot: int, traffic_reset_at: str | None) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await _ensure_remnawave_subscription_columns(db)
        await db.execute(
            'UPDATE remnawave_subscriptions SET traffic_reset_at = ?, updated_at = ? WHERE user_tg_id = ? AND slot = ?',
            (traffic_reset_at, utc_now(), tg_id, slot),
        )
        await db.commit()


async def update_remnawave_subscription_identity(tg_id: int, slot: int, *, user_uuid: str | None = None, username: str | None = None) -> None:
    fields = []
    values = []
    if user_uuid is not None:
        fields.append('user_uuid = ?')
        values.append(user_uuid)
    if username is not None:
        fields.append('username = ?')
        values.append(username)
    if not fields:
        return
    fields.append('updated_at = ?')
    values.append(utc_now())
    values.extend([tg_id, slot])
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            f"UPDATE remnawave_subscriptions SET {', '.join(fields)} WHERE user_tg_id = ? AND slot = ?",
            tuple(values),
        )
        await db.commit()


async def update_remnawave_subscription_fields(tg_id: int, slot: int, **fields: Any) -> None:
    if not fields:
        return
    now = utc_now()
    clauses = [f'{key} = ?' for key in fields]
    values = list(fields.values())
    values.extend([now, tg_id, slot])
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            f"UPDATE remnawave_subscriptions SET {', '.join(clauses)}, updated_at = ? WHERE user_tg_id = ? AND slot = ?",
            tuple(values),
        )
        await db.commit()


async def set_remnawave_subscription_mobile_disabled(tg_id: int, slot: int, mobile_disabled: int) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await _ensure_remnawave_subscription_columns(db)
        await db.execute(
            'UPDATE remnawave_subscriptions SET mobile_disabled = ?, updated_at = ? WHERE user_tg_id = ? AND slot = ?',
            (1 if mobile_disabled else 0, utc_now(), tg_id, slot),
        )
        await db.commit()


async def get_remnawave_subscriptions(payment_id: str):
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM remnawave_subscriptions WHERE payment_id = ? ORDER BY slot ASC', (payment_id,))
        return await cursor.fetchall()


async def get_remnawave_subscription_by_user_slot(tg_id: int, slot: int):
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            'SELECT * FROM remnawave_subscriptions WHERE user_tg_id = ? AND slot = ? ORDER BY updated_at DESC, id DESC LIMIT 1',
            (tg_id, slot),
        )
        return await cursor.fetchone()


async def get_all_remnawave_subscriptions():
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM remnawave_subscriptions ORDER BY user_tg_id ASC, slot ASC, updated_at DESC, id DESC')
        return await cursor.fetchall()


async def get_user_subscriptions(tg_id: int):
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM remnawave_subscriptions WHERE user_tg_id = ? ORDER BY slot ASC, updated_at DESC, id DESC', (tg_id,))
        return await cursor.fetchall()


async def get_user_subscriptions_by_kind(tg_id: int, kind: str):
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM remnawave_subscriptions WHERE user_tg_id = ? AND kind = ? ORDER BY slot ASC, updated_at DESC, id DESC', (tg_id, kind))
        return await cursor.fetchall()


async def get_next_subscription_slot(tg_id: int) -> int:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT COALESCE(MAX(slot), 0) AS max_slot FROM remnawave_subscriptions WHERE user_tg_id = ?', (tg_id,))
        row = await cursor.fetchone()
        return int(row['max_slot'] or 0) + 1


async def get_latest_active_subscription(tg_id: int):
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            '''
            SELECT * FROM remnawave_subscriptions
            WHERE user_tg_id = ?
            ORDER BY COALESCE(expire_at, '') DESC, updated_at DESC, id DESC
            LIMIT 1
            ''',
            (tg_id,),
        )
        return await cursor.fetchone()


async def get_meta_value(key: str) -> str | None:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT value FROM app_meta WHERE key = ? LIMIT 1', (key,))
        row = await cursor.fetchone()
        return row['value'] if row else None


async def set_meta_value(key: str, value: str) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            'INSERT INTO app_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
            (key, value),
        )
        await db.commit()


async def delete_user_subscriptions(tg_id: int) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute('DELETE FROM remnawave_subscriptions WHERE user_tg_id = ?', (tg_id,))
        await db.commit()


async def delete_user_subscriptions_by_kind(tg_id: int, kind: str) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute('DELETE FROM remnawave_subscriptions WHERE user_tg_id = ? AND kind = ?', (tg_id, kind))
        await db.commit()


async def delete_user_subscription_slot(tg_id: int, slot: int) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute('DELETE FROM remnawave_subscriptions WHERE user_tg_id = ? AND slot = ?', (tg_id, slot))
        await db.commit()


async def delete_all_user_subscriptions() -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute('DELETE FROM remnawave_subscriptions')
        await db.commit()


async def deactivate_all_users_access() -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute('UPDATE users SET access_active = 0, access_until = NULL, access_key = NULL, updated_at = ?', (utc_now(),))
        await db.commit()


async def purge_all_local_subscriptions_once() -> int:
    marker = await get_meta_value('purged_local_subscriptions_v1')
    if marker == '1':
        return 0
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute('DELETE FROM remnawave_subscriptions')
        await db.execute('UPDATE users SET access_active = 0, access_until = NULL, access_key = NULL, updated_at = ?', (utc_now(),))
        await db.commit()
    await set_meta_value('purged_local_subscriptions_v1', '1')
    return 1

async def save_support_links(support_message_ids: list[int], user_tg_id: int) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        for mid in support_message_ids:
            await db.execute('INSERT OR REPLACE INTO support_links (support_message_id, user_tg_id, created_at) VALUES (?, ?, ?)', (mid, user_tg_id, utc_now()))
        await db.commit()


async def get_user_id_by_support_message(support_message_id: int) -> int | None:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT user_tg_id FROM support_links WHERE support_message_id = ?', (support_message_id,))
        row = await cursor.fetchone()
        return row['user_tg_id'] if row else None


async def get_referral_count(tg_id: int) -> int:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT COALESCE(ref_paid_count, 0) AS count FROM users WHERE tg_id = ? LIMIT 1', (tg_id,))
        row = await cursor.fetchone()
        return int(row['count']) if row else 0


async def get_month_referral_count(tg_id: int, month_key: str) -> int:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            '''
            SELECT COUNT(*) AS count
            FROM users
            WHERE referrer_id = ?
              AND COALESCE(referral_paid_at, '') LIKE ?
            ''',
            (tg_id, f'{month_key}%'),
        )
        row = await cursor.fetchone()
        return int(row['count']) if row else 0


async def get_active_partners():
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        # Не скрываем партнёров, если у них одновременно есть статус админа.
        cursor = await db.execute('SELECT * FROM users WHERE is_partner = 1 ORDER BY partner_since DESC, tg_id DESC')
        return await cursor.fetchall()


async def get_active_clients():
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM users WHERE access_active = 1 AND is_partner = 0 AND is_admin = 0 ORDER BY updated_at DESC, tg_id DESC')
        return await cursor.fetchall()


async def get_active_admins():
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM users WHERE is_admin = 1 ORDER BY updated_at DESC, tg_id DESC')
        return await cursor.fetchall()


async def get_all_users():
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            '''
            SELECT * FROM users
            WHERE tg_id > 0
              AND (COALESCE(username, '') <> '' OR COALESCE(first_name, '') <> '')
            ORDER BY COALESCE(updated_at, created_at) DESC, tg_id DESC
            '''
        )
        return await cursor.fetchall()


async def get_trial_promo_broadcast_targets():
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            '''
            SELECT DISTINCT u.*
            FROM users u
            WHERE u.tg_id > 0
              AND (COALESCE(u.username, '') <> '' OR COALESCE(u.first_name, '') <> '')
              AND (COALESCE(u.trial_used, 0) = 1
                   OR EXISTS (SELECT 1 FROM remnawave_subscriptions s WHERE s.user_tg_id = u.tg_id AND s.kind = 'trial'))
              AND NOT EXISTS (
                  SELECT 1
                  FROM remnawave_subscriptions s
                  WHERE s.user_tg_id = u.tg_id
                    AND s.kind IN ('payment', 'balance_new', 'balance_renew', 'renew', 'admin_test', 'partner_grant')
              )
            ORDER BY COALESCE(u.updated_at, u.created_at) DESC, u.tg_id DESC
            '''
        )
        return await cursor.fetchall()


async def get_no_trial_broadcast_targets(days_old: int = 1):
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days_old, 0))
    cutoff_iso = cutoff.isoformat(timespec='seconds')
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            '''
            SELECT DISTINCT u.*
            FROM users u
            WHERE u.tg_id > 0
              AND (COALESCE(u.username, '') <> '' OR COALESCE(u.first_name, '') <> '')
              AND COALESCE(u.trial_used, 0) = 0
              AND COALESCE(u.no_trial_notified_at, '') = ''
              AND COALESCE(u.created_at, '') <= ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM remnawave_subscriptions s
                  WHERE s.user_tg_id = u.tg_id
                    AND s.kind IN ('trial', 'promo_trial')
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM remnawave_subscriptions s
                  WHERE s.user_tg_id = u.tg_id
                    AND s.kind IN ('payment', 'balance_new', 'balance_renew', 'renew', 'admin_test', 'partner_grant')
              )
            ORDER BY COALESCE(u.updated_at, u.created_at) DESC, u.tg_id DESC
            ''',
            (cutoff_iso,),
        )
        return await cursor.fetchall()


async def search_users(query: str, limit: int = 50):
    query = str(query or '').strip()
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        base_filter = "tg_id > 0 AND (COALESCE(username, '') <> '' OR COALESCE(first_name, '') <> '')"
        if not query:
            cursor = await db.execute(
                f'SELECT * FROM users WHERE {base_filter} ORDER BY COALESCE(updated_at, created_at) DESC, tg_id DESC LIMIT ?',
                (limit,),
            )
            return await cursor.fetchall()
        if query.isdigit():
            cursor = await db.execute(
                f'''
                SELECT * FROM users
                WHERE ({base_filter})
                  AND (tg_id = ? OR CAST(tg_id AS TEXT) LIKE ? OR COALESCE(username, '') LIKE ? OR COALESCE(first_name, '') LIKE ?)
                ORDER BY COALESCE(updated_at, created_at) DESC, tg_id DESC
                LIMIT ?
                '''
                ,
                (int(query), f'%{query}%', f'%{query}%', f'%{query}%', limit),
            )
        else:
            needle = f'%{query}%'
            cursor = await db.execute(
                f'''
                SELECT * FROM users
                WHERE {base_filter}
                  AND (COALESCE(username, '') LIKE ? COLLATE NOCASE
                       OR COALESCE(first_name, '') LIKE ? COLLATE NOCASE
                       OR CAST(tg_id AS TEXT) LIKE ?)
                ORDER BY COALESCE(updated_at, created_at) DESC, tg_id DESC
                LIMIT ?
                '''
                ,
                (needle, needle, needle, limit),
            )
        return await cursor.fetchall()

