from fastapi import FastAPI

app = FastAPI(title="GridPulse")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
