# Example workflows (reference material)

These are GraphN starter/hackathon workflows kept here as **reference for DSL
structure and common patterns** — not workflows deployed from this repo. The
deployed workflow lives in [`../workflow.yaml`](../workflow.yaml).

Use them to see how the DSL wires agents, functions, MCP servers, loops, secrets,
and outputs together. Structure here is illustrative — adapt, don't copy verbatim.

## What each one demonstrates

| File | Pattern | Notable bits |
|---|---|---|
| [`city-explorer.yaml`](city-explorer.yaml) | **Two-agent research → synthesize** (same shape as our Health Research Assistant) | `res://` resource refs for agents/MCP; multi-field `input`; `after:` for sequencing; `input_template` threading prior step output via `${steps.scout.output}` |
| [`rag-research-assistant.yaml`](rag-research-assistant.yaml) | **Minimal RAG, two agents + KB** | Components referenced by **name with `{}`** (resolved at create time) instead of `res://` IDs; `chat_hints` steering how the chat UI fills `kb_id` |
| [`perplexity-company-data.yaml`](perplexity-company-data.yaml) | **Document ingest → RAG** with functions | `call: function` steps; `call: for_each` loop (`items`/`as`/`max_iterations`/`do`); fallback expressions `${ a || b || '' }`; functions + agents + MCP in one DAG |
| [`api-data-summarizer.yaml`](api-data-summarizer.yaml) | **Function fetch → agent summarize** (smallest useful shape) | JSON-string `input_template`; expression helpers like `JSON.stringify(...)`; optional input with `||` default |
| [`workflow-security-auditor.yaml`](workflow-security-auditor.yaml) | **Audit → harden**, the OWASP LLM Top 10 scorer | `secrets:` block with `$secret:` refs; MCP `AuditTools` that inspects other workflows. Run this against our workflow to score it. |

## Patterns worth internalizing

- **Reference styles:** `res://agents/agent_xxxx` (pinned ID) vs `Name: {}`
  (resolved by name at create time). Prefer IDs once components exist (per
  [`../CLAUDE.md`](../CLAUDE.md)).
- **Sequencing:** a step runs after everything in its `after:` list; omit `after`
  for the entry step(s).
- **Data flow:** `input_template` (string template) is how you feed prior output
  into agents. Never use `input: {prompt: ...}` for agent steps.
- **`output:`** maps a final `result` key from the last step's output.
- **`chat_hints`** tells the chat UI how to populate inputs — include it in every
  workflow.
- **Step kinds:** `call: agent`, `call: function`, `call: for_each`.

See [`developing-with-agents.md`](developing-with-agents.md) for the full CLI
edit → validate → dry-run → publish loop.
