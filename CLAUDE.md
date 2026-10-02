# GridPulse

A backend service that ingests Dutch day-ahead electricity prices, stores them in PostgreSQL, and exposes insights through a REST API (prices, daily averages, cheapest hours to run devices like EV chargers or heat pumps). This is a portfolio project to demonstrate production-quality Python backend skills for Dutch employers, especially in the energy sector.

## Stack
- Python 3.13, FastAPI, Uvicorn
- SQLAlchemy 2.0 (typed, Mapped[] style), Alembic migrations, psycopg 3
- pydantic-settings for configuration (env vars, .env file never committed)
- httpx for outbound HTTP
- pytest (+ Testcontainers for integration tests later), ruff for linting
- Docker + docker compose for local PostgreSQL
- Later phases: RabbitMQ for events, Kubernetes manifests, GitHub Actions CI

## Architecture
- app/sources/: data-source adapters behind an abstract PriceSource interface (EnergyZero first, ENTSO-E later) so sources are swappable
- app/jobs/: batch ingestion jobs (idempotent: re-running for the same date must not create duplicates)
- app/api/ or app/main.py: thin HTTP layer, no business logic in route handlers
- app/services/: business logic (aggregations, cheapest-hours calculation)
- app/db.py, app/models.py: database session and ORM models
- All timestamps stored in UTC; convert to Europe/Amsterdam only at the API boundary

## Working rules
- Environment: Windows, PowerShell, virtual env at .venv
- Work ONE phase at a time. When a phase is done, STOP and give me a summary: files created/changed, commands run, results, and anything that failed.
- For every significant design decision, add a short "Why" explanation in your summary so I can explain it in interviews.
- Never commit secrets. Keep commits small with clear messages.
- Do not add features beyond the current phase.
