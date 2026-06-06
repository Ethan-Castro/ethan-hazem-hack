# RepReady Live GraphN HYROX Agent Plan

## Summary

- Pull latest `main` first before implementation work.
- Replace the root Health Research Assistant with **RepReady**, a GraphN HYROX coaching workflow.
- Use Google Sheets/Drive through the planned Claude connector, not direct Google OAuth code in this repo.
- Preserve the current health workflow as reference under `examples/health-research-assistant/`.

## Key Changes

- Remove all custom Google OAuth bootstrap work, refresh-token storage, and Google credential secrets from scope.
- Treat the Claude Google connector as the authenticated data layer for Sheets/Drive access.
- Keep local JSON seed files for demos, tests, and initializing connector-backed Sheet data.
- Add `HYROXTrainingTools` as the MCP/tool layer for:
  - `get_user_training_context`
  - `get_recent_workouts`
  - `get_benchmarks`
  - `generate_training_summary`
  - `validate_training_plan`
  - `log_workout`
- Enforce user scoping inside tools with trusted `active_user_id`; chat text cannot switch users.

## GraphN Workflow Design

- Root workflow: `hyrox_secure_training_agent`.
- Inputs:
  - `message`
  - `active_user_id`
  - optional `conversation_context`
- Output:
  - `result`
- Steps:
  - `Intake_Agent`: classify intent and detect prompt injection/privacy attacks.
  - `Privacy_Gate`: deterministic guard before any user data access.
  - `Context_Agent`: retrieves connector-backed athlete context through MCP tools.
  - `Coach_Logger_Agent`: generates workouts, plans, analysis, or logs completed workouts.
  - `Safety_Agent`: validates coaching output before final response.
- YAML follows the repo's GraphN format: `document`, typed `input`, `chat_hints`, `agents`, `mcp_servers`, sequenced `steps`, and `output.result`.

## Connector Plan

- The Claude connector owns Google auth and grants access to the target Sheet/Drive file.
- MCP tools call a connector-backed adapter rather than using raw Google OAuth.
- If connector access is unavailable during local tests, tools fall back to local JSON fixtures.
- README documents required connector setup: connect Google account, expose the RepReady Sheet, confirm read/write access.

## Test Plan

- Demo prompts cover today's workout, logging, shin pain adjustment, weak-point analysis, and six-week plan generation.
- Adversarial prompts verify refusal for cross-user data, prompt reveal, unsafe pain advice, active user switching, and extreme weight cuts.
- Tool tests verify user scoping, safety validation, logging behavior, and JSON fallback.
- Acceptance: live/chat demo gives personalized coaching, uses connector-backed data, logs workouts, and refuses unsafe/privacy attacks.

## Assumptions

- Project name remains **RepReady**.
- Claude connector auth is available before live demo.
- Google Sheets is primary data storage; local JSON is fallback and seed data only.
- No Google OAuth client, service account, or refresh token code will be implemented in this repo.
