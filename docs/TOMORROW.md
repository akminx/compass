# Tomorrow's Plan — Day 1

> Goal: get Compass running end-to-end (scrape → vault write), do 3 LeetCode problems, review 2 ML concepts.
> Expected time: 4–5 hours focused work.

---

## Morning block (1.5–2 hrs) — Project setup

### Step 1 — Initialize the repo (30 min)
```bash
cd ~/Desktop  # or wherever you keep projects
# Copy the compass/ folder from downloads into here
cd compass
uv sync                        # installs all dependencies
cp .env.example .env           # then open .env and fill in:
                               #   VAULT_PATH=/Users/yourname/Documents/compass-vault
                               #   OPENROUTER_API_KEY=your key from openrouter.ai
docker compose up -d           # starts Langfuse on localhost:3000
```

Visit http://localhost:3000 — create an account, create a project called "compass", copy the public + secret keys into `.env`.

### Step 2 — Seed the vault (10 min)
```bash
uv run python scripts/seed_vault.py
```

Then manually copy the profile docs into `compass-vault/_profile/`:
- `akash_resume_v2.md` → rename to `resume.md`
- `skill-inventory.md`
- `akash_interview_prep.md` → rename to `interview-prep.md`
- `akash_role_clarifications.md` → rename to `role-clarifications.md`
- `target-roles.md`
- `skills-competency-map.md`
- `interview-study-plan.md`

### Step 3 — Open in Claude Code (5 min)
```bash
claude  # opens Claude Code in the compass/ directory
```

Give it this first prompt:
> "Read CLAUDE.md and docs/ARCHITECTURE.md. Then implement scrape_greenhouse() in compass/scrapers/greenhouse.py — hit the real Greenhouse API for the 'databricks' board token, parse the JSON response into RawJob objects, handle errors gracefully (return empty list on 404 or network error), add rate limiting (1 second delay between requests), and make the tests in tests/test_scrapers.py pass. Use httpx for async HTTP."

Let Claude Code build it. Review the output. Run:
```bash
uv run pytest tests/test_scrapers.py -v
```

---

## Midday block (1 hr) — LeetCode without AI

Open neetcode.io. No Cursor. No Claude. Plain editor, timer on.

**Problem 1 — Two Sum (Easy, 15 min target)**
- Classic hash map pattern
- Write it, understand why O(n) not O(n²)
- Narrate out loud: "I'm using a hash map because..."

**Problem 2 — Valid Palindrome (Easy, 10 min target)**
- Two pointer pattern
- Clean Python: `s.lower()`, `isalnum()`

**Problem 3 — Best Time to Buy and Sell Stock (Easy, 15 min target)**
- Sliding window / tracking minimum
- If you finish early: do Contains Duplicate

After each problem: delete your solution and write it again from scratch without looking. This is the drill that actually builds the muscle.

---

## Afternoon block (1–1.5 hrs) — Continue Compass + ML review

### Continue Compass with Claude Code
After the Greenhouse scraper works, give Claude Code this prompt:
> "Now implement scrape_lever() in compass/scrapers/lever.py following the same pattern as greenhouse.py. The Lever public API endpoint is: GET https://api.lever.co/v0/postings/{company}?mode=json — it returns an array of posting objects. Parse into RawJob objects. Write tests in tests/test_scrapers.py."

### ML concept review (20 min, no AI)
Read these and make sure you could explain each in one sentence to a non-engineer:

**Today's two concepts:**
1. **Precision vs Recall** — When would you optimize for precision? When for recall? What's a real example of each tradeoff?
2. **Overfitting** — What does it look like in a training curve? What are 3 ways to fix it?

Write your answers in a notebook (paper is fine). Then ask yourself: "Could I explain this to an interviewer for 3 minutes without notes?" If not, spend 5 more minutes on it.

---

## Evening (optional, 30 min) — Review what shipped

1. Check the Langfuse dashboard at localhost:3000 — are traces showing up from your test runs?
2. Open compass-vault in Obsidian — does the folder structure look right?
3. Check docs/STATUS.md — update any checkboxes you completed today
4. Write 2 sentences in `_meta/agent-log.md` about what you built today

---

## Definition of a successful day tomorrow

Minimum:
- [ ] Compass repo initialized, `uv sync` passes
- [ ] Langfuse running at localhost:3000
- [ ] Vault seeded, profile docs copied in
- [ ] Greenhouse scraper implemented and tests passing
- [ ] 3 LeetCode easy problems solved without AI

Stretch:
- [ ] Lever scraper also done
- [ ] Ashby scraper started
- [ ] 2 ML concepts reviewed and could explain confidently

---

## Don't do tomorrow

- Don't try to build the LangGraph pipeline yet — get the scrapers and vault foundation solid first
- Don't use Claude/Cursor for LeetCode — the whole point is the solo practice
- Don't spend more than 30 min on any one LeetCode problem — move on and come back
- Don't skip the Langfuse setup — you want traces from day 1

---

## Quick reference — commands you'll use tomorrow

```bash
uv sync                              # install dependencies
uv run pytest tests/ -q             # run all tests
uv run pytest tests/test_scrapers.py -v  # run scraper tests only
uv run python scripts/seed_vault.py # seed vault structure
docker compose up -d                # start Langfuse
docker compose down                 # stop Langfuse
claude                              # open Claude Code
```
