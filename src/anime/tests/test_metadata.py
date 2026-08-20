# ruff: noqa: D103, PLR2004, S101

from dataclasses import FrozenInstanceError
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from anime.metadata import AnimeMetadataUnavailable
from anime.models import AnimeMetadataRecord
from anime.store import MalAnimeMetadataStore
from anime.use_cases import GetAnimeMetadata


@pytest.fixture
def mal_payload():
    """Return representative raw MAL anime metadata."""
    return {
        "title": "Fullmetal Alchemist: Brotherhood",
        "alternative_titles": {"en": "Fullmetal Alchemist Brotherhood"},
        "main_picture": {
            "medium": "https://img/medium.jpg",
            "large": "https://img/large.jpg",
        },
        "media_type": "tv",
        "start_date": "2009-04",
        "end_date": "2010-07-04",
        "synopsis": "Two brothers search for a philosopher's stone.",
        "status": "finished_airing",
        "genres": [{"id": 1, "name": "Action"}],
        "mean": 9.1,
        "num_scoring_users": 2100000,
        "num_episodes": 64,
        "average_episode_duration": 1440,
        "studios": [{"id": 4, "name": "Bones"}],
        "start_season": {"year": 2009, "season": "spring"},
        "broadcast": {"day_of_the_week": "sunday", "start_time": "17:00"},
        "source": "manga",
        "related_anime": [{"node": {"id": 121}, "relation_type": "prequel"}],
        "recommendations": [{"node": {"id": 9253}, "num_recommendations": 42}],
    }


@pytest.fixture
def valid_record(db):  # noqa: ARG001
    """Persist fresh last-known-good metadata."""
    now = timezone.now()
    return AnimeMetadataRecord.objects.create(
        media_id=1,
        canonical_title="Persisted title",
        genres=["Action"],
        studios=["Bones"],
        relations=[{"media_id": 2, "relation_type": "sequel"}],
        recommendations=[{"media_id": 3, "count": 4}],
        fetched_at=now,
        refresh_after=now + timedelta(hours=24),
    )


@pytest.mark.django_db
def test_refresh_normalizes_and_persists_complete_payload(mal_payload):
    store = MalAnimeMetadataStore()
    with patch.object(store, "_fetch_provider_payload", return_value=mal_payload):
        snapshot = store.refresh(5114)

    record = AnimeMetadataRecord.objects.get(media_id=5114)
    assert snapshot.canonical_title == mal_payload["title"]
    assert snapshot.genres == ("Action",)
    assert snapshot.runtime == 1440
    assert snapshot.start_date == "2009-04"
    assert snapshot.end_date == "2010-07-04"
    assert snapshot.relations[0].relation_type == "prequel"
    assert snapshot.recommendations[0].count == 42
    assert record.refresh_after == record.fetched_at + timedelta(hours=24)
    with pytest.raises(FrozenInstanceError):
        snapshot.canonical_title = "Changed"


@pytest.mark.django_db
def test_normalization_preserves_optional_absence_and_date_precision(mal_payload):
    mal_payload.update(
        alternative_titles={},
        main_picture=None,
        synopsis="",
        num_episodes=0,
        average_episode_duration=0,
        start_date="2026",
        end_date="2026-08",
    )
    store = MalAnimeMetadataStore()
    with patch.object(store, "_fetch_provider_payload", return_value=mal_payload):
        snapshot = store.refresh(1)

    assert snapshot.alternative_title_en is None
    assert snapshot.image is None
    assert snapshot.synopsis is None
    assert snapshot.episode_count is None
    assert snapshot.runtime is None
    assert (snapshot.start_date, snapshot.end_date) == ("2026", "2026-08")


@pytest.mark.django_db
def test_fresh_read_uses_only_database(valid_record):
    store = Mock(wraps=MalAnimeMetadataStore())
    snapshot = GetAnimeMetadata(store).execute(valid_record.media_id)
    assert snapshot.canonical_title == "Persisted title"
    store.refresh.assert_not_called()


@pytest.mark.django_db
def test_stale_read_claims_only_one_enqueue(valid_record):
    AnimeMetadataRecord.objects.filter(pk=valid_record.pk).update(
        refresh_after=timezone.now() - timedelta(seconds=1),
        last_refresh_attempt_at=None,
    )
    use_case = GetAnimeMetadata()
    with patch("anime.tasks.refresh_anime_metadata.delay") as delay:
        first = use_case.execute(valid_record.media_id)
        second = use_case.execute(valid_record.media_id)

    assert first == second
    delay.assert_called_once_with(valid_record.media_id)


@pytest.mark.django_db
def test_enqueue_failure_does_not_break_stale_read(valid_record):
    AnimeMetadataRecord.objects.filter(pk=valid_record.pk).update(
        refresh_after=timezone.now() - timedelta(seconds=1),
        last_refresh_attempt_at=None,
    )
    with patch(
        "anime.tasks.refresh_anime_metadata.delay",
        side_effect=ConnectionError,
    ):
        snapshot = GetAnimeMetadata().execute(valid_record.media_id)
    assert snapshot.canonical_title == valid_record.canonical_title


@pytest.mark.django_db
def test_failed_refresh_preserves_last_known_good(valid_record):
    original = MalAnimeMetadataStore().to_snapshot(valid_record)
    store = MalAnimeMetadataStore()
    with (
        patch.object(store, "_fetch_provider_payload", side_effect=TimeoutError),
        pytest.raises(AnimeMetadataUnavailable),
    ):
        store.refresh(valid_record.media_id)

    valid_record.refresh_from_db()
    assert MalAnimeMetadataStore().to_snapshot(valid_record) == original
    assert valid_record.last_refresh_error_at is not None
    assert "TimeoutError" in valid_record.last_error_message


@pytest.mark.django_db
def test_first_failure_creates_cooldown_without_snapshot():
    store = MalAnimeMetadataStore()
    with (
        patch.object(
            store, "_fetch_provider_payload", side_effect=TimeoutError
        ) as fetch,
        pytest.raises(AnimeMetadataUnavailable),
    ):
        GetAnimeMetadata(store).execute(7)
    with pytest.raises(AnimeMetadataUnavailable):
        GetAnimeMetadata(store).execute(7)

    record = AnimeMetadataRecord.objects.get(media_id=7)
    assert record.fetched_at is None
    assert store.get_local(7) is None
    assert fetch.call_count == 1


@pytest.mark.django_db
def test_database_constraints_reject_invalid_identity(valid_record):
    with pytest.raises(IntegrityError), transaction.atomic():
        AnimeMetadataRecord.objects.create(media_id=valid_record.media_id)
    with pytest.raises(IntegrityError), transaction.atomic():
        AnimeMetadataRecord.objects.create(media_id=0)
