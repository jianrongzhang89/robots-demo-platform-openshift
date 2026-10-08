from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .catalog import Catalog
from .interpreter import interpret
from .providers import MockProvider, OpenAIProvider


ROOT = Path(__file__).resolve().parents[1]
catalog = Catalog.load(ROOT / "fixtures" / "catalog.hotel-demo.json")
app = FastAPI(title="Fleet Copilot Phase 1", version="0.1.0")
app.mount("/ui", StaticFiles(directory=ROOT / "ui"), name="ui")


class InterpretRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@app.get("/api/catalog")
def get_catalog():
    return catalog.as_dict()


@app.post("/api/interpret")
def post_interpret(payload: InterpretRequest):
    provider = OpenAIProvider() if os.environ.get("OPENAI_API_KEY") else MockProvider()
    return interpret(payload.text, catalog, provider).as_dict()


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "ui" / "index.html")
