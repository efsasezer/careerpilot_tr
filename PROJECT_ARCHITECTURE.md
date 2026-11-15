# Project architecture

```text
Browser (React + TypeScript, Vite)
  └── Bearer access key ──> FastAPI (backend/main.py)
                               ├── matching.py      classify stored listings against the profile (cached)
                               ├── eligibility.py   requirement extraction + per-requirement verdicts
                               ├── notifications.py in-app records, e-mail / Telegram digests
                               ├── sync.py          source sync, background runner, scheduler
                               │     └── sources/*  SBB, Kariyer Kapısı, İŞKUR, Yerel Yönetimler, İlan.gov.tr
                               ├── documents.py     PDF / DOCX / HTML text + staff-table parsing
                               └── SQLAlchemy ──> SQLite (careerpilot.db)
```

## Data flow

1. `sync.run_sync` asks each source for its listing index, upserts a `Job` per listing
   (identity: `source_listings.external_id`), and fetches the detail only when the listing is
   new or its list hash changed. Details are official PDFs (SBB, İŞKUR) or HTML pages.
2. Parsed staff-table rows are stored as `document_positions`; `matching.decompose_job_positions`
   turns each row into a position evaluated only against its own requirements.
3. `eligibility.classify_public_job` returns `met / not_met / unknown` per requirement and a
   category. It never invents profile data: missing information yields `unknown`.
4. `matching.build_matches` merges the same announcement published by several sources and caches
   the result until the profile, tracking state or listings change.
5. After every sync and profile update `notifications.process_notifications` creates one
   `new_match` record per listing/category and `deadline` reminders, then sends a digest to the
   enabled channels. Records are deduplicated by `dedupe_key`.

## API surface (all except `/health` require `Authorization: Bearer <CAREERPILOT_ACCESS_TOKEN>`)

| Route | Purpose |
|---|---|
| `GET /matches` | Lean classified positions for the UI |
| `GET /jobs/{id}/detail` | Full text, documents and per-position verdicts for one listing |
| `PATCH /jobs/{id}/tracking` | saved / applied / hidden + notes |
| `GET/PUT /profile` | Candidate profile (`kpss_scores` holds every score type) |
| `GET /notifications`, `POST /notifications/{id}/read`, `POST /notifications/read-all` | Notification centre |
| `GET/PUT /notifications/settings`, `POST /notifications/test` | Preferences and channel test |
| `POST /sync`, `GET /sync/status` | Start a background sync and poll progress |
| `GET /sources` | Per-source status from `source_sync_history` |
| `GET /public/matches`, `/public/summary`, `/public/listings`, `/jobs` | Full-text matches, summary and raw listing pool (scripts, checks) |

`CAREERPILOT_DEMO_MODE=true` (or `CAREERPILOT_READ_ONLY=true`) rejects every mutating request and
disables the scheduler. There is no built-in fallback token. Without `CAREERPILOT_ACCESS_TOKEN` only direct loopback
requests (no proxy headers, not on Render) are served; everything else gets 503.
Rows are never deleted: non-listings and same-source duplicates get `jobs.archived_reason`.

## Frontend

`src/services/api` (typed client, auth context, TanStack Query hooks) · `src/pages` (dashboard,
listings, tracking list, calendar, notifications, sources, profile, settings) ·
`src/components/jobs` (listing card, detail drawer opened through the `?ilan=<id>` query
parameter). The UI never recomputes eligibility; it groups positions per listing and filters.
The access key is kept in `sessionStorage` (or `localStorage` when “keep me signed in” is ticked)
and is re-validated with `/auth/check` on load.

## Checks

`python -m pytest -q` (uses a temporary database) · `npm --prefix frontend test` ·
`npm --prefix frontend run build`.
