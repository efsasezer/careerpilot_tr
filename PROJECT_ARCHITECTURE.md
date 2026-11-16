# Project architecture

```text
Browser (React + TypeScript, Vite)
  └── /api + session cookie ──> FastAPI (backend/main.py)
                               ├── matching.py      classify stored listings against the profile (cached)
                               ├── eligibility.py   requirement extraction + per-requirement verdicts
                               ├── notifications.py in-app records, e-mail / Telegram digests
                               ├── sync.py          source sync, background runner, scheduler
                               │     └── sources/*  SBB, Kariyer Kapısı, İŞKUR, Yerel Yönetimler, İlan.gov.tr, ÖSYM
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

## API surface (everything except `/health` and `/auth/*` requires the session cookie)

| Route | Purpose |
|---|---|
| `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | Single-password login, server-side sessions (`user_sessions`) |
| `GET /matches`, `GET /jobs/{id}/detail` | Classified positions; `category` is the effective one, `system_category` the engine's |
| `PUT/DELETE /jobs/{id}/verification`, `POST .../acknowledge` | Manual decision per listing or position, bound to a content version |
| `PATCH /jobs/{id}/tracking` | saved / applied / awaiting / won / lost / hidden + notes (`user_job_state`) |
| `GET /calendar`, `POST /jobs/{id}/events`, `PATCH/DELETE /events/{id}` | Dated events extracted by `events.py`; user edits survive re-sync |
| `GET/POST/PATCH/DELETE /tasks`, `POST /tasks/{id}/complete` | Personal and recurring tasks |
| `GET /notifications` | Daily in-app notifications are computed on request (`notifications.refresh_daily`) |
| `POST /sync`, `GET /sync/status`, `POST /jobs/{id}/ocr`, `GET /jobs/{id}/document.pdf` | Manual scan, re-read with OCR, official PDF pass-through |
| `GET/PUT /profile`, `GET /sources`, `GET /public/*`, `GET /jobs` | Profile, source report, raw pool |

Re-sync, profile changes and engine updates only change the system verdict; `user_verifications`
is never written by them. `ocr.py` (RapidOCR + pypdfium2, no system packages) is used when a PDF
has no text layer; OCR-derived text never yields an automatic "eligible".

## Frontend

`src/services/api` (typed client, auth context, TanStack Query hooks) · `src/pages` (dashboard,
listings, tracking list, calendar, notifications, sources, profile, settings) ·
`src/components/jobs` (listing card, detail drawer opened through the `?ilan=<id>` query
parameter). The UI never recomputes eligibility; it groups positions per listing and filters.
The browser stores no password or token: the API is reached same-origin under `/api`
(Vite proxy locally, Render rewrite in production) and the session lives in an HttpOnly cookie.

## Checks

`python -m pytest -q` (uses a temporary database) · `npm --prefix frontend test` ·
`npm --prefix frontend run build`.
