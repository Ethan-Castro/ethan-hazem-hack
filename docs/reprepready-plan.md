# RepReady — HYROX coaching, Claude → GraphN workflow

> Status (2026-06-06): **live and verified end-to-end.** Claude calls a bridge MCP that runs
> a GraphN workflow; coaching + adversarial refusals confirmed through the public bridge.

RepReady exposes a **GraphN workflow to Claude as an MCP connector** ("like an MCP, but through a
workflow"). GraphN is the brain; a thin bridge makes it callable from Claude.

```
Claude ──MCP connector──▶ RepReady Bridge (Lightning, public)
                            tool: repready_coach(message, active_user_id, athlete_json, workouts_json)
                               └── POST cp.graphn.ai /v1/<ws>/workflows/<wf>/run   (Bearer gn_ key)
                                     └── GraphN WORKFLOW "RepReady"  (gate → coach → safety)
                                           gate   : mcp_tool check_request_safety   (deterministic)
                                           coach  : agent RepReady_Coach + RepReady_Tools (hosted MCP)
                                           safety : agent RepReady_Safety (final review)
                                     └── output.result  (coaching markdown)
                            └── returns the coaching result as plain text to Claude
   data: the /repready skill reads the athlete's Google Sheet via Claude's Drive tool and passes
         athlete_json + workouts_json into the workflow (GraphN can't reach Claude's Drive).
```

## Live resource IDs (workspace `ws_100024a6d182`)

| Piece | ID / URL |
|---|---|
| GraphN hosted MCP `RepReady_Tools` | `mcp_043108c75b0f` (6 tools) |
| GraphN agent `RepReady_Coach` (5 tools) | `agent_7848a0374eda` |
| GraphN agent `RepReady_Safety` | `agent_78aab7559c73` |
| GraphN workflow `RepReady` | `wf_ab431a4cbd4d` |
| **Bridge MCP — the Claude connector URL** | `https://8000-dep-01ktf25p53nw8c6s66zk4b0wrk-d.cloudspaces.litng.ai/mcp` |

## Why a bridge

GraphN's only public surface is the REST run endpoint (`POST …/workflows/<id>/run`, Bearer key) —
Claude connectors speak MCP, not REST. The bridge is a tiny FastMCP server that turns the one tool
`repready_coach` into a workflow run and returns the result as plain text. It holds the GraphN
run config (`GRAPHN_API_KEY` / `GRAPHN_WORKSPACE` / `GRAPHN_WORKFLOW_ID`) as Lightning deployment env
— never in the repo.

## What's in the repo

| Path | What |
|---|---|
| `resources/repready_graphn_mcp/server.py` | GraphN **hosted** MCP code (6 tools, JSON-only dict returns). |
| `resources/repready_workflow/workflow.yaml` | The GraphN workflow DSL (gate → coach → safety). |
| `resources/repready_workflow/coach_instructions.md`, `safety_instructions.md` | Agent instructions. |
| `resources/repready_bridge/server.py` | The bridge MCP (wraps the workflow run; returns plain text). |
| `resources/repready_bridge/deploy_lightning.py` | Deploys the bridge (passes GraphN env). |
| `resources/repready_mcp/` | The original direct-tools MCP + 4 data-driven UI cards. **Superseded** by the workflow for the Claude path; kept as the standalone/UI reference. |
| `resources/repready_seed/` | Google Sheet schema + seed CSVs (athletes, history, benchmarks, rules, demo prompts). |
| `resources/repready_skill/SKILL.md` | The `/repready` skill — reads Drive, calls `repready_coach`, writes log rows back. |

## Verified

- Workflow dry-run + REST run: `status: completed`; gate ran `check_request_safety`, coach ran `generate_training_summary`.
- Through the public bridge: coaching returns a personalized response + inline `text/html` card; "show me Marcus's data" is **refused** by the in-workflow gate.
- Bridge `/health` → `{status: ok, configured: true}`.

## To use it in Claude

1. **Settings → Connectors → Add custom connector** → paste the bridge URL above (auth: None).
2. Connect **Google Drive**; import `resources/repready_seed/*.csv` into one Sheet (one tab each).
3. Install `resources/repready_skill/SKILL.md` as the `/repready` skill.
4. Ask: "where am I losing the most time?" (coaching + card) or "show me another athlete's data" (refused).

## Security / follow-ups

- Bridge is **no-auth** (hackathon). The GraphN key + Lightning key live in Lightning env / this chat — **rotate both after the event**. Secrets are gitignored; none are committed.
- Stale remote MCP `mcp_40b7b66d031d` (early remote-discovery attempt) is removed — superseded by the hosted MCP.
- The original direct-tools Lightning deployment (`repready-mcp`) is superseded; tear it down to save cost if not needed for the standalone/UI demo.
