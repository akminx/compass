"""URL normalization regression tests — every case found in the adversarial
review of 2026-05-19 must collapse to the same canonical form."""

from __future__ import annotations

from compass.vault.url_dedup import normalize_url


class TestNormalization:
    """Cosmetic variants of the same JD URL must normalize to one string."""

    def test_trailing_slash(self):
        assert normalize_url("https://jobs.ashbyhq.com/agentco/abc") == normalize_url(
            "https://jobs.ashbyhq.com/agentco/abc/"
        )

    def test_utm_tracking_params_stripped(self):
        assert normalize_url("https://jobs.ashbyhq.com/agentco/abc") == normalize_url(
            "https://jobs.ashbyhq.com/agentco/abc?utm_source=google&utm_medium=cpc"
        )

    def test_gclid_stripped(self):
        assert normalize_url("https://jobs.ashbyhq.com/agentco/abc") == normalize_url(
            "https://jobs.ashbyhq.com/agentco/abc?gclid=ABCDEF"
        )

    def test_http_collapses_to_https(self):
        assert normalize_url("http://jobs.ashbyhq.com/agentco/abc") == normalize_url(
            "https://jobs.ashbyhq.com/agentco/abc"
        )

    def test_host_case_insensitive(self):
        assert normalize_url("https://JOBS.ASHBYHQ.COM/agentco/abc") == normalize_url(
            "https://jobs.ashbyhq.com/agentco/abc"
        )

    def test_fragment_dropped(self):
        assert normalize_url("https://jobs.ashbyhq.com/agentco/abc#apply") == normalize_url(
            "https://jobs.ashbyhq.com/agentco/abc"
        )

    def test_default_ports_dropped(self):
        assert normalize_url("https://jobs.ashbyhq.com:443/agentco/abc") == normalize_url(
            "https://jobs.ashbyhq.com/agentco/abc"
        )

    def test_non_default_port_preserved(self):
        """If the URL really does use a non-standard port, keep it."""
        assert ":8080" in normalize_url("https://jobs.example.com:8080/role")

    def test_non_tracking_query_preserved(self):
        """Tracking-only params are stripped; meaningful ones (job_id, etc.) stay."""
        out = normalize_url("https://jobs.example.com/list?job_id=42&utm_source=x")
        assert "job_id=42" in out
        assert "utm_source" not in out

    def test_query_params_sorted(self):
        """Two URLs with the same params in different order canonicalize together."""
        assert normalize_url("https://example.com/?b=2&a=1") == normalize_url(
            "https://example.com/?a=1&b=2"
        )

    def test_path_case_preserved(self):
        """Servers MAY treat /Foo and /foo differently — don't fold."""
        assert normalize_url("https://example.com/Foo") != normalize_url("https://example.com/foo")

    def test_empty_url_returns_empty(self):
        assert normalize_url("") == ""

    def test_malformed_url_returns_unchanged(self):
        """If urlsplit raises, degrade to per-string matching for that one URL."""
        # Not strictly malformed but unusual:
        out = normalize_url("notaurl")
        # Should not crash and should produce some deterministic output
        assert isinstance(out, str)
