"""Application factory: `uv run uvicorn chess_trainer.api.app:app --reload`."""

from importlib import resources
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from chess_trainer.api.routes import accounts, library, training, users
from chess_trainer.api.routes import resources as resource_routes

# The frontend is plain static files (no build step) shipped inside the
# package and served by the API itself, so everything is same-origin and no
# CORS configuration is needed.
WEB_DIR = Path(str(resources.files("chess_trainer") / "web"))


class RevalidatedStaticFiles(StaticFiles):
    """Static files the browser must re-check before reuse. Without a
    Cache-Control header browsers cache the ES modules heuristically and keep
    running old code after an update; `no-cache` still lets them reuse a file
    when its ETag is unchanged (a cheap 304)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app() -> FastAPI:
    app = FastAPI(
        title="Chess Trainer",
        description="Personalized training from your own Lichess and Chess.com games.",
        version="0.1.0",
    )
    app.include_router(users.router)
    app.include_router(accounts.router)
    app.include_router(resource_routes.router)
    app.include_router(library.router)
    app.include_router(training.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/app/")

    app.mount("/app", RevalidatedStaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
