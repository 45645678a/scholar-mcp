"""Tests for recommender.py — keyword extraction and query building."""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from recommender import (
    _scan_directory,
    _build_query,
    recommend_papers,
    PY_IMPORT_RE,
    ACADEMIC_TERMS_RE,
)


# ═══════════════════════════════════════
# Import Regex
# ═══════════════════════════════════════

class TestImportRegex:
    def test_import_basic(self):
        m = PY_IMPORT_RE.findall("import numpy")
        assert "numpy" in m

    def test_from_import(self):
        m = PY_IMPORT_RE.findall("from scipy.optimize import minimize")
        assert "scipy.optimize" in m

    def test_indented(self):
        m = PY_IMPORT_RE.findall("    import torch")
        assert "torch" in m


# ═══════════════════════════════════════
# Academic Terms Regex
# ═══════════════════════════════════════

class TestAcademicTermsRegex:
    def test_finds_terms(self):
        text = "We use a neural network with gradient descent optimization."
        matches = ACADEMIC_TERMS_RE.findall(text)
        terms_lower = [m.lower() for m in matches]
        assert "neural network" in terms_lower
        assert "gradient descent" in terms_lower
        assert "optimization" in terms_lower

    def test_case_insensitive(self):
        text = "The TRANSFORMER model uses attention mechanism."
        matches = ACADEMIC_TERMS_RE.findall(text)
        terms_lower = [m.lower() for m in matches]
        assert "transformer" in terms_lower
        assert "attention mechanism" in terms_lower


# ═══════════════════════════════════════
# Scan Directory
# ═══════════════════════════════════════

class TestScanDirectory:
    def test_scan_python_files(self, tmp_path):
        """Should extract imports from Python files."""
        py_file = tmp_path / "main.py"
        py_file.write_text("import numpy\nimport torch\nfrom scipy.optimize import minimize\n")

        result = _scan_directory(str(tmp_path))
        assert result["files_scanned"] == 1
        assert "numpy" in result["imports"]
        assert "torch" in result["imports"]
        assert "scipy" in result["imports"]

    def test_scan_empty_dir(self, tmp_path):
        result = _scan_directory(str(tmp_path))
        assert result["files_scanned"] == 0
        assert len(result["imports"]) == 0

    def test_scan_latex(self, tmp_path):
        tex_file = tmp_path / "main.tex"
        tex_file.write_text(r"\title{Gradient Coil Design for MRI}" + "\n")

        result = _scan_directory(str(tmp_path))
        assert result["files_scanned"] == 1
        assert len(result["latex_titles"]) == 1
        assert "Gradient Coil Design for MRI" in result["latex_titles"][0]

    def test_skips_hidden_dirs(self, tmp_path):
        hidden = tmp_path / ".git" / "objects"
        hidden.mkdir(parents=True)
        (hidden / "test.py").write_text("import numpy\n")

        result = _scan_directory(str(tmp_path))
        assert result["files_scanned"] == 0


# ═══════════════════════════════════════
# Build Query
# ═══════════════════════════════════════

class TestBuildQuery:
    def test_from_imports(self):
        from collections import Counter
        scan = {
            "imports": Counter({"numpy": 5, "torch": 3}),
            "academic_terms": Counter(),
            "latex_titles": [],
            "files_scanned": 2,
        }
        query = _build_query(scan)
        assert len(query) > 0
        # Should include mapped keywords
        assert any(w in query.lower() for w in ["numerical", "deep", "learning", "computing"])

    def test_latex_title_high_weight(self):
        from collections import Counter
        scan = {
            "imports": Counter(),
            "academic_terms": Counter(),
            "latex_titles": ["Gradient Coil Optimization for MRI"],
            "files_scanned": 1,
        }
        query = _build_query(scan)
        assert "Gradient" in query

    def test_empty(self):
        from collections import Counter
        scan = {
            "imports": Counter(),
            "academic_terms": Counter(),
            "latex_titles": [],
            "files_scanned": 0,
        }
        query = _build_query(scan)
        assert query == ""


# ═══════════════════════════════════════
# Recommend Papers (integration)
# ═══════════════════════════════════════

class TestRecommendPapers:
    def test_invalid_path(self):
        result = recommend_papers("/nonexistent/path/12345")
        assert result["success"] is False

    @patch("recommender.search_papers")
    def test_with_python_workspace(self, mock_search, tmp_path):
        mock_search.return_value = {"results": [{"title": "Test Paper", "doi": "10.1/test", "cited_by": 5}]}

        py_file = tmp_path / "model.py"
        py_file.write_text("import torch\nimport numpy\n")

        result = recommend_papers(str(tmp_path), top_n=5)
        assert result["success"] is True
        assert "torch" in result["detected_libraries"] or "numpy" in result["detected_libraries"]
        assert "search_queries" in result  # multi-query output
        assert len(result["search_queries"]) >= 1
        mock_search.assert_called()
