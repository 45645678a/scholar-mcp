"""Scholar MCP Server — 本地论文工具 MCP 服务器

提供 9 源并发论文搜索、多源 PDF 下载、AI 全文分析、代码推荐、引用图谱功能。
所有操作在本地执行，搜索 API 均免费无需 Key。

启动方式 (stdio):
    python scholar_mcp_server.py
"""

import os
import re
import sys
import json
import shutil
import tempfile
import requests
from mcp.server.fastmcp import FastMCP

# 确保能 import 同目录的模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from downloader import download_paper, batch_download, health_check
from searcher import search_papers
from recommender import recommend_papers
from citation_graph import get_citation_graph
from pdf_reader import extract_text as extract_pdf_text
from translator import translate_text, translate_pdf
from cache import stats as cache_stats, clear_all as cache_clear
from logger import get_logger

log = get_logger("server")

# ─── 环境变量 ───
# AI API 配置（兼容任意 OpenAI 格式 API：DeepSeek / OpenAI / Azure / Ollama 等）
AI_API_BASE = os.environ.get("AI_API_BASE", "https://api.deepseek.com")  # 不带 /chat/completions
AI_API_KEY = os.environ.get("AI_API_KEY", os.environ.get("DS_KEY", ""))  # 优先用 AI_API_KEY，兼容旧 DS_KEY
AI_MODEL = os.environ.get("AI_MODEL", "deepseek-chat")
CROSSREF = "https://api.crossref.org/works"

# JATS XML 标签清理正则（预编译）
_JATS_TAG_RE = re.compile(r"</?jats:[^>]+>")

# ─── MCP Server ───

mcp = FastMCP("scholar-local")


@mcp.tool()
def paper_download(doi: str, output_dir: str = ".") -> str:
    """通过 DOI 下载一篇论文 PDF（本地多源下载：Unpaywall → Publisher OA → arXiv → Sci-Hub → scidownl）。

    Args:
        doi: 论文的 DOI，例如 "10.1109/tim.2021.3106677"
        output_dir: 保存 PDF 的目录路径，默认为当前目录

    Returns:
        下载结果的 JSON 字符串，包含 success, doi, path, size_mb, source 等字段
    """
    doi = doi.strip()
    if not doi:
        return json.dumps({"success": False, "error": "DOI cannot be empty"})
    log.info("download: doi=%s dir=%s", doi, output_dir)
    result = download_paper(doi, output_dir)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def paper_batch_download(dois: list[str], output_dir: str = ".") -> str:
    """批量下载多篇论文 PDF。

    Args:
        dois: DOI 列表，例如 ["10.1109/tim.2021.3106677", "10.1109/tie.2020.3032868"]
        output_dir: 保存 PDF 的目录路径，默认为当前目录

    Returns:
        批量下载结果的 JSON 字符串，包含每篇的状态和汇总统计
    """
    if not dois:
        return json.dumps({"success": False, "error": "DOI list cannot be empty"})
    log.info("batch_download: %d DOIs, dir=%s", len(dois), output_dir)
    result = batch_download(dois, output_dir)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def paper_search(query: str, rows: int = 8, offset: int = 0) -> str:
    """搜索论文 (9 源并发：Semantic Scholar / OpenAlex / Crossref / PubMed / arXiv / CORE / Europe PMC / DOAJ / dblp)。

    支持关键词搜索或直接输入 DOI 查询详情。支持分页：用 offset 翻页。

    Args:
        query: 搜索关键词或 DOI，例如 "gradient magnetic field coil" 或 "10.1109/tim.2021.3106677"
        rows: 返回结果数量，默认 8
        offset: 分页偏移量，默认 0（第一页）。例如 offset=8 返回第 9-16 条结果

    Returns:
        搜索结果 JSON，包含 title, authors, journal, year, doi, cited_by, abstract 等
    """
    query = query.strip()
    if not query:
        return json.dumps({"success": False, "error": "query cannot be empty"})
    rows = max(1, min(rows, 50))
    offset = max(0, offset)
    log.info("search: query=%r rows=%d offset=%d", query[:80], rows, offset)

    if offset > 0:
        # 分页：获取 offset+rows 条结果，然后切片
        total_needed = offset + rows
        result = search_papers(query, total_needed)
        if result.get("success") and result.get("results"):
            all_results = result["results"]
            paged = all_results[offset:offset + rows]
            for i, r in enumerate(paged):
                r["index"] = offset + i + 1
            result["results"] = paged
            result["count"] = len(paged)
            result["offset"] = offset
            result["has_more"] = len(all_results) > offset + rows
        return json.dumps(result, ensure_ascii=False, indent=2)

    result = search_papers(query, rows)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def paper_ai_analyze(doi: str) -> str:
    """使用 AI 分析论文，返回核心贡献、研究方法、关键发现等。

    支持任意 OpenAI 兼容 API（通过 AI_API_BASE / AI_API_KEY / AI_MODEL 环境变量配置）。
    如果能下载到 PDF，会提取全文（最多 20 页、12000 字符）进行深度分析；否则退回到 abstract 分析。

    Args:
        doi: 论文的 DOI，例如 "10.1109/tim.2021.3106677"

    Returns:
        AI 分析结果 JSON
    """
    doi = doi.strip()
    if not doi:
        return json.dumps({"success": False, "error": "DOI cannot be empty"})

    if not AI_API_KEY:
        return json.dumps({"success": False, "error": "AI_API_KEY (or DS_KEY) not set, AI analysis unavailable"})

    tmp_dir = None
    try:
        # 获取论文元数据
        r = requests.get(f"{CROSSREF}/{requests.utils.quote(doi)}", timeout=10)
        if r.status_code != 200:
            return json.dumps({"success": False, "error": f"DOI not found: {doi}"})

        item = r.json().get("message", {})
        title = (item.get("title") or [""])[0]
        authors = ", ".join(
            f"{a.get('given', '')} {a.get('family', '')}"
            for a in (item.get("author") or [])
        )
        journal = (item.get("container-title") or [""])[0]
        year = ""
        if item.get("published") and item["published"].get("date-parts"):
            year = str(item["published"]["date-parts"][0][0])
        abstract = _JATS_TAG_RE.sub("", item.get("abstract") or "").strip()

        # 尝试获取全文：下载 PDF → 提取文本
        full_text = ""
        analysis_mode = "abstract_only"
        try:
            tmp_dir = tempfile.mkdtemp(prefix="scholar_mcp_")
            dl_result = download_paper(doi, tmp_dir)
            if dl_result.get("success") and dl_result.get("path"):
                pdf_result = extract_pdf_text(dl_result["path"], max_pages=20, max_chars=12000)
                if pdf_result.get("success"):
                    full_text = pdf_result["text"]
                    analysis_mode = f"full_text ({pdf_result['pages']} pages, {pdf_result['chars']} chars, {pdf_result['method']})"
                    log.info("ai_analyze: full text extracted for %s", doi)
        except Exception as e:
            log.warning("ai_analyze: PDF extraction failed for %s: %s", doi, e)

        # 构建 prompt
        if full_text:
            prompt = f"""You are an academic research assistant. Analyze this paper thoroughly in Chinese based on the full text provided.

Title: {title}
Authors: {authors}
Journal: {journal} ({year})

--- FULL TEXT ---
{full_text}
--- END ---

Provide a thorough analysis:
1. **核心贡献**: 一句话概括
2. **研究背景**: 为什么做这个研究（2-3句）
3. **研究方法**: 详细描述使用的方法和技术路线（3-5句）
4. **关键发现**: 3-5个具体的定量或定性结果
5. **创新点**: 与现有研究的具体区别
6. **局限性**: 2-3点
7. **应用前景**: 1-2句"""
            max_tokens = 1500
        else:
            prompt = f"""You are an academic research assistant. Analyze this paper concisely in Chinese.

Title: {title}
Authors: {authors}
Journal: {journal} ({year})
{"Abstract: " + abstract if abstract else ""}

Provide:
1. **核心贡献**: 一句话概括
2. **研究方法**: 2-3句
3. **关键发现**: 2-3个要点
4. **创新点**: 与现有研究的区别
5. **局限性**: 1-2点"""
            max_tokens = 800

        # 调用 AI API
        api_url = f"{AI_API_BASE.rstrip('/')}/chat/completions"
        log.info("ai_analyze: calling %s model=%s", api_url, AI_MODEL)
        ar = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {AI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": AI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": max_tokens,
            },
            timeout=120,
        )

        # 验证 AI API 响应
        if ar.status_code != 200:
            log.error("ai_analyze: API returned HTTP %d: %s", ar.status_code, ar.text[:200])
            return json.dumps({"success": False, "error": f"AI API error: HTTP {ar.status_code}"})

        ar_json = ar.json()
        choices = ar_json.get("choices")
        if not choices or not isinstance(choices, list):
            return json.dumps({"success": False, "error": "AI API returned invalid response (no choices)"})

        analysis = choices[0].get("message", {}).get("content", "")
        if not analysis:
            return json.dumps({"success": False, "error": "AI API returned empty analysis"})

        return json.dumps({
            "success": True,
            "doi": doi,
            "title": title,
            "authors": authors,
            "journal": f"{journal} ({year})",
            "model": AI_MODEL,
            "analysis_mode": analysis_mode,
            "analysis": analysis,
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        log.exception("ai_analyze failed for %s", doi)
        return json.dumps({"success": False, "error": str(e)})
    finally:
        # 清理临时目录
        if tmp_dir and os.path.isdir(tmp_dir):
            try:
                shutil.rmtree(tmp_dir)
            except OSError:
                pass


@mcp.tool()
def paper_recommend(workspace_path: str, top_n: int = 8) -> str:
    """分析工作区代码，自动推荐相关学术论文。

    扫描指定目录下的源文件（.py, .tex, .md 等），提取 import 库名、算法术语、
    LaTeX 标题等特征，映射到学术领域关键词后搜索论文推荐。

    Args:
        workspace_path: 工作区根目录路径，例如 "E:/半导体实验"
        top_n: 返回推荐论文数量，默认 8

    Returns:
        推荐结果 JSON，包含检测到的库/术语、搜索查询和推荐论文列表
    """
    top_n = max(1, min(top_n, 30))
    log.info("recommend: path=%s top_n=%d", workspace_path, top_n)
    result = recommend_papers(workspace_path, top_n)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def paper_citation_graph(doi: str, depth: int = 1, max_per_level: int = 10) -> str:
    """生成论文引用图谱（Mermaid 可视化 + 结构化数据）。

    通过 Semantic Scholar API 获取论文的引用(citations)和参考文献(references)，
    输出 Mermaid 图谱代码（可直接在 Markdown 中渲染）和结构化 JSON。

    Args:
        doi: 论文的 DOI，例如 "10.1109/tim.2021.3106677"
        depth: 递归深度 (1=直接引用/参考, 2=二层引用)，默认 1
        max_per_level: 每层最多获取的论文数，默认 10

    Returns:
        引用图谱 JSON，包含 mermaid (图谱代码), nodes, edges, statistics 等
    """
    doi = doi.strip()
    if not doi:
        return json.dumps({"success": False, "error": "DOI cannot be empty"})
    depth = max(1, min(depth, 3))
    max_per_level = max(1, min(max_per_level, 50))
    log.info("citation_graph: doi=%s depth=%d max=%d", doi, depth, max_per_level)
    result = get_citation_graph(doi, depth, max_per_level)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def paper_translate(doi: str = "", pdf_path: str = "", text: str = "",
                    target_lang: str = "zh") -> str:
    """翻译论文内容（支持 DOI、PDF 文件路径或直接文本输入）。

    通过 AI API 进行学术翻译，保留专业术语和公式。支持分段翻译大文本。
    翻译语言可选：zh(中文), en(英文), ja(日文), ko(韩文), de(德文), fr(法文) 等。

    Args:
        doi: 论文 DOI（会自动下载 PDF 后翻译），与 pdf_path/text 三选一
        pdf_path: 本地 PDF 文件路径
        text: 直接输入要翻译的文本
        target_lang: 目标语言代码，默认 "zh"（中文）

    Returns:
        翻译结果 JSON
    """
    if doi:
        doi = doi.strip()
        log.info("translate: doi=%s lang=%s", doi, target_lang)
        import tempfile
        import shutil as _shutil
        tmp_dir = None
        try:
            tmp_dir = tempfile.mkdtemp(prefix="scholar_translate_")
            dl_result = download_paper(doi, tmp_dir)
            if not dl_result.get("success") or not dl_result.get("path"):
                return json.dumps({"success": False, "error": f"cannot download PDF for {doi}: {dl_result.get('error', 'unknown')}"})
            result = translate_pdf(dl_result["path"], target_lang=target_lang)
            result["doi"] = doi
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
        finally:
            if tmp_dir and os.path.isdir(tmp_dir):
                try:
                    _shutil.rmtree(tmp_dir)
                except OSError:
                    pass
    elif pdf_path:
        log.info("translate: pdf=%s lang=%s", pdf_path, target_lang)
        result = translate_pdf(pdf_path, target_lang=target_lang)
        return json.dumps(result, ensure_ascii=False, indent=2)
    elif text:
        log.info("translate: text (%d chars) lang=%s", len(text), target_lang)
        result = translate_text(text, target_lang=target_lang)
        return json.dumps(result, ensure_ascii=False, indent=2)
    else:
        return json.dumps({"success": False, "error": "provide one of: doi, pdf_path, or text"})


@mcp.tool()
def paper_health() -> str:
    """检查论文下载服务各数据源的可用性（Unpaywall、arXiv、Sci-Hub 镜像）。

    Returns:
        各数据源健康状态的 JSON 字符串
    """
    result = health_check()
    return json.dumps(result, ensure_ascii=False, indent=2)


def main():
    """Entry point for CLI and PyPI."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
