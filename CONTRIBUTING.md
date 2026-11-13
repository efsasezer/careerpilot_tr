# Contributing

## Setup

Install the Python dependencies from the repository root and create a local
Node environment for the modern frontend:

```powershell
python -m pip install -r requirements.txt
Set-Location frontend
npm ci
```

## Validation

Before submitting changes, run the checks relevant to the files changed:

```powershell
# Repository root
python -m pytest -q

# frontend/
npm test
npm run build
```

Do not change API response schemas or reimplement the backend eligibility
engine in the frontend without an explicit product decision. Keep private
credentials out of source, `.env.example`, Vite variables, commits, and
browser storage. The React app accepts its access key in memory; the legacy
Streamlit service reads its key from the server environment.

## Render

All current services are in the root `render.yaml`. Keep their service names
distinct and preserve the existing API and Streamlit entries when changing the
React static-site definition. `autoDeploy` is disabled; validate the Blueprint
before applying changes in Render.
