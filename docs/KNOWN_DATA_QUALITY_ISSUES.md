# Known Data-Quality Issues — Pipeline Behavior

> Surfaced during the Phase 1.B.2 deep adversarial review against real vault data. These are pre-existing Phase 0.B / 1.A LLM-behavior defects that distort scoring + skill matching. Fix scope: **Phase 2.A's eval harness work** — each needs a regression test against labeled JDs before prompt tuning, otherwise we whack-a-mole.

**Tag context:** discovered at `phase-1b2-rag`. Vault snapshot: 23 JobNotes across multiple target-company boards.

---

## B1. `extract_node` under-extracts `skills_required` on best-fit roles

**Symptom:** roles that are obvious matches for the candidate end up with empty or near-empty `skills_required` lists, which artificially caps the score because the scorer has nothing to match against.

**Evidence:**
- `jobs/2026-03-27-companya-Software_Engineer_Agent_Architecture-04a9b65f.md` → `skills_required: []`, `skills_matched: []`, `match_score: 3.0`. The JD describes building an agent SDK + runtime + evals — a near-perfect fit for the candidate's MCP/agent cluster (level 3-4). The score reasoning even acknowledges the alignment, but the score caps at 3.0 because there are no required-skill entries to flip into matched. **A fair human grade is ~4.0.**
- `jobs/2026-05-06-companyb-Software_Engineer-7c26fdaf.md` → `skills_required: [Python]` only, despite the JD emphasizing sub-agent orchestration, tool use, agent infrastructure.

**Hypothesis:** the extract prompt is being too literal about "explicit requirements only" and missing skills implied by responsibility statements. JDs at agentic startups frequently lead with mission text ("build the orchestration engine"), with the canonical skill list buried or implied.

**Phase 2.A fix surface:**
- Tighten extract prompt to also pull canonical skills from responsibility statements (`build orchestration engine` → LangGraph, `subagent coordination` → Multi-Agent).
- Add a labeled JD eval where the ground-truth skill list includes implied skills; assert extract recall ≥ 0.7.

---

## B2. `extract_node` mis-reads OR-lists as AND-lists

**Symptom:** "languages such as A, B, C, or similar" is interpreted as four ANDed requirements. Candidate gets dinged on missing alternatives the JD didn't actually require.

**Evidence:**
- `jobs/2026-04-15-companyb-AI_Support_Engineer-25133cbd.md` → JD: "Strong ability to read and reason about code in **multiple languages, such as Python, TypeScript, Java, Go, or similar**". Extracted: `skills_required: [Python, TypeScript, Go, Docker]`. Scorer marked TS+Go as missing → 2.0 → auto-rejected. **A fair human assigns ~3.0-3.5.** The role was incorrectly auto-rejected by extraction artefact.

**Phase 2.A fix surface:**
- Extract prompt addendum: explicit OR-list detection ("languages such as X, Y, or Z" → store as `nice_to_have_skills` or a separate `language_alternatives` field, not as `skills_required`).
- Eval coverage: at least 3 OR-list JDs in the labeled set with ground-truth scores.

---

## B3. `score_node` occasionally marks candidate-strong skills as missing

**Symptom:** scorer LLM lists a skill in `missing_skills` despite the candidate having a non-trivial level in the profile.

**Evidence:**
- `jobs/2026-04-07-companyc-Security_Engineer_Cloud-a25113ae.md` → `skills_required: [Python]`, `skills_missing: [Python]`, `skills_matched: []`. The candidate has Python at level 3 (skill-inventory.md). RAG would have surfaced the Python chunk on any query containing "Python". The scorer LLM didn't consult the retrieved profile faithfully.
- Low-fit branch failure mode: when the overall role is wildly off (security, in this case), the scorer appears to short-circuit and declare every required skill missing without verifying the candidate's level.

**Phase 2.A fix surface:**
- Score prompt assertion: "Before adding a skill to missing_skills, verify it is NOT in the candidate's profile at level ≥ 2."
- Defensive post-filter: in `score.py`, augment `_constrain_to_jd_skills` to also check `skills_missing` against the candidate's profile and downgrade false-misses to nothing. (Requires access to canonical skill levels at score time — currently only the chunks are passed.)
- Eval regression test: "if candidate has skill X at level ≥ 3 AND skill X is in `skills_required`, then X MUST appear in `skills_matched`, never in `skills_missing`."

---

## B4. ✅ FIXED in `phase-1b2-rag` — `intake_filter` title-keyword stage was leaky

Resolved at this tag: added `engineering manager`, `engineering lead`, `director/head/vp of engineering`, `solutions engineer`, `solution engineer`, `security engineer`, `application security`, `infrastructure security`, `operations specialist`, `product operations`, `program manager` to `OUT_SUBSTRING_KEYWORDS`. The four false-negatives observed (Company-A EM, Company-B AI Ops Specialist, Company-A Senior Solutions Eng, Company-C Security Eng) now correctly drop at intake.

---

## B5. Anti-claim gating is inconsistent on post-training/research roles

**Symptom:** the candidate's `role-clarifications.md` declares SFT/LoRA/RLHF/DPO as level 0 (explicit anti-claim). Sometimes the scorer catches this, sometimes it doesn't.

**Evidence:**
- Company-B Research Post-Training role → correctly scored 0.0, reasoning cited RLHF=0.
- `jobs/2025-08-22-companyb-Senior_Research_Engineer-5030d3e2.md` → JD requires "Prior experience post-training and deploying LLMs in production". Scored 3.0. The disqualifier was missed.

**Phase 2.A fix surface:**
- The anti-claim signal should be a hard rule, not a contextual hint. Add an explicit pre-score check: if JD `required_skills` contains any of {fine-tuning, RLHF, post-training, SFT, LoRA, DPO} AND candidate role-clarification anti-claims include them, then score is capped at 1.0 regardless of LLM output.

---

---

## B6. Derived-field staleness asymmetry — `role_family` is set once and never reconciled

**Symptom:** when the keyword OUT list expands (as in commit `3828d8f`), existing JobNotes that should now be classified out-of-scope keep their old `role_family`. `gap_aggregator.regenerate()` reads ALL JobNotes regardless of `role_family`, so stale entries keep contributing to the master gap plan.

**Evidence:**
- `jobs/2026-03-17-companyb-AI_Operations_Specialist_Agentic_Workflows-f489c32b.md` has `role_family: agent-engineer` but `keyword_classify()` now correctly returns `out-of-scope` for that title. The JobNote was written before "operations specialist" was in the OUT list. Its skills still feed gap-plan weights.

**Pattern:** counters (`appears_in_jobs`, `roles_seen`) are derived at every gap_aggregator run — Phase 0 bug #12 / Phase 1.A bug #1 enforced this discipline. But `role_family` is treated as ground truth once written. **Same asymmetry could repeat for any future "set-once classification" field** (e.g. `tier`, `seniority`).

**Phase 2.A fix surface:**
- Either: `gap_aggregator.load_jobs()` re-runs `keyword_classify` on each JobNote and skips out-of-scope.
- Or: a one-time migration script that re-classifies and updates `role_family` in place (similar to the Phase 1.A `cleanup_stale_jobnotes.py` pattern).
- Either way: add a regression test that asserts "no JobNote in the vault has a `role_family` that current code would classify as `out-of-scope`."

---

## B7. `gap_aggregator` includes `auto_rejected` / `timed_out` / `null hitl_decision` jobs at full weight

**Symptom:** the gap plan is computed from all 23 JobNotes — currently 1 approved, 10 auto_rejected, 8 null (pre-1.B.1), 4 timed_out — with no `hitl_decision` filter. A `timed_out` job with score 4.0 contributes the same gap signal as an `approved` job.

**Trade-off:** the original spec rationale was "JD-market signal is independent of personal action" — even rejected jobs reveal what skills the market wants. Defensible. But it conflates:
- "Skills the market demands generally" (all in-scope JDs)
- "Skills I should study to convert near-misses to applies" (high-score auto_rejected = stretch signals)
- "Skills the human is committed to pursuing" (approved only)

**Phase 2.A fix surface:**
- Add an optional filter mode to `gap_aggregator.regenerate(filter_decision=None | "approved_or_above_threshold")`.
- Document the chosen weighting decision in `_profile/preferences.md` so the user can tune.

---

## B8. `tailor_node` has no programmatic constraint against hallucination

**Symptom:** unlike `score_node`'s `_constrain_to_jd_skills`, `tailor_node`'s prompt says "Mention real projects and concrete numbers when the profile provides them" but enforces nothing. The agent could invent project names and they'd ship to the JobNote.

**Evidence:** the one tailored paragraph in the vault (a target-company Special Projects role) was spot-checked — every concrete claim verified against `_profile/resume.md`. **No hallucination in this sample**, but n=1 with no code-level defense.

**Risk:** Sonnet on a sparse JD ("Founder mindset, 2+ years exp") with a longer profile could easily invent specifics.

**Phase 2.A fix surface:**
- Post-generation regex pass that flags proper-noun project mentions not present in `resume.md` (similar to extract's JD-substring validation in Phase 0).
- Eval coverage: hand-label 5 generated tailoring paragraphs against ground-truth resume facts; assert zero unsupported claims.

---

## Portfolio-claim risks (operational, not code bugs)

These are NOT data-quality bugs but portfolio narrative risks: the spec advertises features whose code is built but real data is empty.

### PR1. Skill assessor loop is theoretical — zero evidence URIs

`grep '^evidence:' ~/Documents/compass-vault/skills/*.md` returns 95/95 `evidence: []`. The "unique angle" — the agent that grades candidate skills against `learning-vault://` evidence — has never operated on real input. The MCP `assess_skills` tool returns immediately with no work.

**The README narrative says:** "an agent inside it that grades my skills against the live job market and tells me what to study next." Currently it can't, because no evidence is wired up. The infrastructure exists; the demo isn't recorded.

**Mitigation paths:**
- Manually wire 3-5 `learning-vault://` URIs to a sample of skills (e.g. MCP, LangGraph, RAG) — proves the loop end-to-end.
- Record one assessor run with grade-change output as a portfolio screenshot.

### PR2. Application lifecycle has never been used

`~/Documents/compass-vault/applications/` is empty. All 23 JobNotes have `applied_at: null`. The Dashboard panels "In-flight applications" and "Today's next actions" will both always be empty until someone runs `add_application(job_id)`.

**Mitigation:** apply to one job for real, exercise the full lifecycle (`add_application` → `update_application_status` → next-action reminder). Provides a portfolio screenshot.

### PR3. Concurrent pipeline runs not protected

Two parallel `run_pipeline()` invocations share `HITL_CHECKPOINT_DB`. SQLite raises `database is locked` and one process may leave a thread without a saved checkpoint. Also two parallel `gap_aggregator.regenerate()` calls race on `MASTER_GAP_PLAN_PATH.write_text()` — atomic per call but last-writer-wins across processes.

**Phase 1.B.3 fix surface:** Modal cron + human-MCP race is the real-world trigger. Use SQLite advisory lock or `flock` on a sentinel file.

---

## What's working correctly (positive findings)

These were spot-checked and are NOT a problem:

- **`jd_summary`** extraction is faithful across 8 spot-checks. No hallucinated facts. ATS boilerplate correctly excluded.
- **`_constrain_to_jd_skills`** filter (Phase 0 fix #5) is intact. Would catch over-extraction; current bug class is under-extraction.
- **LLM-stage `intake_filter`** is well-calibrated. Catches Japanese pre-sales architect, fellowship roles, GTM partnerships, HR coordinator — all correct. No false positives observed.
- **Pre-RAG vs post-RAG (Phase 1.B.1 vs 1.B.2)** comparison shows no quality regression. Top-k=8 chunks produce score reasoning at comparable depth to the prior full-inventory inject.
- **Audit-trail integrity** (`hitl_decision`, `hitl_at`, `tailored_paragraph`, `score_threshold`) is correct across the 23 JobNotes inspected.

---

## Why these are deferred to Phase 2.A

The spec's Phase 2.A is the **eval harness** phase: 30+ hand-labeled JDs with ground-truth scores + skill lists, run nightly, alert on MAE drift. That's the right place to attack B1/B2/B3/B5 because:

1. Each bug class needs a regression test, not a one-off prompt tweak.
2. Prompt tuning without measurement is whack-a-mole — fixing B1 might break B2 silently.
3. The labeled dataset doubles as the portfolio artifact ("eval-driven LLM development").

Phase 1.B.2 closed the architectural RAG portfolio claim. Phase 1.B.3 closes the cron+observability claim. Phase 2.A makes the LLM behavior measurably correct.

---

## Stop-gap mitigation pre-2.A

If a particular roll-out is needed before the eval harness:

1. **B3 has the highest cost-to-value for a manual fix** — adding a one-line "verify candidate level ≥ 2 before declaring missing" assertion in the score prompt is low-risk.
2. **B2 has high impact when it fires** but is rare. Manual JD-by-JD review until 2.A is cheap (only ~20 jobs/week reach scoring).
3. **B1 affects every best-fit JD.** This is the single most consequential prompt-tuning target.

**Recommendation:** do not attempt B1-B3 ad-hoc. Build 2.A first.
