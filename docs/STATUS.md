# STATUS.md — Compass: Career Coach

> Updated as each layer ships. This is the living build log.

---

## Current Status: 🟡 Pre-build — Setup Phase

---

## Layer Status

| Layer | Status | Notes |
|---|---|---|
| Repo scaffold | ⬜ Not started | |
| Obsidian vault schema | ⬜ Not started | |
| ATS scrapers (Greenhouse) | ⬜ Not started | |
| ATS scrapers (Lever) | ⬜ Not started | |
| ATS scrapers (Ashby) | ⬜ Not started | |
| JobSpy wrapper | ⬜ Not started | |
| LangGraph pipeline skeleton | ⬜ Not started | |
| extract_node | ⬜ Not started | |
| score_node | ⬜ Not started | |
| reflection_node | ⬜ Not started | |
| hitl_node | ⬜ Not started | |
| tailor_node | ⬜ Not started | |
| vault_write_node | ⬜ Not started | |
| Langfuse self-hosted setup | ⬜ Not started | |
| Langfuse pipeline integration | ⬜ Not started | |
| MCP server | ⬜ Not started | |
| Eval dataset (30-50 pairs) | ⬜ Not started | |
| Eval harness runner | ⬜ Not started | |
| Modal deployment | ⬜ Not started | |
| Streamlit/dashboard | ⬜ Not started | |

---

## Build Order (Do in this sequence)

### Phase 1 — Foundation (Week 1)
- [ ] Scaffold repo with `uv init`, directory structure, pyproject.toml
- [ ] Set up Langfuse self-hosted with Docker
- [ ] Seed vault: copy profile docs, create skill-inventory.md
- [ ] Build Greenhouse scraper + tests
- [ ] Build Lever scraper + tests
- [ ] Build Ashby scraper + tests
- [ ] Define `RawJob` Pydantic model
- [ ] Define `CompassState` TypedDict
- [ ] Define vault frontmatter schemas (all note types)
- [ ] Build vault writer functions

### Phase 2 — Core Pipeline (Week 2)
- [ ] Build `extract_node` with Pydantic AI
- [ ] Build `score_node` with Langfuse tracing
- [ ] Build `reflection_node`
- [ ] Wire LangGraph graph (no HiTL yet)
- [ ] End-to-end test: scrape → extract → score → write to vault
- [ ] Verify Langfuse traces showing cost per run

### Phase 3 — Intelligence Layer (Week 3)
- [ ] Add `hitl_node` with LangGraph interrupt()
- [ ] Add `tailor_node`
- [ ] Build eval dataset (30 pairs)
- [ ] Build eval harness runner
- [ ] Run first eval, log to Langfuse
- [ ] Generate first study plan

### Phase 4 — Portfolio Polish (Week 4)
- [ ] Build MCP server with 6 tools
- [ ] Add Modal cron deployment
- [ ] Mermaid architecture diagram in README
- [ ] Public Langfuse trace URL in README
- [ ] Eval results chart (precision vs. cost)
- [ ] Write blog post / project write-up
- [ ] Update resume with career coach bullet + GitHub URL

---

## Milestone Log
<!-- Agent appends here as milestones are hit -->

- `2026-05-15` — Project initialized, docs written, vault seeded
