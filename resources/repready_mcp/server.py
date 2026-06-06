#!/usr/bin/env python3
"""RepReady Tools — a HYROX coaching MCP connector (FastMCP + mcp-ui inline UIs).

Remote MCP server: host it publicly (Lightning AI), add the URL as a Claude custom
connector, and register the same URL in GraphN as a `remote` MCP. See DEPLOY-lightning.md.

UI approach (mcp-ui): tools that have a visual return a second content block — an
embedded `text/html` resource whose data is INLINED server-side as
`window.__REPREADY_DATA__`. The HTML is self-contained (no external SDK / CDN / CSP /
client handshake), so it renders inline in claude.ai and Claude Desktop. The first
content block is always the JSON text so the model can read the result too.

Design: STATELESS. Athlete data lives in the user's Google Sheet (read/written by
Claude's native Google Drive tool) and is passed in as JSON strings. No Google creds.
Every data tool takes a TRUSTED `active_user_id` (set by the caller, never chat text);
`check_request_safety` enforces scope/privacy/safety deterministically.

Run locally:  python server.py            (Streamable HTTP on 0.0.0.0:$PORT, path /mcp)
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import mcp.types as mt
from fastmcp import FastMCP

UI_DIR = Path(__file__).parent / "ui"

mcp = FastMCP(
    "RepReady Tools",
    instructions=(
        "HYROX coaching tools. Always pass the trusted active_user_id; never switch users "
        "or expose another athlete's data. Call check_request_safety first."
    ),
)

# ----------------------------------------------------------------------------------
# Embedded HYROX reference data (kept in sync with resources/repready_seed/generate_seed.py)
# ----------------------------------------------------------------------------------
STATIONS = [
    "1km_run", "ski_erg_1000m", "sled_push_50m", "sled_pull_50m",
    "burpee_broad_jump_80m", "row_1000m", "farmers_carry_200m",
    "sandbag_lunge_100m", "wall_balls",
]
_OPEN_M_TIMES = {
    "1km_run": [210, 255, 300, 360], "ski_erg_1000m": [195, 225, 260, 310],
    "sled_push_50m": [60, 95, 140, 200], "sled_pull_50m": [75, 110, 160, 220],
    "burpee_broad_jump_80m": [180, 240, 300, 390], "row_1000m": [200, 230, 265, 320],
    "farmers_carry_200m": [60, 80, 105, 140], "sandbag_lunge_100m": [150, 210, 270, 360],
    "wall_balls": [240, 330, 450, 600],
}
_DIV_GENDER_MULT = {("Open", "M"): 1.00, ("Open", "F"): 1.12, ("Pro", "M"): 1.05, ("Pro", "F"): 1.17}
_WEIGHTS = {
    "sled_push_50m": {("Open", "M"): 152, ("Open", "F"): 102, ("Pro", "M"): 202, ("Pro", "F"): 152},
    "sled_pull_50m": {("Open", "M"): 103, ("Open", "F"): 78, ("Pro", "M"): 153, ("Pro", "F"): 103},
    "farmers_carry_200m": {("Open", "M"): 48, ("Open", "F"): 32, ("Pro", "M"): 64, ("Pro", "F"): 48},
    "sandbag_lunge_100m": {("Open", "M"): 20, ("Open", "F"): 10, ("Pro", "M"): 30, ("Pro", "F"): 20},
    "wall_balls": {("Open", "M"): 6, ("Open", "F"): 4, ("Pro", "M"): 9, ("Pro", "F"): 6},
}
_TIERS = ("elite_time_sec", "competitive_time_sec", "intermediate_time_sec", "beginner_time_sec")

# Deterministic training-rule thresholds (mirror the TrainingRules tab).
RULES = {"max_hi_sessions": 3, "min_rest_days": 1, "max_weekly_volume_increase_pct": 10, "taper_days": 10}

# Broad classifiers so the validator/summary recognise real-world session names.
HARD_SESSIONS = {
    "intervals", "hyrox_sim", "hyrox_simulation", "threshold", "tempo", "race_sim",
    "race_simulation", "race_pace", "vo2", "vo2max", "vo2_max", "speed", "sprints",
    "fartlek", "brick", "plyometric", "plyometrics", "track",
}
IMPACT_SESSIONS = HARD_SESSIONS | {"run", "long_run", "easy_run", "recovery_run", "jog", "running"}
LOWER_LIMB = {
    "shin", "shins", "knee", "knees", "ankle", "ankles", "foot", "feet", "calf", "calves",
    "achilles", "hip", "hips", "quad", "quads", "hamstring", "hamstrings", "itb", "it_band",
    "plantar", "tibia", "tibial",
}


def _benchmark_for(division: str, gender: str, station: str) -> dict[str, Any] | None:
    key = (division, gender)
    if key not in _DIV_GENDER_MULT or station not in _OPEN_M_TIMES:
        return None
    mult = _DIV_GENDER_MULT[key]
    tiers = {t: round(v * mult) for t, v in zip(_TIERS, _OPEN_M_TIMES[station])}
    return {"station": station, "division": division, "gender": gender,
            "weight_kg": _WEIGHTS.get(station, {}).get(key, 0),
            "reps": 100 if station == "wall_balls" else 0, **tiers}


# ----------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------
def _load(value: Any, default: Any) -> Any:
    """Accept a JSON string OR an already-parsed object; fall back to default."""
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _aget(d: dict, *keys: str, default: Any = None) -> Any:
    """First non-empty value among aliased keys (tolerates input key variations)."""
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _norm(s: Any) -> str:
    return str(s or "").strip().lower().replace(" ", "_")


_SIDE_WORDS = {"left", "right", "l", "r", "upper", "lower", "both"}


def _area_words(area: Any) -> set[str]:
    """Significant body-part words in an injury area, e.g. 'left_shin' -> {'shin'}."""
    return {w for w in re.split(r"[^a-z0-9]+", _norm(area)) if w and w not in _SIDE_WORDS}


def _tier_for(seconds: float, bm: dict[str, Any]) -> str:
    if seconds <= bm["elite_time_sec"]:
        return "elite"
    if seconds <= bm["competitive_time_sec"]:
        return "competitive"
    if seconds <= bm["intermediate_time_sec"]:
        return "intermediate"
    return "beginner"


def _result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _ui_result(payload: dict[str, Any], ui_file: str) -> list:
    """Return [text JSON for the model, embedded text/html resource for inline UI].

    The payload is inlined into the HTML as window.__REPREADY_DATA__ so the card
    renders with no external SDK, CDN, CSP allowance, or client handshake.
    """
    blob = _result(payload).replace("</", "<\\/")  # neutralise </script>
    html = (UI_DIR / ui_file).read_text(encoding="utf-8")
    tag = f"<script>window.__REPREADY_DATA__ = {blob};</script>"
    html = html.replace("</head>", tag + "\n</head>", 1) if "</head>" in html else tag + html
    return [
        mt.TextContent(type="text", text=_result(payload)),
        mt.EmbeddedResource(
            type="resource",
            resource=mt.TextResourceContents(
                uri=f"ui://repready/{ui_file}", mimeType="text/html", text=html
            ),
        ),
    ]


# ----------------------------------------------------------------------------------
# Tool 1: deterministic privacy / safety gate (no UI)
# ----------------------------------------------------------------------------------
_REVEAL_PAT = re.compile(
    r"(system prompt|your instructions|ignore (your |previous |all )?instructions|"
    r"developer mode|reveal.*(prompt|instruction|tool)|print.*(prompt|instruction|tool list)|"
    r"jailbreak|what are your (rules|instructions|tools))",
    re.IGNORECASE,
)
_SWITCH_PAT = re.compile(
    r"(treat me as|act as|i am now|switch to|load (his|her|their|the other)|"
    r"as (ath_|user )|set (the )?active[_ ]user|pretend to be|you are now)",
    re.IGNORECASE,
)
_OTHER_USER_PAT = re.compile(r"\bath_[a-z0-9_]+\b", re.IGNORECASE)
_PAIN_PAT = re.compile(
    r"(sharp|stabbing|swollen|swelling|can'?t (walk|put weight)|popped|tore|torn|"
    r"fracture|acute|severe pain|really hurts|excruciating)", re.IGNORECASE,
)
_PUSH_PAT = re.compile(
    r"(push (me|through|past)|ignore the pain|no pain no gain|tough it out|"
    r"train through|work through (it|the pain)|grind through)", re.IGNORECASE,
)
# Rapid/extreme cut: number + unit + short timeframe (days/hours), or unsafe-method keywords.
_CUT_PAT = re.compile(
    r"("
    r"(cut|drop|lose|shed|slash)\s+\d+(\.\d+)?\s?(kg|kgs|lb|lbs|pound|pounds)\s+"
    r"(in|over|within)\s+\d+\s*(day|days|hour|hours|hr|hrs)"
    r"|cut\s+water|water\s+cut|dehydrat\w+|crash\s+diet|crash\s+cut|starv\w+|"
    r"sweat\s+(it|out|off|down)|sauna\s+(suit|cut)|rapid\s+weight\s+(loss|cut)|extreme\s+(cut|diet)"
    r")", re.IGNORECASE,
)


@mcp.tool(
    description=(
        "Deterministic privacy & safety gate. Call this FIRST on every user turn. "
        "Blocks cross-user data access, active-user switching, prompt/instruction reveal, "
        "unsafe 'push through (sharp) pain' advice, and rapid/extreme weight cuts. No UI. "
        "Pass the trusted active_user_id, and requested_user_id if the message names another athlete."
    )
)
def check_request_safety(message: str, active_user_id: str, requested_user_id: str = "") -> str:
    msg = message or ""
    matched: list[dict[str, str]] = []

    others = {u.lower() for u in _OTHER_USER_PAT.findall(msg)} - {(active_user_id or "").lower()}
    if (requested_user_id and requested_user_id != active_user_id) or others:
        matched.append({"rule_id": "rule_scope_active_user", "category": "scope", "severity": "block",
                        "reason": "Request targets a different athlete's data.",
                        "message": "I can only access your own training data."})
    if _SWITCH_PAT.search(msg):
        matched.append({"rule_id": "rule_scope_active_user", "category": "scope", "severity": "block",
                        "reason": "Attempt to switch the active user from chat text.",
                        "message": "I can't switch which athlete I'm coaching from chat — identity is set securely."})
    if _REVEAL_PAT.search(msg):
        matched.append({"rule_id": "rule_no_prompt_reveal", "category": "privacy", "severity": "block",
                        "reason": "Attempt to reveal system instructions / tool list.",
                        "message": "I can't share my internal instructions, but I'm happy to help with your HYROX training."})
    if _CUT_PAT.search(msg):
        matched.append({"rule_id": "rule_no_extreme_cut", "category": "safety", "severity": "block",
                        "reason": "Rapid/extreme weight-cut request.",
                        "message": ("I won't help with a rapid or extreme weight cut — it's unsafe and hurts "
                                    "performance. Safe change is ~0.5-1 kg/week; see a registered dietitian for more.")})
    if _PAIN_PAT.search(msg) and _PUSH_PAT.search(msg):
        matched.append({"rule_id": "rule_pain_no_impact", "category": "safety", "severity": "block",
                        "reason": "Request to push through sharp/acute pain.",
                        "message": ("I won't push you through sharp or acute pain. Offload it with low-impact "
                                    "work and get it assessed by a professional if it persists.")})

    blocked = [m for m in matched if m["severity"] == "block"]
    return _result({
        "allow": not blocked,
        "category": blocked[0]["category"] if blocked else "ok",
        "reason": blocked[0]["reason"] if blocked else "No safety rule triggered.",
        "user_message": blocked[0]["message"] if blocked else "",
        "matched_rules": matched,
        "active_user_id": active_user_id,
    })


# ----------------------------------------------------------------------------------
# Tool 2: benchmarks (UI: benchmarks table)
# ----------------------------------------------------------------------------------
@mcp.tool(
    description=(
        "Return HYROX station standards (elite/competitive/intermediate/beginner split times "
        "+ station weights) for a division ('Open'|'Pro') and gender ('M'|'F'). Omit `station` "
        "for all stations. Renders a benchmark table card."
    )
)
def get_benchmarks(division: str, gender: str, station: str = "") -> list:
    division = (division or "Open").title()
    gender = (gender or "F").upper()[:1]
    wanted = [_norm(station)] if station else STATIONS
    rows = [b for s in wanted if (b := _benchmark_for(division, gender, s))]
    return _ui_result({
        "title": f"HYROX standards — {division} {gender}",
        "division": division, "gender": gender, "stations": rows,
        "note": "Illustrative reference splits (seconds). Swap in authoritative numbers later.",
    }, "benchmarks.html")


# ----------------------------------------------------------------------------------
# Tool 3: training summary / weak points (UI: dashboard)
# ----------------------------------------------------------------------------------
def _stations_in(workout: dict) -> list[dict]:
    """Station entries from details.stations OR a top-level `stations` list."""
    details = _load(workout.get("details"), {}) or {}
    stns = _load(details.get("stations"), None)
    if stns is None:
        stns = _load(workout.get("stations"), [])
    return stns or []


@mcp.tool(
    description=(
        "Summarize an athlete's recent training and surface weak points vs HYROX benchmarks. "
        "Pass the trusted active_user_id, athlete_json (one Athletes row), and workouts_json (a "
        "list of WorkoutHistory rows for THIS user). Weak points need logged station splits "
        "(details.stations[].time_sec). Renders a dashboard card."
    )
)
def generate_training_summary(active_user_id: str, athlete_json: str = "{}", workouts_json: str = "[]") -> list:
    athlete = _load(athlete_json, {})
    workouts = _load(workouts_json, [])
    if isinstance(workouts, dict):
        workouts = [workouts]

    division = (_aget(athlete, "division", default="Open")).title()
    gender = (_aget(athlete, "gender", default="F")).upper()[:1]

    by_type: dict[str, int] = {}
    total_distance = 0.0
    rpes: list[float] = []
    pain_days: list[str] = []
    hard_sessions = 0
    station_best: dict[str, float] = {}

    for w in workouts:
        st = _norm(w.get("session_type") or "other")
        by_type[st] = by_type.get(st, 0) + 1
        if st in HARD_SESSIONS:
            hard_sessions += 1
        try:
            total_distance += float(w.get("distance_km") or 0)
        except (TypeError, ValueError):
            pass
        try:
            if w.get("avg_rpe") not in (None, ""):
                rpes.append(float(w["avg_rpe"]))
        except (TypeError, ValueError):
            pass
        if _load(w.get("pain_flags"), []):
            pain_days.append(w.get("date", "?"))
        for stn in _stations_in(w):
            name = _norm(stn.get("station") or stn.get("name"))
            t = stn.get("time_sec") or stn.get("seconds") or stn.get("time")
            if name in _OPEN_M_TIMES and t:
                try:
                    station_best[name] = min(station_best.get(name, 1e9), float(t))
                except (TypeError, ValueError):
                    pass

    weak_points = []
    for name, t in station_best.items():
        bm = _benchmark_for(division, gender, name)
        if not bm:
            continue
        weak_points.append({
            "station": name, "your_best_sec": round(t), "tier": _tier_for(t, bm),
            "competitive_sec": bm["competitive_time_sec"],
            "gap_to_competitive_sec": round(t - bm["competitive_time_sec"]),
        })
    weak_points.sort(key=lambda x: x["gap_to_competitive_sec"], reverse=True)

    payload = {
        "title": f"Training summary — {_aget(athlete, 'name', default=active_user_id)}",
        "athlete": {
            "name": _aget(athlete, "name", default=active_user_id),
            "division": division, "gender": gender,
            "goal_event": _aget(athlete, "goal_event", "event", "target_event"),
            "goal_event_date": _aget(athlete, "goal_event_date", "event_date", "goal_date", "target_event_date"),
            "goal_finish_time": _aget(athlete, "goal_finish_time", "goal_time", "target_time"),
            "current_pb": _aget(athlete, "current_pb", "pb", "personal_best"),
        },
        "totals": {
            "sessions": len(workouts), "distance_km": round(total_distance, 1),
            "avg_rpe": round(sum(rpes) / len(rpes), 1) if rpes else None,
            "hard_sessions": hard_sessions,
        },
        "sessions_by_type": by_type,
        "pain_days": pain_days,
        "weak_points": weak_points[:5],
        "active_user_id": active_user_id,
    }
    if not weak_points:
        payload["weak_points_note"] = (
            "No structured station splits found in recent workouts. Log station times as "
            "details.stations[].time_sec (e.g. sled_push_50m) to surface weak points vs benchmark."
        )
    return _ui_result(payload, "dashboard.html")


# ----------------------------------------------------------------------------------
# Tool 4: validate a training plan (UI: plan view with badges)
# ----------------------------------------------------------------------------------
def _session_text(s: dict) -> str:
    return " ".join(str(s.get(k, "")) for k in ("targets", "notes", "title", "description", "focus", "name")).lower()


@mcp.tool(
    description=(
        "Validate a proposed training plan against deterministic safety rules: max 3 hard "
        "sessions/week (intervals, hyrox_sim, threshold, tempo, race_sim, vo2, speed, plyo, "
        "brick...), >=1 rest/recovery day/week, <=10% weekly volume jump, no high-impact loading "
        "on an actively painful area (block if a session names the area; warn if a lower-limb pain "
        "flag is active and any high-impact session is scheduled), taper near the event. "
        "plan_json = {\"weeks\":[{\"week\":1,\"sessions\":[{\"day\":\"Mon\",\"session_type\":\"intervals\","
        "\"distance_km\":7,\"targets\":\"...\"}]}]}. athlete_json optional (pain/event checks). "
        "Renders a plan view with pass/warn/block badges."
    )
)
def validate_training_plan(active_user_id: str, plan_json: str = "{}", athlete_json: str = "{}") -> list:
    plan = _load(plan_json, {})
    athlete = _load(athlete_json, {})
    weeks = (plan.get("weeks") if isinstance(plan, dict) else plan) or []

    active_areas = sorted({
        _norm(inj.get("area"))
        for inj in _load(_aget(athlete, "injuries", "injury", default=[]), []) or []
        if isinstance(inj, dict)
        and _norm(inj.get("status")) in {"managing", "recovering", "active", "flaring"}
        and _norm(inj.get("area"))
    })
    lower_limb_active = any(_area_words(a) & LOWER_LIMB for a in active_areas)

    event_date = None
    raw_date = _aget(athlete, "goal_event_date", "event_date", "goal_date", "target_event_date")
    try:
        if raw_date:
            event_date = datetime.strptime(str(raw_date)[:10], "%Y-%m-%d").date()
    except ValueError:
        pass

    issues: list[dict[str, Any]] = []
    week_reports: list[dict[str, Any]] = []
    prev_volume: float | None = None

    for idx, wk in enumerate(weeks):
        num = wk.get("week", idx + 1)
        sessions = wk.get("sessions", []) or []
        hard = sum(1 for s in sessions if _norm(s.get("session_type")) in HARD_SESSIONS)
        rest = sum(1 for s in sessions if _norm(s.get("session_type")) in {"rest", "recovery", "off", "mobility"})
        volume = sum(float(s.get("distance_km") or 0) for s in sessions)
        wk_issues: list[dict[str, Any]] = []

        if hard > RULES["max_hi_sessions"]:
            wk_issues.append({"rule_id": "rule_max_hi_sessions", "severity": "warn",
                              "message": f"Week {num}: {hard} hard sessions (>3) — add an easy/recovery day."})
        if rest < RULES["min_rest_days"]:
            wk_issues.append({"rule_id": "rule_min_rest_days", "severity": "warn",
                              "message": f"Week {num}: no rest/recovery day — schedule at least one."})
        if prev_volume and volume > prev_volume * (1 + RULES["max_weekly_volume_increase_pct"] / 100):
            wk_issues.append({"rule_id": "rule_weekly_volume_jump", "severity": "warn",
                              "message": f"Week {num}: volume jumps >10% ({prev_volume:.0f}→{volume:.0f} km) — ramp gradually."})

        for s in sessions:
            stype = _norm(s.get("session_type"))
            if stype not in IMPACT_SESSIONS:
                continue
            twords = {w for w in re.split(r"[^a-z0-9]+", _session_text(s)) if w}
            named = [a for a in active_areas if _area_words(a) & twords]
            if named:
                wk_issues.append({"rule_id": "rule_pain_no_impact", "severity": "block",
                                  "message": (f"Week {num}: high-impact '{stype}' explicitly loads an actively painful "
                                              f"area ({', '.join(named)}) — swap to low-impact engine work (bike/ski/row).")})
            elif lower_limb_active:
                wk_issues.append({"rule_id": "rule_pain_no_impact", "severity": "warn",
                                  "message": (f"Week {num}: high-impact '{stype}' while {', '.join(active_areas)} "
                                              f"pain is active — confirm it offloads the area or swap to low-impact.")})

        if event_date and idx == len(weeks) - 1:
            wk_issues.append({"rule_id": "rule_taper_before_event", "severity": "info",
                              "message": f"Week {num} is your final week — if it's inside ~10 days of {event_date}, taper volume ~40-50%."})

        issues.extend(wk_issues)
        week_reports.append({"week": num, "hard_sessions": hard, "rest_days": rest,
                             "volume_km": round(volume, 1), "issues": wk_issues})
        prev_volume = volume if volume else prev_volume

    blocks = [i for i in issues if i["severity"] == "block"]
    warns = [i for i in issues if i["severity"] == "warn"]
    return _ui_result({
        "title": "Plan safety check",
        "ok": not blocks,
        "summary": ("Plan blocked — fix the safety issue below." if blocks else
                    f"{len(warns)} warning(s) to consider." if warns else "Plan passes all safety rules."),
        "counts": {"block": len(blocks), "warn": len(warns), "info": len(issues) - len(blocks) - len(warns)},
        "active_pain": active_areas,
        "weeks": week_reports,
        "issues": issues,
        "active_user_id": active_user_id,
    }, "plan.html")


# ----------------------------------------------------------------------------------
# Tool 5: format a workout log row (UI: log confirmation card)
# ----------------------------------------------------------------------------------
@mcp.tool(
    description=(
        "Turn a described workout into a WorkoutHistory row (with JSON-string fields) ready for "
        "Claude to append to the Google Sheet. Pass the trusted active_user_id and workout_json = "
        "{\"date\":\"2026-06-13\",\"session_type\":\"station_work\",\"title\":\"...\",\"details\":{...},"
        "\"duration_min\":57,\"distance_km\":0.5,\"avg_rpe\":8,\"pain_flags\":[],\"notes\":\"\"}. "
        "Renders a log-confirmation card. This only STAGES the row — confirm with the user, then "
        "append it yourself via the Drive tool. It does not write to the Sheet."
    )
)
def format_workout_log_row(active_user_id: str, workout_json: str = "{}") -> list:
    w = _load(workout_json, {})
    d = w.get("date") or date.today().isoformat()
    suffix = d.replace("-", "")[4:] if len(str(d)) >= 8 else str(d)
    row = {
        "log_id": w.get("log_id") or f"wh_{(active_user_id or '').replace('ath_', '')}_{suffix}",
        "user_id": active_user_id,
        "date": d,
        "session_type": _norm(w.get("session_type") or "other"),
        "title": w.get("title") or "Workout",
        "details": json.dumps(_load(w.get("details"), {}), separators=(",", ":"), ensure_ascii=False),
        "duration_min": w.get("duration_min", 0),
        "distance_km": w.get("distance_km", 0),
        "avg_rpe": w.get("avg_rpe", ""),
        "pain_flags": json.dumps(_load(w.get("pain_flags"), []), separators=(",", ":"), ensure_ascii=False),
        "completed": "TRUE" if w.get("completed", True) else "FALSE",
        "notes": w.get("notes", ""),
    }
    columns = ["log_id", "user_id", "date", "session_type", "title", "details",
               "duration_min", "distance_km", "avg_rpe", "pain_flags", "completed", "notes"]
    return _ui_result({
        "title": "Workout ready to log",
        "sheet_tab": "WorkoutHistory",
        "columns": columns,
        "row": row,
        "append_values": [[row[c] for c in columns]],
        "confirm": "Append this row to WorkoutHistory? (the skill writes it via Google Drive)",
        "active_user_id": active_user_id,
    }, "log.html")


@mcp.custom_route("/health", methods=["GET"])
async def health(_request):  # noqa: ANN001
    """Plain 200 for load-balancer / deployment health checks (MCP lives at /mcp)."""
    from starlette.responses import JSONResponse

    return JSONResponse({"status": "ok", "service": "RepReady Tools"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    mcp.run(transport="http", host="0.0.0.0", port=port)
