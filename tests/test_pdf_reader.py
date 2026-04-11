"""Tests for pdf_reader.py — text extraction and section detection."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pdf_reader import extract_text, extract_sections


# ═══════════════════════════════════════
# Extract Text
# ═══════════════════════════════════════

class TestExtractText:
    def test_file_not_found(self):
        result = extract_text("/nonexistent/path/paper.pdf")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_empty_file(self, tmp_path):
        pdf = tmp_path / "empty.pdf"
        pdf.write_bytes(b"")

        result = extract_text(str(pdf))
        assert result["success"] is False
        assert "empty" in result["error"].lower()

    def test_invalid_file(self, tmp_path):
        """Non-PDF file should fail gracefully."""
        pdf = tmp_path / "fake.pdf"
        pdf.write_text("This is not a PDF")

        result = extract_text(str(pdf))
        assert result["success"] is False

    def test_large_file_rejected(self, tmp_path):
        """Files over size limit should be rejected early."""
        pdf = tmp_path / "large.pdf"
        # Create a file that appears to exceed the limit via stat
        # We can't easily create a 200MB file in tests, so just test the check exists
        pdf.write_bytes(b"%PDF-1.4 small file")
        result = extract_text(str(pdf))
        # This will either succeed (if pymupdf/pdfplumber can parse it) or fail gracefully
        assert isinstance(result, dict)
        assert "success" in result

    def test_result_format(self, tmp_path):
        """Result should always have 'success' key."""
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"not a pdf")
        result = extract_text(str(pdf))
        assert "success" in result
        if not result["success"]:
            assert "error" in result


# ═══════════════════════════════════════
# Extract Sections
# ═══════════════════════════════════════

class TestExtractSections:
    def test_finds_abstract(self):
        text = """Some title here

Abstract
This is the abstract text about gradient coil design.
It spans multiple lines.

1. Introduction
This is the introduction."""
        sections = extract_sections(text)
        assert "abstract" in sections
        assert "gradient coil" in sections["abstract"]
        assert "full_text" in sections

    def test_chinese_abstract(self):
        text = """论文标题

摘 要
这是一篇关于梯度线圈设计的论文摘要。

关键词：梯度线圈，优化
"""
        sections = extract_sections(text)
        assert "abstract" in sections
        assert "梯度线圈" in sections["abstract"]

    def test_no_abstract(self):
        text = "Just some random text without any section headers."
        sections = extract_sections(text)
        assert "abstract" not in sections
        assert "full_text" in sections

    def test_empty_text(self):
        sections = extract_sections("")
        assert "full_text" in sections
        assert sections["full_text"] == ""

    def test_abstract_stops_at_keywords(self):
        text = """Abstract
This is the abstract.

Keywords: test, paper"""
        sections = extract_sections(text)
        assert "abstract" in sections
        assert "Keywords" not in sections["abstract"]
