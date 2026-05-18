"""
Eval dataset management.

The dataset is a JSON file: compass/evals/labeled_dataset.json
Format:
[
  {
    "id": "eval-001",
    "jd_text": "...",
    "expected_score": 4.2,
    "expected_skills": ["LangGraph", "Pydantic", "RAG"],
    "notes": "Strong match — all required skills present"
  }
]

Start with 30 examples — enough to detect regressions.
Half synthesized with an LLM, half hand-labeled from real JDs.
"""

from pathlib import Path

DATASET_PATH = Path(__file__).parent / "labeled_dataset.json"


def load_dataset() -> list[dict]:
    """Load the labeled evaluation dataset."""
    raise NotImplementedError("load_dataset not yet implemented")


def add_example(
    jd_text: str, expected_score: float, expected_skills: list[str], notes: str = ""
) -> None:
    """Add a new labeled example to the dataset."""
    raise NotImplementedError("add_example not yet implemented")
