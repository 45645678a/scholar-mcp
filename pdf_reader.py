"""PDF 全文提取模块 — 将 PDF 转为纯文本

支持 PyMuPDF (fitz) 和 pdfplumber 双引擎，自动选择可用的。
"""

import os


def extract_text(pdf_path: str, max_pages: int = 30, max_chars: int = 15000) -> dict:
    """从 PDF 文件提取文本内容

    Args:
        pdf_path: PDF 文件路径
        max_pages: 最大提取页数（防止超大文件）
        max_chars: 最大返回字符数（控制 LLM token 用量）

    Returns:
        dict: {success, text, pages, chars, method}
    """
    if not os.path.exists(pdf_path):
        return {"success": False, "error": f"File not found: {pdf_path}"}

    # 方法 1: PyMuPDF (fitz) — 速度快、质量高
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        pages_text = []
        total_chars = 0
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            text = page.get_text("text")
            pages_text.append(text)
            total_chars += len(text)
            if total_chars >= max_chars:
                break
        doc.close()
        full_text = "\n\n".join(pages_text)[:max_chars]
        if full_text.strip():
            return {
                "success": True,
                "text": full_text,
                "pages": len(pages_text),
                "chars": len(full_text),
                "method": "pymupdf",
            }
    except ImportError:
        pass
    except Exception as e:
        pass

    # 方法 2: pdfplumber — 纯 Python，兼容性好
    try:
        import pdfplumber
        pages_text = []
        total_chars = 0
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                if i >= max_pages:
                    break
                text = page.extract_text() or ""
                pages_text.append(text)
                total_chars += len(text)
                if total_chars >= max_chars:
                    break
        full_text = "\n\n".join(pages_text)[:max_chars]
        if full_text.strip():
            return {
                "success": True,
                "text": full_text,
                "pages": len(pages_text),
                "chars": len(full_text),
                "method": "pdfplumber",
            }
    except ImportError:
        pass
    except Exception as e:
        pass

    return {
        "success": False,
        "error": "No PDF extraction library available. Install: pip install pymupdf  (or)  pip install pdfplumber",
    }


def extract_sections(text: str) -> dict:
    """从提取的文本中尝试识别论文各部分

    Returns:
        dict with keys like title, abstract, introduction, methods, results, conclusion
    """
    import re

    sections = {}
    lines = text.split("\n")

    # 尝试提取 Abstract
    abstract_start = -1
    for i, line in enumerate(lines):
        if re.match(r"^\s*(abstract|摘\s*要)\s*$", line, re.IGNORECASE):
            abstract_start = i + 1
            break

    if abstract_start > 0:
        abstract_lines = []
        for line in lines[abstract_start:abstract_start + 20]:
            if re.match(r"^\s*(1\.?\s*introduction|keywords|关键词|引言)", line, re.IGNORECASE):
                break
            abstract_lines.append(line)
        sections["abstract"] = " ".join(abstract_lines).strip()

    # 返回完整文本 + 识别的 sections
    sections["full_text"] = text
    return sections
