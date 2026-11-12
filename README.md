# Automaton Auditor

The Automaton Auditor evaluates a GitHub repository and an accompanying report with a
LangGraph courtroom. Repository, document, and vision detectives collect structured
evidence in parallel. Three independent, schema-constrained judges assess each rubric
criterion, then deterministic Python rules resolve their opinions and write a Markdown
audit.

## Requirements

- Python 3.11 or newer
- Git
- An OpenAI API key (or another provider configured for LangChain)
- `uv`

## Setup

```powershell
uv sync --extra dev
Copy-Item .env.example .env
```

Set `OPENAI_API_KEY` and, if needed, `JUDGE_MODEL` in `.env`. Vision review is optional;
set `VISION_MODEL` to a vision-capable LangChain model to enable it. Judge responses allow
up to 4,096 output tokens. Judge identity and criterion IDs are attached by the application;
opinion fields use function calling with validated JSON-text fallback for compatible
OpenAI-style providers. LangSmith tracing is configured through the environment variables
in `.env.example`. The rubric and output
directory must be selected through `AUDITOR_RUBRIC`/`AUDIT_OUTPUT_DIR` or the matching
CLI options; clone hosts default to GitHub and GitLab and can be changed with
`ALLOWED_GIT_HOSTS`.

## Run

The report input accepts PDF, Markdown, or plain text. PDF inputs are parsed and their
embedded or vector diagrams are eligible for optional vision analysis.

```powershell
uv run automaton-auditor `
  --repo-url https://github.com/owner/repository `
  --rubric rubric.json `
  --pdf reports/final_report.pdf `
  --output-dir audit/report_onself_generated
```

The program prints the generated `audit_report.md` path and reports graph/provider
errors to standard error. Use separate output directories
for self, peer, and received reports. The target repository is cloned into a temporary
directory and removed after analysis; its code is parsed but never executed.

Validate a final PDF's file-path citations and architecture-section explanations against
the tracked repository:

```powershell
uv run check-audit-report --pdf reports/final_report.pdf --repo-root .
```

This checks cited paths against Git-tracked files. If `--repo-root` is not a Git
repository, it warns and checks against files present on disk instead.

Render the full graph topology as Mermaid for interim/final report diagrams:

```powershell
uv run draw-auditor-topology --output reports/auditor-topology.mmd
```

The generated Mermaid diagram uses dark text for readability and distinct colors for
each workflow role.

## Architecture

`ContextBuilder` loads and validates `rubric.json`. `RepoInvestigator`, `DocAnalyst`, and
`VisionInspector` run in parallel and write to reducer-backed state. `EvidenceAggregator`
cross-references report paths against the cloned repository before a conditional route
starts the parallel Prosecutor, Defense, and TechLead branches. `ChiefJustice` filters
unsupported opinions, applies statute score caps and variance handling, and writes the
final Markdown report. If repository evidence cannot be collected, `ErrorReport` writes a
failure report instead.

Repository scanners use Python AST parsing, not regular expressions, to inspect graph
edges, state types, tool safety, judge output validation, persona prompts, and synthesis.
`src/tools/doc_tools.py` includes bounded document chunking, term retrieval, path
extraction, and image/vector-diagram extraction.

## Tests

```powershell
uv run pytest
```

Graph compilation tests require the project dependencies. The judge and vision calls
require configured provider credentials and are not needed for the offline unit tests.

## Experimental extensions

CrewAI and AutoGen integrations are intentionally not part of the default runtime. The
`src/extensions/` package is reserved for opt-in experiments; no extension is imported by
the production graph.
