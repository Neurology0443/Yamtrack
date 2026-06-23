"""Cache helpers for complete MAL anime franchise UI payloads."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

logger = logging.getLogger(__name__)

_REQUIRED_ENTRY_KEYS = {"media_id", "source", "media_type", "title"}
_ALIASABLE_SECTION_KEYS = {"continuity_extras"}

_FORBIDDEN_ENTRY_KEYS = {
    "media",
    "item",
    "status",
    "progress",
    "user",
    "user_id",
    "current_user",
    "html",
    "rendered_html",
}


PAYLOAD_ROLE_GLOBAL = "global"
PAYLOAD_ROLE_DETAIL_SCOPED = "detail_scoped"
PAYLOAD_KIND_CANONICAL_FRANCHISE = "canonical_franchise"
DETAIL_PAYLOAD_KIND_SEED_CONTEXT = "seed_context"
VALID_DETAIL_PAYLOAD_KINDS = {
    DETAIL_PAYLOAD_KIND_SEED_CONTEXT,
}


def get_global_payload_key(media_id) -> str:
    """Return the canonical global franchise payload cache key."""
    return f"mal_anime_franchise_{media_id}"


def get_global_meta_key(media_id) -> str:
    """Return the global payload sidecar metadata cache key."""
    return f"{get_global_payload_key(media_id)}:meta"


def get_scoped_payload_key(media_id) -> str:
    """Return the detail-scoped franchise payload cache key."""
    return f"mal_anime_franchise_scoped_{media_id}"


def get_scoped_meta_key(media_id) -> str:
    """Return the scoped payload sidecar metadata cache key."""
    return f"{get_scoped_payload_key(media_id)}:meta"


def get_alias_key(media_id) -> str:
    """Return the lightweight alias key for a MAL anime franchise payload."""
    return f"mal_anime_franchise_alias_{media_id}"


def get_alias_index_key(canonical_media_id) -> str:
    """Return the index key listing aliases for a canonical payload."""
    return f"{get_global_payload_key(canonical_media_id)}:aliases"


@dataclass(frozen=True)
class FranchisePayloadLookup:
    """Resolved role-specific franchise payload lookup result."""

    requested_media_id: str
    canonical_media_id: str
    payload: dict | None
    meta: dict


@dataclass(frozen=True)
class DetailFranchisePayloadLookup:
    """Resolved detail-page franchise payload lookup result."""

    requested_media_id: str
    cache_media_id: str
    canonical_media_id: str
    payload: dict[str, Any]
    meta: dict[str, Any]
    hit_kind: str
    payload_role: str
    detail_payload_kind: str | None = None


def get_queue_lock_key(media_id) -> str:
    """Return the enqueue deduplication lock key."""
    return f"{get_global_payload_key(media_id)}:queue_lock"


def get_task_lock_key(media_id) -> str:
    """Return the worker execution deduplication lock key."""
    return f"{get_global_payload_key(media_id)}:task_lock"


def get_build_meta_key(media_id) -> str:
    """Return build/scheduling metadata key for media_id."""
    return f"mal_anime_franchise_build_{media_id}:meta"


def get_ttl_seconds() -> int:
    """Return the long-lived TTL for franchise payloads and metadata."""
    return settings.ANIME_FRANCHISE_CACHE_TTL_DAYS * 24 * 60 * 60


def get_queue_lock_ttl_seconds() -> int:
    """Return the enqueue lock TTL in seconds."""
    return settings.ANIME_FRANCHISE_QUEUE_LOCK_MINUTES * 60


def get_task_lock_ttl_seconds() -> int:
    """Return the task lock TTL in seconds."""
    return settings.ANIME_FRANCHISE_TASK_LOCK_MINUTES * 60


def _entry_media_id(entry) -> str | None:
    if not isinstance(entry, dict):
        return None
    media_id = entry.get("media_id")
    if media_id in (None, ""):
        return None
    return str(media_id)


def _extract_entry_media_ids(entries) -> set[str]:
    media_ids = set()
    if not isinstance(entries, list):
        return media_ids

    for entry in entries:
        media_id = _entry_media_id(entry)
        if media_id:
            media_ids.add(media_id)
    return media_ids


def extract_series_media_ids(payload: dict) -> set[str]:
    """Return media IDs explicitly present in the main series line."""
    if not isinstance(payload, dict):
        return set()

    series = payload.get("series")
    if not isinstance(series, dict):
        return set()

    return _extract_entry_media_ids(series.get("entries", []))


def extract_aliasable_media_ids(payload: dict) -> set[str]:
    """Return media IDs allowed to resolve to a canonical franchise payload."""
    if not isinstance(payload, dict):
        return set()

    media_ids = extract_series_media_ids(payload)

    sections = payload.get("sections")
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            if section.get("key") not in _ALIASABLE_SECTION_KEYS:
                continue
            media_ids.update(_extract_entry_media_ids(section.get("entries", [])))

    return media_ids


def extract_payload_media_ids(payload: dict) -> set[str]:
    """Return all media IDs explicitly present in a complete franchise payload."""
    if not isinstance(payload, dict):
        return set()

    media_ids = extract_series_media_ids(payload)

    sections = payload.get("sections")
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            media_ids.update(_extract_entry_media_ids(section.get("entries", [])))

    return media_ids


def determine_canonical_media_id(payload: dict, fallback_media_id) -> str:
    """Return the canonical media ID for a complete franchise payload."""
    fallback_media_id = str(fallback_media_id)

    if not isinstance(payload, dict):
        return fallback_media_id

    series = payload.get("series")
    if isinstance(series, dict):
        entries = series.get("entries")
        if isinstance(entries, list) and entries:
            first_media_id = _entry_media_id(entries[0])
            if first_media_id:
                return first_media_id

    canonical_root_media_id = payload.get("canonical_root_media_id")
    if canonical_root_media_id not in (None, ""):
        return str(canonical_root_media_id)

    return fallback_media_id


def _find_payload_entry_title(payload: dict, media_id: str) -> str:
    media_id = str(media_id)

    series = payload.get("series")
    if isinstance(series, dict):
        for entry in series.get("entries", []):
            if _entry_media_id(entry) == media_id and entry.get("title"):
                return str(entry["title"])

    sections = payload.get("sections")
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            for entry in section.get("entries", []):
                if _entry_media_id(entry) == media_id and entry.get("title"):
                    return str(entry["title"])

    return ""


def prepare_payload_for_aliasing(
    payload: dict,
    *,
    build_seed_media_id,
    truncated: bool,
    aliases_enabled: bool | None = None,
) -> tuple[dict, str, set[str]]:
    """Return payload with canonical root and explicit alias coverage metadata."""
    payload = dict(payload)
    build_seed_media_id = str(build_seed_media_id)
    if aliases_enabled is None:
        aliases_enabled = settings.ANIME_FRANCHISE_CACHE_ALIASES_ENABLED

    if truncated or not aliases_enabled:
        payload["root_media_id"] = build_seed_media_id
        payload["canonical_root_media_id"] = build_seed_media_id
        payload["aliasable_media_ids"] = [build_seed_media_id]
        payload["covered_media_ids"] = sorted(extract_payload_media_ids(payload))
        return payload, build_seed_media_id, {build_seed_media_id}

    canonical_media_id = determine_canonical_media_id(
        payload,
        fallback_media_id=build_seed_media_id,
    )

    aliasable_media_ids = extract_aliasable_media_ids(payload)
    covered_media_ids = extract_payload_media_ids(payload)

    if canonical_media_id not in aliasable_media_ids:
        aliasable_media_ids.add(canonical_media_id)

    if canonical_media_id not in covered_media_ids:
        covered_media_ids.add(canonical_media_id)

    if build_seed_media_id == canonical_media_id:
        aliasable_media_ids.add(build_seed_media_id)

    payload["root_media_id"] = canonical_media_id
    payload["canonical_root_media_id"] = canonical_media_id
    payload["aliasable_media_ids"] = sorted(aliasable_media_ids)
    payload["covered_media_ids"] = sorted(covered_media_ids)

    if canonical_media_id != build_seed_media_id:
        canonical_title = _find_payload_entry_title(payload, canonical_media_id)
        if canonical_title:
            payload["display_title"] = canonical_title

    return payload, canonical_media_id, aliasable_media_ids


def _build_alias_record(*, canonical_media_id: str, aliased_media_id: str) -> dict:
    now = timezone.now().isoformat()
    return {
        "schema_version": settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION,
        "canonical_media_id": str(canonical_media_id),
        "aliased_media_id": str(aliased_media_id),
        "created_at": now,
    }


def _normalize_alias_record(alias) -> dict | None:
    if not isinstance(alias, dict):
        return None
    if alias.get("schema_version") != settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION:
        return None

    canonical_media_id = alias.get("canonical_media_id")
    aliased_media_id = alias.get("aliased_media_id")
    if canonical_media_id in (None, "") or aliased_media_id in (None, ""):
        return None

    return {
        "schema_version": settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION,
        "canonical_media_id": str(canonical_media_id),
        "aliased_media_id": str(aliased_media_id),
        "created_at": alias.get("created_at") or "",
    }


def payload_covers_media_id(payload: dict, media_id) -> bool:
    """Return whether a cached payload explicitly allows aliasing for media_id."""
    if not isinstance(payload, dict):
        return False

    aliasable_media_ids = payload.get("aliasable_media_ids")
    if not isinstance(aliasable_media_ids, list):
        return False

    return str(media_id) in {str(item) for item in aliasable_media_ids}


def _serialize_datetime(value):
    if value is None or isinstance(value, str):
        return value
    return value.isoformat()


def _safe_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_cached_datetime(value):
    """Parse a cached aware/naive ISO datetime value into an aware datetime."""
    if value in (None, ""):
        return None
    if hasattr(value, "tzinfo"):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = parse_datetime(value)
        except (TypeError, ValueError):
            return None
    else:
        return None
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def default_meta(**overrides) -> dict:
    """Return normalized default metadata for a franchise payload sidecar."""
    meta = {
        "schema_version": settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION,
        "fetched_at": None,
        "last_accessed_at": timezone.now().isoformat(),
        "node_count": 0,
        "build_duration_seconds": None,
        "truncated": False,
        "truncation_reason": "",
        "last_success_at": None,
    }
    meta.update(overrides)
    meta["fetched_at"] = _serialize_datetime(meta.get("fetched_at"))
    meta["last_accessed_at"] = _serialize_datetime(meta.get("last_accessed_at"))
    meta["last_success_at"] = _serialize_datetime(meta.get("last_success_at"))
    if meta["truncation_reason"] is None:
        meta["truncation_reason"] = ""
    meta["truncated"] = bool(meta.get("truncated"))
    return meta


def normalize_meta(meta) -> dict:
    """Return sidecar metadata with all expected keys populated."""
    base = default_meta()
    if not isinstance(meta, dict):
        return base

    for key in base:
        if key in meta:
            base[key] = meta[key]

    normalized = default_meta(**base)
    if not isinstance(normalized.get("schema_version"), int):
        normalized["schema_version"] = settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION
    if not normalized.get("last_accessed_at"):
        normalized["last_accessed_at"] = timezone.now().isoformat()
    normalized["truncation_reason"] = normalized.get("truncation_reason") or ""
    normalized["node_count"] = _safe_int(normalized.get("node_count"), 0)
    normalized["truncated"] = bool(normalized.get("truncated"))
    return normalized


def _touch_or_set(key, value, ttl) -> bool:
    try:
        if cache.touch(key, timeout=ttl):
            return True
    except (AttributeError, NotImplementedError, TypeError):
        pass

    if value is None:
        value = cache.get(key)
    if value is None:
        return False
    cache.set(key, value, timeout=ttl)
    return True


def _count_nodes(payload: dict) -> int:
    media_ids = set()
    for entry in payload.get("series", {}).get("entries", []):
        media_ids.add(str(entry.get("media_id")))
    for section in payload.get("sections", []):
        for entry in section.get("entries", []):
            media_ids.add(str(entry.get("media_id")))
    media_ids.discard("None")
    return len(media_ids)


def _is_non_empty_string(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_bool_compatible(value) -> bool:
    return isinstance(value, bool)


def _is_valid_entry(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    return all(_is_non_empty_string(entry.get(key)) for key in _REQUIRED_ENTRY_KEYS)


def _is_valid_series(series) -> bool:
    if not isinstance(series, dict):
        return False
    if "key" in series and not isinstance(series["key"], str):
        return False
    if "title" in series and not isinstance(series["title"], str):
        return False
    entries = series.get("entries")
    if not isinstance(entries, list):
        return False
    return all(_is_valid_entry(entry) for entry in entries)


def _is_valid_section(section) -> bool:
    if not isinstance(section, dict):
        return False
    entries = section.get("entries")
    visible_in_ui = section.get("visible_in_ui")
    hidden_if_empty = section.get("hidden_if_empty")
    return (
        _is_non_empty_string(section.get("key"))
        and _is_non_empty_string(section.get("title"))
        and isinstance(entries, list)
        and all(_is_valid_entry(entry) for entry in entries)
        and ("visible_in_ui" not in section or _is_bool_compatible(visible_in_ui))
        and ("hidden_if_empty" not in section or _is_bool_compatible(hidden_if_empty))
    )


def is_valid_payload(payload) -> bool:
    """Return whether a cached payload is structurally render-compatible."""
    if not isinstance(payload, dict):
        return False
    sections = payload.get("sections")
    return (
        payload.get("schema_version") == settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION
        and _is_non_empty_string(payload.get("root_media_id"))
        and _is_non_empty_string(payload.get("display_title"))
        and _is_valid_series(payload.get("series"))
        and isinstance(sections, list)
        and all(_is_valid_section(section) for section in sections)
    )


def assert_json_safe_payload(payload: dict) -> None:
    """Raise if a franchise payload cannot be JSON serialized."""
    try:
        json.dumps(payload)
    except (TypeError, ValueError) as exc:
        message = "MAL anime franchise payload is not JSON-safe"
        raise ValueError(message) from exc


def _contains_forbidden_user_data(value) -> bool:
    if isinstance(value, dict):
        for key, inner_value in value.items():
            if key in _FORBIDDEN_ENTRY_KEYS:
                return True
            if _contains_forbidden_user_data(inner_value):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_user_data(item) for item in value)
    return False


def _has_required_role_fields(payload: Mapping[str, Any], role: str) -> bool:
    if payload.get("payload_role") != role:
        return False
    if not _is_non_empty_string(payload.get("build_seed_media_id")):
        return False
    if role == PAYLOAD_ROLE_GLOBAL:
        return payload.get("payload_kind") == PAYLOAD_KIND_CANONICAL_FRANCHISE
    return (
        payload.get("detail_payload_kind") in VALID_DETAIL_PAYLOAD_KINDS
        and _is_non_empty_string(payload.get("rule_key"))
        and _is_non_empty_string(payload.get("global_canonical_root_media_id"))
    )


def is_valid_global_payload(payload: Mapping[str, Any]) -> bool:
    """Return whether payload is a valid canonical global franchise payload."""
    return (
        is_valid_payload(payload)
        and _has_required_role_fields(payload, PAYLOAD_ROLE_GLOBAL)
        and not _contains_forbidden_user_data(payload)
    )


def is_valid_scoped_payload(payload: Mapping[str, Any]) -> bool:
    """Return whether payload is a valid detail-scoped franchise payload."""
    return (
        is_valid_payload(payload)
        and _has_required_role_fields(payload, PAYLOAD_ROLE_DETAIL_SCOPED)
        and not _contains_forbidden_user_data(payload)
    )


def _validate_json_safe(payload: Mapping[str, Any]) -> bool:
    try:
        assert_json_safe_payload(dict(payload))
    except ValueError:
        return False
    return True


def _load_payload_from_keys(
    *,
    media_id: str,
    payload_key: str,
    meta_key: str,
    expected_role: str,
    validator: Callable[[Mapping[str, Any]], bool],
    delete_invalid: Callable[[], None],
) -> FranchisePayloadLookup | None:
    payload = cache.get(payload_key)
    meta = normalize_meta(cache.get(meta_key))
    if payload is None:
        return None
    if not validator(payload) or not _validate_json_safe(payload):
        logger.warning(
            "Deleting invalid MAL anime franchise %s payload for media_id=%s",
            expected_role,
            media_id,
        )
        delete_invalid()
        return None

    ttl = get_ttl_seconds()
    meta["last_accessed_at"] = timezone.now().isoformat()
    _touch_or_set(payload_key, payload, ttl)
    cache.set(meta_key, meta, timeout=ttl)
    return FranchisePayloadLookup(
        requested_media_id=str(media_id),
        canonical_media_id=str(payload.get("canonical_root_media_id") or media_id),
        payload=dict(payload),
        meta=meta,
    )


def _write_payload_to_keys(
    *,
    payload_key: str,
    meta_key: str,
    payload: Mapping[str, Any],
    expected_role: str,
    validator: Callable[[Mapping[str, Any]], bool],
    timeout: int,
    meta: Mapping[str, Any] | None = None,
) -> dict:
    payload = dict(payload)
    payload["schema_version"] = settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION
    if payload.get("payload_role") != expected_role:
        message = f"Invalid MAL anime franchise payload role: {expected_role}"
        raise ValueError(message)
    if not validator(payload) or not _validate_json_safe(payload):
        message = "Invalid MAL anime franchise payload"
        raise ValueError(message)
    saved_meta = normalize_meta(meta)
    cache.set(payload_key, payload, timeout=timeout)
    cache.set(meta_key, saved_meta, timeout=timeout)
    return saved_meta


def load_global_payload(media_id) -> FranchisePayloadLookup | None:
    """Load only a canonical global payload for media_id."""
    media_id = str(media_id)
    return _load_payload_from_keys(
        media_id=media_id,
        payload_key=get_global_payload_key(media_id),
        meta_key=get_global_meta_key(media_id),
        expected_role=PAYLOAD_ROLE_GLOBAL,
        validator=is_valid_global_payload,
        delete_invalid=lambda: delete_global_payload(media_id),
    )


def load_scoped_payload(media_id) -> FranchisePayloadLookup | None:
    """Load only a detail-scoped payload for media_id."""
    media_id = str(media_id)
    return _load_payload_from_keys(
        media_id=media_id,
        payload_key=get_scoped_payload_key(media_id),
        meta_key=get_scoped_meta_key(media_id),
        expected_role=PAYLOAD_ROLE_DETAIL_SCOPED,
        validator=is_valid_scoped_payload,
        delete_invalid=lambda: delete_scoped_payload(media_id),
    )


def delete_global_payload(media_id) -> None:
    """Delete a canonical global cached payload and metadata for media_id."""
    media_id = str(media_id)
    cache.delete(get_global_payload_key(media_id))
    cache.delete(get_global_meta_key(media_id))


def delete_scoped_payload(media_id) -> None:
    """Delete a detail-scoped cached payload and metadata for media_id."""
    media_id = str(media_id)
    cache.delete(get_scoped_payload_key(media_id))
    cache.delete(get_scoped_meta_key(media_id))


def delete_alias_for_media(media_id) -> None:
    """Delete an alias and remove it from its canonical alias index."""
    media_id = str(media_id)
    alias_key = get_alias_key(media_id)
    alias = _normalize_alias_record(cache.get(alias_key))
    cache.delete(alias_key)
    if alias is None:
        return
    alias_index_key = get_alias_index_key(alias["canonical_media_id"])
    alias_ids = cache.get(alias_index_key)
    if not isinstance(alias_ids, list):
        return
    remaining = [str(alias_id) for alias_id in alias_ids if str(alias_id) != media_id]
    if remaining:
        cache.set(alias_index_key, remaining, timeout=get_ttl_seconds())
    else:
        cache.delete(alias_index_key)


def _delete_alias_if_owned_by(media_id, canonical_media_id) -> bool:
    media_id = str(media_id)
    canonical_media_id = str(canonical_media_id)
    alias = _normalize_alias_record(cache.get(get_alias_key(media_id)))
    if alias is None:
        cache.delete(get_alias_key(media_id))
        return True
    if alias["canonical_media_id"] != canonical_media_id:
        return False
    cache.delete(get_alias_key(media_id))
    return True


def delete_aliases_for_canonical(canonical_media_id) -> None:
    """Delete every alias owned by canonical_media_id."""
    canonical_media_id = str(canonical_media_id)
    alias_ids = cache.get(get_alias_index_key(canonical_media_id))
    if isinstance(alias_ids, list):
        for media_id in alias_ids:
            _delete_alias_if_owned_by(media_id, canonical_media_id)
    cache.delete(get_alias_index_key(canonical_media_id))


def replace_aliases(
    canonical_media_id, payload: dict, *, truncated: bool = False
) -> int:
    """Replace lightweight alias records for a canonical global franchise payload."""
    canonical_media_id = str(canonical_media_id)
    if not settings.ANIME_FRANCHISE_CACHE_ALIASES_ENABLED:
        return 0
    if truncated:
        delete_aliases_for_canonical(canonical_media_id)
        return 0
    payload = dict(payload)
    payload.setdefault(
        "schema_version", settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION
    )
    if not is_valid_global_payload(payload):
        return 0
    aliasable_media_ids = payload.get("aliasable_media_ids")
    if not isinstance(aliasable_media_ids, list):
        return 0
    new_alias_ids = {
        str(mid) for mid in aliasable_media_ids if str(mid) != canonical_media_id
    }
    ttl = get_ttl_seconds()
    old_alias_ids = cache.get(get_alias_index_key(canonical_media_id))
    if not isinstance(old_alias_ids, list):
        old_alias_ids = []
    for old_media_id in old_alias_ids:
        if str(old_media_id) not in new_alias_ids:
            _delete_alias_if_owned_by(old_media_id, canonical_media_id)
    for aliased_media_id in sorted(new_alias_ids):
        delete_global_payload(aliased_media_id)
        cache.set(
            get_alias_key(aliased_media_id),
            _build_alias_record(
                canonical_media_id=canonical_media_id, aliased_media_id=aliased_media_id
            ),
            timeout=ttl,
        )
    cache.set(
        get_alias_index_key(canonical_media_id), sorted(new_alias_ids), timeout=ttl
    )
    return len(new_alias_ids)


def _load_alias_for_media(media_id) -> dict | None:
    media_id = str(media_id)
    alias = _normalize_alias_record(cache.get(get_alias_key(media_id)))
    if alias is None:
        return None
    if alias["aliased_media_id"] != media_id:
        cache.delete(get_alias_key(media_id))
        return None
    return alias


def load_valid_alias_payload_for_media(media_id) -> FranchisePayloadLookup | None:
    """Load alias target only if it resolves to a valid global payload."""
    requested_media_id = str(media_id)
    if not settings.ANIME_FRANCHISE_CACHE_ALIASES_ENABLED:
        return None
    alias = _load_alias_for_media(requested_media_id)
    if alias is None:
        return None
    canonical_media_id = alias["canonical_media_id"]
    if canonical_media_id == requested_media_id:
        cache.delete(get_alias_key(requested_media_id))
        return None
    lookup = load_global_payload(canonical_media_id)
    if lookup is None or not payload_covers_media_id(
        lookup.payload, requested_media_id
    ):
        logger.warning(
            "Deleting invalid MAL anime franchise alias for media_id=%s "
            "canonical_media_id=%s",
            requested_media_id,
            canonical_media_id,
        )
        cache.delete(get_alias_key(requested_media_id))
        return None
    return FranchisePayloadLookup(
        requested_media_id=requested_media_id,
        canonical_media_id=canonical_media_id,
        payload=lookup.payload,
        meta=lookup.meta,
    )


def load_detail_franchise_payload(media_id) -> DetailFranchisePayloadLookup | None:
    """Resolve detail payload with strict scoped -> global -> alias priority."""
    requested_media_id = str(media_id)
    scoped = load_scoped_payload(requested_media_id)
    if scoped and scoped.payload is not None:
        return DetailFranchisePayloadLookup(
            requested_media_id=requested_media_id,
            cache_media_id=requested_media_id,
            canonical_media_id=str(
                scoped.payload.get("global_canonical_root_media_id")
                or scoped.canonical_media_id
            ),
            payload=scoped.payload,
            meta=scoped.meta,
            hit_kind="scoped_exact",
            payload_role=PAYLOAD_ROLE_DETAIL_SCOPED,
            detail_payload_kind=scoped.payload.get("detail_payload_kind"),
        )
    global_lookup = load_global_payload(requested_media_id)
    if global_lookup and global_lookup.payload is not None:
        return DetailFranchisePayloadLookup(
            requested_media_id=requested_media_id,
            cache_media_id=requested_media_id,
            canonical_media_id=global_lookup.canonical_media_id,
            payload=global_lookup.payload,
            meta=global_lookup.meta,
            hit_kind="global_exact",
            payload_role=PAYLOAD_ROLE_GLOBAL,
        )
    alias_lookup = load_valid_alias_payload_for_media(requested_media_id)
    if alias_lookup and alias_lookup.payload is not None:
        return DetailFranchisePayloadLookup(
            requested_media_id=requested_media_id,
            cache_media_id=alias_lookup.canonical_media_id,
            canonical_media_id=alias_lookup.canonical_media_id,
            payload=alias_lookup.payload,
            meta=alias_lookup.meta,
            hit_kind="alias",
            payload_role=PAYLOAD_ROLE_GLOBAL,
        )
    return None


def save_global_payload(media_id, payload, *, timeout=None, meta=None) -> dict:
    """Persist a canonical global franchise payload."""
    media_id = str(media_id)
    payload = dict(payload)
    payload.setdefault(
        "schema_version", settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION
    )
    ttl = timeout or get_ttl_seconds()
    saved_meta = _write_payload_to_keys(
        payload_key=get_global_payload_key(media_id),
        meta_key=get_global_meta_key(media_id),
        payload=payload,
        expected_role=PAYLOAD_ROLE_GLOBAL,
        validator=is_valid_global_payload,
        timeout=ttl,
        meta=meta,
    )
    delete_alias_for_media(media_id)
    return saved_meta


def save_scoped_payload(media_id, payload, *, timeout=None, meta=None) -> dict:
    """Persist a detail-scoped franchise payload."""
    media_id = str(media_id)
    payload = dict(payload)
    payload.setdefault(
        "schema_version", settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION
    )
    return _write_payload_to_keys(
        payload_key=get_scoped_payload_key(media_id),
        meta_key=get_scoped_meta_key(media_id),
        payload=payload,
        expected_role=PAYLOAD_ROLE_DETAIL_SCOPED,
        validator=is_valid_scoped_payload,
        timeout=timeout or get_ttl_seconds(),
        meta=meta,
    )


def build_payload_meta(
    payload,
    *,
    fetched_at=None,
    build_duration_seconds=None,
    node_count=None,
    truncated=False,
    truncation_reason="",
):
    """Build normalized display payload metadata for a saved payload."""
    now = fetched_at or timezone.now()
    return default_meta(
        schema_version=settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION,
        fetched_at=now,
        last_accessed_at=now,
        node_count=node_count if node_count is not None else _count_nodes(payload),
        build_duration_seconds=build_duration_seconds,
        truncated=truncated,
        truncation_reason=truncation_reason,
        last_success_at=now,
    )


def is_fresh(meta) -> bool:
    """Return whether the franchise payload is logically fresh."""
    if not meta or not meta.get("fetched_at"):
        return False
    fetched_at = parse_cached_datetime(meta["fetched_at"])
    if fetched_at is None:
        return False
    return fetched_at >= timezone.now() - timedelta(
        days=settings.ANIME_FRANCHISE_CACHE_FRESH_DAYS,
    )


def _is_within_cooldown(value, hours) -> bool:
    parsed = parse_cached_datetime(value)
    if parsed is None:
        return False
    return parsed > timezone.now() - timedelta(hours=hours)


def default_build_meta(**overrides) -> dict:
    """Return normalized metadata for build scheduling state."""
    meta = {
        "schema_version": settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION,
        "last_attempt_at": None,
        "last_error_at": None,
        "last_error_message": "",
        "last_success_at": None,
    }
    meta.update(overrides)
    meta["last_attempt_at"] = _serialize_datetime(meta.get("last_attempt_at"))
    meta["last_error_at"] = _serialize_datetime(meta.get("last_error_at"))
    meta["last_success_at"] = _serialize_datetime(meta.get("last_success_at"))
    meta["last_error_message"] = meta.get("last_error_message") or ""
    return meta


def normalize_build_meta(meta) -> dict:
    """Return normalized build/scheduling metadata."""
    base = default_build_meta()
    if isinstance(meta, dict):
        for key in base:
            if key in meta:
                base[key] = meta[key]
    return default_build_meta(**base)


def load_build_meta(media_id) -> dict:
    """Load normalized build/scheduling metadata for media_id."""
    return normalize_build_meta(cache.get(get_build_meta_key(media_id)))


def update_build_meta(media_id, updates) -> dict:
    """Update build/scheduling metadata for media_id."""
    meta = load_build_meta(media_id)
    meta.update(updates)
    meta = normalize_build_meta(meta)
    cache.set(get_build_meta_key(media_id), meta, timeout=get_ttl_seconds())
    return meta


def can_schedule_build(build_meta) -> bool:
    """Return whether build cooldowns allow a background build/refresh."""
    build_meta = normalize_build_meta(build_meta)
    if _is_within_cooldown(
        build_meta.get("last_error_at"),
        settings.ANIME_FRANCHISE_RETRY_AFTER_ERROR_HOURS,
    ):
        return False
    return not _is_within_cooldown(
        build_meta.get("last_attempt_at"),
        settings.ANIME_FRANCHISE_BUILD_COOLDOWN_HOURS,
    )


def update_meta(media_id, updates) -> dict:
    """Update global payload metadata while preserving any existing global payload."""
    ttl = get_ttl_seconds()
    payload = cache.get(get_global_payload_key(media_id))
    meta = normalize_meta(cache.get(get_global_meta_key(media_id)))
    meta.update(updates)
    meta = normalize_meta(meta)
    cache.set(get_global_meta_key(media_id), meta, timeout=ttl)
    if payload is not None:
        _touch_or_set(get_global_payload_key(media_id), payload, ttl)
    return meta


def mark_attempt(media_id) -> dict:
    """Record a franchise build attempt in build metadata."""
    return update_build_meta(media_id, {"last_attempt_at": timezone.now().isoformat()})


def mark_error(media_id, error_message) -> dict:
    """Record a franchise build error in build metadata."""
    return update_build_meta(
        media_id,
        {
            "last_error_at": timezone.now().isoformat(),
            "last_error_message": str(error_message)[:250],
        },
    )


def maybe_schedule_build(media_id, payload_meta=None, *, has_payload=False) -> bool:
    """Queue a franchise build if freshness and build cooldowns permit."""
    media_id = str(media_id)
    if has_payload and is_fresh(payload_meta):
        return False
    if not can_schedule_build(load_build_meta(media_id)):
        return False

    lock_key = get_queue_lock_key(media_id)
    if not cache.add(lock_key, "1", timeout=get_queue_lock_ttl_seconds()):
        logger.info(
            "MAL anime franchise build already queued for media_id=%s",
            media_id,
        )
        return False

    try:
        from app.tasks import build_mal_anime_franchise_payload  # noqa: PLC0415

        build_mal_anime_franchise_payload.delay(media_id)
        mark_attempt(media_id)
    except Exception:
        cache.delete(lock_key)
        logger.exception(
            "Failed to enqueue MAL anime franchise build for media_id=%s",
            media_id,
        )
        return False

    return True


# Backward-compatible aliases for the previous internal helper names.
_parse_datetime = parse_cached_datetime
_default_meta = default_meta
_normalize_meta = normalize_meta
is_payload_valid = is_valid_payload
is_cache_fresh = is_fresh
