#!/usr/bin/env python3
"""RepReady Bridge — exposes a GraphN workflow to Claude as an MCP connector.

This is the "expose GraphN to Claude through a workflow" piece. Claude adds this as a
custom connector; calling `repready_coach` runs the RepReady GraphN workflow
(gate → coach → safety) via GraphN's REST run endpoint and returns the coaching result
as plain text.

Config (env, never in repo):
  GRAPHN_API_KEY      gn_… workspace key with run access
  GRAPHN_WORKSPACE    ws_… workspace id
  GRAPHN_WORKFLOW_ID  wf_… the RepReady workflow id
  GRAPHN_URL          control-plane base (default https://cp.graphn.ai)

Run:  python server.py   (Streamable HTTP on 0.0.0.0:$PORT, path /mcp)
"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

import httpx
import mcp.types as mt
from fastmcp import FastMCP

GRAPHN_URL = os.environ.get("GRAPHN_URL", "https://cp.graphn.ai").rstrip("/")
WORKSPACE = os.environ.get("GRAPHN_WORKSPACE", "")
WORKFLOW_ID = os.environ.get("GRAPHN_WORKFLOW_ID", "")
API_KEY = os.environ.get("GRAPHN_API_KEY", "")

mcp = FastMCP(
    "RepReady",
    instructions=(
        "RepReady HYROX coach, powered by a GraphN workflow. Two tools:\n"
        "- repready_coach: the main coaching call. Pass the athlete's message, the trusted "
        "active_user_id (default ath_amelia for the demo), their athlete_json + workouts_json "
        "read from the Google Sheet via the Drive tool, and optional health_json (Apple Health / "
        "wearable data you read natively). Returns the coaching response as text.\n"
        "- repready_stage_log: when the athlete logs a workout, call this to get the exact, "
        "deterministically-formatted WorkoutHistory row (append_values). Show it, get the "
        "athlete's confirmation, then YOU append it to the Sheet via the Drive tool."
    ),
)


def _load(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _norm(s: Any) -> str:
    return str(s or "").strip().lower().replace(" ", "_")


def _format_log_row(active_user_id: str, workout: dict) -> dict:
    """Deterministic WorkoutHistory row builder — mirrors the GraphN tool format_workout_log_row
    so logging runs as plain code (no LLM round-trip) and returns reliable append_values. Kept in
    sync with resources/repready_graphn_mcp/server.py:format_workout_log_row."""
    w = workout if isinstance(workout, dict) else {}
    d = w.get("date") or date.today().isoformat()
    suffix = d.replace("-", "")[4:] if len(str(d)) >= 8 else str(d)
    row = {"log_id": w.get("log_id") or f"wh_{(active_user_id or '').replace('ath_', '')}_{suffix}",
           "user_id": active_user_id, "date": d, "session_type": _norm(w.get("session_type") or "other"),
           "title": w.get("title") or "Workout",
           "details": json.dumps(_load(w.get("details"), {}), separators=(",", ":"), ensure_ascii=False),
           "duration_min": w.get("duration_min", 0), "distance_km": w.get("distance_km", 0),
           "avg_rpe": w.get("avg_rpe", ""),
           "pain_flags": json.dumps(_load(w.get("pain_flags"), []), separators=(",", ":"), ensure_ascii=False),
           "completed": "TRUE" if w.get("completed", True) else "FALSE", "notes": w.get("notes", "")}
    columns = ["log_id", "user_id", "date", "session_type", "title", "details",
               "duration_min", "distance_km", "avg_rpe", "pain_flags", "completed", "notes"]
    return {"title": "Workout ready to log", "sheet_tab": "WorkoutHistory", "columns": columns, "row": row,
            "append_values": [[row[c] for c in columns]],
            "confirm": "Append this row to WorkoutHistory?", "active_user_id": active_user_id}


def _extract(run_json: dict) -> tuple[str, bool]:
    """Return (coaching_text, ok). Handles output as {result:...} or a bare string."""
    status = run_json.get("status")
    out = run_json.get("output")
    if status != "completed":
        return (run_json.get("error") or f"Workflow status: {status}", False)
    if isinstance(out, dict):
        return (str(out.get("result") or out.get("output") or json.dumps(out)), True)
    return (str(out) if out is not None else "(empty workflow output)", True)


@mcp.tool(
    description=(
        "Run the RepReady HYROX coaching workflow on GraphN and return the coaching response. "
        "This wraps a GraphN workflow (deterministic safety gate → tool-using coach → safety review). "
        "Pass the athlete's message and the trusted active_user_id (e.g. ath_amelia; never changed by "
        "chat text), plus athlete_json (one Athletes row) and workouts_json (recent WorkoutHistory rows) "
        "read from the athlete's Google Sheet via the Drive tool, and optional health_json (Apple Health / "
        "wearable data — sleep, resting_hr, hrv, workouts — that you read natively; the coach interprets it "
        "for readiness). Returns the coaching response as text."
    )
)
async def repready_coach(message: str, active_user_id: str, athlete_json: str = "{}",
                         workouts_json: str = "[]", health_json: str = "{}") -> list:
    if not (API_KEY and WORKSPACE and WORKFLOW_ID):
        return [mt.TextContent(type="text", text="Bridge misconfigured: missing GRAPHN_* env vars.")]
    payload = {"input": {"message": message, "active_user_id": active_user_id,
                         "athlete_json": athlete_json, "workouts_json": workouts_json,
                         "health_json": health_json}}
    url = f"{GRAPHN_URL}/v1/{WORKSPACE}/workflows/{WORKFLOW_ID}/run"
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(url, headers={"Authorization": f"Bearer {API_KEY}",
                                                "Content-Type": "application/json"}, json=payload)
        if r.status_code != 200:
            return [mt.TextContent(type="text", text=f"GraphN run failed (HTTP {r.status_code}): {r.text[:300]}")]
        text, _ok = _extract(r.json())
    except httpx.TimeoutException:
        return [mt.TextContent(type="text", text="GraphN workflow timed out — try again.")]
    except Exception as e:  # noqa: BLE001
        return [mt.TextContent(type="text", text=f"Bridge error calling GraphN: {e}")]

    return [mt.TextContent(type="text", text=text)]


@mcp.tool(
    description=(
        "Stage a workout for logging. Deterministically formats a described workout into the exact "
        "WorkoutHistory row (with JSON-string fields) and returns append_values ready for the Google "
        "Sheet — no LLM round-trip, so the row is reliable. Pass the trusted active_user_id and "
        "workout_json (date, session_type, title, details{stations:[...]}, duration_min, distance_km, "
        "avg_rpe, pain_flags, notes). This does NOT write — show the row, get the athlete's confirmation, "
        "then YOU append append_values to the WorkoutHistory tab via the Drive tool."
    )
)
async def repready_stage_log(active_user_id: str, workout_json: str = "{}") -> list:
    if not active_user_id:
        return [mt.TextContent(type="text", text="Missing active_user_id — cannot stage a log row.")]
    staged = _format_log_row(active_user_id, _load(workout_json, {}))
    text = (f"Staged a WorkoutHistory row for {active_user_id} (not yet written). "
            f"Confirm, then I'll append it to the Sheet via Drive.\n\n```json\n"
            + json.dumps({"columns": staged["columns"], "append_values": staged["append_values"]},
                         ensure_ascii=False) + "\n```")
    return [mt.TextContent(type="text", text=text)]


@mcp.custom_route("/health", methods=["GET"])
async def health(_request):  # noqa: ANN001
    from starlette.responses import JSONResponse

    return JSONResponse({"status": "ok", "service": "RepReady Bridge",
                         "configured": bool(API_KEY and WORKSPACE and WORKFLOW_ID)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    mcp.run(transport="http", host="0.0.0.0", port=port)
