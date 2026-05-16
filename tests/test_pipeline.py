"""
Integration tests for the LangGraph pipeline.
Run: uv run pytest tests/test_pipeline.py -v

Note: these tests make real LLM calls and require OPENROUTER_API_KEY to be set.
Mark slow tests with @pytest.mark.slow to skip them in fast CI runs.
"""
import pytest
from compass.pipeline.state import RawJob, CompassState
from datetime import date


SAMPLE_JD = """
Applied AI Engineer — Databricks

We're looking for an engineer to build LLM-powered features on the Databricks Lakehouse.
You'll work on Genie, our natural language data querying engine, and compound AI agent systems.

Required: Python, LangGraph, MLflow, RAG pipeline design, eval methodology
Nice to have: PySpark, Delta Lake, Unity Catalog, Vector Search

3+ years of software engineering experience required.
"""


@pytest.fixture
def sample_raw_job():
    return RawJob(
        company="Databricks",
        title="Applied AI Engineer",
        url="https://databricks.com/careers/applied-ai-engineer",
        source="greenhouse",
        description=SAMPLE_JD,
        date_posted=date.today(),
    )


@pytest.mark.asyncio
@pytest.mark.slow
async def test_extract_node_returns_requirements(sample_raw_job):
    """extract_node correctly extracts structured requirements from a JD."""
    # TODO: implement once extract_node is built
    pass


@pytest.mark.asyncio
@pytest.mark.slow
async def test_score_node_returns_score(sample_raw_job):
    """score_node returns a score between 0 and 5."""
    # TODO: implement once score_node is built
    pass


@pytest.mark.asyncio
@pytest.mark.slow
async def test_full_pipeline_end_to_end(sample_raw_job):
    """Full pipeline runs without error on a sample job."""
    # TODO: implement once all nodes are built
    pass
