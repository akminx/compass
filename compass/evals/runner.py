"""
Eval harness runner — runs nightly, logs results to Langfuse.

Run: uv run python -m compass.evals.runner

What it measures:
  - Score MAE (mean absolute error vs human labels)
  - Skill extraction recall (did we find all skills a human identified?)
  - Cost per eval run
  - Tokens per node

Results are logged to Langfuse as a Dataset Run.
A summary is printed to stdout and written to compass/evals/results.json.

This is what you show in interviews when asked about eval methodology.
The chart of precision vs cost across model configs is generated here.
"""
raise NotImplementedError("eval runner not yet implemented — build this in Phase 3")
