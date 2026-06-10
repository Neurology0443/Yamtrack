# Anime Franchise Grouping (MAL anime) — Reference

This is the reference document for the **current** MAL anime franchise UI grouping path.

It describes what is executed today, how placement is decided, and where compatibility layers still exist.

## 1) Functional scope

- Feature-gated by `ANIME_FRANCHISE_GROUPING_ENABLED`.
- Applied in `media_details` only for `source=mal` and `media_type=anime`.
- Produces `anime_franchise` context consumed by `templates/app/media_details.html`.
- Import projection is intentionally out of scope for this document.

The first-visit fallback is not the complete franchise payload and is not the source of truth. It exists only to avoid showing the raw MAL `related_anime` melting pot while the complete payload is being built. Once a complete payload exists, the normal categorized franchise UI remains authoritative.

## 2) Principal runtime path (today)

1. `AnimeFranchiseService` (`src/app/services/anime_franchise.py`)
2. `AnimeFranchiseUiPipeline` (`src/app/services/anime_franchise_ui/__init__.py`)
3. `SeriesBuilder`
4. `UiCandidateAssembler`
5. `RulePipeline`
6. `LayoutCompiler`
7. `ViewModelAdapter`
8. `views.py` integration + enrichment (`anime_franchise` reconstruction)
9. `anime_franchise_footer.py` footer labels/badges
10. `templates/app/media_details.html` presentation

## 3) Snapshot semantics (canonical input)

`AnimeFranchiseSnapshot` (from `anime_franchise_snapshot.py`) is the canonical franchise state used by UI and import projections.

Current fields and meaning:

- `continuity_component`: transitive node set connected by continuity relations (prequel/sequel).
- `series_line`: TV-only continuity line (ordered).
- `direct_anchors`: anchors used for direct-neighbor harvesting.
- `direct_candidates`: direct normalized relations collected from anchors.
- `promoted_continuity_candidates`: UI-only continuity projection that extends direct non-TV continuity seeds transitively for `Main Story Extras`.
- `promoted_continuity_candidates` is not an import input; import profiles continue to read only their own selection inputs.
- `canonical_root_media_id`: stable root ID for the continuity component.
- `fallback_anchor_media_id`: fallback direct anchor when there is no `series_line`.
- `has_series_line`: convenience flag for TV continuity availability.

### Current fallback behavior when `has_series_line` is false

- `Series` remains empty.
- Direct-candidate collection still runs from fallback/root anchor.
- No synthetic/fake series row is injected.

## 4) Fixed `Series` vs dynamic secondary sections

### Fixed `Series` block (principal contract)

- Built only by `SeriesBuilder` from `snapshot.series_line`.
- Not produced by section rule packs.
- Not treated as a dynamic section.

### Dynamic secondary sections

- Candidates come from `UiCandidateAssembler`.
- `continuity_extras` can use both direct candidates and promoted transitive non-TV continuity candidates.
- Promoted continuity anchoring exception is intentionally scoped to candidates already classified as `continuity_extras`.
- Placement/refinement occurs in ordered rule packs.
- Final grouping/ordering is compiled by `LayoutCompiler`.

## 5) Rule pack order and actual engine behavior

Preset order (`anime_franchise_ui/presets/default.py`):

1. `base_facts`
2. `base_placement`
3. `relation_rules`
4. `secondary_refinement_rules`
5. `anchor_rules`
6. `format_rules`
7. `section_rules`

### Behavior model (current, accurate)

- Packs run in order.
- `base_placement` provides initial section hypothesis.
- `secondary_refinement_rules` refines coarse secondary placement after `relation_rules`: it can reclassify TV side stories and very short side stories from `specials` to `related_series`, then refine `related_series` into `alternatives` and `spin_offs` before format filtering.
- Section ordering intent keeps `spin_offs` first, then `alternatives`, then residual `related_series`.
- Later packs may override `candidate.section_key`.
- `section_rules` is metadata-only (title/order/hidden policy), no candidate placement actions.
- The engine appends `metadata["placement_trace"]` whenever `section_key` changes.

This is **not** a global “first-match-wins” engine.

## 6) Responsibilities by layer (clear boundaries)

### Business placement logic (principal)

- `anime_franchise_ui/rules/*.py`

### Structural-only

- `anime_franchise_ui/layout.py`
- Groups by section key, applies section definitions, ordering, hidden-if-empty.
- Does not replay relation/anchor/format business policy.

### Compatibility layer

- `anime_franchise_ui/adapter.py`
- Adapts compiled output to integration payload shape.
- No placement logic.

### Integration + presentation enrichment

- `app/views.py`
- `app/anime_franchise_footer.py`

Current view-side enrichment includes:

- rebuilding `anime_franchise` block for template contract,
- adding `series_label` (`Season N`) for series entries,
- applying footer-friendly relation/format labels and active-state markers.

### Template role

- `templates/app/media_details.html` consumes prepared context.
- Presentation/display logic only (loops/visibility checks), not classification logic.

## 7) Relation signal fields (`relation_type`, `relation_types`, `metadata["origins"]`)

Current intent and practical use:

- `relation_type`: compatibility facade (single representative relation value).
- `relation_types`: richer multi-signal relation set (primary for ambiguous grouping cases).
- `metadata["origins"]`: detailed provenance from assembler.

Important nuance:

- `origins` is useful for debugging and targeted heuristics.
- It is not yet a broad standalone placement driver across the whole policy.

## 8) Section policy (current maturity)

Visible sections currently configured:

- `continuity_extras` (Main Story Extras)
- `specials`
- `spin_offs`
- `alternatives`
- `related_series`

Internal compatibility/filtered section:

- `ignored` (`visible_in_ui=False`)

Current policy is intentionally conservative and maintainable:

- coarse relation-driven placement,
- related-series refinement for long TV spin-offs and alternatives,
- anchor filtering for direct/fallback relevance,
- conservative format exclusions,
- section metadata stabilization pass.

`related_series` remains the fallback residual bucket for related entries that are not captured by these refinements.

This is a solid base, but not presented as “fully refined for every MAL edge case”.

## 9) What is principal vs compatibility vs transitional

- **Principal / active path**: service + modern UI pipeline + rules.
- **Structural-only**: `layout.py`.
- **Compatibility layer**: `adapter.py` payload-shape bridge.
- **Integration/presentation compatibility**: view reconstruction + footer enrichment.
- **Transitional/legacy**: older UI grouping mental models are not the main execution path.

## 10) Change discipline

When changing grouping behavior:

1. Change rule packs first (facts / placement / relation / anchor / format / section metadata).
2. Keep `Series` sourced only from `snapshot.series_line`.
3. Avoid adding business placement logic to layout/adapter/template.
4. Update debugging/customization docs and tests with the behavior change.

## Async complete-payload cache

MAL anime grouping uses two complementary caches:

1. The existing MAL anime cache stores individual MAL anime metadata records and remains responsible for cache/stale refresh of each anime entry.
2. The complete franchise cache stores the assembled, template-ready franchise payload without user-specific data.

The complete payload cache is keyed by the MAL anime ID:

```text
Payload key: mal_anime_franchise_<id>
Meta key: mal_anime_franchise_<id>:meta
Queue lock: mal_anime_franchise_<id>:queue_lock
Task lock: mal_anime_franchise_<id>:task_lock
```

On the first detail-page visit with no complete franchise payload, Yamtrack keeps `media.related.related_anime` visible as the lightweight fallback and queues `build_mal_anime_franchise_payload`. The HTTP view does not call `AnimeFranchiseService().build(...)` synchronously. After Celery finishes, a normal page refresh loads the complete franchise payload from cache, enriches it with the current user's status/progress during rendering, and hides `related_anime` to avoid duplicate franchise sections.

Stale complete payloads are still displayed. If freshness/cooldown settings allow it, Yamtrack queues a background refresh while continuing to serve the stale payload.

The complete franchise payload must remain user-agnostic: it must not contain `Item`, `BasicMedia`, progress, status, rendered HTML, or any `request.user`-dependent values. User-specific enrichment is performed only by `prepare_anime_franchise_context(...)` at render time.

Cached franchise payloads are strictly validated before rendering. Invalid or malformed payloads are ignored, so the direct MAL `related_anime` fallback remains visible and a background rebuild can be queued. A valid payload with no series or section entries is also treated as non-displayable and does not hide `related_anime`.

The cache writer refuses non JSON-safe values and user-specific keys; render-time user enrichment is never written back to the cached payload. If a background build produces an invalid payload, Yamtrack preserves the previous successful franchise payload and records the failure in metadata.
