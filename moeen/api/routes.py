"""HTTP routes: the dashboard page, JSON API and the processed-camera preview stream.

    GET  /                               dashboard
    GET  /api/health                     is the server up, is the camera loop running
    GET  /api/status                     current state snapshot + most recent event
    GET  /api/events?limit&status&type&open    recent events, newest first
    GET  /api/events/<id>                one event with its status history
    POST /api/events/<id>/assistance     "Assistance recorded"   (JSON body: {"note": "..."})
    POST /api/events/<id>/resolve        "Resolve"               (JSON body: {"note": "..."})
    GET  /api/config                     detection thresholds in use (read-only)
    GET  /video_feed                     MJPEG stream of frames processed by the Python loop
    GET  /api/preview.jpg                latest processed frame

The browser never opens the webcam; frames come from the Python process.
POST routes require ``Content-Type: application/json``: a plain cross-site HTML form cannot
send that, which blocks the simplest forged-request attacks on this local, login-free tool
(it is not commercial-grade security).
"""

from __future__ import annotations

import dataclasses
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, render_template, request

from moeen import __version__
from moeen.database import EventNotFound, InvalidStatusTransition
from moeen.database.repository import MAX_NOTE_LENGTH
from moeen.database.timestamps import format_ts, utc_now
from moeen.runtime import Command

bp = Blueprint("moeen", __name__)

_BOUNDARY = "moeenframe"


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _ctx() -> dict[str, Any]:
    return current_app.config["MOEEN"]


def _repo():
    repo = _ctx()["repo"]
    if repo is None:
        raise ApiError(503, "The event database is disabled, so there is no event history.")
    return repo


@bp.app_errorhandler(ApiError)
def _api_error(exc: ApiError):
    return jsonify({"error": exc.message}), exc.status


@bp.app_errorhandler(EventNotFound)
def _not_found(exc):
    return jsonify({"error": str(exc)}), 404


@bp.app_errorhandler(InvalidStatusTransition)
def _conflict(exc):
    return jsonify({"error": str(exc)}), 409


@bp.app_errorhandler(ValueError)
def _bad_value(exc):
    return jsonify({"error": str(exc)}), 400


@bp.app_errorhandler(404)
def _route_not_found(exc):
    if request.path.startswith("/api/"):
        return jsonify({"error": f"no such API route: {request.path}"}), 404
    return exc


@bp.app_errorhandler(405)
def _method_not_allowed(exc):
    return jsonify({"error": f"{request.method} is not allowed on {request.path}"}), 405


# ---------------------------------------------------------------- page
@bp.get("/")
def index():
    cfg = _ctx()["config"].dashboard
    return render_template("index.html", status_poll_ms=cfg.status_poll_ms,
                           events_poll_ms=cfg.events_poll_ms,
                           preview_enabled=cfg.preview_enabled, version=__version__)


# ---------------------------------------------------------------- status
@bp.get("/api/health")
def health():
    store = _ctx()["store"]
    return jsonify({"ok": True, "version": __version__, "pipeline_running": store.pipeline_running,
                    "database": _ctx()["repo"] is not None, "server_time": format_ts(utc_now())})


@bp.get("/api/status")
def status():
    ctx = _ctx()
    store = ctx["store"]
    snap, age = store.snapshot()
    stale_after = ctx["config"].dashboard.stale_after_seconds
    last_event = None
    if ctx["repo"] is not None:
        latest = ctx["repo"].list_events(limit=1)
        last_event = latest[0].to_dict() if latest else None
    return jsonify({
        "pipeline_running": store.pipeline_running,
        "stale": snap is None or age is None or age > stale_after,
        "age_s": None if age is None else round(age, 2),
        "snapshot": snap,
        "last_event": last_event,
        "server_time": format_ts(utc_now()),
    })


@bp.get("/api/config")
def config_view():
    cfg = _ctx()["config"]
    return jsonify({"fall_detection": dataclasses.asdict(cfg.fall_detection),
                    "immobility": dataclasses.asdict(cfg.immobility),
                    "dashboard": {k: v for k, v in dataclasses.asdict(cfg.dashboard).items()
                                  if k not in ("host", "port")}})


# ---------------------------------------------------------------- events
def _int_arg(name: str, default: int, lo: int, hi: int) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ApiError(400, f"'{name}' must be an integer") from None
    if not lo <= value <= hi:
        raise ApiError(400, f"'{name}' must be between {lo} and {hi}")
    return value


@bp.get("/api/events")
def list_events():
    repo = _repo()
    limit = _int_arg("limit", 20, 1, 200)
    offset = _int_arg("offset", 0, 0, 1_000_000)
    status = request.args.getlist("status") or None
    event_type = request.args.get("type") or None
    open_only = request.args.get("open", "").lower() in ("1", "true", "yes")
    try:
        events = repo.list_events(limit=limit, offset=offset, status=status,
                                  event_type=event_type, open_only=open_only)
        total = repo.count_events(status=status, event_type=event_type, open_only=open_only)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    return jsonify({"events": [e.to_dict() for e in events], "total": total,
                    "open": repo.count_events(open_only=True)})


@bp.get("/api/events/<int:event_id>")
def get_event(event_id: int):
    repo = _repo()
    event = repo.get_event(event_id)
    history = [{"changed_at": h.changed_at,
                "from_status": h.from_status.value if h.from_status else None,
                "to_status": h.to_status.value, "note": h.note}
               for h in repo.status_history(event_id)]
    return jsonify({"event": event.to_dict(), "history": history})


def _note_from_body() -> str | None:
    if not request.is_json:
        raise ApiError(415, "Send the request with Content-Type: application/json.")
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError(400, "The request body must be a JSON object.")
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        raise ApiError(400, "'note' must be a string.")
    note = (note or "").strip()[:MAX_NOTE_LENGTH]
    return note or None


def _act(event_id: int, kind: str):
    """Apply an action via the processing loop when it runs, otherwise directly."""
    ctx = _ctx()
    repo = _repo()
    note = _note_from_body()
    store = ctx["store"]
    if store.pipeline_running and not store.stopped:
        cmd = store.submit(Command(kind=kind, event_id=event_id, note=note))
        if not cmd.wait(ctx["config"].dashboard.command_timeout_seconds):
            raise ApiError(503, "The camera loop did not respond in time. Try again.")
        if isinstance(cmd.error, (EventNotFound, InvalidStatusTransition, ValueError)):
            raise cmd.error
        if cmd.error is not None:
            raise ApiError(503, f"The action could not be applied: {cmd.error}")
        event, out = cmd.result
        live = out is not None
    else:
        from moeen.runtime.commands import apply_command
        event, _ = apply_command(kind, event_id, note, repo=repo, detector=None, events=None)
        live = False
    return jsonify({"event": event.to_dict(), "applied_to_live_incident": live})


@bp.post("/api/events/<int:event_id>/assistance")
def record_assistance(event_id: int):
    return _act(event_id, "assistance")


@bp.post("/api/events/<int:event_id>/resolve")
def resolve(event_id: int):
    return _act(event_id, "resolve")


# ---------------------------------------------------------------- preview
@bp.get("/api/preview.jpg")
def preview_jpg():
    ctx = _ctx()
    if not ctx["config"].dashboard.preview_enabled:
        raise ApiError(404, "The camera preview is turned off (dashboard.preview_enabled).")
    frame, _ = ctx["store"].latest_frame()
    if frame is None:
        raise ApiError(503, "No processed frame yet.")
    return Response(frame, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})


@bp.get("/video_feed")
def video_feed():
    ctx = _ctx()
    if not ctx["config"].dashboard.preview_enabled:
        raise ApiError(404, "The camera preview is turned off (dashboard.preview_enabled).")
    store = ctx["store"]

    def stream():
        seq = 0
        while not store.stopped:
            frame, new_seq = store.wait_for_frame(seq, timeout=1.0)
            if store.stopped:
                break
            if frame is None or new_seq == seq:
                continue
            seq = new_seq
            yield (f"--{_BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                   f"Content-Length: {len(frame)}\r\n\r\n").encode() + frame + b"\r\n"

    return Response(stream(), mimetype=f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
                    headers={"Cache-Control": "no-store"})
