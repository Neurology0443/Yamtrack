"""Graph discovery helpers for MAL anime franchise grouping."""

from __future__ import annotations

import re
from collections import deque
from datetime import date

from app.providers import mal
from app.services.anime_franchise_types import AnimeNode, AnimeRelation

CONTINUITY_RELATIONS = {"prequel", "sequel"}
YEAR_CHUNKS = 1
YEAR_MONTH_CHUNKS = 2
YEAR_MONTH_DAY_CHUNKS = 3


class AnimeFranchiseGraphBuilder:
    """Discover MAL anime entries and normalize graph relations."""

    def __init__(self, metadata_fetcher=None, *, refresh_cache=False):
        """Create a graph builder with an optional metadata fetcher."""
        self.metadata_fetcher = metadata_fetcher or mal.anime
        self.refresh_cache = refresh_cache
        self._node_cache: dict[str, AnimeNode] = {}
        self._classification_node_cache: dict[str, AnimeNode] = {}

    def build(self, root_media_id: str) -> dict[str, AnimeNode]:
        """Build the MAL anime graph around sequel/prequel continuity."""
        self._node_cache = {}
        root_id = str(root_media_id)
        queue = deque([root_id])

        while queue:
            node_id = queue.popleft()
            node = self._get_node(node_id)
            for relation in node.relations:
                if relation.relation_type in CONTINUITY_RELATIONS:
                    target_id = relation.target_media_id
                    if target_id not in self._node_cache:
                        queue.append(target_id)

        return self._node_cache

    def get_direct_neighbors(self, media_id: str) -> list[AnimeRelation]:
        """Return direct normalized relations for a given MAL anime entry."""
        return self._get_node(media_id).relations

    def ensure_node(self, media_id: str) -> AnimeNode:
        """Ensure a node exists in cache and return it."""
        return self._get_node(media_id)

    def ensure_classification_node(self, media_id: str) -> AnimeNode:
        """Return a partial node containing only classification-ready metadata."""
        media_id = str(media_id)
        cached = self._classification_node_cache.get(media_id)
        if cached:
            return cached

        metadata = mal.anime_classification_metadata(
            media_id,
            refresh_cache=self.refresh_cache,
        )
        node = AnimeNode(
            media_id=str(metadata["media_id"]),
            title=metadata["title"],
            source=metadata["source"],
            media_type=metadata["details"].get("raw_media_type", ""),
            image=metadata["image"],
            start_date=self._parse_start_date(metadata["details"].get("start_date")),
            relations=[],
            runtime_minutes=self._parse_runtime_minutes(
                metadata["details"].get("runtime"),
            ),
            episode_count=None,
        )
        self._classification_node_cache[media_id] = node
        return node

    def _get_node(self, media_id: str) -> AnimeNode:
        media_id = str(media_id)
        cached = self._node_cache.get(media_id)
        if cached:
            return cached

        try:
            metadata = self.metadata_fetcher(
                media_id,
                refresh_cache=self.refresh_cache,
            )
        except TypeError:
            metadata = self.metadata_fetcher(media_id)
        node = AnimeNode(
            media_id=str(metadata["media_id"]),
            title=metadata["title"],
            source=metadata["source"],
            media_type=metadata["details"].get("raw_media_type", ""),
            image=metadata["image"],
            start_date=self._parse_start_date(metadata["details"].get("start_date")),
            relations=self._normalize_relations(
                str(metadata["media_id"]),
                metadata,
            ),
            runtime_minutes=self._parse_runtime_minutes(
                metadata["details"].get("runtime"),
            ),
            episode_count=self._parse_episode_count(
                metadata["details"].get("episodes"),
            ),
        )
        self._node_cache[node.media_id] = node
        return node

    def _normalize_relations(
        self,
        media_id: str,
        metadata: dict,
    ) -> list[AnimeRelation]:
        normalized_relations = []
        for relation in metadata.get("related", {}).get("related_anime", []):
            relation_type = mal.normalize_relation_type(
                relation.get("relation_type"),
            )
            if not relation_type:
                continue
            target_id = str(relation["media_id"])
            normalized_relations.append(
                AnimeRelation(
                    source_media_id=media_id,
                    target_media_id=target_id,
                    relation_type=relation_type,
                    target_title=relation.get("title"),
                    target_image=relation.get("image"),
                    target_source=relation.get("source"),
                    target_route_media_type=relation.get("media_type"),
                )
            )
        return normalized_relations

    @staticmethod
    def _parse_start_date(raw_start_date: str | None) -> date | None:
        if not raw_start_date:
            return None

        chunks = raw_start_date.split("-")
        try:
            if len(chunks) == YEAR_CHUNKS:
                return date(int(chunks[0]), 1, 1)
            if len(chunks) == YEAR_MONTH_CHUNKS:
                return date(int(chunks[0]), int(chunks[1]), 1)
            if len(chunks) == YEAR_MONTH_DAY_CHUNKS:
                return date(
                    int(chunks[0]),
                    int(chunks[1]),
                    int(chunks[2]),
                )
        except (TypeError, ValueError):
            return None
        return None

    @staticmethod
    def _parse_runtime_minutes(raw_runtime: str | None) -> int | None:
        if not raw_runtime:
            return None

        normalized = raw_runtime.strip().lower()

        hours_match = re.search(
            r"(?P<hours>\d+)\s*(?:h|hr|hrs|hour|hours)\.?",
            normalized,
        )
        minutes_match = re.search(
            r"(?P<minutes>\d+)\s*(?:m|min|mins|minute|minutes)\.?",
            normalized,
        )

        if not hours_match and not minutes_match:
            return None

        hours = int(hours_match.group("hours")) if hours_match else 0
        minutes = int(minutes_match.group("minutes")) if minutes_match else 0
        return (hours * 60) + minutes

    @staticmethod
    def _parse_episode_count(raw_episode_count: int | str | None) -> int | None:
        if raw_episode_count in (None, ""):
            return None

        try:
            return int(raw_episode_count)
        except (TypeError, ValueError):
            return None
