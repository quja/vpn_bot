import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


DEFAULT_REF_PERCENT = int(os.getenv('DEFAULT_REF_PERCENT', '30'))
PARTNER_REF_PERCENT = int(os.getenv('PARTNER_REF_PERCENT', '50'))
REF_BONUS_COUNT = int(os.getenv('REF_BONUS_COUNT', '6'))
MOBILE_TRAFFIC_GB = int(os.getenv('MOBILE_TRAFFIC_GB', '50'))
MOBILE_REFILL_PRICE = int(os.getenv('MOBILE_REFILL_PRICE', '3'))
PARTNER_TRAFFIC_GB = int(os.getenv('PARTNER_TRAFFIC_GB', '50'))
TRIAL_TRAFFIC_GB = int(os.getenv('TRIAL_TRAFFIC_GB', '10'))
TRIAL_SQUAD_UUID = os.getenv('REMNAWAVE_SQUAD_3_UUID', '').strip()
TRIAL_TRAFFIC_LIMIT_GB = int(os.getenv('REMNAWAVE_SUB3_TRAFFIC_LIMIT_GB', str(TRIAL_TRAFFIC_GB)))

BASE_DIR = Path(__file__).resolve().parent.parent


def _resolve_path(value: str, default: str) -> str:
    raw = os.getenv(value, default).strip()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (BASE_DIR / path).resolve()
    return str(path)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_id: int
    support_chat_id: int
    db_path: str

    yookassa_shop_id: str
    yookassa_secret_key: str

    remnawave_base_url: str
    remnawave_token: str
    remnawave_caddy_token: str
    remnawave_squad_1_uuid: str
    remnawave_squad_2_uuid: str
    remnawave_squad_3_uuid: str
    remnawave_api_prefix: str
    remnawave_check_interval_sec: int

    profile_ad_text: str
    happ_import_url: str


def _to_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_settings() -> Settings:
    return Settings(
        bot_token=os.getenv('BOT_TOKEN', '').strip(),
        admin_id=_to_int(os.getenv('ADMIN_ID', '5447304193'), 5447304193),
        support_chat_id=_to_int(os.getenv('SUPPORT_CHAT_ID', '0')),
        db_path=_resolve_path('DB_PATH', '~/.noirlatch/bot.db'),
        yookassa_shop_id=os.getenv('YOOKASSA_SHOP_ID', '').strip(),
        yookassa_secret_key=os.getenv('YOOKASSA_SECRET_KEY', '').strip(),
        remnawave_base_url=os.getenv('REMNAWAVE_BASE_URL', '').strip(),
        remnawave_token=os.getenv('REMNAWAVE_TOKEN', '').strip(),
        remnawave_caddy_token=os.getenv('REMNAWAVE_CADDY_TOKEN', '').strip(),
        remnawave_squad_1_uuid=os.getenv('REMNAWAVE_SQUAD_1_UUID', '').strip(),
        remnawave_squad_2_uuid=os.getenv('REMNAWAVE_SQUAD_2_UUID', '').strip(),
        remnawave_squad_3_uuid=os.getenv('REMNAWAVE_SQUAD_3_UUID', '').strip(),
        remnawave_api_prefix=os.getenv('REMNAWAVE_API_PREFIX', '/api').strip(),
        remnawave_check_interval_sec=_to_int(os.getenv('REMNAWAVE_CHECK_INTERVAL_SEC', '1200')),
        profile_ad_text=os.getenv('PROFILE_AD_TEXT', '').strip(),
        happ_import_url=os.getenv('HAPP_IMPORT_URL', '').strip(),
    )


settings = load_settings()
