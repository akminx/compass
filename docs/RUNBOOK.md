# Runbook — Compass

## First-time setup
```bash
git clone https://github.com/akminx/compass && cd compass
uv sync
cp .env.example .env
# Fill in .env with your OpenRouter key, vault path

# Start Langfuse
docker compose up -d
# Visit http://localhost:3000, create account + project, copy keys to .env

# Seed the vault
uv run python scripts/seed_vault.py

# Copy profile docs into vault/_profile/ manually (see docs below)

# Run tests
uv run pytest tests/ -q
```

## Run the pipeline once
```bash
uv run python -m compass.pipeline.graph
```

## Run the eval harness
```bash
uv run python -m compass.evals.runner
```

## Start the MCP server
```bash
uv run python -m compass.mcp_server.server
```

## Profile docs to copy into vault/_profile/
- resume.md
- skill-inventory.md
- interview-prep.md
- role-clarifications.md
- target-roles.md
- skills-competency-map.md
- interview-study-plan.md
