"""Tests for translator.py — text splitting and translation."""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from translator import translate_text, _split_text


# ═══════════════════════════════════════
# Text Splitting
# ═══════════════════════════════════════

class TestSplitText:
    def test_short_text(self):
        chunks = _split_text("Hello world", chunk_size=100)
        assert len(chunks) == 1
        assert chunks[0] == "Hello world"

    def test_long_text_split_on_paragraph(self):
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = _split_text(text, chunk_size=30)
        assert len(chunks) >= 2
        # All content should be preserved
        joined = "\n\n".join(chunks)
        assert "First" in joined
        assert "Third" in joined

    def test_empty_text(self):
        chunks = _split_text("", chunk_size=100)
        assert len(chunks) == 1

    def test_single_paragraph_too_long(self):
        text = "A" * 200
        chunks = _split_text(text, chunk_size=100)
        assert len(chunks) >= 1


# ═══════════════════════════════════════
# Translation
# ═══════════════════════════════════════

class TestTranslateText:
    def test_no_api_key(self):
        with patch("translator.AI_API_KEY", ""):
            result = translate_text("test")
            assert result["success"] is False
            assert "API_KEY" in result["error"]

    def test_empty_text(self):
        with patch("translator.AI_API_KEY", "test-key"):
            result = translate_text("")
            assert result["success"] is False
            assert "empty" in result["error"].lower()

    @patch("translator._call_ai")
    def test_success(self, mock_ai):
        mock_ai.return_value = "这是翻译结果"
        with patch("translator.AI_API_KEY", "test-key"):
            result = translate_text("This is a test", target_lang="zh")
            assert result["success"] is True
            assert "这是翻译结果" in result["translated_text"]
            assert result["target_language"] == "Chinese (Simplified)"

    @patch("translator._call_ai")
    def test_multi_chunk(self, mock_ai):
        mock_ai.return_value = "translated chunk"
        with patch("translator.AI_API_KEY", "test-key"):
            long_text = "Paragraph one.\n\n" * 50  # Long enough to split
            result = translate_text(long_text, target_lang="zh")
            assert result["success"] is True
            assert result["chunks"] >= 1

    @patch("translator._call_ai")
    def test_api_failure(self, mock_ai):
        mock_ai.side_effect = RuntimeError("API error")
        with patch("translator.AI_API_KEY", "test-key"):
            result = translate_text("test text", target_lang="zh")
            assert result["success"] is False
            assert "failed" in result["error"].lower()

    @patch("translator._call_ai")
    def test_english_target(self, mock_ai):
        mock_ai.return_value = "This is the translation"
        with patch("translator.AI_API_KEY", "test-key"):
            result = translate_text("这是测试", target_lang="en")
            assert result["success"] is True
            assert result["target_language"] == "English"
