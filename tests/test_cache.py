"""Tests for cache.py — SQLite search cache."""
import sys
import os
import time
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cache


@pytest.fixture(autouse=True)
def temp_cache(tmp_path):
    """Use temporary cache dir for all tests."""
    with patch.object(cache, "CACHE_DIR", str(tmp_path)), \
         patch.object(cache, "CACHE_DB", str(tmp_path / "cache.db")), \
         patch.object(cache, "CACHE_ENABLED", True), \
         patch.object(cache, "CACHE_TTL", 3600):
        yield tmp_path


class TestSearchCache:
    def test_miss_returns_none(self):
        result = cache.get_search("nonexistent query", 10)
        assert result is None

    def test_set_and_get(self):
        data = {"success": True, "count": 5, "results": [{"title": "Test"}]}
        cache.set_search("test query", 10, data)

        cached = cache.get_search("test query", 10)
        assert cached is not None
        assert cached["count"] == 5

    def test_case_insensitive(self):
        data = {"success": True, "results": []}
        cache.set_search("Test Query", 10, data)

        cached = cache.get_search("test query", 10)
        assert cached is not None

    def test_different_rows_different_key(self):
        data5 = {"success": True, "count": 5, "results": []}
        data10 = {"success": True, "count": 10, "results": []}
        cache.set_search("test", 5, data5)
        cache.set_search("test", 10, data10)

        assert cache.get_search("test", 5)["count"] == 5
        assert cache.get_search("test", 10)["count"] == 10

    def test_failed_results_not_cached(self):
        data = {"success": False, "error": "all failed"}
        cache.set_search("bad query", 10, data)

        cached = cache.get_search("bad query", 10)
        assert cached is None

    def test_expired_not_returned(self):
        data = {"success": True, "results": []}
        cache.set_search("old query", 10, data)

        # Fake TTL to 0
        with patch.object(cache, "CACHE_TTL", 0):
            cached = cache.get_search("old query", 10)
            assert cached is None

    def test_disabled_cache(self):
        with patch.object(cache, "CACHE_ENABLED", False):
            data = {"success": True, "results": []}
            cache.set_search("test", 10, data)
            cached = cache.get_search("test", 10)
            assert cached is None


class TestCacheManagement:
    def test_clear_all(self):
        cache.set_search("q1", 10, {"success": True, "results": []})
        cache.set_search("q2", 10, {"success": True, "results": []})
        cache.clear_all()
        assert cache.get_search("q1", 10) is None
        assert cache.get_search("q2", 10) is None

    def test_stats(self):
        cache.set_search("q1", 10, {"success": True, "results": []})
        s = cache.stats()
        assert s["enabled"] is True
        assert s["total_entries"] >= 1
