"""论文引用图谱 — 基于 Semantic Scholar API

获取论文的引用和参考文献关系，生成 Mermaid 图谱可视化 + 结构化数据。
"""

import time
import requests

from logger import get_logger

log = get_logger("citation_graph")

S2_API = "https://api.semanticscholar.org/graph/v1/paper"

# Semantic Scholar 速率限制：100 requests/5min (free tier)
_MIN_REQUEST_INTERVAL = 0.3  # 秒


def _s2_id(doi: str) -> str:
    """构造 Semantic Scholar Paper ID"""
    doi = doi.strip()
    if doi.startswith("10."):
        return f"DOI:{doi}"
    elif doi.lower().startswith("arxiv:"):
        return f"ARXIV:{doi.split(':', 1)[1]}"
    elif doi.startswith("CorpusID:"):
        return doi
    else:
        # 尝试作为 DOI
        return f"DOI:{doi}" if "/" in doi else doi


def _short_title(title: str, max_len: int = 40) -> str:
    """截断标题用于图谱显示"""
    if len(title) <= max_len:
        return title
    return title[:max_len - 3] + "..."


def _sanitize_mermaid(text: str) -> str:
    """清理文本使其在 Mermaid 中安全显示（保留 + 号）"""
    for ch in ['"', "'", "(", ")", "[", "]", "{", "}", "|", "<", ">", "#", "&", ";", "`"]:
        text = text.replace(ch, "")
    return text.strip()


def _s2_get(url: str, params: dict, timeout: int = 15) -> dict | None:
    """带速率限制的 S2 API 请求"""
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code == 429:
            log.warning("S2 API rate limited, waiting 2s...")
            time.sleep(2)
            r = requests.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.debug("S2 API returned %d for %s", r.status_code, url)
        return None
    except Exception as e:
        log.debug("S2 API error: %s", e)
        return None


def get_citation_graph(doi: str, depth: int = 1, max_per_level: int = 10) -> dict:
    """获取论文引用图谱

    Args:
        doi: 论文 DOI 或标识符
        depth: 递归深度 (1=直接引用/参考, 2=二层引用)
        max_per_level: 每层最多获取的论文数

    Returns:
        包含 mermaid 图谱代码和结构化数据的字典
    """
    paper_id = _s2_id(doi)
    fields = "title,authors,year,citationCount,externalIds"

    # 获取中心论文信息
    center_data = _s2_get(f"{S2_API}/{paper_id}", {"fields": fields})
    if not center_data:
        return {"success": False, "error": f"paper not found: {doi}"}

    center_title = center_data.get("title", "Unknown")
    center_year = center_data.get("year", "")
    center_cited = center_data.get("citationCount", 0)
    center_doi = (center_data.get("externalIds") or {}).get("DOI", doi)

    nodes = [{
        "id": "center",
        "title": center_title,
        "year": center_year,
        "cited_by": center_cited,
        "doi": center_doi,
        "type": "center",
    }]
    edges = []

    # 用于循环检测的已见论文集合（DOI 或标题）
    seen_papers = {center_doi.lower() if center_doi else "", center_title.lower()}

    # 获取参考文献 (references = 这篇论文引用了哪些)
    ref_data = _s2_get(
        f"{S2_API}/{paper_id}/references",
        {"fields": fields, "limit": max_per_level},
    )
    if ref_data:
        for i, item in enumerate(ref_data.get("data") or []):
            cited_paper = item.get("citedPaper", {})
            if not cited_paper or not cited_paper.get("title"):
                continue

            ref_doi = (cited_paper.get("externalIds") or {}).get("DOI", "")
            title = cited_paper.get("title", "Unknown")

            # 循环检测
            paper_key = ref_doi.lower() if ref_doi else title.lower()
            if paper_key in seen_papers:
                continue
            seen_papers.add(paper_key)

            node_id = f"ref_{i}"
            nodes.append({
                "id": node_id,
                "title": title,
                "year": cited_paper.get("year", ""),
                "cited_by": cited_paper.get("citationCount", 0),
                "doi": ref_doi,
                "type": "reference",
            })
            edges.append({"from": "center", "to": node_id, "type": "references"})

    time.sleep(_MIN_REQUEST_INTERVAL)

    # 获取引用 (citations = 哪些论文引用了本文)
    cit_data = _s2_get(
        f"{S2_API}/{paper_id}/citations",
        {"fields": fields, "limit": max_per_level},
    )
    if cit_data:
        for i, item in enumerate(cit_data.get("data") or []):
            citing_paper = item.get("citingPaper", {})
            if not citing_paper or not citing_paper.get("title"):
                continue

            cit_doi = (citing_paper.get("externalIds") or {}).get("DOI", "")
            title = citing_paper.get("title", "Unknown")

            # 循环检测
            paper_key = cit_doi.lower() if cit_doi else title.lower()
            if paper_key in seen_papers:
                continue
            seen_papers.add(paper_key)

            node_id = f"cit_{i}"
            nodes.append({
                "id": node_id,
                "title": title,
                "year": citing_paper.get("year", ""),
                "cited_by": citing_paper.get("citationCount", 0),
                "doi": cit_doi,
                "type": "citation",
            })
            edges.append({"from": node_id, "to": "center", "type": "cites"})

    # 深度 2：获取引用的引用（仅获取引用链，不递归全图）
    if depth >= 2:
        top_citations = [n for n in nodes if n["type"] == "citation"]
        top_citations.sort(key=lambda x: x.get("cited_by", 0), reverse=True)
        for node in top_citations[:3]:  # 最多扩展 3 个高被引节点
            if not node.get("doi"):
                continue
            time.sleep(_MIN_REQUEST_INTERVAL)
            pid = _s2_id(node["doi"])
            l2_data = _s2_get(
                f"{S2_API}/{pid}/citations",
                {"fields": fields, "limit": 5},
            )
            if not l2_data:
                continue
            for j, item in enumerate(l2_data.get("data") or []):
                citing = item.get("citingPaper", {})
                if not citing or not citing.get("title"):
                    continue

                cit_doi = (citing.get("externalIds") or {}).get("DOI", "")
                title = citing.get("title", "Unknown")

                # 循环检测
                paper_key = cit_doi.lower() if cit_doi else title.lower()
                if paper_key in seen_papers:
                    continue
                seen_papers.add(paper_key)

                node_id = f"{node['id']}_cit_{j}"
                nodes.append({
                    "id": node_id,
                    "title": title,
                    "year": citing.get("year", ""),
                    "cited_by": citing.get("citationCount", 0),
                    "doi": cit_doi,
                    "type": "citation_l2",
                })
                edges.append({"from": node_id, "to": node["id"], "type": "cites"})

    # 生成 Mermaid 图谱
    mermaid = _generate_mermaid(nodes, edges, center_title)

    # 统计
    ref_count = sum(1 for n in nodes if n["type"] == "reference")
    cit_count = sum(1 for n in nodes if n["type"] in ("citation", "citation_l2"))

    log.info("citation graph: %d nodes, %d edges (refs=%d, cits=%d)", len(nodes), len(edges), ref_count, cit_count)

    return {
        "success": True,
        "center_paper": {
            "title": center_title,
            "doi": center_doi,
            "year": center_year,
            "cited_by": center_cited,
        },
        "statistics": {
            "references": ref_count,
            "citations": cit_count,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
        },
        "mermaid": mermaid,
        "nodes": nodes,
        "edges": edges,
    }


def _generate_mermaid(nodes: list[dict], edges: list[dict], center_title: str) -> str:
    """生成 Mermaid 图谱代码"""
    lines = ["graph LR"]

    # 样式定义
    lines.append("    classDef center fill:#e74c3c,stroke:#c0392b,color:#fff,font-weight:bold")
    lines.append("    classDef reference fill:#3498db,stroke:#2980b9,color:#fff")
    lines.append("    classDef citation fill:#2ecc71,stroke:#27ae60,color:#fff")
    lines.append("    classDef citation_l2 fill:#95a5a6,stroke:#7f8c8d,color:#fff")
    lines.append("")

    # 节点
    for node in nodes:
        title = _sanitize_mermaid(_short_title(node["title"]))
        year = f" {node['year']}" if node.get("year") else ""
        cited = f" c:{node['cited_by']}" if node.get("cited_by") else ""
        label = f"{title}{year}{cited}"
        lines.append(f'    {node["id"]}["{label}"]')

    lines.append("")

    # 边
    for edge in edges:
        if edge["type"] == "references":
            lines.append(f'    {edge["from"]} -->|references| {edge["to"]}')
        else:
            lines.append(f'    {edge["from"]} -->|cites| {edge["to"]}')

    lines.append("")

    # 应用样式
    for node in nodes:
        lines.append(f'    class {node["id"]} {node["type"]}')

    return "\n".join(lines)
