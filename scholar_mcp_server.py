"""Scholar MCP Server — 本地论文工具 MCP 服务器

提供论文下载(Sci-Hub/arXiv/Unpaywall)、搜索、AI分析、代码推荐、引用图谱功能。
所有下载在本地执行，无需远程 API。

启动方式 (stdio):
    python scholar_mcp_server.py
"""

import os
import sys
import json
import requests
from mcp.server.fastmcp import FastMCP

# 确保能 import 同目录的模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from downloader import download_paper, batch_download, health_check
from searcher import search_papers
from recommender import recommend_papers
from citation_graph import get_citation_graph

# ─── 环境变量 ───
# AI API 配置（兼容任意 OpenAI 格式 API：DeepSeek / OpenAI / Azure / Ollama 等）
AI_API_BASE = os.environ.get("AI_API_BASE", "https://api.deepseek.com")  # 不带 /chat/completions
AI_API_KEY = os.environ.get("AI_API_KEY", os.environ.get("DS_KEY", ""))  # 优先用 AI_API_KEY，兼容旧 DS_KEY
AI_MODEL = os.environ.get("AI_MODEL", "deepseek-chat")
CROSSREF = "https://api.crossref.org/works"

# ─── MCP Server ───

mcp = FastMCP("scholar-local")


@mcp.tool()
def paper_download(doi: str, output_dir: str = ".") -> str:
    """通过 DOI 下载一篇论文 PDF（本地多源下载：Unpaywall → arXiv → Sci-Hub）。

    Args:
        doi: 论文的 DOI，例如 "10.1109/tim.2021.3106677"
        output_dir: 保存 PDF 的目录路径，默认为当前目录

    Returns:
        下载结果的 JSON 字符串，包含 success, doi, path, size_mb, source 等字段
    """
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
    result = batch_download(dois, output_dir)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def paper_search(query: str, rows: int = 8) -> str:
    """搜索论文 (Crossref + Semantic Scholar 双源合并去重)。

    支持关键词搜索或直接输入 DOI 查询详情。

    Args:
        query: 搜索关键词或 DOI，例如 "gradient magnetic field coil" 或 "10.1109/tim.2021.3106677"
        rows: 返回结果数量，默认 8

    Returns:
        搜索结果 JSON，包含 title, authors, journal, year, doi, cited_by, abstract 等
    """
    result = search_papers(query, rows)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def paper_ai_analyze(doi: str) -> str:
    """使用 AI 分析论文，返回核心贡献、研究方法、关键发现等。

    支持任意 OpenAI 兼容 API（通过 AI_API_BASE / AI_API_KEY / AI_MODEL 环境变量配置）。

    Args:
        doi: 论文的 DOI，例如 "10.1109/tim.2021.3106677"

    Returns:
        AI 分析结果 JSON
    """
    if not AI_API_KEY:
        return json.dumps({"success": False, "error": "AI_API_KEY (or DS_KEY) not set, AI analysis unavailable"})

    try:
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
        abstract = (
            (item.get("abstract") or "")
            .replace("<jats:p>", "")
            .replace("</jats:p>", "")
            .strip()
        )

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

        # 兼容任意 OpenAI 格式 API
        api_url = f"{AI_API_BASE.rstrip('/')}/chat/completions"
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
                "max_tokens": 800,
            },
            timeout=60,
        )
        analysis = ar.json()["choices"][0]["message"]["content"]

        return json.dumps({
            "success": True,
            "doi": doi,
            "title": title,
            "authors": authors,
            "journal": f"{journal} ({year})",
            "model": AI_MODEL,
            "analysis": analysis,
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


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
    result = get_citation_graph(doi, depth, max_per_level)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def paper_health() -> str:
    """检查论文下载服务各数据源的可用性（Unpaywall、arXiv、Sci-Hub 镜像）。

    Returns:
        各数据源健康状态的 JSON 字符串
    """
    result = health_check()
    return json.dumps(result, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
