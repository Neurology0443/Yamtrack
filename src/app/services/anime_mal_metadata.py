"""Helpers for deriving lightweight MAL anime metadata payloads."""

from __future__ import annotations


def anime_minimal_from_metadata(metadata: dict) -> dict:
    """Build the same minimal anime payload shape from full MAL metadata."""
    details = metadata.get("details") or {}
    return {
        "media_id": str(metadata["media_id"]),
        "title": metadata["title"],
        "source": metadata["source"],
        "media_type": metadata["media_type"],
        "image": metadata["image"],
        "details": {
            "raw_media_type": details.get("raw_media_type"),
            "start_date": details.get("start_date"),
            "status": details.get("status", ""),
        },
    }
