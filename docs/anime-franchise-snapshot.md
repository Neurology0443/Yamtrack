# Anime franchise snapshot

## Goal

The snapshot is the canonical, normalized franchise state built from MAL relation data. UI grouping, import selection, and cache payloads are separate projections built on top of it.

## Why the snapshot exists

MAL relations can be noisy, inconsistent, incomplete, or shaped differently depending on which entry is used as the starting point. Yamtrack needs one deterministic representation before UI, import, or cache decisions are made.

The snapshot prevents duplicating relation-walking logic across UI grouping, import profiles, and cache builds. It keeps product behavior stable while letting rule packs, import profiles, and cache delivery evolve independently.

## Ownership boundaries

Snapshot owns:

- canonical franchise facts;
- continuity model;
- normalized relation data;
- direct and promoted candidate discovery.

Snapshot does not own:

- UI placement;
- import profile policy;
- cache delivery behavior;
- request-specific rendering.

This keeps franchise facts stable while allowing UI, import, and cache policies to evolve independently.

## UI sections are not franchise facts

A UI section is a presentation decision, not a snapshot fact.

For example, an entry may appear under `Related Series`, `Spin Offs`, or `Alternatives` depending on UI policy, relation signals, runtime, format, and refinement rules.

The snapshot should not store those section decisions. It should provide stable franchise facts that UI grouping, import selection, and cache delivery can consume independently.

## Build flow

```text
MAL provider metadata
 -> AnimeFranchiseGraphBuilder
 -> normalized graph nodes / relation edges
 -> AnimeFranchiseSnapshotService
 -> AnimeFranchiseSnapshot
```

## Core fields

### `root_node`

The MAL anime node requested by the caller.

Used by:

- snapshot fallback anchoring;
- UI current-entry checks;
- cache build display/root context.

It should not be treated as the canonical franchise root when `canonical_root_media_id` says otherwise.

### `continuity_component`

The normalized franchise continuity component hydrated by the graph builder.

Used by:

- import profile selection;
- canonical root fallback when no TV line exists;
- snapshot-derived candidate discovery.

It should not be rendered directly as the UI layout.

### `series_line`

Ordered TV-only continuity line.

Used by:

- `SeriesBuilder` to render the fixed `Series` block;
- cache canonical-root selection when available;
- candidate assembly to avoid duplicating fixed series entries.

It should not be used as a generic list of every important franchise entry.

### `direct_anchors`

Nodes used to collect direct secondary candidates. Usually this is the full `series_line`; for a non-TV root it can also include the root.

Used by candidate assembly and direct-candidate collection. It should not imply final section placement.

### `direct_candidates`

Direct normalized relations from anchors after fixed series entries are excluded.

Used by `UiCandidateAssembler` and satellite import profiles. It should not include promoted transitive exceptions; those remain separate.

### `promoted_continuity_candidates`

Deliberately promoted non-TV prequel/sequel continuity relations beyond direct anchors.

Used by the UI candidate assembler to keep transitive non-TV continuity visible to rules. It should stay distinguishable from direct candidates.

### `no_series_line_secondary_candidates`

Secondary relation candidates used only when no TV `series_line` exists.

Used by no-series UI fallback behavior. It should not create fake fixed `Series` entries.

### `root_story_parent_candidates`

Direct `full_story` links from a non-TV root to a TV parent.

Used by candidate assembly and relation rules to handle non-TV detail pages with a direct parent story. It should not redefine the root as a TV entry.

### `canonical_root_media_id`

Stable root media ID for the franchise component. It is the first `series_line` entry when available, otherwise the earliest continuity node.

Used by cache canonical payloads and import scan state. It should not be confused with the current page media ID.

### `fallback_anchor_media_id`

Fallback anchor, currently the root media ID.

Used by no-series-line candidate anchoring. It should not be used to override `canonical_root_media_id`.

### `has_series_line`

Boolean stating whether a TV-only `series_line` exists.

Used by candidate assembly and UI rules to switch no-series behavior on or off. It should not be inferred from section contents.

## How UI uses the snapshot

- `SeriesBuilder` reads `series_line` for the fixed `Series` block.
- `UiCandidateAssembler` reads candidates and provenance fields.
- Rule packs classify assembled candidates into dynamic secondary sections.
- UI code should not mutate the snapshot.

## How import uses the snapshot

- Import profiles read the snapshot directly.
- `continuity` uses the continuity component with import-specific exclusions.
- `satellites` uses direct candidates and profile-specific relation/runtime rules.
- `satellites` may inspect local `prequel`/`sequel` relations already present in the snapshot when validating short single-episode candidates.
- This inspection is import selection policy only; the snapshot still owns franchise facts, not import decisions.
- `complete` combines continuity and satellites.

Import selection must not blindly follow UI sections. UI grouping and import selection are separate projections.

## How cache uses the snapshot

The cache build uses the snapshot plus the UI projection to serialize a complete, user-agnostic payload. The canonical root comes from the snapshot-derived canonical media ID. Alias decisions are based on aliasable entries in the serialized payload, which is built from snapshot/UI output.

Cache code should not mutate the snapshot or add user-specific state to it.

## Important invariants

- Snapshot output should be deterministic for the same provider inputs.
- `series_line` is TV-only.
- No fake `Series` entry is created when no `series_line` exists.
- UI, import, and cache are projections, not owners of snapshot data.
- Direct and promoted candidates must remain distinguishable.
- The snapshot should not contain user-specific state.

## Debugging snapshot output

Host command:

```bash
python manage.py shell -c "from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService; s=AnimeFranchiseSnapshotService().build('34161'); print('canonical', s.canonical_root_media_id); print('series', [n.media_id for n in s.series_line]); print('direct', [(r.source_media_id,r.target_media_id,r.relation_type) for r in s.direct_candidates])"
```

Docker command:

```bash
docker compose exec yamtrack python manage.py shell -c "from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService; s=AnimeFranchiseSnapshotService().build('34161'); print('canonical', s.canonical_root_media_id); print('series', [n.media_id for n in s.series_line]); print('direct', [(r.source_media_id,r.target_media_id,r.relation_type) for r in s.direct_candidates])"
```
