from django.db import models


class AnimeMetadataRecord(models.Model):  # noqa: DJ008
    """Durable last-known-good MAL metadata and refresh state."""

    media_id = models.PositiveBigIntegerField()
    source = models.CharField(max_length=16, default="mal")
    canonical_title = models.CharField(max_length=255, null=True)  # noqa: DJ001
    alternative_title_en = models.CharField(max_length=255, null=True)  # noqa: DJ001
    image = models.URLField(max_length=500, null=True)  # noqa: DJ001
    synopsis = models.TextField(null=True)  # noqa: DJ001
    genres = models.JSONField(default=list)
    score = models.FloatField(null=True)
    score_count = models.PositiveIntegerField(null=True)
    episode_count = models.PositiveIntegerField(null=True)
    media_type = models.CharField(max_length=32, null=True)  # noqa: DJ001
    start_date = models.CharField(max_length=10, null=True)  # noqa: DJ001
    end_date = models.CharField(max_length=10, null=True)  # noqa: DJ001
    status = models.CharField(max_length=64, null=True)  # noqa: DJ001
    runtime = models.PositiveIntegerField(null=True)
    studios = models.JSONField(default=list)
    season_year = models.PositiveIntegerField(null=True)
    season_name = models.CharField(max_length=16, null=True)  # noqa: DJ001
    broadcast_day = models.CharField(max_length=32, null=True)  # noqa: DJ001
    broadcast_time = models.CharField(max_length=8, null=True)  # noqa: DJ001
    source_material = models.CharField(max_length=64, null=True)  # noqa: DJ001
    relations = models.JSONField(default=list)
    recommendations = models.JSONField(default=list)
    fetched_at = models.DateTimeField(null=True)
    refresh_after = models.DateTimeField(null=True, db_index=True)
    last_refresh_attempt_at = models.DateTimeField(null=True)
    last_refresh_error_at = models.DateTimeField(null=True)
    last_error_message = models.TextField(null=True)  # noqa: DJ001

    class Meta:
        """Database invariants for provider identity and MAL IDs."""

        constraints = [
            models.UniqueConstraint(
                fields=("source", "media_id"),
                name="anime_metadata_unique_source_media",
            ),
            models.CheckConstraint(
                condition=models.Q(media_id__gt=0),
                name="anime_metadata_positive_media_id",
            ),
        ]
