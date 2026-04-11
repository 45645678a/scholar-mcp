"""论文翻译模块 — 使用 AI API 翻译论文全文或摘要

支持任意 OpenAI 兼容 API（DeepSeek / OpenAI / Azure / Ollama 等）。
支持分段翻译大文本，避免超过 token 限制。
"""

import os
import json
import requests

from pdf_reader import extract_text
from logger import get_logger

log = get_logger("translator")

AI_API_BASE = os.environ.get("AI_API_BASE", "https://api.deepseek.com")
AI_API_KEY = os.environ.get("AI_API_KEY", os.environ.get("DS_KEY", ""))
AI_MODEL = os.environ.get("AI_MODEL", "deepseek-chat")

# 每段最大字符数（避免超过 API token 限制）
CHUNK_SIZE = 4000
# 翻译请求超时
TRANSLATE_TIMEOUT = 180


def _call_ai(prompt: str, max_tokens: int = 2000) -> str:
    """调用 AI API"""
    api_url = f"{AI_API_BASE.rstrip('/')}/chat/completions"
    r = requests.post(
        api_url,
        headers={
            "Authorization": f"Bearer {AI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": AI_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": max_tokens,
        },
        timeout=TRANSLATE_TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"AI API error: HTTP {r.status_code}")

    data = r.json()
    choices = data.get("choices")
    if not choices:
        raise RuntimeError("AI API returned no choices")

    return choices[0].get("message", {}).get("content", "")


def _split_text(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """将文本按段落边界分段"""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    paragraphs = text.split("\n\n")
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 > chunk_size:
            if current:
                chunks.append(current.strip())
            current = para
        else:
            current = current + "\n\n" + para if current else para

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text[:chunk_size]]


def translate_text(text: str, target_lang: str = "zh", source_lang: str = "auto") -> dict:
    """翻译文本

    Args:
        text: 要翻译的文本
        target_lang: 目标语言 (zh=中文, en=英文, ja=日文, ko=韩文, etc.)
        source_lang: 源语言 (auto=自动检测)

    Returns:
        dict: {success, translated_text, chunks, model}
    """
    if not AI_API_KEY:
        return {"success": False, "error": "AI_API_KEY not set"}

    if not text or not text.strip():
        return {"success": False, "error": "empty text"}

    lang_names = {
        "zh": "Chinese (Simplified)",
        "en": "English",
        "ja": "Japanese",
        "ko": "Korean",
        "de": "German",
        "fr": "French",
        "es": "Spanish",
        "ru": "Russian",
    }
    target_name = lang_names.get(target_lang, target_lang)

    chunks = _split_text(text)
    translated_parts = []

    log.info("translating %d chars in %d chunks to %s", len(text), len(chunks), target_name)

    for i, chunk in enumerate(chunks):
        prompt = f"""Translate the following academic text to {target_name}.
Preserve all technical terms, formulas, and proper nouns.
Keep the original paragraph structure.
Do not add explanations or notes — only output the translation.

Text to translate:
{chunk}"""

        try:
            result = _call_ai(prompt, max_tokens=len(chunk) + 500)
            translated_parts.append(result)
            log.debug("chunk %d/%d translated", i + 1, len(chunks))
        except Exception as e:
            log.error("translation chunk %d failed: %s", i + 1, e)
            return {
                "success": False,
                "error": f"translation failed at chunk {i + 1}/{len(chunks)}: {str(e)}",
                "partial_translation": "\n\n".join(translated_parts) if translated_parts else "",
            }

    full_translation = "\n\n".join(translated_parts)

    return {
        "success": True,
        "translated_text": full_translation,
        "source_chars": len(text),
        "translated_chars": len(full_translation),
        "chunks": len(chunks),
        "target_language": target_name,
        "model": AI_MODEL,
    }


def translate_pdf(pdf_path: str, target_lang: str = "zh",
                  max_pages: int = 30, max_chars: int = 15000) -> dict:
    """翻译 PDF 论文

    Args:
        pdf_path: PDF 文件路径
        target_lang: 目标语言
        max_pages: 最大提取页数
        max_chars: 最大提取字符数

    Returns:
        dict: {success, translated_text, pages, method, ...}
    """
    # 提取文本
    extract_result = extract_text(pdf_path, max_pages=max_pages, max_chars=max_chars)
    if not extract_result.get("success"):
        return {"success": False, "error": f"PDF extraction failed: {extract_result.get('error', 'unknown')}"}

    text = extract_result["text"]

    # 翻译
    result = translate_text(text, target_lang=target_lang)
    if result.get("success"):
        result["pdf_pages"] = extract_result["pages"]
        result["pdf_method"] = extract_result["method"]

    return result
