# Project architecture

## Runtime components

```text
Browser
  └── React + TypeScript + Vite static site (careerpilot-tr-web)
        └── HTTPS GET + Bearer authorization
              └── FastAPI (careerpilot-tr-api)
                    └── SQLAlchemy → project-root careerpilot.db

Legacy Streamlit service (careerpilot-tr-frontend)
  └── Reads API_URL and CAREERPILOT_ACCESS_TOKEN from its server environment
        └── FastAPI
```

The three Render services are defined independently in `render.yaml`. The
React app is a static site; its build receives only `VITE_API_URL`. Never pass
`CAREERPILOT_ACCESS_TOKEN` to the static service or use a `VITE_` variable for
secrets: Vite embeds those variables in public browser assets.

## React application

- `src/app/`: route setup and access-key session flow.
- `src/components/`: shared layout, status, badge, and analysis components.
- `src/pages/`: dashboard, job search, matches, candidate profile, sources,
  calendar, opportunities, and settings screens.
- `src/services/api/`: typed HTTP client, in-memory auth context, and
  TanStack Query hooks.
- `src/types/`: TypeScript contracts for backend responses.

The backend remains authoritative for eligibility. The frontend displays
classifications and detailed reasoning returned by `/public/matches`; it does
not implement a second matching engine. Browser-side search and filters only
change the visible collection.

## API access and data handling

The backend's access middleware protects profile and other private API
responses. The React app asks for the access key at sign-in, validates it with
`/auth/check`, and retains it in memory only. Logging out clears the query
cache and key. Render's Streamlit service uses its server-side environment
secret instead. `CAREERPILOT_DEMO_MODE=true` blocks mutation requests; public
read routes remain protected by the configured access check.

The API reads the existing `careerpilot.db` using the path resolved by
`backend/database.py`. Do not replace, sanitize, or commit this personal-data
database without confirming repository privacy and authorization. The Render
free filesystem is ephemeral; SQLite changes on Render are not durable across
restarts or deployments.

## Local development and checks

Run the API from the repository root:

```powershell
python -m pip install -r requirements.txt
$env:CAREERPILOT_DEMO_MODE = "true"
uvicorn backend.main:app --reload
```

In another terminal:

```powershell
Set-Location frontend
npm ci
$env:VITE_API_URL = "http://127.0.0.1:8000"
npm run dev
```

Backend tests: `python -m pytest -q` from the repository root.
Frontend tests/build: `npm test` and `npm run build` from `frontend/`.
