# Anime Series View

## Product behavior

Anime Series View is the anime-list presentation that groups the user's tracked MAL anime into franchise and singleton cards. It is distinct from the MAL anime detail page: the detail page explains one MAL franchise, while Anime Series View reorganizes the user's Anime library.

- The `series` layout applies only to the Anime media list.
- Non-anime media types fall back to normal grid/table behavior; when `layout=series` is requested outside Anime, the current view path falls back to grid-style media-list behavior.
- One persisted franchise card represents tracked anime that confidently project to the same Series View root.
- Anime with no groupable evidence become explicit singleton cards.
- Non-confident projections are skipped and are not persisted.
- Cards summarize groups; they do not render member titles.
- Cards show the hover title and tracked-entry count.

## Architecture

```text
AnimeFranchiseSnapshotService
    ↓
AnimeSeriesViewProjectionBuilder
    ↓
AnimeSeriesViewFranchiseRefreshService
    ↓
AnimeSeriesViewMembership
    ↓
build_anime_series_view
    ↓
anime_series_groups.html / anime_series_group_card.html
```

`media_list` rendering must remain DB-only. No MAL provider call, snapshot build, cache build, DB write, or Celery scheduling belongs in `build_anime_series_view` or Series View rendering. Refresh work belongs to triggers, tasks, import, maintenance, and rebuild commands before the reader runs.

Series View is a projection of canonical franchise snapshots. It is not the MAL anime detail-page franchise UI, and detail-page UI sections are not Series View grouping rules.

## Projection source

The projection builder consumes canonical franchise snapshots and can use these relation collections:

- `root_story_parent_candidates`
- `no_series_line_secondary_candidates`
- `direct_candidates`
- `all_normalized_relations`

Candidate relations are de-duplicated by source media ID, target media ID, and relation type before Series View rules are applied.

## Projection rules

The projection uses the real Series View rule set, not the detail-page UI sections.

Groupable relations are:

- `prequel`
- `sequel`
- `parent_story`
- `full_story`
- `side_story`
- `spin_off`

Continuity relations are:

- `prequel`
- `sequel`

Strong reroot relations are:

- `parent_story`
- `full_story`

Compatible root media types are:

- `tv`
- `ona`
- `movie`
- `ova`

These relations are not groupable and do not reroot Series View projections:

- `alternative_version`
- `alternative_setting`

Unsafe or non-franchise relations such as `character`, `adaptation`, `recommendation`, and `other` are ignored for Series View grouping.

## Root selection and confidence

The builder prefers conservative cards over surprising merges.

- If a snapshot has a usable `series_line`, the local root starts from the first line entry.
- The builder can perform at most one controlled reroot.
- `parent_story` and `full_story` are strong reroot signals.
- Weaker reroots must be confirmed by canonical snapshot evidence such as a series line or clear continuity.
- Truncated or unconfirmed weak reroots become unresolved instead of being persisted.
- If no groupable evidence exists, the seed becomes a singleton projection.
- If groupable evidence exists but the root is not reliable, the projection is unresolved and skipped.

## Persisted read model

`AnimeSeriesViewMembership` is the per-user read model consumed by the list reader. It stores:

- `user`
- `media_id`
- `root_media_id`
- `display_media_id`
- `display_title`
- `display_alternative_title_en`
- `display_image`
- `display_media_type`
- `display_start_date`
- `group_kind`
- `projection_version`
- `created_at`
- `updated_at`

Persistence constraints and read-path indexes:

- unique constraint on `(user, media_id)`;
- indexes on `(user, media_id)`, `(user, root_media_id)`, and `(user, projection_version)`;
- current canonical `projection_version = franchise_root_v4`;
- `group_kind = franchise | singleton`.

Memberships are per-user rows for the user's tracked anime. They are not a global franchise index.

After projection-version bumps, old rows should be rebuilt so stored memberships use current semantics and display metadata. The reader can tolerate legacy rows during migration, but rebuild is the explicit repair and backfill path.

## Refresh sources

Anime Series View rendering is DB-only. Refresh work happens before rendering through triggers, tasks, commands, import, and maintenance.

Refresh sources include:

- manual MAL anime add;
- delete MAL anime;
- import-created anime;
- autonomous maintenance first observation;
- autonomous maintenance root change;
- autonomous maintenance detected maintenance-fingerprint change;
- optional refresh on every maintenance success when `ANIME_FRANCHISE_MAINTENANCE_REFRESH_SERIES_VIEW_ON_SUCCESS=True`;
- explicit rebuild command.

See [anime franchise maintenance](anime-franchise-maintenance.md) for the maintenance refresh path.

## Refresh behavior

Manual MAL anime add uses the coordinated franchise path:

```text
manual MAL anime add
    ↓ transaction commit
AnimeFranchiseManualAddTriggerService
    ↓
Process manual MAL anime franchise
    ↓
AnimeFranchiseMaintenanceService.process_seed(... refresh_series_view=True)
```

Manual add refreshes the detail-page cache and Series View quickly. It does not process discovery notifications.

Delete MAL anime uses the direct Series View refresh path:

```text
delete MAL anime
    ↓ transaction commit
AnimeSeriesViewRefreshTriggerService.schedule_delete
    ↓
Refresh Anime Series View franchise projection mode=delete
```

Delete mode removes direct memberships for deleted media, then rebuilds affected groups best-effort.

Import refreshes Series View inside the import run after new `Anime` rows are created. It refreshes the imported IDs plus seed/root context, and it can reuse the shared build session.

Maintenance refreshes Series View through `AnimeFranchiseMaintenanceService`. Refresh can happen on first observation, root change, maintenance fingerprint change, or every successful maintenance run depending on settings.

Direct refresh operational behavior:

- web-triggered scheduling happens after transaction commit;
- queue locks prevent duplicate direct refresh scheduling for the same user/media/mode tuple;
- the direct refresh task deletes its queue lock in `finally`;
- normal refresh is non-destructive until a projection succeeds;
- unresolved projections are logged and skipped;
- refresh writes only tracked MAL anime rows for the target user.

## Reader and UI rendering

`build_anime_series_view` reads `AnimeSeriesViewMembership` rows and groups by `root_media_id`. It does not build snapshots and does not call MAL.

The reader receives the full filtered user media list before group pagination. This preserves search, status, and sort filters before card grouping. Series View pagination is 12 groups per page.

HTMX Series View partial rendering uses `app/components/anime_series_groups.html`, and the HTMX target is `.anime-series-groups`.

`unprojected_count` counts tracked entries without usable memberships. If `unprojected_count` is non-zero, the first Series View page shows the preparation message. Empty Series View uses the standard media-list empty state and should not invent a special empty state.

Card rendering:

- cover uses `display_image`;
- link uses `display_media_id` through `media_url`;
- hover overlay uses `display_alternative_title_en` if present;
- fallback hover title is `display_title`;
- count below cover is `group.entries|length`;
- member titles are not rendered;
- media type labels, ratings, progress, and track controls are intentionally not rendered on Series View cards.

## Rebuild command

Use the management command to backfill, repair, or update memberships after projection-version changes:

```bash
docker compose exec yamtrack python manage.py rebuild_anime_series_view --all-users --dry-run
docker compose exec yamtrack python manage.py rebuild_anime_series_view --all-users
docker compose exec yamtrack python manage.py rebuild_anime_series_view --user-id 1 --dry-run
docker compose exec yamtrack python manage.py rebuild_anime_series_view --user-id 1 --media-id 11757 --dry-run
docker compose exec yamtrack python manage.py rebuild_anime_series_view --all-users --limit 100 --dry-run
```

`--refresh-cache` should only be used intentionally when fresher MAL/provider data is desired. Do not use `--refresh-cache` for routine projection-version rebuilds unless extra MAL API pressure is acceptable. Even without `--refresh-cache`, a rebuild can contact MAL when the local provider cache does not contain the nodes required to build the snapshot.

## Debugging checklist

Check these symptoms from the read model back toward the projection and provider cache:

- `unprojected_count > 0`;
- no `AnimeSeriesViewMembership` row for a tracked MAL anime;
- stale membership after projection-version bump;
- missing `display_alternative_title_en`;
- wrong root or unexpected reroot;
- franchise split into multiple cards;
- alternative-only anime merged when they should stay separate;
- too many MAL calls during rebuild;
- direct refresh queue lock stuck or repeatedly skipped;
- Celery task `Refresh Anime Series View franchise projection` failure;
- coordinated task `Process manual MAL anime franchise` failure;
- maintenance scan not refreshing Series View when expected.

## Boundaries and known examples

These examples explain the rules; do not hardcode these examples or their MAL IDs into product behavior.

- SAO + Gun Gale Online can share a Sword Art Online card when there is confident groupable evidence.
- SAO Progressive entries connected only by `alternative_setting` or `alternative_version` should stay separate.
- Code Geass branches can share a card if the snapshot confirms groupable franchise structure.
- Spice & Wolf old/remake continuities stay separate when their connection is only alternative-style evidence.
- Parent-story or full-story specials can reroot to the parent title when the canonical snapshot confirms the parent.

## Future direction

The current model is a per-user read model. It is robust for this step. A future Spec 2 could replace or complement it with a global MAL franchise index:

```text
media_id -> root_media_id + display metadata
```

The projection should remain pure and independent of the user so this evolution stays possible.
