import asyncio

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from sqlalchemy import text

from app.api import books
from app.db.session import Base, engine
from app.tracing import configure_tracer


def create_app() -> FastAPI:
    configure_tracer()
    app = FastAPI(title="books-ai API", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(books.router)

    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    return app


app = create_app()


async def _wait_for_db(max_attempts: int = 10, delay: float = 2.0) -> None:
    for attempt in range(1, max_attempts + 1):
        try:
            async with engine.begin() as conn:
                # Ensure the expected schema exists before create_all (matches k8s init.sql).
                await conn.execute(text("CREATE SCHEMA IF NOT EXISTS books;"))
                await conn.run_sync(Base.metadata.create_all)
            return
        except Exception as exc:  # noqa: BLE001
            if attempt == max_attempts:
                raise
            await asyncio.sleep(delay)


@app.on_event("startup")
async def on_startup() -> None:
    await _wait_for_db()



