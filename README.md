# CompassAQ

CompassAQ is an air quality data management and analytics platform. The repository includes a FastAPI backend, a React/Vite frontend, PostgreSQL, Docker Compose orchestration, CSV upload support, external air quality source integrations, device and sensor administration tools, maps, charts, aggregation logic, AQI-related calculations, and admin configuration pages.

## Getting Started

The primary local entry point is Docker Compose.

1. Copy the environment template to `.env` and replace the example-only placeholder values.
2. Start the stack from the repository root:
   - `docker compose up --build`
3. For a detached run, use:
   - `docker compose up -d --build`
4. If you need to apply database migrations manually, use:
   - `docker compose run --rm api alembic upgrade head`

What the Compose stack starts:

- PostgreSQL database
- FastAPI API service
- background scheduler
- frontend served from the built React app behind Nginx
- Adminer for database inspection

For direct development outside Docker:

- Backend: install the Python dependencies from `backend/requirements.txt` and run `uvicorn api.main:app` from the `backend/` directory.
- Frontend: run `npm install` in `frontend/`, then `npm run dev`.
- Database: provide PostgreSQL and configure `DATABASE_URL` or the `POSTGRES_*` variables.

The Vite dev server proxies `/api` to `http://localhost:8000`, so the frontend can talk to the backend during local development without separate CORS setup. If you do call the API from a different origin, set `CORS_ALLOW_ORIGINS`.

First-run behavior:

- `GET /setup/status` checks whether setup is required.
- If the database already has users but the setup flag is not set, the API auto-marks setup complete on the status check.
- On startup, the API seeds missing `ExternalAPI` rows for OpenAQ, PurpleAir, and AirGradient.
- The Docker entrypoint runs Alembic migrations when the schema does not already have an `alembic_version` table.

Safe verification commands:

- `docker compose config`
- `pytest`
- `npm --prefix frontend run test:run`
- `npm --prefix frontend run build`

## Environment Variables

The variables below are the ones currently used by the codebase. Some are required, and some are optional or only needed for specific features.

| Variable(s) | Purpose |
| --- | --- |
| `DATABASE_URL` | Optional full PostgreSQL connection string. If unset, the app builds a URL from the `POSTGRES_*` variables. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Required database credentials when `DATABASE_URL` is not set. |
| `POSTGRES_HOST`, `POSTGRES_PORT` | Database host and port. In Docker Compose, the default host is `db` and the port is `5432`. |
| `API_PORT` | Port used by the API service in Docker Compose and direct startup. |
| `BIND_HOST`, `BIND_PORT` | Optional bind settings when running the API directly. `API_HOST` and `HOST` are also accepted by the startup code as fallbacks. |
| `ADMINER_PORT` | Port exposed for the Adminer UI when using Docker Compose. |
| `JWT_SECRET_KEY` | Required signing key for authentication tokens. |
| `JWT_ALGORITHM` | JWT algorithm, default `HS256`. |
| `JWT_ISSUER`, `JWT_AUDIENCE` | Token issuer and audience values. |
| `ACCESS_TOKEN_EXPIRE_SECONDS`, `REFRESH_TOKEN_EXPIRE_SECONDS` | Token lifetime settings. |
| `AUTH_MAX_FAILED_LOGINS`, `AUTH_LOCKOUT_MINUTES`, `AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS`, `AUTH_LOGIN_RATE_LIMIT_IP_MAX`, `AUTH_LOGIN_RATE_LIMIT_GLOBAL_MAX`, `AUTH_PASSWORD_MIN_LENGTH` | Authentication policy settings. |
| `CORS_ALLOW_ORIGINS` | Optional comma-separated allowlist for cross-origin requests. Leave unset for same-origin production use. |
| `COMPASSAQ_CSV_UPLOAD_API_KEY` | Required API key for programmatic CSV uploads. |
| `COMPASSAQ_CSV_UPLOAD_MAX_BYTES` | Optional CSV upload size limit. Default is `1048576` bytes. |
| `OPENAQ_API_KEY` | Optional OpenAQ integration key. |
| `PURPLEAIR_API_KEY` | Optional PurpleAir integration key. |
| `AIRGRADIENT_API_KEY` | Optional AirGradient integration key. |
| `OPENAQ_TARGET_SENSOR_ID` | Optional sensor target override for OpenAQ import jobs. |
| `PURPLEAIR_SENSOR_INDEX` | Optional PurpleAir sensor mapping used by the importer. |
| `PURPLEAIR_TARGET_SENSOR_ID` | Optional sensor target override for PurpleAir import jobs. |
| `SCHEDULER_TICK_SECONDS` | Scheduler polling interval. |
| `SCHEDULER_CREATE_DEFAULT` | Controls whether a default schedule is created automatically. |
| `PM25_MIN_HOURS` | Optional PM2.5 aggregation setting used by backend calculations. |

If a value is not listed above, verify it before production use rather than assuming it is required.

## Project Structure

| Path | Purpose |
| --- | --- |
| `backend/` | FastAPI backend, services, models, routes, source integrations, QA/QC code, jobs, and tests. |
| `backend/api/` | API application wiring and route modules. |
| `backend/api/routes/admin/` | Admin endpoints for devices, external APIs, imports, events, jobs, plugins, QC rules, users, diagnostics, and system preferences. |
| `backend/services/` | Shared business logic such as auth, CSV import, AQI, event logging, and system settings. |
| `backend/sources/` | External source importers for OpenAQ, PurpleAir, and AirGradient. |
| `backend/qaqc/` | QA/QC plugin registry, pipelines, and built-in/local rules. |
| `backend/models/` | SQLAlchemy models. |
| `backend/db/` | Database configuration and session setup. |
| `backend/jobs/` | Scheduler and background job code. |
| `backend/docs/` | Backend-specific documentation, including CSV upload details. |
| `backend/tests/` | Backend test suite. |
| `frontend/` | React/Vite frontend application. |
| `frontend/src/` | Frontend application source. |
| `frontend/src/components/` | Shared UI components. |
| `frontend/src/auth/` | Frontend authentication helpers and guards. |
| `frontend/src/test/` | Frontend tests and test setup. |
| `frontend/nginx/` | Nginx config used by the production frontend container. |
| `frontend/public/` | Static assets for the frontend. |
| `backend/migrations/versions/` | Alembic migration history. |
| `docs/` | Repository documentation such as CORS notes and frontend Docker notes. |
| `tests/` | Repository-level tests. |
| `docker-compose.yml` | Local multi-service orchestration for the app stack. |
| `.env.template.example` | Environment template with the main configuration variables. |

## Data Sources

The codebase currently includes these source integrations:

- OpenAQ
- PurpleAir
- AirGradient
- Manual CSV ingestion for measurement data

Related supporting services:

- Geoapify is used for location search during setup and admin workflows.
- The admin UI can manage `ExternalAPI` records, which is how source integrations are configured in the application.

On startup, missing default `ExternalAPI` rows are seeded for OpenAQ, PurpleAir, and AirGradient. Additional source records can be managed through the admin interface, but verify their provider behavior before production use.

## CSV Upload Format

Programmatic CSV upload is available at `POST /ingest/upload-csv` and uses the `X-API-Key` header for authentication.

Required environment variables:

- `COMPASSAQ_CSV_UPLOAD_API_KEY`
- `COMPASSAQ_CSV_UPLOAD_MAX_BYTES` is optional and defaults to `1048576`

Request format:

- `multipart/form-data`
- one uploaded file field named `file`

Required CSV columns:

- `internalsensorid`
- `datetime`
- `value`

Notes:

- The file must be UTF-8 text CSV.
- The header row is required.
- Header names are matched case-insensitively after trimming.
- `datetime` must be ISO 8601.
- If `datetime` has no timezone, the sensor device timezone from the database is used.
- Duplicate measurements for the same sensor and timestamp are rejected.
- Valid rows are inserted even if other rows fail; the response includes inserted and failed counts.

Example:

```csv
internalsensorid,datetime,value
1675,2026-01-15T00:00:00Z,12.5
1676,2026-01-15T00:05:00,9.8
```

The same validation and import logic is also used by the admin CSV upload route.

## Admin Setup

CompassAQ has a first-run setup flow in `backend/api/routes/setup.py`.

Current setup behavior:

- `GET /setup/status` reports whether setup is required.
- `GET /setup/data-sources` lists configurable external APIs while setup is still open.
- `POST /setup/admin` creates the initial administrator account.
- `POST /setup/data-source` stores an API key for a selected external API.
- `POST /setup/verify-data-source` checks keys for OpenAQ, PurpleAir, or AirGradient before saving.
- `POST /setup/geoapify` stores the Geoapify key used for location search.
- `POST /setup/verify-geoapify` checks the Geoapify key before saving.
- `POST /setup/complete` marks setup complete after an admin account exists.

Important setup details:

- These endpoints are public until setup is complete.
- The created first admin receives the `admin` role.
- Password policy is enforced during setup.
- The admin API routes require the `users:write` scope after setup.

Admin functionality currently present includes management pages and endpoints for users, devices, sensors, external APIs, CSV imports, event logs, jobs, plugins, QC rules, system preferences, and diagnostics.

## Contributing

Contribution guidelines are still being defined. External contributions should not be submitted or assumed accepted until the project maintainers define the contribution process.

## License

No open-source license has been selected yet. Until a `LICENSE` file is added, all rights are reserved; do not copy, reuse, modify, or redistribute this code without permission.
