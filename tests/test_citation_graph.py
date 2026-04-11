"""Tests for citation_graph.py — graph generation, dedup, and mermaid output."""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from citation_graph import (
    get_citation_graph,
    _s2_id,
    _short_title,
    _sanitize_mermaid,
    _generate_mermaid,
)


# ═══════════════════════════════════════
# S2 ID Construction
# ═══════════════════════════════════════

class TestS2Id:
    def test_doi(self):
        assert _s2_id("10.1109/tmi.2023.001") == "DOI:10.1109/tmi.2023.001"

    def test_arxiv(self):
        assert _s2_id("arXiv:2301.00001") == "ARXIV:2301.00001"
        assert _s2_id("ARXIV:2301.00001") == "ARXIV:2301.00001"

    def test_corpus_id(self):
        assert _s2_id("CorpusID:12345") == "CorpusID:12345"

    def test_unknown_with_slash(self):
        assert _s2_id("some/identifier") == "DOI:some/identifier"

    def test_unknown_without_slash(self):
        assert _s2_id("plain_id") == "plain_id"

    def test_strip_whitespace(self):
        assert _s2_id("  10.1109/test  ") == "DOI:10.1109/test"


# ═══════════════════════════════════════
# Title Helpers
# ═══════════════════════════════════════

class TestShortTitle:
    def test_short(self):
        assert _short_title("Short Title") == "Short Title"

    def test_long(self):
        long_title = "A" * 50
        result = _short_title(long_title, max_len=40)
        assert len(result) == 40
        assert result.endswith("...")

    def test_exact_length(self):
        title = "A" * 40
        assert _short_title(title, max_len=40) == title


class TestSanitizeMermaid:
    def test_removes_special_chars(self):
        assert _sanitize_mermaid('Hello "World"') == "Hello World"
        assert _sanitize_mermaid("Test (value)") == "Test value"

    def test_preserves_plus(self):
        assert _sanitize_mermaid("C++ Programming") == "C++ Programming"

    def test_strips_whitespace(self):
        assert _sanitize_mermaid("  hello  ") == "hello"


# ═══════════════════════════════════════
# Mermaid Generation
# ═══════════════════════════════════════

class TestGenerateMermaid:
    def test_basic_graph(self):
        nodes = [
            {"id": "center", "title": "Main Paper", "year": 2023, "cited_by": 100, "type": "center"},
            {"id": "ref_0", "title": "Reference A", "year": 2020, "cited_by": 50, "type": "reference"},
            {"id": "cit_0", "title": "Citation B", "year": 2024, "cited_by": 10, "type": "citation"},
        ]
        edges = [
            {"from": "center", "to": "ref_0", "type": "references"},
            {"from": "cit_0", "to": "center", "type": "cites"},
        ]
        mermaid = _generate_mermaid(nodes, edges, "Main Paper")

        assert "graph LR" in mermaid
        assert "center" in mermaid
        assert "ref_0" in mermaid
        assert "cit_0" in mermaid
        assert "-->|references|" in mermaid
        assert "-->|cites|" in mermaid
        assert "classDef center" in mermaid

    def test_empty_graph(self):
        nodes = [{"id": "center", "title": "Paper", "year": 2023, "cited_by": 0, "type": "center"}]
        mermaid = _generate_mermaid(nodes, [], "Paper")
        assert "graph LR" in mermaid
        assert "center" in mermaid


# ═══════════════════════════════════════
# Full Citation Graph (mocked API)
# ═══════════════════════════════════════

class TestGetCitationGraph:
    def _mock_s2_response(self, title="Test Paper", year=2023, cited=50, doi="10.1/test"):
        return {
            "title": title,
            "year": year,
            "citationCount": cited,
            "externalIds": {"DOI": doi},
            "authors": [{"name": "Author A"}],
        }

    @patch("citation_graph._s2_get")
    def test_basic(self, mock_get):
        """Should return graph with center paper when API works."""
        mock_get.side_effect = [
            self._mock_s2_response(),  # center paper
            {"data": [{"citedPaper": self._mock_s2_response("Ref 1", 2020, 30, "10.1/ref1")}]},  # refs
            {"data": [{"citingPaper": self._mock_s2_response("Cit 1", 2024, 5, "10.1/cit1")}]},  # cits
        ]

        result = get_citation_graph("10.1/test", depth=1)
        assert result["success"] is True
        assert result["center_paper"]["title"] == "Test Paper"
        assert len(result["nodes"]) == 3  # center + ref + cit
        assert len(result["edges"]) == 2
        assert result["statistics"]["references"] == 1
        assert result["statistics"]["citations"] == 1
        assert "graph LR" in result["mermaid"]

    @patch("citation_graph._s2_get")
    def test_paper_not_found(self, mock_get):
        """Should return error when paper not found."""
        mock_get.return_value = None

        result = get_citation_graph("10.1/nonexistent")
        assert result["success"] is False
        assert "not found" in result["error"]

    @patch("citation_graph._s2_get")
    def test_no_refs_no_cits(self, mock_get):
        """Should handle paper with no references or citations."""
        mock_get.side_effect = [
            self._mock_s2_response(),  # center
            {"data": []},  # empty refs
            {"data": []},  # empty cits
        ]

        result = get_citation_graph("10.1/test")
        assert result["success"] is True
        assert len(result["nodes"]) == 1  # center only
        assert len(result["edges"]) == 0

    @patch("citation_graph._s2_get")
    def test_dedup_same_doi(self, mock_get):
        """Same DOI in refs and cits should not create duplicate nodes."""
        same_paper = self._mock_s2_response("Same Paper", 2021, 20, "10.1/same")
        mock_get.side_effect = [
            self._mock_s2_response(),  # center
            {"data": [{"citedPaper": same_paper}]},  # refs
            {"data": [{"citingPaper": same_paper}]},  # cits (same DOI)
        ]

        result = get_citation_graph("10.1/test")
        assert result["success"] is True
        # Should have center + 1 paper (deduped), not center + 2
        titles = [n["title"] for n in result["nodes"]]
        assert titles.count("Same Paper") == 1

    @patch("citation_graph._s2_get")
    def test_depth_2(self, mock_get):
        """Depth 2 should expand top-cited citations."""
        cit_paper = self._mock_s2_response("High Cited", 2024, 100, "10.1/hc")
        l2_paper = self._mock_s2_response("Level 2 Paper", 2025, 3, "10.1/l2")

        mock_get.side_effect = [
            self._mock_s2_response(),  # center
            {"data": []},  # refs
            {"data": [{"citingPaper": cit_paper}]},  # cits
            {"data": [{"citingPaper": l2_paper}]},  # l2 cits
        ]

        result = get_citation_graph("10.1/test", depth=2)
        assert result["success"] is True
        types = [n["type"] for n in result["nodes"]]
        assert "citation_l2" in types
