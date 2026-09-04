"""Application factory: `uv run uvicorn chess_trainer.api.app:app --reload`."""

from importlib import resources
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from chess_trainer.api.routes import accounts, users
from chess_trainer.api.routes import resources as resource_routes

# The frontend is plain static files (no build step) shipped inside the
# package and served by the API itself, so everything is same-origin and no
# CORS configuration is needed.
WEB_DIR = Path(str(resources.files("chess_trainer") / "web"))


def create_app() -> FastAPI:
    app = FastAPI(
        title="Chess Trainer",
        description="Personalized training from your own Lichess and Chess.com games.",
        version="0.1.0",
    )
    app.include_router(users.router)
    app.include_router(accounts.router)
    app.include_router(resource_routes.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/app/")

    app.mount("/app", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
