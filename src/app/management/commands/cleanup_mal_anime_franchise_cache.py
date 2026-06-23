"""Clean legacy/invalid MAL anime franchise Redis cache entries."""
# ruff: noqa: D101,D102

from __future__ import annotations

from django.core.cache import cache
from django.core.management.base import BaseCommand

from app.services import anime_franchise_cache


class Command(BaseCommand):
    help = "Dry-run or delete legacy MAL anime franchise global cache payloads."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--schedule-rebuild", action="store_true")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--media-id")
        parser.add_argument("--verbose", action="store_true")

    def _iter_raw_keys(self, pattern):
        if hasattr(cache, "iter_keys"):
            try:
                yield from cache.iter_keys(pattern)
            except Exception as error:  # noqa: BLE001
                self.stderr.write(
                    "Cannot scan cache backend for MAL anime franchise keys: "
                    f"{error}; use --media-id to inspect one key explicitly."
                )
            return
        backend = getattr(cache, "_cache", None)
        if backend is not None and hasattr(backend, "iter_keys"):
            try:
                yield from backend.iter_keys(pattern)
            except Exception as error:  # noqa: BLE001
                self.stderr.write(
                    "Cannot scan cache backend for MAL anime franchise keys: "
                    f"{error}; use --media-id to inspect one key explicitly."
                )
            return
        if backend is not None and hasattr(backend, "keys"):
            try:
                for raw_key in backend.keys(pattern):
                    yield raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            except Exception as error:  # noqa: BLE001
                self.stderr.write(
                    "Cannot scan cache backend for MAL anime franchise keys: "
                    f"{error}; use --media-id to inspect one key explicitly."
                )
            return
        self.stderr.write(
            "Cannot scan cache backend for MAL anime franchise keys; "
            "use --media-id to inspect one key explicitly."
        )

    def _iter_global_keys(self, media_id=None):
        if media_id:
            yield anime_franchise_cache.get_global_payload_key(media_id)
            return
        yield from self._iter_raw_keys("mal_anime_franchise_*")

    def _is_global_payload_key(self, key):
        key = str(key)
        return (
            key.startswith("mal_anime_franchise_")
            and not key.startswith("mal_anime_franchise_scoped_")
            and not key.startswith("mal_anime_franchise_alias_")
            and not key.startswith("mal_anime_franchise_build_")
            and not key.endswith(":meta")
            and not key.endswith(":aliases")
            and not key.endswith(":queue_lock")
            and not key.endswith(":task_lock")
        )

    def handle(self, *args, **options):  # noqa: ARG002,C901
        apply = options["apply"]
        schedule = options["schedule_rebuild"]
        limit = options.get("limit")
        verbose = options["verbose"]
        summary = {
            "processed_global_keys": 0,
            "global_valid": 0,
            "legacy_global_deleted": 0,
            "invalid_global_deleted": 0,
            "scheduled_rebuilds": 0,
            "skipped_locks_or_cooldowns": 0,
            "dry_run": not apply,
        }
        for key in self._iter_global_keys(options.get("media_id")):
            if not self._is_global_payload_key(key):
                continue
            if limit is not None and summary["processed_global_keys"] >= limit:
                break
            summary["processed_global_keys"] += 1
            media_id = str(key).replace("mal_anime_franchise_", "", 1)
            payload = cache.get(key)
            if anime_franchise_cache.is_valid_global_payload(payload):
                summary["global_valid"] += 1
                continue
            is_legacy = isinstance(payload, dict) and "payload_role" not in payload
            if verbose:
                reason = "legacy" if is_legacy else "invalid"
                self.stdout.write(f"Would delete {key} ({reason})")
            if apply:
                anime_franchise_cache.delete_global_payload(media_id)
            if is_legacy:
                summary["legacy_global_deleted"] += 1
            else:
                summary["invalid_global_deleted"] += 1
            if apply and schedule:
                if anime_franchise_cache.maybe_schedule_build(
                    media_id,
                    payload_meta=None,
                    has_payload=False,
                ):
                    summary["scheduled_rebuilds"] += 1
                else:
                    summary["skipped_locks_or_cooldowns"] += 1
        for key, value in summary.items():
            self.stdout.write(f"{key}: {value}")
