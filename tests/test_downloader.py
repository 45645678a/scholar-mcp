"""Tests for downloader.py — download chain and health check."""
import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from downloader import download_paper, batch_download, health_check


# ═══════════════════════════════════════
# Download Paper
# ═══════════════════════════════════════

class TestDownloadPaper:
    @patch("downloader._try_publisher_oa", return_value=None)
    @patch("downloader._try_arxiv", return_value=None)
    @patch("downloader._try_scihub", return_value=None)
    @patch("downloader._try_scidownl", return_value=None)
    @patch("downloader.requests.get")
    def test_unpaywall_success(self, mock_get, mock_scidownl, mock_scihub, mock_arxiv, mock_pub, tmp_path):
        """Should use Unpaywall first when it returns a PDF URL."""
        pdf_content = b"%PDF-1.4 fake pdf content here" + b"\x00" * 1100  # >1024 bytes for validation

        def side_effect(url, **kwargs):
            resp = MagicMock()
            if "unpaywall" in url:
                resp.status_code = 200
                resp.json.return_value = {
                    "best_oa_location": {"url_for_pdf": "https://example.com/paper_oa.pdf"},
                    "is_oa": True,
                }
                return resp
            elif "paper_oa.pdf" in url:
                resp.status_code = 200
                resp.content = pdf_content
                resp.headers = {"Content-Type": "application/pdf"}
                return resp
            resp.status_code = 404
            return resp

        mock_get.side_effect = side_effect

        result = download_paper("10.1234/test", str(tmp_path))
        assert result["success"] is True
        assert result["source"] == "unpaywall_oa"
        assert os.path.exists(result["path"])

    def test_all_fail(self, tmp_path):
        """When all sources fail, should return success=False."""
        with patch("downloader._try_unpaywall", return_value=None), \
             patch("downloader._try_publisher_oa", return_value=None), \
             patch("downloader._try_arxiv", return_value=None), \
             patch("downloader._try_scihub", return_value=None), \
             patch("downloader._try_scidownl", return_value=None):
            result = download_paper("10.9999/nonexistent", str(tmp_path))
            assert result["success"] is False


# ═══════════════════════════════════════
# Batch Download
# ═══════════════════════════════════════

class TestBatchDownload:
    @patch("downloader.download_paper")
    def test_batch(self, mock_dl, tmp_path):
        mock_dl.return_value = {
            "success": True, "doi": "10.1/test",
            "path": str(tmp_path / "test.pdf"),
            "size_mb": 0.5, "source": "unpaywall_oa",
        }

        result = batch_download(["10.1/a", "10.1/b"], str(tmp_path))
        assert result["total"] == 2
        assert result["success"] == 2  # key is "success" not "success_count"
        assert mock_dl.call_count == 2

    def test_empty_list(self, tmp_path):
        result = batch_download([], str(tmp_path))
        assert result["total"] == 0


# ═══════════════════════════════════════
# Health Check
# ═══════════════════════════════════════

class TestHealthCheck:
    @patch("downloader.requests.get")
    @patch("downloader.requests.head")
    def test_structure(self, mock_head, mock_get):
        """Health check should return a structured result with sources dict."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        mock_head.return_value = mock_resp

        result = health_check()
        assert "sources" in result
        assert isinstance(result["sources"], dict)
        assert "unpaywall" in result["sources"]
        assert "overall" in result
