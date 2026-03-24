"""Tests for searcher.py — connectors, dedup, and search quality."""
import json
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from searcher import (
    search_papers,
    _merge_results,
    _normalize_title,
    _jaccard_sim,
    _search_s2,
    _search_crossref,
)


# ═══════════════════════════════════════
# Title Normalization
# ═══════════════════════════════════════

class TestNormalizeTitle:
    def test_basic(self):
        assert _normalize_title("Hello World") == "hello world"

    def test_punctuation(self):
        assert _normalize_title("Attention: Is All You Need!") == "attention is all you need"

    def test_extra_spaces(self):
        assert _normalize_title("  Hello   World  ") == "hello world"

    def test_empty(self):
        assert _normalize_title("") == ""


# ═══════════════════════════════════════
# Jaccard Similarity
# ═══════════════════════════════════════

class TestJaccardSim:
    def test_identical(self):
        assert _jaccard_sim("hello world", "hello world") == 1.0

    def test_different(self):
        assert _jaccard_sim("hello world", "foo bar baz") == 0.0

    def test_partial(self):
        # {"hello", "world"} & {"hello", "there"} = {"hello"}
        # union = {"hello", "world", "there"} = 3
        assert abs(_jaccard_sim("hello world", "hello there") - 1 / 3) < 0.01

    def test_empty(self):
        assert _jaccard_sim("", "hello") == 0.0
        assert _jaccard_sim("", "") == 0.0

    def test_high_overlap(self):
        a = "attention is all you need"
        b = "attention is all we need"
        # 4/6 = 0.667 < 0.7
        sim = _jaccard_sim(a, b)
        assert 0.5 < sim < 0.8


# ═══════════════════════════════════════
# Merge / Dedup
# ═══════════════════════════════════════

class TestMergeResults:
    def test_doi_dedup(self, sample_paper, sample_paper_variant):
        """Same DOI should merge into one result."""
        merged = _merge_results([[sample_paper], [sample_paper_variant]], limit=10)
        assert len(merged) == 1
        assert merged[0]["cited_by"] == 100000  # max of both

    def test_title_dedup(self):
        """Similar titles without DOI should merge via Jaccard."""
        p1 = {"title": "A Method for Gradient Coil Design Optimization", "doi": "", "cited_by": 10, "year": "2023", "abstract": "text1", "authors": "", "open_access_url": "", "source": "s2"}
        p2 = {"title": "A Method for Gradient Coil Design Optimization using FEM", "doi": "", "cited_by": 5, "year": "2023", "abstract": "", "authors": "Author X", "open_access_url": "", "source": "crossref"}
        merged = _merge_results([[p1], [p2]], limit=10)
        # 8/9 words overlap → Jaccard ~0.89 > 0.7 → should merge
        assert len(merged) == 1
        # Should take max cited_by and fill missing authors
        assert merged[0]["cited_by"] == 10
        assert merged[0]["authors"] == "Author X"

    def test_different_papers_not_merged(self, sample_paper, sample_paper_different):
        """Different papers should NOT merge."""
        # Override DOIs to be different
        p1 = {**sample_paper, "doi": "10.1111/aaa"}
        p2 = {**sample_paper_different, "doi": "10.2222/bbb"}
        merged = _merge_results([[p1], [p2]], limit=10)
        assert len(merged) == 2

    def test_empty_sources(self):
        merged = _merge_results([[], []], limit=10)
        assert merged == []

    def test_limit(self, sample_paper, sample_paper_different):
        p1 = {**sample_paper, "doi": "10.1111/aaa"}
        p2 = {**sample_paper_different, "doi": "10.2222/bbb"}
        merged = _merge_results([[p1, p2]], limit=1)
        assert len(merged) == 1

    def test_sorted_by_citations(self):
        p1 = {"title": "Paper A", "doi": "10.1/a", "cited_by": 50, "year": "2020", "abstract": "", "authors": "", "open_access_url": "", "source": "s2"}
        p2 = {"title": "Paper B", "doi": "10.1/b", "cited_by": 500, "year": "2019", "abstract": "", "authors": "", "open_access_url": "", "source": "s2"}
        merged = _merge_results([[p1, p2]], limit=10)
        assert merged[0]["title"] == "Paper B"  # higher citations first

    def test_index_assigned(self, sample_paper):
        merged = _merge_results([[sample_paper]], limit=10)
        assert merged[0]["index"] == 1


# ═══════════════════════════════════════
# Connector: Semantic Scholar
# ═══════════════════════════════════════

class TestSearchS2:
    @patch("searcher.requests.get")
    def test_basic(self, mock_get, mock_s2_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_s2_response
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        results = _search_s2("gradient coil", 5)
        assert len(results) == 1
        assert results[0]["title"] == "Gradient Coil Design Optimization"
        assert results[0]["doi"] == "10.1109/tmi.2023.001"
        assert results[0]["source"] == "semantic_scholar"

    @patch("searcher.requests.get")
    def test_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_get.return_value = mock_resp

        results = _search_s2("nonexistent", 5)
        assert results == []


# ═══════════════════════════════════════
# Connector: Crossref
# ═══════════════════════════════════════

class TestSearchCrossref:
    @patch("searcher.requests.get")
    def test_basic(self, mock_get, mock_crossref_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_crossref_response
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        results = _search_crossref("gradient coil", 5)
        assert len(results) == 1
        assert results[0]["doi"] == "10.1109/tmi.2023.001"
        assert results[0]["source"] == "crossref"


# ═══════════════════════════════════════
# Full search_papers (integration-level mock)
# ═══════════════════════════════════════

class TestSearchPapers:
    @patch("searcher.requests.get")
    def test_doi_query(self, mock_get, mock_crossref_response):
        """DOI queries should go to Crossref only."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_crossref_response
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        result = search_papers("10.1109/tmi.2023.001", rows=1)
        assert result["success"] is True
        assert result["count"] == 1

    def test_all_fail_error(self):
        """When all sources fail, should return error."""
        def _fail(q, r):
            raise Exception("fail")

        with patch.dict("searcher.ALL_CONNECTORS", {"fake": _fail}, clear=True):
            result = search_papers("test query", rows=5)
            assert result["success"] is False
