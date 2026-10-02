from fastapi import FastAPI

from app.api.routes import health, prices

app = FastAPI(
    title="GridPulse",
    description="Dutch day-ahead electricity prices and insights. "
    "Times are Europe/Amsterdam; prices are EUR/kWh as decimal strings.",
    version="0.1.0",
    openapi_tags=[
        {"name": "prices", "description": "Day-ahead prices, daily statistics, cheapest hours"},
        {"name": "health", "description": "Liveness and readiness checks"},
    ],
)
app.include_router(health.router)
app.include_router(prices.router, prefix="/api/v1")
