"""PDF 全文提取模块 — 将 PDF 转为纯文本

支持 PyMuPDF (fitz) 和 pdfplumber 双引擎，自动选择可用的。
"""

import os
import re

from logger import get_logger

log = get_logger("pdf_reader")

# 文件大小限制：200MB
MAX_FILE_SIZE = 200 * 1024 * 1024


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

    file_size = os.path.getsize(pdf_path)
    if file_size > MAX_FILE_SIZE:
        return {"success": False, "error": f"File too large: {file_size / 1024 / 1024:.1f}MB (limit {MAX_FILE_SIZE // 1024 // 1024}MB)"}

    if file_size == 0:
        return {"success": False, "error": "File is empty"}

    # 方法 1: PyMuPDF (fitz) — 速度快、质量高
    pymupdf_error = None
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
        else:
            pymupdf_error = "extracted text is empty (scanned PDF?)"
            log.debug("pymupdf returned empty text for %s", pdf_path)
    except ImportError:
        pymupdf_error = "pymupdf not installed"
    except Exception as e:
        pymupdf_error = str(e)
        log.warning("pymupdf failed for %s: %s", pdf_path, e)

    # 方法 2: pdfplumber — 纯 Python，兼容性好
    pdfplumber_error = None
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
        else:
            pdfplumber_error = "extracted text is empty (scanned PDF?)"
    except ImportError:
        pdfplumber_error = "pdfplumber not installed"
    except Exception as e:
        pdfplumber_error = str(e)
        log.warning("pdfplumber failed for %s: %s", pdf_path, e)

    # 两个引擎都失败
    errors = []
    if pymupdf_error:
        errors.append(f"pymupdf: {pymupdf_error}")
    if pdfplumber_error:
        errors.append(f"pdfplumber: {pdfplumber_error}")

    if not errors:
        return {
            "success": False,
            "error": "No PDF extraction library available. Install: pip install pymupdf  (or)  pip install pdfplumber",
        }

    return {"success": False, "error": "; ".join(errors)}


def extract_tables(pdf_path: str, max_pages: int = 30) -> dict:
    """从 PDF 提取表格数据

    Args:
        pdf_path: PDF 文件路径
        max_pages: 最大提取页数

    Returns:
        dict: {success, tables: [{page, rows, data}], count}
    """
    if not os.path.exists(pdf_path):
        return {"success": False, "error": f"File not found: {pdf_path}"}

    tables = []

    # pdfplumber 表格提取能力更强
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                if i >= max_pages:
                    break
                page_tables = page.extract_tables()
                if not page_tables:
                    continue
                for t_idx, table in enumerate(page_tables):
                    if not table:
                        continue
                    # 清洗数据
                    cleaned = []
                    for row in table:
                        cleaned.append([
                            (cell or "").strip().replace("\n", " ")
                            for cell in row
                        ])
                    if cleaned:
                        tables.append({
                            "page": i + 1,
                            "table_index": t_idx,
                            "rows": len(cleaned),
                            "cols": max(len(r) for r in cleaned) if cleaned else 0,
                            "data": cleaned,
                        })

        if tables:
            return {
                "success": True,
                "count": len(tables),
                "tables": tables,
                "method": "pdfplumber",
            }
    except ImportError:
        pass
    except Exception as e:
        log.warning("pdfplumber table extraction failed: %s", e)

    # PyMuPDF 没有内置表格提取，尝试基本的文本表格检测
    try:
        import fitz
        doc = fitz.open(pdf_path)
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            # 使用 find_tables() (PyMuPDF >= 1.23.0)
            if hasattr(page, "find_tables"):
                page_tables = page.find_tables()
                for t_idx, table in enumerate(page_tables.tables if hasattr(page_tables, 'tables') else page_tables):
                    try:
                        data = table.extract()
                        if data:
                            cleaned = [
                                [(cell or "").strip() for cell in row]
                                for row in data
                            ]
                            if cleaned:
                                tables.append({
                                    "page": i + 1,
                                    "table_index": t_idx,
                                    "rows": len(cleaned),
                                    "cols": max(len(r) for r in cleaned) if cleaned else 0,
                                    "data": cleaned,
                                })
                    except Exception:
                        continue
        doc.close()

        if tables:
            return {
                "success": True,
                "count": len(tables),
                "tables": tables,
                "method": "pymupdf",
            }
    except ImportError:
        pass
    except Exception as e:
        log.warning("pymupdf table extraction failed: %s", e)

    return {
        "success": False,
        "error": "No tables found or no PDF library with table extraction available. Install: pip install pdfplumber",
    }


def extract_sections(text: str) -> dict:
    """从提取的文本中尝试识别论文各部分

    Returns:
        dict with keys like title, abstract, introduction, methods, results, conclusion
    """
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
