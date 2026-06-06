# Health Research Assistant (GraphN)

A multi-agent workflow on [GraphN](https://graphn.ai) that answers health questions
with cited research briefs and plain-language patient guidance, sourced from live
PubMed papers and FDA drug labels.

> For demo / hackathon purposes only. Not medical advice.

## Architecture

```
question ──> Researcher ──> PatientAdvisor ──> result
              (PubMed +        (plain-language
               openFDA)         + citations)
```

| Component | Role |
|---|---|
| **Researcher** (`agent_2aa8dd010563`) | Searches PubMed via `search_medical_literature`, looks up FDA labels via `lookup_drug_info`, returns an evidence-based brief. Has explicit anti-prompt-injection guardrails. |
| **PatientAdvisor** (`agent_51b846ab8443`) | Translates findings into patient-friendly language with citations and safety disclaimers. |
| **HealthTools** (`mcp_a0b7b535fc33`) | Hosted MCP server exposing two tools, run in Firecracker microVM sandboxes. No API keys required. |

Workflow ID: `wf_d20b56206b85` · Workspace: `ws_100024a6d182`

## Repo layout

| Path | What |
|---|---|
| `workflow.yaml` | The workflow DSL (the DAG that wires the two agents). |
| `resources/agent_researcher.json` | Researcher agent definition (instructions, model, tools). |
| `resources/agent_patientadvisor.json` | PatientAdvisor agent definition. |
| `resources/mcp_healthtools.json` | HealthTools MCP server spec + tool schemas. |
| `inputs/*.json` | Example inputs for dry-runs. |
| `examples/` | Other GraphN workflow YAMLs kept as DSL-structure reference (not deployed). See `examples/README.md`. |

> Note: the HealthTools tool *source* (Python) is not exported by the API for
> hosted MCP servers — only the tool schemas. Edit tool code in the GraphN UI.

## Development loop

Requires the [GraphN CLI](https://graphn.ai) and `graphn login`.

```bash
# validate the DSL
graphn workflow validate ./workflow.yaml

# test without the gateway (first run is a ~1 min cold start)
graphn workflow dry-run wf_d20b56206b85 --input-file ./inputs/metformin.json

# push a DSL change, then publish
graphn workflow update wf_d20b56206b85 --dsl ./workflow.yaml
graphn workflow publish wf_d20b56206b85 -m "Describe change"

# production run (needs gateway URL configured)
graphn workflow run wf_d20b56206b85 --input-file ./inputs/ibuprofen.json
```

## Ideas / TODO

- [ ] Harden against the OWASP LLM Top 10 (Security Auditor starter scores starters ~3/10; target >7).
- [ ] Add a third agent that searches ClinicalTrials.gov (`clinicaltrials.gov/api/v2/studies`, no key).
- [ ] Confirm `lookup_drug_info` (openFDA) actually fires — the metformin dry-run fell back to PubMed when the FDA label could not be retrieved.
