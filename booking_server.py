#!/usr/bin/env python3
"""AlphaPassbook — cyberpunk booking ops dashboard with WebSocket logs."""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import httpx
import secrets
import uvicorn
import yaml
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

BOOK_URL = "https://api1.passportindia.gov.in/v1/secure/bookappointonline"

AUTH_USERNAME = "AlphaPassbook"
AUTH_PASSWORD = "Alphafx@123"
SESSION_SECRET = secrets.token_hex(32)  # regenerated each process start

HEADERS_TEMPLATE = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://services1.passportindia.gov.in",
    "Referer": "https://services1.passportindia.gov.in/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "x-aim-plugin-installed": "true",
}


class JobStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    KILLED = "killed"
    TIMEOUT = "timeout"
    AUTH_ERROR = "auth_error"


def parse_duration(value: str | float | int) -> float:
    """Parse '0.2s', '400s', or raw numbers into seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower()
    m = re.match(r"^([\d.]+)\s*s(?:ec(?:ond)?s?)?$", s)
    if m:
        return float(m.group(1))
    return float(s)


def format_date_for_api(date_str: str) -> str:
    """Ensure DD/MM/YYYY format."""
    if "/" in date_str:
        return date_str
    # ISO YYYY-MM-DD from date picker
    parts = date_str.split("-")
    if len(parts) == 3:
        return f"{parts[2]}/{parts[1]}/{parts[0]}"
    return date_str


@dataclass
class WorkerSpec:
    app_ref_no: str
    pbo_id: int | str
    cal_appt_date: str


@dataclass
class JobConfig:
    token: str
    workers: list[WorkerSpec]
    delay: float = 0.5
    close_after: float = 400.0
    label: str = ""


@dataclass
class JobState:
    job_id: str
    config: JobConfig
    status: JobStatus = JobStatus.RUNNING
    started_at: float = field(default_factory=time.time)
    success_result: dict | None = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    worker_tasks: list[asyncio.Task] = field(default_factory=list)


class LogBroadcaster:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._history: list[dict] = []
        self._max_history = 500

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        for entry in self._history[-100:]:
            try:
                await ws.send_json(entry)
            except Exception:
                break

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def log(
        self,
        message: str,
        *,
        level: str = "info",
        job_id: str | None = None,
        data: dict | None = None,
    ) -> None:
        entry = {
            "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "level": level,
            "message": message,
            "job_id": job_id,
            "data": data,
        }
        self._history.append(entry)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        dead: list[WebSocket] = []
        for ws in self._clients:
            try:
                await ws.send_json(entry)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def broadcast_jobs(self, jobs: list[dict]) -> None:
        entry = {"type": "jobs_update", "jobs": jobs, "active_count": sum(1 for j in jobs if j["status"] == "running")}
        dead: list[WebSocket] = []
        for ws in self._clients:
            try:
                await ws.send_json(entry)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)


broadcaster = LogBroadcaster()
jobs: dict[str, JobState] = {}


def job_summary(state: JobState) -> dict:
    cfg = state.config
    return {
        "job_id": state.job_id,
        "label": cfg.label or cfg.workers[0].app_ref_no if cfg.workers else "—",
        "status": state.status.value,
        "workers": len(cfg.workers),
        "app_ref_no": cfg.workers[0].app_ref_no if cfg.workers else "",
        "started_at": datetime.fromtimestamp(state.started_at).strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_s": round(time.time() - state.started_at, 1),
        "success": state.success_result,
    }


async def notify_jobs_update() -> None:
    await broadcaster.broadcast_jobs([job_summary(j) for j in jobs.values()])


async def book_appointment(token: str, app_ref_no: str, pbo_id: int | str, cal_appt_date: str) -> dict:
    headers = {**HEADERS_TEMPLATE, "Authorization": f"Bearer {token}"}
    payload = {
        "requestResponseMap": {
            "appRefNo": app_ref_no,
            "enquiryQuota": "",
            "appTask": "Schedule",
            "appointmentQuota": "Online",
            "calendarDisplayFlag": "N",
            "calApptDate": cal_appt_date,
            "pboId": str(pbo_id),
        }
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(BOOK_URL, headers=headers, json=payload)
        try:
            return resp.json()
        except Exception:
            return {"error": resp.text, "status_code": resp.status_code}


def classify_response(result: dict) -> str:
    if result.get("error") == "Unauthorized" or result.get("status") == "invalid_authentication":
        return "unauthorized"
    if result.get("strReturnString") == "success":
        return "success"
    if result.get("strReturnString") == "error":
        return "slot_unavailable"
    return "unknown"


async def worker_loop(job: JobState, spec: WorkerSpec, worker_idx: int) -> None:
    tag = f"W{worker_idx}"
    app_ref = spec.app_ref_no
    pbo = spec.pbo_id
    date = spec.cal_appt_date
    attempt = 0

    while not job.stop_event.is_set():
        if time.time() - job.started_at >= job.config.close_after:
            await broadcaster.log(
                f"[{tag}] Timeout reached ({job.config.close_after}s)",
                level="warn",
                job_id=job.job_id,
            )
            break

        attempt += 1
        await broadcaster.log(
            f"[{tag}] Attempt #{attempt} — appRef={app_ref} pboId={pbo} date={date}",
            level="info",
            job_id=job.job_id,
        )

        try:
            result = await book_appointment(job.config.token, app_ref, pbo, date)
        except Exception as exc:
            await broadcaster.log(
                f"[{tag}] Request failed: {exc}",
                level="error",
                job_id=job.job_id,
            )
            await asyncio.sleep(job.config.delay)
            continue

        kind = classify_response(result)
        pretty = json.dumps(result, indent=2)

        if kind == "unauthorized":
            await broadcaster.log(
                f"[{tag}] UNAUTHORIZED — invalid bearer token",
                level="error",
                job_id=job.job_id,
                data=result,
            )
            job.status = JobStatus.AUTH_ERROR
            job.stop_event.set()
            return

        if kind == "success":
            appt = (result.get("requestResponseMap") or {}).get("appointmentNo", "?")
            msg = (result.get("requestResponseMap") or {}).get("appMesg", "")
            await broadcaster.log(
                f"[{tag}] BOOKED! Appointment #{appt} — {msg}",
                level="success",
                job_id=job.job_id,
                data=result,
            )
            job.status = JobStatus.SUCCESS
            job.success_result = result
            job.stop_event.set()
            return

        if kind == "slot_unavailable":
            await broadcaster.log(
                f"[{tag}] Slot not available (will retry in {job.config.delay}s)",
                level="warn",
                job_id=job.job_id,
                data=result,
            )
        else:
            await broadcaster.log(
                f"[{tag}] Unexpected response",
                level="warn",
                job_id=job.job_id,
                data=result,
            )

        await asyncio.sleep(job.config.delay)


async def run_job(config: JobConfig, label: str = "", preassigned_id: str | None = None) -> str:
    config.label = label or config.workers[0].app_ref_no if config.workers else "job"
    job_id = preassigned_id or str(uuid.uuid4())[:8]
    state = JobState(job_id=job_id, config=config)
    jobs[job_id] = state

    await broadcaster.log(
        f"Job {job_id} started — {len(config.workers)} worker(s), "
        f"delay={config.delay}s, closeAfter={config.close_after}s",
        level="info",
        job_id=job_id,
    )
    await notify_jobs_update()

    for i, spec in enumerate(config.workers):
        task = asyncio.create_task(worker_loop(state, spec, i + 1))
        state.worker_tasks.append(task)

    async def watchdog() -> None:
        await asyncio.sleep(config.close_after)
        if not state.stop_event.is_set():
            state.status = JobStatus.TIMEOUT
            state.stop_event.set()
            await broadcaster.log(f"Job {job_id} closed after {config.close_after}s", level="warn", job_id=job_id)

    watchdog_task = asyncio.create_task(watchdog())

    await asyncio.gather(*state.worker_tasks, return_exceptions=True)
    watchdog_task.cancel()

    if state.status == JobStatus.RUNNING:
        state.status = JobStatus.KILLED if state.stop_event.is_set() else JobStatus.TIMEOUT

    await broadcaster.log(f"Job {job_id} finished — status: {state.status.value}", level="info", job_id=job_id)
    await notify_jobs_update()
    return job_id


async def kill_job(job_id: str) -> bool:
    state = jobs.get(job_id)
    if not state or state.stop_event.is_set():
        return False
    state.status = JobStatus.KILLED
    state.stop_event.set()
    for t in state.worker_tasks:
        t.cancel()
    await broadcaster.log(f"Job {job_id} killed by user", level="warn", job_id=job_id)
    await notify_jobs_update()
    return True


def build_config_from_yaml(data: Any) -> list[JobConfig]:
    if isinstance(data, list):
        return _configs_from_entries(data, "")

    if not isinstance(data, dict):
        return []

    token = data.get("token", "")
    if "jobs" in data:
        entries = data["jobs"]
    elif "app_ref_no" in data:
        entries = [data]
    else:
        entries = [v for v in data.values() if isinstance(v, dict) and "app_ref_no" in v]

    return _configs_from_entries(entries, token)


def _configs_from_entries(entries: list, token: str) -> list[JobConfig]:

    configs: list[JobConfig] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_token = (entry.get("token") or token or "").strip()
        app_ref = entry.get("app_ref_no", "")
        dates = entry.get("dateTotry") or entry.get("dates") or []
        pbo_ids = entry.get("pboId") or entry.get("pbo_ids") or []
        delay = parse_duration(entry.get("delay", "0.5s"))
        close_after = parse_duration(entry.get("closejobafter") or entry.get("close_after", "400s"))

        workers: list[WorkerSpec] = []
        for pbo in pbo_ids:
            for d in dates:
                workers.append(
                    WorkerSpec(
                        app_ref_no=app_ref,
                        pbo_id=pbo,
                        cal_appt_date=format_date_for_api(str(d)),
                    )
                )

        if workers and entry_token:
            configs.append(
                JobConfig(token=entry_token, workers=workers, delay=delay, close_after=close_after)
            )

    return configs


# ── API models ──────────────────────────────────────────────────────────────

class StartJobRequest(BaseModel):
    token: str
    app_ref_no: str = Field(alias="appRefNo")
    pbo_id: str = Field(alias="pboId")
    cal_appt_date: str = Field(alias="calApptDate")
    delay: float = 0.5
    close_after: float = Field(default=400.0, alias="closeAfter")

    model_config = {"populate_by_name": True}


class YamlJobRequest(BaseModel):
    yaml_content: str


class LoginRequest(BaseModel):
    username: str
    password: str


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="AlphaPassbook")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, max_age=86400 * 7)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def is_authenticated(request: Request) -> bool:
    return request.session.get("authenticated") is True


def require_auth(request: Request) -> None:
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Not authenticated")


@app.get("/")
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse("/dashboard", status_code=302)
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/dashboard")
async def dashboard_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/", status_code=302)
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.post("/api/login")
async def login(req: LoginRequest, request: Request):
    if req.username == AUTH_USERNAME and req.password == AUTH_PASSWORD:
        request.session["authenticated"] = True
        request.session["user"] = req.username
        return {"ok": True, "user": req.username}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.post("/api/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/auth/check")
async def auth_check(request: Request):
    return {"authenticated": is_authenticated(request), "user": request.session.get("user")}


@app.get("/api/jobs")
async def list_jobs(request: Request):
    require_auth(request)
    return {"jobs": [job_summary(j) for j in jobs.values()], "active_count": sum(1 for j in jobs.values() if j.status == JobStatus.RUNNING and not j.stop_event.is_set())}


@app.post("/api/jobs/start")
async def start_job(req: StartJobRequest, request: Request):
    require_auth(request)
    workers = [
        WorkerSpec(
            app_ref_no=req.app_ref_no,
            pbo_id=req.pbo_id,
            cal_appt_date=format_date_for_api(req.cal_appt_date),
        )
    ]
    config = JobConfig(
        token=req.token.strip(),
        workers=workers,
        delay=req.delay,
        close_after=req.close_after,
    )
    job_id = str(uuid.uuid4())[:8]
    asyncio.create_task(run_job(config, preassigned_id=job_id))
    return {"job_id": job_id, "status": "started"}


@app.post("/api/jobs/import-yaml")
async def import_yaml(req: YamlJobRequest, request: Request):
    require_auth(request)
    data = yaml.safe_load(req.yaml_content)
    if not data:
        return {"error": "Empty YAML"}
    configs = build_config_from_yaml(data)
    if not configs:
        return {"error": "No valid jobs found in YAML"}
    started = []
    for cfg in configs:
        jid = str(uuid.uuid4())[:8]
        asyncio.create_task(run_job(cfg, preassigned_id=jid))
        started.append(jid)
    return {"job_ids": started, "count": len(started)}


@app.post("/api/jobs/import-yaml-file")
async def import_yaml_file(request: Request, file: UploadFile = File(...)):
    require_auth(request)
    content = (await file.read()).decode("utf-8")
    data = yaml.safe_load(content)
    if not data:
        return {"error": "Empty YAML"}
    configs = build_config_from_yaml(data)
    if not configs:
        return {"error": "No valid jobs found in YAML"}
    started = []
    for cfg in configs:
        jid = str(uuid.uuid4())[:8]
        asyncio.create_task(run_job(cfg, preassigned_id=jid))
        started.append(jid)
    return {"job_ids": started, "count": len(started)}


@app.post("/api/jobs/{job_id}/kill")
async def kill_job_endpoint(job_id: str, request: Request):
    require_auth(request)
    ok = await kill_job(job_id)
    if not ok:
        return {"error": "Job not found or already stopped"}
    return {"job_id": job_id, "status": "killed"}


@app.post("/api/jobs/kill-all")
async def kill_all_jobs(request: Request):
    require_auth(request)
    killed = []
    for jid, state in list(jobs.items()):
        if not state.stop_event.is_set():
            await kill_job(jid)
            killed.append(jid)
    return {"killed": killed}


@app.websocket("/ws/logs")
async def websocket_logs(ws: WebSocket):
    session = ws.scope.get("session", {})
    if not session.get("authenticated"):
        await ws.close(code=4401, reason="Not authenticated")
        return
    await broadcaster.connect(ws)
    await ws.send_json({
        "type": "jobs_update",
        "jobs": [job_summary(j) for j in jobs.values()],
        "active_count": sum(1 for j in jobs.values() if j.status == JobStatus.RUNNING and not j.stop_event.is_set()),
    })
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        broadcaster.disconnect(ws)


if __name__ == "__main__":
    uvicorn.run("booking_server:app", host="0.0.0.0", port=8080, reload=True)
