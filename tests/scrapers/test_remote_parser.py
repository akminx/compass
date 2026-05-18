import pytest

from compass.scrapers._remote_parser import infer_remote_policy


@pytest.mark.parametrize(
    "loc,expected",
    [
        ("Remote", True),
        ("Remote - US", True),
        ("Remote, US", True),
        ("US Remote", True),
        ("Anywhere", True),
        ("Work from home", True),
        ("WFH", True),
        ("Hybrid", None),
        ("Hybrid - SF", None),
        ("San Francisco", False),
        ("New York, NY", False),
        ("San Francisco, CA or Remote", True),
        (None, None),
        ("", None),
        ("Remote AL", None),  # ambiguous: Alabama; conservative None
        ("Remote (United States)", True),
    ],
)
def test_infer_remote_policy(loc, expected):
    assert infer_remote_policy(loc) is expected


def test_greenhouse_scraper_wires_remote_field():
    """Regression: a Greenhouse posting with location='Remote - US' produces remote=True."""
    from compass.scrapers.greenhouse import _to_rawjob

    raw = {
        "id": 1,
        "title": "Backend Engineer",
        "absolute_url": "https://x/1",
        "content": "Build APIs in Python.",
        "location": {"name": "Remote - US"},
        "updated_at": "2026-05-18T00:00:00Z",
    }
    job = _to_rawjob(board_token="x", raw=raw)
    assert job is not None
    assert job.remote is True


def test_greenhouse_scraper_remote_false_for_city():
    from compass.scrapers.greenhouse import _to_rawjob

    raw = {
        "id": 1,
        "title": "Backend Engineer",
        "absolute_url": "https://x/1",
        "content": "Build APIs in Python.",
        "location": {"name": "San Francisco"},
        "updated_at": "2026-05-18T00:00:00Z",
    }
    job = _to_rawjob(board_token="x", raw=raw)
    assert job is not None
    assert job.remote is False


def test_lever_scraper_wires_remote_field():
    """Regression: a Lever posting with location='Anywhere' produces remote=True."""
    from compass.scrapers.lever import _to_rawjob

    raw = {
        "id": 1,
        "text": "Frontend Engineer",
        "hostedUrl": "https://x/1",
        "descriptionPlain": "Build UI in React.",
        "categories": {"location": "Anywhere"},
        "createdAt": 1716000000000,
    }
    job = _to_rawjob(company="x", raw=raw)
    assert job is not None
    assert job.remote is True


def test_lever_scraper_remote_false_for_city():
    from compass.scrapers.lever import _to_rawjob

    raw = {
        "id": 1,
        "text": "Frontend Engineer",
        "hostedUrl": "https://x/1",
        "descriptionPlain": "Build UI in React.",
        "categories": {"location": "New York, NY"},
        "createdAt": 1716000000000,
    }
    job = _to_rawjob(company="x", raw=raw)
    assert job is not None
    assert job.remote is False
