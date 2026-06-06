#!/usr/bin/env python3
"""RepReady Tools — GraphN HOSTED MCP (JSON-only).

Same deterministic HYROX logic as the Lightning UI server, but every tool returns a
plain dict (GraphN agents consume JSON — no mcp-ui cards here; the inline UI lives in
the external bridge that fronts the workflow). Stateless: athlete data is passed in as
JSON strings (from the Google Sheet, read Claude-side). Every data tool takes a trusted
active_user_id.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from fastmcp import FastMCP

mcp = FastMCP("RepReady_Tools")

# ---------------------------------------------------------------- reference data
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
RULES = {"max_hi_sessions": 3, "min_rest_days": 1, "max_weekly_volume_increase_pct": 10, "taper_days": 10}
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
_SIDE_WORDS = {"left", "right", "l", "r", "upper", "lower", "both"}


def _benchmark_for(division: str, gender: str, station: str) -> dict[str, Any] | None:
    key = (division, gender)
    if key not in _DIV_GENDER_MULT or station not in _OPEN_M_TIMES:
        return None
    mult = _DIV_GENDER_MULT[key]
    tiers = {t: round(v * mult) for t, v in zip(_TIERS, _OPEN_M_TIMES[station])}
    return {"station": station, "division": division, "gender": gender,
            "weight_kg": _WEIGHTS.get(station, {}).get(key, 0),
            "reps": 100 if station == "wall_balls" else 0, **tiers}


def _load(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _aget(d: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _own_rows(rows: Any, active_user_id: str) -> tuple[list, int]:
    """Defense-in-depth: keep only rows that belong to the active user. A row with no
    user_id is trusted (kept); a row tagged to a DIFFERENT user is dropped. Returns
    (kept_rows, dropped_count). The skill should already pass only the active user's
    rows — this guarantees a stray foreign row can never leak through the tools."""
    aid = _norm(active_user_id)
    if isinstance(rows, dict):
        rows = [rows]
    kept: list = []
    dropped = 0
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        uid = _norm(_aget(r, "user_id", "athlete_id", "userId", default=""))
        if uid and aid and uid != aid:
            dropped += 1
            continue
        kept.append(r)
    return kept, dropped


def _athlete_matches(athlete: dict, active_user_id: str) -> bool:
    """True if the athlete row is the active user's (or carries no id to check)."""
    if not isinstance(athlete, dict) or not athlete:
        return True
    uid = _norm(_aget(athlete, "user_id", "athlete_id", "id", "userId", default=""))
    return uid in ("", _norm(active_user_id))


def _norm(s: Any) -> str:
    return str(s or "").strip().lower().replace(" ", "_")


def _area_words(area: Any) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", _norm(area)) if w and w not in _SIDE_WORDS}


def _tier_for(seconds: float, bm: dict[str, Any]) -> str:
    if seconds <= bm["elite_time_sec"]:
        return "elite"
    if seconds <= bm["competitive_time_sec"]:
        return "competitive"
    if seconds <= bm["intermediate_time_sec"]:
        return "intermediate"
    return "beginner"


def _stations_in(workout: dict) -> list[dict]:
    details = _load(workout.get("details"), {}) or {}
    stns = _load(details.get("stations"), None)
    if stns is None:
        stns = _load(workout.get("stations"), [])
    return stns or []


def _session_text(s: dict) -> str:
    return " ".join(str(s.get(k, "")) for k in ("targets", "notes", "title", "description", "focus", "name")).lower()


_REVEAL_PAT = re.compile(
    r"(system prompt|your instructions|ignore (your |previous |all )?instructions|developer mode|"
    r"reveal.*(prompt|instruction|tool)|print.*(prompt|instruction|tool list)|jailbreak|"
    r"what are your (rules|instructions|tools))", re.IGNORECASE)
_SWITCH_PAT = re.compile(
    r"(treat me as|act as|i am now|switch to|load (his|her|their|the other)|as (ath_|user )|"
    r"set (the )?active[_ ]user|pretend to be|you are now)", re.IGNORECASE)
_OTHER_USER_PAT = re.compile(r"\bath_[a-z0-9_]+\b", re.IGNORECASE)
_PAIN_PAT = re.compile(
    r"(sharp|stabbing|swollen|swelling|can'?t (walk|put weight)|popped|tore|torn|fracture|"
    r"acute|severe pain|really hurts|excruciating)", re.IGNORECASE)
_PUSH_PAT = re.compile(
    r"(push (me|through|past)|ignore the pain|no pain no gain|tough it out|train through|"
    r"work through (it|the pain)|grind through)", re.IGNORECASE)
_CUT_PAT = re.compile(
    r"((cut|drop|lose|shed|slash)\s+\d+(\.\d+)?\s?(kg|kgs|lb|lbs|pound|pounds)\s+(in|over|within)\s+"
    r"\d+\s*(day|days|hour|hours|hr|hrs)|cut\s+water|water\s+cut|dehydrat\w+|crash\s+diet|crash\s+cut|"
    r"starv\w+|sweat\s+(it|out|off|down)|sauna\s+(suit|cut)|rapid\s+weight\s+(loss|cut)|extreme\s+(cut|diet))",
    re.IGNORECASE)


@mcp.tool
def check_request_safety(message: str, active_user_id: str, requested_user_id: str = "") -> dict:
    """Deterministic privacy & safety gate. Call FIRST. Blocks cross-user data access,
    active-user switching, prompt/instruction reveal, push-through-(sharp)-pain, and
    rapid/extreme weight cuts. Pass the trusted active_user_id (and requested_user_id if
    the message names another athlete). Returns {allow, category, reason, user_message, matched_rules}."""
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
                        "message": ("I won't help with a rapid or extreme weight cut — it's unsafe and hurts performance. "
                                    "Safe change is ~0.5-1 kg/week; see a registered dietitian for more.")})
    if _PAIN_PAT.search(msg) and _PUSH_PAT.search(msg):
        matched.append({"rule_id": "rule_pain_no_impact", "category": "safety", "severity": "block",
                        "reason": "Request to push through sharp/acute pain.",
                        "message": ("I won't push you through sharp or acute pain. Offload it with low-impact work and "
                                    "get it assessed by a professional if it persists.")})
    blocked = [m for m in matched if m["severity"] == "block"]
    return {"allow": not blocked, "category": blocked[0]["category"] if blocked else "ok",
            "reason": blocked[0]["reason"] if blocked else "No safety rule triggered.",
            "user_message": blocked[0]["message"] if blocked else "",
            "matched_rules": matched, "active_user_id": active_user_id}


@mcp.tool
def get_benchmarks(division: str, gender: str, station: str = "") -> dict:
    """HYROX station standards (elite/competitive/intermediate/beginner split times + station
    weights) for a division ('Open'|'Pro') and gender ('M'|'F'). Omit station for all stations."""
    division = (division or "Open").title()
    gender = (gender or "F").upper()[:1]
    wanted = [_norm(station)] if station else STATIONS
    rows = [b for s in wanted if (b := _benchmark_for(division, gender, s))]
    return {"title": f"HYROX standards — {division} {gender}", "division": division, "gender": gender,
            "stations": rows, "note": "Illustrative reference splits (seconds)."}


@mcp.tool
def generate_training_summary(active_user_id: str, athlete_json: str = "{}", workouts_json: str = "[]") -> dict:
    """Summarize recent training + weak points vs benchmarks. athlete_json = one Athletes row;
    workouts_json = list of this user's WorkoutHistory rows. Weak points need logged station
    splits (details.stations[].time_sec)."""
    athlete = _load(athlete_json, {})
    workouts = _load(workouts_json, [])
    if isinstance(workouts, dict):
        workouts = [workouts]
    if not _athlete_matches(athlete, active_user_id):
        athlete = {}  # ignore an athlete row that isn't the active user's
    workouts, dropped_foreign = _own_rows(workouts, active_user_id)
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
        weak_points.append({"station": name, "your_best_sec": round(t), "tier": _tier_for(t, bm),
                            "competitive_sec": bm["competitive_time_sec"],
                            "gap_to_competitive_sec": round(t - bm["competitive_time_sec"])})
    weak_points.sort(key=lambda x: x["gap_to_competitive_sec"], reverse=True)
    payload = {
        "title": f"Training summary — {_aget(athlete, 'name', default=active_user_id)}",
        "athlete": {"name": _aget(athlete, "name", default=active_user_id), "division": division, "gender": gender,
                    "goal_event": _aget(athlete, "goal_event", "event", "target_event"),
                    "goal_event_date": _aget(athlete, "goal_event_date", "event_date", "goal_date", "target_event_date"),
                    "goal_finish_time": _aget(athlete, "goal_finish_time", "goal_time", "target_time"),
                    "current_pb": _aget(athlete, "current_pb", "pb", "personal_best")},
        "totals": {"sessions": len(workouts), "distance_km": round(total_distance, 1),
                   "avg_rpe": round(sum(rpes) / len(rpes), 1) if rpes else None, "hard_sessions": hard_sessions},
        "sessions_by_type": by_type, "pain_days": pain_days, "weak_points": weak_points[:5],
        "active_user_id": active_user_id,
    }
    if not weak_points:
        payload["weak_points_note"] = ("No structured station splits in recent workouts. Log station times as "
                                       "details.stations[].time_sec to surface weak points vs benchmark.")
    if dropped_foreign:
        payload["dropped_foreign_rows"] = dropped_foreign  # rows tagged to another user, ignored
    return payload


@mcp.tool
def validate_training_plan(active_user_id: str, plan_json: str = "{}", athlete_json: str = "{}") -> dict:
    """Validate a plan vs deterministic safety rules: <=3 hard sessions/week, >=1 rest day/week,
    <=10% weekly volume jump, no high-impact loading on an actively painful area (block if a session
    names the area; warn if a lower-limb pain flag is active and any high-impact session is scheduled),
    taper near the event. plan_json = {"weeks":[{"week":1,"sessions":[{"session_type":"intervals",
    "distance_km":7,"targets":"..."}]}]}. Returns {ok, summary, counts, weeks, issues}."""
    plan = _load(plan_json, {})
    athlete = _load(athlete_json, {})
    if not _athlete_matches(athlete, active_user_id):
        athlete = {}  # don't validate against another athlete's profile/injuries
    weeks = (plan.get("weeks") if isinstance(plan, dict) else plan) or []
    active_areas = sorted({
        _norm(inj.get("area")) for inj in _load(_aget(athlete, "injuries", "injury", default=[]), []) or []
        if isinstance(inj, dict) and _norm(inj.get("status")) in {"managing", "recovering", "active", "flaring"}
        and _norm(inj.get("area"))})
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
                                  "message": (f"Week {num}: high-impact '{stype}' while {', '.join(active_areas)} pain is "
                                              f"active — confirm it offloads the area or swap to low-impact.")})
        if event_date and idx == len(weeks) - 1:
            wk_issues.append({"rule_id": "rule_taper_before_event", "severity": "info",
                              "message": f"Week {num} is your final week — if inside ~10 days of {event_date}, taper volume ~40-50%."})
        issues.extend(wk_issues)
        week_reports.append({"week": num, "hard_sessions": hard, "rest_days": rest,
                             "volume_km": round(volume, 1), "issues": wk_issues})
        prev_volume = volume if volume else prev_volume
    blocks = [i for i in issues if i["severity"] == "block"]
    warns = [i for i in issues if i["severity"] == "warn"]
    return {"title": "Plan safety check", "ok": not blocks,
            "summary": ("Plan blocked — fix the safety issue below." if blocks else
                        f"{len(warns)} warning(s) to consider." if warns else "Plan passes all safety rules."),
            "counts": {"block": len(blocks), "warn": len(warns), "info": len(issues) - len(blocks) - len(warns)},
            "active_pain": active_areas, "weeks": week_reports, "issues": issues, "active_user_id": active_user_id}


@mcp.tool
def format_workout_log_row(active_user_id: str, workout_json: str = "{}") -> dict:
    """Turn a described workout into a WorkoutHistory row (JSON-string fields) ready to append to
    the Google Sheet. Returns {sheet_tab, columns, row, append_values, confirm}. Staging only —
    the caller appends via Drive after confirming."""
    w = _load(workout_json, {})
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


@mcp.tool
def summarize_recovery_context(active_user_id: str, health_json: str = "{}") -> dict:
    """Interpret Apple Health / wearable data into compact recovery signals. Claude reads the
    health data (it owns Apple Health access) and passes it in as health_json — this tool only
    INTERPRETS it, it does NOT plan training. health_json may include any of: sleep,
    resting_hr, hrv, and workouts — each a list of {date, value} (value aliases: hours/bpm/ms
    accepted). Returns sleep / resting-HR / HRV trends (recent vs baseline), 7-day workout
    count, and a deterministic readiness flag (green|amber|red) + one-line guidance hint."""
    h = _load(health_json, {})
    if not isinstance(h, dict):
        h = {}

    def _series(*keys: str) -> list[float]:
        raw = _load(_aget(h, *keys, default=[]), [])
        out: list[float] = []
        for x in (raw if isinstance(raw, list) else [raw]):
            v = x.get("value", x.get("hours", x.get("bpm", x.get("ms", x.get("minutes"))))) if isinstance(x, dict) else x
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                pass
        return out

    def _avg(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 1) if xs else None

    def _trend(xs: list[float], lower_is_better: bool) -> dict:
        recent, base = _avg(xs[-3:]), _avg(xs)
        if recent is None or base is None or len(xs) < 2:
            return {"recent": recent, "baseline": base, "direction": "flat", "pct_change": 0.0, "flag": "ok"}
        delta = recent - base
        pct = (delta / base * 100) if base else 0.0
        worse = (delta > 0) if lower_is_better else (delta < 0)
        return {"recent": recent, "baseline": base,
                "direction": "up" if delta > 0 else ("down" if delta < 0 else "flat"),
                "pct_change": round(pct, 1), "flag": "watch" if (worse and abs(pct) >= 5) else "ok"}

    sleep = _series("sleep", "sleep_hours", "sleepHours")
    rhr = _series("resting_hr", "resting_heart_rate", "restingHeartRate", "rhr")
    hrv = _series("hrv", "heart_rate_variability", "hrv_ms")
    workouts = _load(_aget(h, "workouts", "recent_workouts", default=[]), [])
    workouts, _ = _own_rows(workouts, active_user_id)

    sleep_t, rhr_t, hrv_t = _trend(sleep, False), _trend(rhr, True), _trend(hrv, False)
    last_sleep = sleep[-1] if sleep else None
    flags: list[str] = []
    if hrv_t["flag"] == "watch":
        flags.append("HRV suppressed vs baseline")
    if rhr_t["flag"] == "watch":
        flags.append("resting HR elevated vs baseline")
    if last_sleep is not None and last_sleep < 6:
        flags.append("short sleep last night")
    if sleep_t["recent"] is not None and sleep_t["recent"] < 6.5:
        flags.append("running a sleep debt")
    readiness = "red" if len(flags) >= 2 else ("amber" if flags else "green")
    hint = {"green": "Recovery looks fine — train as planned.",
            "amber": "One recovery flag — keep intensity in check and prioritize sleep.",
            "red": "Multiple recovery flags — favor easy/recovery work today, not a hard session."}[readiness]
    return {"title": "Recovery context", "readiness": readiness, "flags": flags, "guidance": hint,
            "sleep": {"last_night_hours": last_sleep, **sleep_t}, "resting_hr": rhr_t, "hrv": hrv_t,
            "recent_workouts_7d": len(workouts),
            "note": "Interpretation only — the coach decides the session. Not medical advice.",
            "active_user_id": active_user_id}


if __name__ == "__main__":
    mcp.run()
