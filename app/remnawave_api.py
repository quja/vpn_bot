from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx

from .config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemnawaveSubscriptionSpec:
    slot: int
    squad_uuid: str
    traffic_limit_gb: int


class RemnawaveClient:
    def __init__(self) -> None:
        base = settings.remnawave_base_url.rstrip("/")
        self.api_base = base if base.endswith("/api") else f"{base}/api"
        self.headers = {
            "Authorization": f"Bearer {settings.remnawave_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _clean(self, data: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in data.items() if v is not None}

    def _mask_headers(self) -> dict[str, str]:
        headers = dict(self.headers)
        auth = headers.get("Authorization", "")
        if auth.startswith("Bearer ") and len(auth) > 20:
            headers["Authorization"] = auth[:12] + "…" + auth[-4:]
        return headers

    def _normalize_tag(self, value: str) -> str:
        value = re.sub(r"[^A-Z0-9_]", "_", value.upper())
        value = re.sub(r"_+", "_", value).strip("_")
        return value[:15]

    def _make_tag(self, telegram_id: int, suffix: str = "1") -> str:
        base = f"TG{telegram_id}_{suffix}"
        tag = self._normalize_tag(base)
        if len(tag) <= 15:
            return tag
        short_id = str(telegram_id)[-10:]
        return self._normalize_tag(f"TG{short_id}_{suffix}")[:15]

    def _make_username(self, telegram_id: int, *, salt: str = "") -> str:
        digest = hashlib.sha1(f"{telegram_id}:{salt}".encode("utf-8")).hexdigest()[:6]
        # Safe for Remnawave's <36 char limit and still human-readable.
        return f"tg{telegram_id}_{digest}"[:35]

    def _unwrap(self, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("response"), (dict, list)):
            return data["response"]
        return data

    def _unwrap_user_response(self, data: Any) -> dict[str, Any]:
        data = self._unwrap(data)
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                return first
        return {}

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.api_base}{path}"

        logger.debug(
            "Remnawave request: %s %s | headers=%s | payload=%s | params=%s",
            method,
            url,
            self._mask_headers(),
            json,
            params,
        )

        async with httpx.AsyncClient(timeout=30.0, headers=self.headers, follow_redirects=True) as client:
            response = await client.request(method, url, json=json, params=params)

        text = response.text.strip()
        body = None
        if text:
            try:
                body = response.json()
            except Exception:
                body = text

        logger.debug("Remnawave response: %s %s -> %s | body=%s", method, url, response.status_code, body)

        if response.status_code == 404:
            if path.startswith("/bandwidth-stats/users/"):
                logger.debug("Remnawave stats not found: %s %s", method, url)
            elif path.startswith("/users/by-username/") or path.startswith("/users/by-telegram-id/") or path.startswith("/users/"):
                logger.debug("Remnawave user lookup 404: %s %s | body=%s", method, url, body)
            else:
                logger.warning("Remnawave 404: %s %s | body=%s", method, url, body)
            return None

        response.raise_for_status()
        if not text:
            return None
        try:
            return response.json()
        except Exception:
            return text

    async def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        data = await self._request("GET", f"/users/by-username/{quote(username)}")
        return self._unwrap_user_response(data) if data else None

    async def get_user_by_uuid(self, user_uuid: str) -> dict[str, Any] | None:
        data = await self._request("GET", f"/users/{quote(user_uuid)}")
        return self._unwrap_user_response(data) if data else None

    async def get_user_traffic(self, user_uuid: str, *, start: str | None = None, end: str | None = None) -> dict[str, Any] | None:
        params: dict[str, str] = {}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        for path in (f"/bandwidth-stats/users/{quote(user_uuid)}", f"/bandwidth-stats/users/{quote(user_uuid)}/legacy"):
            data = await self._request("GET", path, params=params or None)
            if not data:
                continue
            unwrapped = self._unwrap(data)
            if isinstance(unwrapped, dict):
                return unwrapped
            if isinstance(unwrapped, list):
                return {"items": unwrapped, "data": unwrapped, "response": unwrapped}
        return None

    def _build_create_user_variants(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        base = self._clean(payload)
        if not base:
            return [{}]

        variants: list[dict[str, Any]] = []

        def add(drop_keys: set[str]) -> None:
            candidate = {k: v for k, v in base.items() if k not in drop_keys}
            if candidate not in variants:
                variants.append(candidate)

        # Start with the full payload, then remove the most suspicious fields one
        # by one. This keeps the feature working even if Remnawave changes the
        # create-user schema slightly between versions.
        add(set())
        add({"trafficLimitStrategy"})
        add({"trafficLimitStrategy", "trafficLimitBytes"})
        add({"trafficLimitStrategy", "trafficLimitBytes", "activeInternalSquads"})
        add({"trafficLimitStrategy", "trafficLimitBytes", "activeInternalSquads", "telegramId"})
        add({"trafficLimitStrategy", "trafficLimitBytes", "activeInternalSquads", "telegramId", "description"})
        add({"trafficLimitStrategy", "trafficLimitBytes", "activeInternalSquads", "telegramId", "description", "tag"})
        add({"trafficLimitStrategy", "trafficLimitBytes", "activeInternalSquads", "telegramId", "description", "tag", "expireAt"})
        add({"trafficLimitStrategy", "trafficLimitBytes", "activeInternalSquads", "telegramId", "description", "tag", "expireAt", "status"})
        add({"trafficLimitStrategy", "trafficLimitBytes", "activeInternalSquads", "telegramId", "description", "tag", "expireAt", "status", "uuid", "userUuid", "user_uuid"})
        if not variants:
            variants = [base]
        return variants

    async def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        variants = self._build_create_user_variants(payload)
        last_exc: Exception | None = None
        clean_payload = self._clean(payload)

        async def _reuse_existing_user(candidate: dict[str, Any], exc: Exception | None = None) -> dict[str, Any] | None:
            username = str(candidate.get("username") or clean_payload.get("username") or "").strip()
            telegram_id = candidate.get("telegramId", clean_payload.get("telegramId"))
            existing: dict[str, Any] | None = None

            if username:
                try:
                    existing = await self.get_user_by_username(username)
                except Exception as lookup_exc:
                    logger.warning("Remnawave username lookup failed for %s: %s", username, lookup_exc)

            if not existing and telegram_id is not None:
                try:
                    users = await self.find_user_by_telegram_id(int(telegram_id))
                    if users:
                        existing = users[0]
                except Exception as lookup_exc:
                    logger.warning("Remnawave telegram lookup failed for %s: %s", telegram_id, lookup_exc)

            if not existing:
                return None

            try:
                merged = dict(candidate)
                merged["uuid"] = existing.get("uuid")
                merged.pop("userUuid", None)
                merged.pop("user_uuid", None)
                return await self.update_user(merged)
            except Exception as update_exc:
                logger.warning(
                    "Remnawave existing user reuse failed: username=%s uuid=%s | %s",
                    username,
                    existing.get("uuid"),
                    update_exc,
                )
                return existing

        for index, candidate in enumerate(variants, start=1):
            try:
                data = await self._request("POST", "/users", json=candidate)
                user = self._unwrap_user_response(data)
                if not user:
                    raise RuntimeError("Remnawave create user returned empty response")
                if candidate != clean_payload:
                    try:
                        # Best-effort enrich the created user with any optional metadata.
                        enrich = dict(clean_payload)
                        enrich.pop("uuid", None)
                        enrich.pop("userUuid", None)
                        enrich.pop("user_uuid", None)
                        enrich["uuid"] = user.get("uuid")
                        await self.update_user(enrich)
                    except Exception as exc:
                        logger.warning("Remnawave post-create enrichment failed: %s", exc)
                return user
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status = getattr(exc.response, "status_code", None)
                body = getattr(exc.response, "text", "") or ""
                if status in {400, 409, 422}:
                    logger.warning(
                        "Remnawave create user variant %s/%s failed with %s: payload_keys=%s body=%s",
                        index,
                        len(variants),
                        status,
                        list(candidate.keys()),
                        body[:1000],
                    )
                    if status in {400, 409} and ("already exists" in body.lower() or "A019" in body or "username" in body.lower()):
                        reused = await _reuse_existing_user(candidate, exc)
                        if reused:
                            return reused
                    continue
                raise
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Remnawave create user variant %s/%s failed: payload_keys=%s | %s",
                    index,
                    len(variants),
                    list(candidate.keys()),
                    exc,
                )
                continue

        if last_exc:
            raise last_exc
        raise RuntimeError("Remnawave create user failed")

    async def _resolve_user_for_update(self, data: dict[str, Any]) -> dict[str, Any] | None:
        user_uuid = str(data.get("uuid") or data.get("userUuid") or data.get("user_uuid") or "").strip()
        telegram_id = data.get("telegramId")
        username = str(data.get("username") or "").strip()

        if user_uuid:
            current = await self.get_user_by_uuid(user_uuid)
            if current:
                return current

        if telegram_id is not None:
            try:
                users = await self.find_user_by_telegram_id(int(telegram_id))
                if users:
                    return users[0]
            except Exception:
                pass

        if username:
            current = await self.get_user_by_username(username)
            if current:
                return current

        return None

    async def update_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._clean(payload)
        current = await self._resolve_user_for_update(data)
        user_uuid = str(data.get("uuid") or data.get("userUuid") or data.get("user_uuid") or "").strip()
        if current and current.get("uuid"):
            user_uuid = str(current.get("uuid") or user_uuid).strip()

        body = dict(data)
        if user_uuid:
            body["uuid"] = user_uuid
            body.setdefault("userUuid", user_uuid)
            body.setdefault("user_uuid", user_uuid)

        if not user_uuid:
            if current:
                return current
            return await self.create_user(body)

        try:
            response = await self._request("PUT", f"/users/{quote(user_uuid)}", json=body)
            user = self._unwrap_user_response(response)
            if user:
                return user
        except Exception as exc:
            logger.warning("Remnawave update attempt failed: PUT /users/%s | %s", user_uuid, exc)

        if current:
            return current

        created = await self.create_user(body)
        if created:
            return created
        raise RuntimeError("Remnawave update user returned empty response")

    async def delete_user(self, user_uuid: str) -> dict[str, Any] | None:
        return await self._request("POST", "/users/bulk/delete", json={"uuids": [str(user_uuid)]})

    async def bulk_delete_users(self, user_uuids: list[str]) -> dict[str, Any] | None:
        uuids = [str(uuid).strip() for uuid in user_uuids if str(uuid).strip()]
        if not uuids:
            return None
        return await self._request("POST", "/users/bulk/delete", json={"uuids": uuids})

    async def disable_user(self, user_uuid: str) -> dict[str, Any] | None:
        return await self._request("POST", f"/users/{quote(user_uuid)}/actions/disable")

    async def enable_user(self, user_uuid: str) -> dict[str, Any] | None:
        return await self._request("POST", f"/users/{quote(user_uuid)}/actions/enable")

    async def reset_user_traffic(self, user_uuid: str) -> dict[str, Any] | None:
        return await self._request("POST", f"/users/{quote(user_uuid)}/actions/reset-traffic")

    async def create_or_update_subscription(
        self,
        telegram_id: int,
        slot: int,
        days: int,
        squad_uuid: str,
        traffic_limit_gb: int,
        base_username: str,
        description: str,
        traffic_limit_strategy: str = "NO_RESET",
        existing_uuid: str | None = None,
        active_internal_squads: list[str] | None = None,
        username: str | None = None,
        reuse_existing: bool = False,
    ) -> dict[str, Any]:
        user_uuid = (existing_uuid or "").strip() or None
        current = await self.get_user_by_uuid(user_uuid) if user_uuid else None
        if reuse_existing and current is None and telegram_id is not None:
            try:
                existing_users = await self.find_user_by_telegram_id(int(telegram_id))
                if existing_users:
                    current = existing_users[0]
            except Exception:
                pass
        if reuse_existing and current is None and base_username:
            try:
                current = await self.get_user_by_username(base_username)
            except Exception:
                pass

        expire_at = None
        if current and current.get("expireAt") and reuse_existing:
            expire_at = current["expireAt"]
        elif days > 0:
            expire_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")

        username = (str(username).strip() if username else "") or self._make_username(telegram_id, salt=f"{slot}:{base_username or 'sub'}")
        payload: dict[str, Any] = {
            "username": username,
            "telegramId": telegram_id,
            "expireAt": expire_at,
            "status": "ACTIVE",
            "trafficLimitStrategy": traffic_limit_strategy,
            "trafficLimitBytes": 0,
            "description": description,
            "activeInternalSquads": active_internal_squads or [squad_uuid],
            "tag": self._make_tag(telegram_id, str(slot)),
        }

        if current and current.get("uuid"):
            payload["uuid"] = current["uuid"]
            return await self.update_user(payload)

        try:
            return await self.create_user(payload)
        except Exception:
            if reuse_existing:
                logger.warning("Remnawave create/update failed for reusable subscription; falling back to current record if present")
                if current:
                    return current
            raise

    async def create_two_subscriptions(
        self,
        telegram_id: int,
        days: int,
        squad_uuid_1: str,
        squad_uuid_2: str,
        traffic_limit_gb_1: int,
        traffic_limit_gb_2: int,
    ) -> list[dict[str, Any]]:
        description = f"TG {telegram_id} / paid access"
        user = await self.create_or_update_subscription(
            telegram_id=telegram_id,
            slot=1,
            days=days,
            squad_uuid=squad_uuid_1 or squad_uuid_2,
            traffic_limit_gb=0,
            base_username=str(telegram_id),
            description=description,
            traffic_limit_strategy="NO_RESET",
            active_internal_squads=[u for u in (squad_uuid_1, squad_uuid_2) if u],
            reuse_existing=False,
        )
        return [user]

    async def create_subscription_pair(self, **kwargs: Any) -> list[dict[str, Any]]:
        return await self.create_two_subscriptions(
            telegram_id=int(kwargs.get("telegram_id")),
            days=int(kwargs.get("days", 30)),
            squad_uuid_1=str(kwargs.get("wifi_squad_uuid") or kwargs.get("squad_uuid_1") or ""),
            squad_uuid_2=str(kwargs.get("mobile_squad_uuid") or kwargs.get("squad_uuid_2") or ""),
            traffic_limit_gb_1=int(kwargs.get("wifi_traffic_gb", 0)),
            traffic_limit_gb_2=int(kwargs.get("mobile_traffic_gb", 0)),
        )

    async def find_user_by_telegram_id(self, telegram_id: int) -> list[dict[str, Any]]:
        data = await self._request("GET", f"/users/by-telegram-id/{telegram_id}")
        data = self._unwrap(data)
        if not data:
            return []
        if isinstance(data, dict) and isinstance(data.get("response"), list):
            return [item for item in data["response"] if isinstance(item, dict)]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
        return []


remnawave = RemnawaveClient()
