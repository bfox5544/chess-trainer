"""Application factory: `uv run uvicorn chess_trainer.api.app:app --reload`."""

from fastapi import FastAPI

from chess_trainer.api.routes import accounts, resources, users


def create_app() -> FastAPI:
    app = FastAPI(
        title="Chess Trainer",
        description="Personalized training from your own Lichess and Chess.com games.",
        version="0.1.0",
    )
    app.include_router(users.router)
    app.include_router(accounts.router)
    app.include_router(resources.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
