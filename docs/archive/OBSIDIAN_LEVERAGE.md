# Obsidian Leverage — Design Proposals

> The vault is currently a markdown store with YAML frontmatter. Obsidian renders it but the only Obsidian-specific feature we use is Dataview on the dashboard. This doc maps the unused capabilities — wikilinks, graph view, embeds, Bases, Canvas, tags — to concrete project-relevant uses. Pick what to build; the proposals are sized.

**Current state:** 23 JobNotes, 95 SkillNotes, 9 CompanyNotes, 0 ApplicationNotes. Skills appear in JobNote frontmatter as plain string lists (`skills_required: [Python, LangGraph]`). No bidirectional navigation. Graph view is empty.

---

## P1. Bidirectional skill ↔ job wikilinks (your specific ask)

**Goal:** click "Python" in a JobNote → see every job requiring Python. Click any skill in graph view → see the constellation of jobs that demand it. Find rare skills (skills appearing in 1-2 jobs) vs commodity ones (appearing in 10+).

### How Obsidian wikilinks work

`[[Python]]` in any markdown file:
- Renders as a clickable link
- Creates a backlink on the target file (`skills/Python.md` shows "Linked mentions" of the source)
- Appears as an edge in the graph view

Obsidian resolves `[[Python]]` to any file named `Python.md` in the vault. Since `compass-vault/skills/Python.md` exists, the link works. (No `skills/` prefix needed unless there's an ambiguous filename collision.)

### Proposal — non-invasive

Keep the typed frontmatter (`skills_required: [Python, LangGraph]`) as the source of truth — Dataview queries and Python validation both depend on it. ADD a new section to the JobNote body that renders as wikilinks for human navigation + graph view.

**Change to `compass/vault/writer.py:write_job_note`** — when writing the JobNote body, prepend a section like:

```markdown
## Skills

**Required:** [[Python]] · [[LangGraph]] · [[MCP]]
**Nice to have:** [[FastAPI]]
**Matched:** [[Python]] · [[MCP]]
**Missing:** [[LangGraph]] · [[Sub-agents]]

---
```

(One line per category. Bullet/list works too — `- [[Python]]` per line — but inline `·`-separated is denser and reads well.)

**Change to gap_aggregator's `_sync_skill_counters`** (which already updates SkillNote frontmatter): also write a "Jobs Requiring This Skill" section to the SkillNote body. Two options:

**Option A — static list, rewritten each run** (simpler, no plugin dependency):
```markdown
## Jobs requiring this skill

- [[2026-03-27-companya-Software_Engineer_Agent_Architecture-04a9b65f|CompanyA — Software Engineer, Agent Architecture]] · score 3.0 · apply-now
- [[2026-05-06-companyb-Software_Engineer-7c26fdaf|CompanyB — Software Engineer]] · score 3.0 · apply-now
- [[2025-04-18-companya-Software_Engineer_Agent-8f58539b|CompanyA — Software Engineer, Agent]] · score 4.5 · apply-now
```

Sortable by score; renders as clickable links. Updated atomically on each gap-aggregator regen.

**Option B — Dataview query block** (more powerful, requires Dataview plugin which is already used):
````markdown
## Jobs requiring this skill

```dataview
TABLE company, match_score AS Score, tier
FROM "jobs"
WHERE econtains(skills_required, this.file.name)
SORT match_score DESC
```
````

Always fresh, sortable in the UI, no per-job rewriting.

**Recommendation: Option A first, Option B if it gets stale.** Option A is more robust because it works even if Dataview is disabled or breaks. Option B is fancier but couples to a plugin.

### Effort

- Writer body-section change: **30 min** (one new function, wire into `write_job_note`)
- SkillNote body update: **30 min** (extend `_sync_skill_counters` to write the Jobs section)
- Tests: 2 small unit tests
- One-time backfill: write a script that walks existing JobNotes and re-renders body sections (similar to the B6 migration script)
- **Total: ~2 hours**

### What you get

- Click `[[Python]]` in any JobNote → land on `skills/Python.md` → see every JobNote requiring it, ranked by score
- Graph view (Obsidian sidebar → "Open graph view") shows clusters. Skills appearing in many JobNotes become hub nodes. Rare skills are peripheral.
- Visual answer to your specific question — *"which skills are required across many jobs and which are rare/specific"*

---

## P2. Skill rarity dashboard panel

**Goal:** at a glance, see which skills are commodity (every JD wants them) vs differentiated (rare, niche, harder to source).

**Implementation:** add a Dataview block to `compass-vault/dashboard.md`:

````markdown
## Skill rarity — which gaps to prioritize

```dataview
TABLE WITHOUT ID
  file.link AS Skill,
  appears_in_jobs AS "in jobs",
  my_level AS "my level",
  gap_score AS "gap score"
FROM "skills"
WHERE appears_in_jobs > 0
SORT appears_in_jobs DESC, gap_score DESC
LIMIT 30
```

## Rare/specialized skills (appears in 1-2 jobs only)

```dataview
TABLE WITHOUT ID
  file.link AS Skill,
  appears_in_jobs AS "in jobs"
FROM "skills"
WHERE appears_in_jobs > 0 AND appears_in_jobs <= 2
SORT appears_in_jobs ASC
```
````

### Effort

- **5 min** to add to dashboard.md
- No code changes

### What you get

- Top panel: skills sorted by demand frequency. The "commodity" skills (Python, Docker) at the top. Investing in them helps for many jobs.
- Second panel: skills appearing in 1-2 jobs only. These are differentiators — if you don't have them, only specific roles surface. If you DO have them, you can target those niche roles confidently.

---

## P3. Auto-tags on JobNotes for filter dimensions

**Goal:** flexible filtering via Obsidian's tag system. Find all "stretch" jobs across companies, all "apply-now-fit" jobs, all jobs requiring TypeScript, etc.

**Current state:** JobNote has `tags: list[str]` in frontmatter but nothing populates it.

**Proposal:** `vault_write_node` auto-generates tags based on JobNote fields:

```python
tags = []
# tier-derived
if tier == "apply-now": tags.append("#tier/apply-now")
elif tier == "6-month": tags.append("#tier/6mo")
elif tier == "stretch": tags.append("#tier/stretch")
# fit-derived
if match_score >= 4.0: tags.append("#fit/strong")
elif match_score >= 3.0: tags.append("#fit/decent")
elif match_score >= 2.0: tags.append("#fit/stretch")
else: tags.append("#fit/weak")
# role-family-derived
if role_family: tags.append(f"#role/{role_family}")
# hitl-decision-derived
if hitl_decision: tags.append(f"#decision/{hitl_decision}")
```

Use Obsidian's tag pane to filter by any combination.

### Effort

- **20 min** in `vault_write_node` + a one-time migration to apply tags to existing JobNotes
- 1 unit test verifying tag generation

### What you get

- Click any tag in Obsidian's tag pane → see every JobNote with that tag
- Compose tags: `#fit/strong AND #role/agent-engineer` to find strong-fit agent roles
- Tag-based Dataview queries become natural ("show all #decision/timed_out with score > 3.5 — these are the ones the auto-reject lost")

---

## P4. SkillNote embeds candidate level into JobNote view

**Goal:** when reading a JobNote, immediately see your level on each required skill without flipping pages.

**How embeds work:** `![[Python#current-level]]` inlines the content under the "Current level" heading from `skills/Python.md`. Live-rendered in Obsidian.

**Proposal:** in the JobNote body's `## Skills` section:

```markdown
## Skills with candidate level

| Skill | Required? | My level |
|---|---|---|
| Python | required | ![[Python#level]] |
| LangGraph | required | ![[LangGraph#level]] |
| MCP | required | ![[MCP#level]] |
```

This requires each SkillNote to have a `## Level` heading with the level number visible (e.g. `Level 4 (production)`). The seed script can be extended.

**Alternative — Dataview-only**:

````markdown
```dataview
TABLE WITHOUT ID skill AS Skill, my_level AS "My level"
FROM "skills"
WHERE contains(this.skills_required, skill)
```
````

### Effort

- Embeds path: requires modifying SkillNote body to have a `## Level` section (15 min seed + body-rendering change in writer)
- Dataview path: 5 min, no SkillNote changes
- **Total: 10-30 min depending on approach**

### What you get

- Open a JobNote → see "Python: 3, LangGraph: 1, MCP: 4" inline. No clicking.
- Quick scan of your gaps for any role.

---

## P5. Canvas view of the gap plan

**Goal:** visualize the top-N gaps as a graph showing which jobs each gap would unlock.

**Obsidian Canvas** is a node-and-arrow visual editor. You drop notes onto a canvas; Obsidian renders them as cards.

**Proposal:** a script that builds `study-plans/gap-plan.canvas` JSON from the master gap plan + JobNote relationships. Each top-10 gap becomes a center node; arrows fan out to the JobNotes that would benefit. Edge thickness = how many jobs depend on that skill.

**Effort: 1 hour** for a simple generator. The Canvas JSON format is documented and stable.

### What you get

A visual map of "which skills should I learn next, ordered by how many doors they open." More motivating than a ranked list.

This is portfolio-quality polish — recruiters love screenshots of this kind of thing.

---

## P6. Bases (newer Obsidian feature) for table views

**Goal:** SQL-like filtered views of JobNotes/ApplicationNotes without writing Dataview queries each time.

**What Bases are:** `.base` files in Obsidian that define views over frontmatter. Like saved-query database views. Newer feature (released 2025).

**Proposal:** ship 3 `.base` files in the vault:

- `applications.base` — all ApplicationNotes, filterable by status/next_action_date
- `jobs-strong-fit.base` — JobNotes with match_score >= 4.0, sorted by date
- `skills-by-rarity.base` — SkillNotes sorted by appears_in_jobs ascending (rare first)

### Effort

- **30 min** to design + author 3 .base files
- No code changes
- Requires the user to be on Obsidian 1.7+ (Bases shipped 2025)

### What you get

Database-style table views that update automatically. More performant than Dataview for large vaults; first-class UI.

---

## P7. Daily-note linking for organic evidence URIs

**Goal:** close the loop between "I worked on a skill today" and "skill_assessor sees evidence of work."

**Current state:** the candidate has `learning-vault/daily/YYYY-MM-DD.md` files but they're not linked to skills.

**Proposal:** establish a convention in daily notes:

```markdown
# 2026-05-19

Worked on Compass Phase 1.B.2: RAG via Chroma. Shipped the indexer +
retriever. Wrote a [[LangGraph#interrupt and resume]] integration that
checkpoints to SQLite. Tested HITL flow end-to-end.

Skills practiced: [[LangGraph]] [[Chroma]] [[RAG]] [[MCP]]
```

When skill_assessor reads `learning-vault://daily/2026-05-19.md` as evidence for `LangGraph`, the skeptical grader sees: real work, specific artifact, last_modified today. Raises the grade.

**Implementation:** no code change required. Pure convention. Optional: a small `compass/scripts/sync_daily_to_skills.py` that scans daily notes for `[[SkillName]]` patterns and auto-adds the daily-note URI to each referenced SkillNote's evidence list. **20 min.**

### What you get

Daily writing → automatic skill evidence → grade updates on next assessor run. The "build → write → regrade" loop the spec promised, with zero friction.

---

## P8. Tagging interview-stage applications

**Goal:** when an ApplicationNote moves through stages (applied → screen → onsite → offer), tag transitions show up in Obsidian's tag pane.

**Implementation:** `compass/applications/lifecycle.py:update_application_status` already updates the `status` frontmatter. Extend it to also append a stage-transition tag to the ApplicationNote body:

```markdown
## Stage transitions
- 2026-05-19 → #stage/applied
- 2026-05-22 → #stage/screen
- 2026-05-29 → #stage/onsite
```

Each tag becomes a backlink target. Click `#stage/onsite` in the tag pane → see all applications in onsite stage.

### Effort

- **20 min** in `lifecycle.py`
- The user has zero ApplicationNotes today so no backfill needed

### What you get

Visual interview-pipeline tracking in Obsidian. Combined with the existing `list_pending_actions` MCP tool, you get both temporal (next_action_date) and stage-based filtering.

---

## Recommended bundle

If you want a single focused project to ship next that delivers the biggest visual + workflow win:

**Ship P1 + P2 + P3 together** as a small "Obsidian leverage" patch on top of `phase-1b2-rag`:

1. **P1**: JobNote body gets `## Skills` section with `[[skill]]` wikilinks. SkillNote body gets `## Jobs requiring this skill` list.
2. **P2**: dashboard.md gets "Skill rarity" + "Rare/specialized skills" Dataview panels.
3. **P3**: JobNote frontmatter gets auto-generated tags from tier / score / role_family / hitl_decision.

**Total effort: ~3 hours** including the one-time migration scripts to backfill existing JobNotes + SkillNotes.

**Visible result:**
- Obsidian graph view becomes meaningful — clusters of jobs around hub skills, peripheral rare skills visible at a glance
- Click any skill in a JobNote → instantly see every related job
- Tag pane gives you `#fit/strong`, `#role/agent-engineer`, etc. for one-click filters
- Dashboard answers your exact question (which skills are commodity vs rare) at the top

This is also strong portfolio material — Obsidian-as-product-UI for an agentic career coach is the kind of recruiter-facing screenshot that lands.

---

## Things I'd defer

- **P5 Canvas**: pretty but complex to maintain. Wait until daily use surfaces a need.
- **P6 Bases**: requires Obsidian 1.7+ and is still maturing. Try in a side branch first.
- **P7 daily-note linking**: depends on the user actually using daily notes consistently. Currently 3 daily notes exist (May 17-19). If you build the habit first, the tool follows.

---

## Where this fits in the broader phase plan

This is a **vault-rendering layer** — doesn't touch the pipeline, LLM, or HITL infrastructure. It's pure additive Obsidian polish. The cleanest place for it:

- **Phase 1.B.2.x patch** (this branch, before tagging 1.B.3)
- OR **Phase 1.B.3** as a side-quest after Modal cron + Langfuse fix lands

Recommendation: ship the **P1+P2+P3 bundle** as a small side-quest immediately. It's high-ROI, low-risk, and gives you a daily-use UI improvement before the 1.B.3 work starts (which is mostly invisible plumbing).
