#!/usr/bin/env python3
"""RepReady Bridge — exposes a GraphN workflow to Claude as an MCP connector.

This is the "expose GraphN to Claude through a workflow" piece. Claude adds this as a
custom connector; calling `repready_coach` runs the RepReady GraphN workflow
(gate → coach → safety) via GraphN's REST run endpoint and returns the coaching result
PLUS an inline mcp-ui response card (rendered from the result).

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
from pathlib import Path

import httpx
import mcp.types as mt
from fastmcp import FastMCP

GRAPHN_URL = os.environ.get("GRAPHN_URL", "https://cp.graphn.ai").rstrip("/")
WORKSPACE = os.environ.get("GRAPHN_WORKSPACE", "")
WORKFLOW_ID = os.environ.get("GRAPHN_WORKFLOW_ID", "")
API_KEY = os.environ.get("GRAPHN_API_KEY", "")
UI_DIR = Path(__file__).parent / "ui"

mcp = FastMCP(
    "RepReady",
    instructions=(
        "RepReady HYROX coach, powered by a GraphN workflow. Call repready_coach with the "
        "athlete's message and trusted active_user_id (default ath_amelia for the demo), plus "
        "their athlete_json and workouts_json read from the Google Sheet via the Drive tool."
    ),
)


def _ui_result(payload: dict, ui_file: str, text: str) -> list:
    blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = (UI_DIR / ui_file).read_text(encoding="utf-8")
    tag = f"<script>window.__REPREADY_DATA__ = {blob};</script>"
    html = html.replace("</head>", tag + "\n</head>", 1) if "</head>" in html else tag + html
    return [
        mt.TextContent(type="text", text=text),
        mt.EmbeddedResource(type="resource", resource=mt.TextResourceContents(
            uri=f"ui://repready/{ui_file}", mimeType="text/html", text=html)),
    ]


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
        "read from the athlete's Google Sheet via the Drive tool. Renders an inline coaching card."
    )
)
async def repready_coach(message: str, active_user_id: str,
                         athlete_json: str = "{}", workouts_json: str = "[]") -> list:
    if not (API_KEY and WORKSPACE and WORKFLOW_ID):
        return [mt.TextContent(type="text", text="Bridge misconfigured: missing GRAPHN_* env vars.")]
    payload = {"input": {"message": message, "active_user_id": active_user_id,
                         "athlete_json": athlete_json, "workouts_json": workouts_json}}
    url = f"{GRAPHN_URL}/v1/{WORKSPACE}/workflows/{WORKFLOW_ID}/run"
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(url, headers={"Authorization": f"Bearer {API_KEY}",
                                                "Content-Type": "application/json"}, json=payload)
        if r.status_code != 200:
            return [mt.TextContent(type="text", text=f"GraphN run failed (HTTP {r.status_code}): {r.text[:300]}")]
        text, ok = _extract(r.json())
    except httpx.TimeoutException:
        return [mt.TextContent(type="text", text="GraphN workflow timed out — try again.")]
    except Exception as e:  # noqa: BLE001
        return [mt.TextContent(type="text", text=f"Bridge error calling GraphN: {e}")]

    card = {"response": text, "active_user_id": active_user_id, "ok": ok,
            "source": "GraphN workflow · RepReady"}
    return _ui_result(card, "response.html", text)


@mcp.custom_route("/health", methods=["GET"])
async def health(_request):  # noqa: ANN001
    from starlette.responses import JSONResponse

    return JSONResponse({"status": "ok", "service": "RepReady Bridge",
                         "configured": bool(API_KEY and WORKSPACE and WORKFLOW_ID)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    mcp.run(transport="http", host="0.0.0.0", port=port)
