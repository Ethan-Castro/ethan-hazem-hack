# RepReady skill (`/repready`)

RepReady is a HYROX training-coach **Claude skill** (a slash command you run on claude.ai or Claude Desktop). It prescribes daily sessions, logs workouts, analyzes weak points against HYROX benchmarks, and builds/validates training plans — all for **one trusted athlete** whose data lives in a Google Sheet they own.

`SKILL.md` is the behavior spec Claude executes: the trusted-user/privacy model, the 5-stage turn flow (intake → privacy gate → context → coach/log → safety), when to call each tool, and how to handle every demo and adversarial scenario.

## What it pairs with

The skill is the **orchestrator**. It depends on two connectors that you install separately:

1. **RepReady MCP connector** ("RepReady Tools") — a remote MCP server providing the HYROX domain logic and inline UI cards: `check_request_safety`, `get_benchmarks`, `generate_training_summary`, `validate_training_plan`, `format_workout_log_row`. Deploy it and get its public URL via `resources/repready_mcp/DEPLOY-lightning.md`. **The connector URL comes from the Lightning deploy** (e.g. `https://repready-mcp-<hash>.lightning.ai/mcp`); add it under Settings → Connectors → Add custom connector.
2. **Google Drive connector** (native, built into Claude) — used for **all athlete data access**: searching/reading the RepReady Google Sheet and appending workout-log rows. Connect it under Settings → Connectors. The Sheet schema is `resources/repready_seed/SCHEMA.md`.

Without both connectors the skill cannot read data, run the safety gate, or render its cards.

## Install as a slash command

On **claude.ai**:
1. Settings → **Skills** (Capabilities) → **Upload skill**.
2. Upload this `SKILL.md` (zip the `repready_skill/` folder if a folder is required).
3. Invoke it in any chat by typing `/repready`.

On **Claude Desktop**: place this skill in your skills directory and restart, then run `/repready`.

Before the first run, make sure the **Google Drive** connector is connected and the **RepReady** custom connector (Lightning URL) is added, so the tools and Sheet are available when the skill runs.

> Demo athlete: **Amelia Rivera (`ath_amelia`)**. The trusted `active_user_id` is set by the skill context and is never changed by chat input.
