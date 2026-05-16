"""
Compass MCP server — exposes vault and pipeline as tools for Claude Code / Cursor.

Run: uv run python -m compass.mcp_server.server

Add to Claude Code MCP config (~/.config/claude/claude_desktop_config.json):
{
  "mcpServers": {
    "compass": {
      "command": "uv",
      "args": ["run", "python", "-m", "compass.mcp_server.server"],
      "cwd": "/path/to/compass"
    }
  }
}

Tools exposed:
  - search_jobs(query, limit) -> list[JobNote]
  - get_skill_gaps(job_id) -> list[SkillGap]
  - score_jd(jd_text) -> JobScore
  - get_study_plan(skills) -> StudyPlan
  - tailor_resume(job_id) -> TailoringNote
  - add_application(job_id) -> None
"""
raise NotImplementedError("MCP server not yet implemented — build this in Phase 3")
