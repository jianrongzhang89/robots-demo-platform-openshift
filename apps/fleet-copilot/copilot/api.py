from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .catalog import Catalog
from .bridge import RmfBridge, RmfBridgeError
from .interpreter import interpret
from .providers import MockProvider, OpenAIProvider
from .store import ConflictError, NotFoundError, Store


ROOT = Path(__file__).resolve().parents[1]
catalog = Catalog.load(ROOT / "fixtures" / "catalog.hotel-demo.json")
app = FastAPI(title="Fleet Copilot Phase 2", version="0.2.0")
app.mount("/ui", StaticFiles(directory=ROOT / "ui"), name="ui")
store = Store(os.environ.get("FLEET_COPILOT_DB", "/var/lib/fleet-copilot/fleet.db"))
bridge = RmfBridge(os.environ.get("RMF_API_BASE_URL", "http://rmf-core-api:8000"))


class InterpretRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class MissionPreviewRequest(BaseModel):
    site_id: str = "hotel-demo"
    actor_id: str = "development-operator"
    catalog_version: str
    places: list[str]
    rounds: int


class MissionRequest(BaseModel):
    preview_id: str
    site_id: str = "hotel-demo"
    actor_id: str = "development-operator"


class BridgeEventRequest(BaseModel):
    event_type: str
    source: str = "rmf-emulator"
    source_event_id: str | None = None
    payload: dict = Field(default_factory=dict)


@app.get("/api/catalog")
def get_catalog():
    return catalog.as_dict()


@app.post("/api/interpret")
def post_interpret(payload: InterpretRequest):
    provider = OpenAIProvider() if os.environ.get("OPENAI_API_KEY") else MockProvider()
    return interpret(payload.text, catalog, provider).as_dict()


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "phase": 2}


@app.get("/api/v1/readiness")
def readiness():
    return {"status": "ready", "database": "sqlite"}


@app.get("/api/v1/sites/{site_id}/destinations")
def destinations(site_id: str):
    if site_id != "hotel-demo":
        raise HTTPException(status_code=404, detail="site not found")
    return catalog.as_dict()


@app.post("/api/v1/mission-previews", status_code=201)
def create_preview(payload: MissionPreviewRequest):
    if payload.site_id != "hotel-demo":
        raise HTTPException(status_code=404, detail="site not found")
    if payload.catalog_version != catalog.version:
        raise HTTPException(status_code=409, detail="catalog version is stale")
    canonical = [catalog.resolve(place) or place for place in payload.places]
    if any(not catalog.contains(place) for place in canonical):
        raise HTTPException(status_code=422, detail="unknown destination")
    try:
        return store.create_preview(payload.actor_id, payload.site_id, payload.catalog_version, canonical, payload.rounds)
    except ConflictError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/missions", status_code=202)
def create_mission(payload: MissionRequest, response: Response, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    try:
        existing = store.idempotency_mission(payload.actor_id, payload.site_id, idempotency_key or "")
        mission = store.create_mission(payload.actor_id, payload.site_id, idempotency_key or "", payload.preview_id)
        if existing is None and mission["submission"] == "publish_attempted" and not mission["rmf_task_id"]:
            try:
                task_id, rmf_response = bridge.dispatch(mission)
                if os.environ.get("FLEET_COPILOT_CRASH_AFTER_RMF_RESPONSE") == "1":
                    os._exit(137)
                mission = store.bind_rmf_task(mission["mission_id"], task_id, rmf_response)
            except RmfBridgeError as exc:
                mission = store.mark_submission_unknown(mission["mission_id"], str(exc))
        elif existing is not None and mission["submission"] == "publish_attempted" and not mission["rmf_task_id"]:
            matches = bridge.find_by_mission(mission["mission_id"])
            if len(matches) == 1:
                task_id = ((matches[0].get("booking") or {}).get("id"))
                if task_id:
                    mission = store.bind_rmf_task(mission["mission_id"], task_id, {"reconciled": matches[0]})
            elif not matches:
                mission = store.mark_submission_unknown(mission["mission_id"], "RMF task not found during replay reconciliation")
        response.headers["Location"] = f"/api/v1/missions/{mission['mission_id']}"
        return mission
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/missions/{mission_id}")
def get_mission(mission_id: str):
    try:
        return store.get_mission(mission_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/missions/{mission_id}/events")
def get_events(mission_id: str):
    try:
        return {"events": store.events(mission_id)}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/missions/{mission_id}/events")
def post_event(mission_id: str, payload: BridgeEventRequest):
    try:
        return store.record_event(mission_id, payload.event_type, payload.payload, payload.source, payload.source_event_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/missions/{mission_id}/sync")
def sync_mission(mission_id: str):
    try:
        mission = store.get_mission(mission_id)
        if not mission["rmf_task_id"]:
            raise HTTPException(status_code=409, detail="mission has no RMF task")
        state = bridge.state(mission["rmf_task_id"])
        terminal, reason = bridge.terminal_success(state)
        if terminal:
            return store.record_event(mission_id, "completed", {"rmf_state": state, "terminal_reason": reason}, "rmf-web", mission_id + ":state:" + mission["rmf_task_id"] + ":completed")
        status = state.get("status")
        if status == "canceled":
            return store.record_event(mission_id, "canceled", {"rmf_state": state, "terminal_reason": reason}, "rmf-web", mission_id + ":state:" + mission["rmf_task_id"] + ":canceled")
        if status in {"failed", "killed", "error"}:
            return store.record_event(mission_id, "failed", {"rmf_state": state, "terminal_reason": reason}, "rmf-web", mission_id + ":state:" + mission["rmf_task_id"] + ":failed")
        if (state.get("dispatch") or {}).get("status") in {"queued", "underway"} or state.get("status") in {"queued", "underway", "standby"}:
            return store.record_event(mission_id, "queued", {"rmf_state": state}, "rmf-web", mission_id + ":state:" + mission["rmf_task_id"] + ":queued")
        return mission
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RmfBridgeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/v1/missions/{mission_id}/cancellation")
def cancel_mission(mission_id: str):
    try:
        mission = store.get_mission(mission_id)
        response = None
        if mission["rmf_task_id"]:
            response = bridge.cancel(mission["rmf_task_id"], mission_id)
        return store.record_event(mission_id, "cancel_requested", {"rmf_response": response}, "gateway")
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RmfBridgeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/v1/episodes/reset")
def reset_episode():
    return store.reset_episode()


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "ui" / "index.html")
