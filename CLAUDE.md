<!-- graphn:start -->
# GraphN Workflow Builder

GraphN is an AI workflow platform for building agent workflows with LLMs, functions, MCP tools, knowledge bases, and connectors.

**STOP. Before creating ANY components, you MUST:**

1. **Ask the user clarifying questions ONE AT A TIME.** Show progress like "(1/5)". Cover: input format, expected output, external APIs/secrets, models/constraints, error handling. Skip obvious ones.

2. **Propose your architecture and wait for approval.** Describe components, flow, and rationale. **Do NOT proceed until the user confirms.**

**ALWAYS use `graphn_`-prefixed MCP tools instead of shelling out to `graphn` CLI commands.** MCP tools are faster, don't require shell approval, and return structured JSON. Only fall back to the CLI for commands not available as MCP tools (e.g. `graphn docs skills`, `graphn scaffold`, `graphn init`).

**Parallelize with subagents:** When building a workflow with multiple independent components, launch subagents to create them in parallel (one per component). Each subagent writes the code/instructions, creates the component, and returns the ID. Then the parent writes the DSL with all IDs.

## Built-in Platform Capabilities

Functions run in isolated Firecracker VMs with `foundry_helpers` pre-installed. **Do NOT use external APIs for features that are built in.** Import what you need: `from foundry_helpers import asr, vision, storage`

| Module | What it does | When to use |
|--------|-------------|-------------|
| `asr` | Speech-to-text (NeMo/Canary). `transcribe`, `transcribe_video`, `transcribe_chunked` | Transcription, subtitles, voice-to-text |
| `qwen3_asr` | Qwen3-ASR-1.7B. 52+ languages, word-level timestamps, batch, chat-guided ASR | Multilingual transcription, timestamp-rich output |
| `audio` | Extract WAV from video, get duration/metadata | Pre-processing for ASR pipelines |
| `media` | Combined ASR + vision pipelines. `analyze_video`, `summarize_video` | Full video understanding |
| `qwen3_tts` | Text-to-speech (Qwen3-TTS). 10 languages, 9 speakers, voice design, voice cloning | Speech synthesis, audiobook, voiceover |
| `vision` | Image/video analysis (Qwen3-VL). `analyze`, `describe`, `extract_text`, `analyze_video` | Image Q&A, OCR, video scene analysis |
| `image` | Image generation and editing | Creating images |
| `kb` | Knowledge base search, embed, ingest | RAG pipelines |
| `storage` | File I/O (S3-compatible). Upload, download, list, presign | Passing files between steps |
| `models` | List/query available LLMs | Model selection |

`ffmpeg` and `ffprobe` are also available in the VM. `httpx` is pre-installed for external API calls.

**Load `graphn docs skills dsl-helpers` for full API signatures before writing code.**

For detailed guides, load a specific skill:
  `graphn docs skills workflow-building` — End-to-end workflow building: pattern selection, component creation, agent/function/MCP design, and DSL reference
  `graphn docs skills rag-pipeline`      — How to build RAG workflows with knowledge bases
  `graphn docs skills debugging`         — How to debug failed workflows using logs, validate, and describe
  `graphn docs skills dsl-schema`        — Full DSL schema, step types, expressions, and IDs vs Names
  `graphn docs skills dsl-commands`      — CLI command reference tables for all graphn subcommands
  `graphn docs skills dsl-helpers`       — foundry_helpers Python API for functions and MCP servers
  `graphn docs skills dsl-api`           — REST API endpoint reference and curl examples
  `graphn docs skills event-gateway`     — Event-gateway triggers: cron schedules, webhooks, HMAC auth, and graphn trigger commands
  `graphn docs skills gateway-modes`     — Sync, async, batch, and event gateway modes: when to use each, --gateways flag, async polling pattern

## Example workflows (reference, in `examples/`)

The deployed workflow is `workflow.yaml` at the repo root. The `examples/` directory holds other GraphN starter/hackathon workflows kept **purely as DSL-structure reference** — they are NOT deployed from this repo. Skim them to see how the DSL is shaped before writing or editing DSL; adapt patterns, do not copy verbatim. See [examples/README.md](examples/README.md) for what each demonstrates.

| File | Pattern it shows |
|------|------------------|
| `examples/city-explorer.yaml` | Two-agent research → synthesize (our same shape); `res://` ID refs; `after:` sequencing |
| `examples/rag-research-assistant.yaml` | Minimal RAG; components by name with `{}`; `chat_hints` for input steering |
| `examples/perplexity-company-data.yaml` | `call: function` + `call: for_each` loop; functions + agents + MCP in one DAG |
| `examples/api-data-summarizer.yaml` | Smallest function-fetch → agent-summarize; JSON-string `input_template`, expression helpers |
| `examples/workflow-security-auditor.yaml` | `secrets:` with `$secret:` refs; audit → harden (OWASP LLM Top 10) |

`examples/developing-with-agents.md` — the full CLI install / auth / edit → validate → dry-run → publish loop, MCP-serve setup, and troubleshooting.

## RepReady (separate connector + skill — NOT a GraphN workflow)

`resources/repready_*` and `docs/reprepready-plan.md` are a second project: **RepReady**, a HYROX
coaching connector. Architecture: **Claude → bridge MCP → GraphN workflow** ("expose GraphN to
Claude through a workflow"). It IS a GraphN workflow (`wf_ab431a4cbd4d`) — see `resources/mcp_repready.json`.

- `resources/repready_graphn_mcp/server.py` — the GraphN **hosted** MCP `RepReady_Tools` (`mcp_043108c75b0f`, 5 JSON-only tools) the workflow's agents call.
- `resources/repready_workflow/` — the GraphN workflow DSL (gate → coach → safety) + agent instructions (`RepReady_Coach` `agent_7848a0374eda`, `RepReady_Safety` `agent_78aab7559c73`).
- `resources/repready_bridge/` — a thin **FastMCP** bridge on **Lightning AI** exposing one tool `repready_coach`, which POSTs to the GraphN workflow run endpoint and re-renders the result as an inline mcp-ui card. This is the URL Claude adds as a custom connector. Holds `GRAPHN_*` as Lightning deployment env.
- `resources/repready_mcp/` — the original standalone Lightning tools server + data-driven UI cards; **superseded** by the workflow for the Claude path (kept as reference).
- `resources/repready_skill/SKILL.md` — the `/repready` Claude skill: reads the athlete's Google Sheet via Claude's native Drive tool, calls `repready_coach`, writes log rows back. Tools take a trusted `active_user_id`.
- MCP endpoint path is `/mcp` (no trailing slash). Never commit Lightning/GraphN/Google secrets (gitignored); rotate keys after the event.

## Critical Rules (MUST follow)

- **ALWAYS use the returned ID** after any `create` command for ALL subsequent operations — `get`, `update`, `publish`, `test`, `delete`. Names can resolve to wrong resources. NEVER pass a name where an ID is expected.
- **ALWAYS publish components before testing** — runtime uses published versions: `graphn agent publish-all && graphn func publish-all && graphn mcp publish-all`
- **ALWAYS include `chat_hints`** in every workflow DSL. ALWAYS use `result` as the output key.
- **ALWAYS validate before creating** — `graphn wf validate workflow.yaml`
- **ALWAYS verify MCP tool discovery** — `graphn mcp tools <mcp_id>` after creating an MCP server
- **Do NOT delete and recreate a workflow just to update it** — use `graphn wf update <ID> --dsl <file>` then re-publish. Delete + recreate loses version history and creates orphaned component copies. If agent linking fails after update, fix the root cause (usually a name mismatch) and update again — do NOT delete.
- **NEVER use `from mcp.server.fastmcp import FastMCP`** — MUST use `from fastmcp import FastMCP`. requirements.txt MUST include `fastmcp`.
- **NEVER use `input: {prompt: ...}` for agent steps** — MUST use `input_template:`. The executor ignores input.prompt.
- **NEVER use `async def run(input)`** — Use a named async function with typed params and `**kwargs`
- **NEVER hardcode model names** — discover with `graphn model list-chat`
- **NEVER pipe CLI output through fragile parsers** — CLI commands may mix stderr warnings with JSON on stdout. Read CLI JSON output directly or use `2>/dev/null` to suppress warnings.
- **NEVER embed raw API keys or tokens in commands** — if the user provides a secret, create it with `graphn secret create --name "X" --value "..."` and reference as `$secret:sec_xxx` in the DSL.
- **ALWAYS add timeouts and error handling** in function code — use `httpx.AsyncClient(timeout=30)`, catch exceptions, return structured error dicts.
- **NEVER write DSL YAML from memory** — ALWAYS start with `graphn scaffold workflow` or load `graphn docs skills dsl-schema` first.
- **NEVER write foundry_helpers code from memory** — ALWAYS load `graphn docs skills dsl-helpers` first to get correct function signatures.
- **NEVER guess CLI flags** — if unsure about a command, run `graphn <command> --help` to see available options.
- Check connectors first (`graphn connector list`) before writing custom functions for Slack, GitHub, HTTP, etc.
- **Agent names in the DSL `agents:` section must match the agent's actual name exactly.** Avoid spaces in agent names — use underscores (e.g. `Transcript_Summarizer`, not `Transcript Summarizer`). Mismatches cause silent bundling failures.
- **After `wf create`, ALWAYS use workflow-scoped IDs for updates.** `wf create` clones standalone components into the workflow. The workflow uses these clones, NOT the originals. To update a component in a workflow: run `graphn agent list --workflow <wf_id>` (or `func list`/`mcp list`) to get the workflow-scoped IDs, then `graphn agent update <workflow_scoped_id> ...`. NEVER update the standalone version expecting it to affect the workflow — it won't.

**Before writing workflow DSL or foundry_helpers code, ALWAYS load the reference first.** Do NOT guess API signatures or DSL fields.

For long sessions: if the agent seems confused or keeps repeating mistakes, start a new conversation.

Full docs: https://graphn.ai/docs
<!-- graphn:end -->