# Developing with agents: CLI, Cursor, and Claude Code

Reference copy of the GraphN guide for building/iterating on workflows from the
terminal and AI coding assistants (not just the web UI).

> `graphn workflow` and `graphn wf` are the same command; `graphn blueprint` and
> `graphn bp` are the same command.

## 1. Install the CLI

Homebrew (macOS / Linux):

```bash
brew tap voltagepark/graphn
brew install graphn
```

Verify / update:

```bash
graphn version
graphn --help
graphn update
```

## 2. Authenticate

Browser login (recommended) — no API key needed:

```bash
graphn login
```

Or API key (CI / shared environments): create a key in the web app under
Workspace Settings → API Keys, then:

```bash
graphn init --setup-only
graphn whoami
graphn config show
```

Override config via env vars (useful in CI):

| Variable | Purpose |
|---|---|
| `GRAPHN_API_KEY` | API key |
| `GRAPHN_URL` | API base URL (prod: `https://cp.graphn.ai`) |
| `GRAPHN_WORKSPACE` | Workspace ID |
| `GRAPHN_GATEWAY_URL` | Required for `graphn workflow run` (production execution via gateway) |

## 3. Bootstrap the repo for AI assistants (`graphn init`)

`graphn init` (without `--setup-only`) writes files that teach Cursor and Claude
Code how to use the CLI:

| Output | Purpose |
|---|---|
| `.cursor/rules/graphn.md` | Cursor rules: which commands when, patterns, safety |
| `CLAUDE.md` | Instructions for Claude Code (appended if it exists) |

Flags: `--setup-only` (setup, no rules), `--skills-only` (rules, no setup),
`--cursor-only` / `--claude-only`.

## 4. Embedded skills and docs (`graphn docs`)

```bash
graphn docs skills                    # list available skills
graphn docs skills workflow-building  # patterns, deploy checklist, secrets
graphn docs skills rag-pipeline       # RAG / knowledge-base workflows
graphn docs skills debugging          # failure diagnosis, common errors
graphn docs skills gateway-modes      # sync vs async, --gateways flag, polling
graphn docs skills dsl-reference      # full DSL schema and CLI command reference
graphn docs dsl | api | helpers | all
```

## 5. Expose the CLI to the IDE via MCP (`graphn mcp-serve`)

MCP lets Cursor / Claude Code call CLI commands as structured tools.

```bash
graphn mcp-serve   # stdio; the IDE spawns it
```

Cursor — `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "graphn": { "command": "graphn", "args": ["mcp-serve"] }
  }
}
```

Claude Code — `~/.claude/settings.json` under `mcpServers` (same shape). Ensure
`graphn` is on the `PATH` where the IDE runs.

## 6. The development loop

```bash
# inspect
graphn context
graphn workflow list

# edit (push local DSL to the API)
graphn workflow update <workflow-id-or-name> --dsl ./workflow.yaml

# validate
graphn workflow validate ./workflow.yaml
graphn workflow validate ./workflow.yaml --deep

# test without the gateway
graphn workflow dry-run <workflow-id-or-name> --input-file ./input.json

# publish so production resolves pinned versions
graphn agent publish "<Agent Name>"
graphn workflow publish <workflow-id-or-name> -m "Describe change"

# production run (needs gateway URL)
graphn config set-gateway-url https://your-gateway-base
graphn workflow run <workflow-id-or-name> --input-file ./input.json
```

Use `-f text` for human-readable tables, `-v` for HTTP traces.

## 7. Blueprints from the CLI

```bash
graphn blueprint list
graphn blueprint info kb-ingestion
graphn blueprint deploy kb-ingestion --name "My Company KB Search"
```

Blueprint IDs/names change — always use `graphn blueprint list` as source of truth.

## 8. Extending beyond default templates

The Company Knowledge Search blueprint gives you storage → OCR → KB ingest →
Researcher (RAG) → Synthesizer. To match a strict domain workflow you typically:

- Extend MCP tools (keyword search, document listing, bounded full-text read).
- Rewrite Researcher / Synthesizer instructions for your output schema (tables,
  columns, evidence quotes).
- Dry-run on real data and iterate until stakeholders sign off.

Update resources from the terminal with `graphn agent update …`,
`graphn mcp-server update …` (`mcp-server` and `mcp` are the same command).

## 9. Troubleshooting

| Issue | What to try |
|---|---|
| 401 / 403 | `graphn init --setup-only`; check key/workspace. After a CP URL change, `graphn config set-key <new_key>` then `graphn whoami`. |
| `publish "My Workflow"` not found | Use the workflow ID (`wf_…`) from `graphn workflow list`. |
| `workflow run` says gateway required | Set `GRAPHN_GATEWAY_URL` or `graphn config set-gateway-url`. |
| MCP tools not appearing | Confirm `graphn mcp-serve` runs manually; check IDE MCP config and PATH. |
| `mcp start --wait` timed out | Safe to ignore for dry-run / runs; runtime starts the server on first tool call. |
| Dry-run / run hangs or times out | Workflow likely > ~2 min. Use async: `graphn workflow run <id> --mode async --input '…'`, then `graphn exec get <exec_id> --watch`. |
| Feature missing after `graphn update` | Verify with `graphn version`; check GitHub Releases for the newest tag. |

For deeper debugging: `graphn docs skills debugging`. For sync vs async:
`graphn docs skills gateway-modes`.
