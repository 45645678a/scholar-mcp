"""Tests for scholar_mcp_server.py — MCP tool wrappers."""
import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scholar_mcp_server import (
    paper_search,
    paper_download,
    paper_batch_download,
    paper_ai_analyze,
    paper_recommend,
    paper_citation_graph,
    paper_health,
)


# ═══════════════════════════════════════
# Input Validation
# ═══════════════════════════════════════

class TestInputValidation:
    def test_search_empty_query(self):
        result = json.loads(paper_search(""))
        assert result["success"] is False
        assert "empty" in result["error"].lower()

    def test_search_whitespace_query(self):
        result = json.loads(paper_search("   "))
        assert result["success"] is False

    def test_download_empty_doi(self):
        result = json.loads(paper_download(""))
        assert result["success"] is False
        assert "empty" in result["error"].lower()

    def test_batch_download_empty_list(self):
        result = json.loads(paper_batch_download([]))
        assert result["success"] is False

    def test_citation_graph_empty_doi(self):
        result = json.loads(paper_citation_graph(""))
        assert result["success"] is False

    @patch.dict(os.environ, {"AI_API_KEY": ""}, clear=False)
    def test_ai_analyze_no_key(self):
        # Need to reload module to pick up env change
        import scholar_mcp_server as srv
        old_key = srv.AI_API_KEY
        srv.AI_API_KEY = ""
        try:
            result = json.loads(srv.paper_ai_analyze("10.1/test"))
            assert result["success"] is False
            assert "AI_API_KEY" in result["error"]
        finally:
            srv.AI_API_KEY = old_key

    def test_ai_analyze_empty_doi(self):
        result = json.loads(paper_ai_analyze(""))
        assert result["success"] is False


# ═══════════════════════════════════════
# Search Tool
# ═══════════════════════════════════════

class TestPaperSearch:
    @patch("scholar_mcp_server.search_papers")
    def test_returns_json(self, mock_search):
        mock_search.return_value = {"success": True, "count": 1, "results": []}
        result = json.loads(paper_search("test query"))
        assert result["success"] is True
        mock_search.assert_called_once_with("test query", 8)

    @patch("scholar_mcp_server.search_papers")
    def test_rows_clamped(self, mock_search):
        mock_search.return_value = {"success": True, "count": 0, "results": []}
        paper_search("test", rows=100)
        mock_search.assert_called_once_with("test", 50)  # clamped to 50

    @patch("scholar_mcp_server.search_papers")
    def test_rows_min(self, mock_search):
        mock_search.return_value = {"success": True, "count": 0, "results": []}
        paper_search("test", rows=-5)
        mock_search.assert_called_once_with("test", 1)  # clamped to 1


# ═══════════════════════════════════════
# Download Tool
# ═══════════════════════════════════════

class TestPaperDownload:
    @patch("scholar_mcp_server.download_paper")
    def test_returns_json(self, mock_dl):
        mock_dl.return_value = {"success": True, "doi": "10.1/test", "path": "/tmp/test.pdf"}
        result = json.loads(paper_download("10.1/test"))
        assert result["success"] is True

    @patch("scholar_mcp_server.download_paper")
    def test_strips_doi(self, mock_dl):
        mock_dl.return_value = {"success": True, "doi": "10.1/test"}
        paper_download("  10.1/test  ")
        mock_dl.assert_called_once_with("10.1/test", ".")


# ═══════════════════════════════════════
# Citation Graph Tool
# ═══════════════════════════════════════

class TestPaperCitationGraph:
    @patch("scholar_mcp_server.get_citation_graph")
    def test_returns_json(self, mock_graph):
        mock_graph.return_value = {"success": True, "nodes": [], "edges": []}
        result = json.loads(paper_citation_graph("10.1/test"))
        assert result["success"] is True

    @patch("scholar_mcp_server.get_citation_graph")
    def test_depth_clamped(self, mock_graph):
        mock_graph.return_value = {"success": True}
        paper_citation_graph("10.1/test", depth=10)
        mock_graph.assert_called_once_with("10.1/test", 3, 10)  # depth clamped to 3

    @patch("scholar_mcp_server.get_citation_graph")
    def test_max_per_level_clamped(self, mock_graph):
        mock_graph.return_value = {"success": True}
        paper_citation_graph("10.1/test", max_per_level=100)
        mock_graph.assert_called_once_with("10.1/test", 1, 50)  # clamped to 50


# ═══════════════════════════════════════
# Recommend Tool
# ═══════════════════════════════════════

class TestPaperRecommend:
    @patch("scholar_mcp_server.recommend_papers")
    def test_returns_json(self, mock_rec):
        mock_rec.return_value = {"success": True, "recommended_papers": []}
        result = json.loads(paper_recommend("/some/path"))
        assert result["success"] is True

    @patch("scholar_mcp_server.recommend_papers")
    def test_top_n_clamped(self, mock_rec):
        mock_rec.return_value = {"success": True}
        paper_recommend("/path", top_n=100)
        mock_rec.assert_called_once_with("/path", 30)  # clamped to 30


# ═══════════════════════════════════════
# Health Check Tool
# ═══════════════════════════════════════

class TestPaperHealth:
    @patch("scholar_mcp_server.health_check")
    def test_returns_json(self, mock_hc):
        mock_hc.return_value = {"overall": "ok", "sources": {}}
        result = json.loads(paper_health())
        assert "overall" in result


# ═══════════════════════════════════════
# AI Analyze — with mocked API
# ═══════════════════════════════════════

class TestPaperAiAnalyze:
    @patch("scholar_mcp_server.extract_pdf_text")
    @patch("scholar_mcp_server.download_paper")
    @patch("scholar_mcp_server.requests.post")
    @patch("scholar_mcp_server.requests.get")
    def test_success_abstract_mode(self, mock_get, mock_post, mock_dl, mock_pdf):
        import scholar_mcp_server as srv
        old_key = srv.AI_API_KEY
        srv.AI_API_KEY = "test-key"
        try:
            # Mock Crossref metadata
            crossref_resp = MagicMock()
            crossref_resp.status_code = 200
            crossref_resp.json.return_value = {
                "message": {
                    "title": ["Test Paper"],
                    "author": [{"given": "John", "family": "Doe"}],
                    "container-title": ["Test Journal"],
                    "published": {"date-parts": [[2023]]},
                    "abstract": "Test abstract.",
                }
            }
            mock_get.return_value = crossref_resp

            # Mock download failure (abstract-only mode)
            mock_dl.return_value = {"success": False}

            # Mock AI API response
            ai_resp = MagicMock()
            ai_resp.status_code = 200
            ai_resp.json.return_value = {
                "choices": [{"message": {"content": "Analysis result here"}}]
            }
            mock_post.return_value = ai_resp

            result = json.loads(srv.paper_ai_analyze("10.1/test"))
            assert result["success"] is True
            assert result["analysis_mode"] == "abstract_only"
            assert "Analysis result" in result["analysis"]
        finally:
            srv.AI_API_KEY = old_key

    @patch("scholar_mcp_server.requests.get")
    def test_doi_not_found(self, mock_get):
        import scholar_mcp_server as srv
        old_key = srv.AI_API_KEY
        srv.AI_API_KEY = "test-key"
        try:
            resp = MagicMock()
            resp.status_code = 404
            mock_get.return_value = resp

            result = json.loads(srv.paper_ai_analyze("10.1/nonexistent"))
            assert result["success"] is False
            assert "not found" in result["error"].lower()
        finally:
            srv.AI_API_KEY = old_key

    @patch("scholar_mcp_server.download_paper")
    @patch("scholar_mcp_server.requests.post")
    @patch("scholar_mcp_server.requests.get")
    def test_ai_api_error(self, mock_get, mock_post, mock_dl):
        import scholar_mcp_server as srv
        old_key = srv.AI_API_KEY
        srv.AI_API_KEY = "test-key"
        try:
            crossref_resp = MagicMock()
            crossref_resp.status_code = 200
            crossref_resp.json.return_value = {
                "message": {"title": ["Test"], "published": {"date-parts": [[2023]]}}
            }
            mock_get.return_value = crossref_resp
            mock_dl.return_value = {"success": False}

            ai_resp = MagicMock()
            ai_resp.status_code = 500
            ai_resp.text = "Internal Server Error"
            mock_post.return_value = ai_resp

            result = json.loads(srv.paper_ai_analyze("10.1/test"))
            assert result["success"] is False
            assert "500" in result["error"]
        finally:
            srv.AI_API_KEY = old_key
