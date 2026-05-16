# STATUS.md — Compass: Career Coach

> Updated as each layer ships. This is the living build log.

---

## Current Status: 🟡 Plan complete — Ready to implement

Architecture amendments designed and reviewed. Implementation plan at `docs/superpowers/plans/2026-05-16-architecture-amendments.md`.

---

## Layer Status

| Layer | Status | Notes |
|---|---|---|
| Repo scaffold | ✅ Done | uv project, pyproject.toml, directory structure |
| Obsidian vault schema | ✅ Done | Frontmatter schemas in vault/schemas.py, vault seeded with profile docs |
| Architecture design | ✅ Done | ARCHITECTURE.md, amendments plan reviewed and approved |
| RAG layer (Chroma + retriever) | ⬜ Not started | Plan: Task 2-4 |
| HiTL state store | ⬜ Not started | Plan: Task 5 |
| ATS scrapers (Greenhouse) | ⬜ Not started | Plan: Phase 1 |
| ATS scrapers (Lever) | ⬜ Not started | |
| ATS scrapers (Ashby) | ⬜ Not started | |
| JobSpy wrapper | ⬜ Not started | |
| LangGraph pipeline skeleton | ⬜ Not started | graph.py wired, nodes stubbed |
| extract_node | ⬜ Not started | |
| score_node (with RAG) | ⬜ Not started | Plan: Task 4 |
| reflection_node | ⬜ Not started | |
| hitl_node (with external timeout) | ⬜ Not started | Plan: Task 6 |
| tailor_node | ⬜ Not started | |
| vault_write_node | ⬜ Not started | |
| Parallel job processing | ⬜ Not started | Plan: Task 7 |
| Langfuse self-hosted setup | ⬜ Not started | docker-compose.yml ready |
| Langfuse pipeline integration | ⬜ Not started | |
| MCP server | ⬜ Not started | |
| Eval dataset (30-50 pairs) | ⬜ Not started | |
| Eval harness (score MAE + context recall) | ⬜ Not started | Plan: Task 9 |
| Modal deployment (daily scan + timeout checker) | ⬜ Not started | |

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

- `2026-05-15` — Project initialized, docs written, vault seeded
- `2026-05-16` — Architecture amendments designed: RAG layer, HiTL external timeout, parallel processing. Plan reviewed, 5 bugs caught and fixed. Ready to implement.
