"""论文引用图谱 — 基于 Semantic Scholar API

获取论文的引用和参考文献关系，生成 Mermaid 图谱可视化 + 结构化数据。
"""

import requests

S2_API = "https://api.semanticscholar.org/graph/v1/paper"


def _s2_id(doi: str) -> str:
    """构造 Semantic Scholar Paper ID"""
    if doi.startswith("10."):
        return f"DOI:{doi}"
    elif doi.startswith("arXiv:") or doi.startswith("arxiv:"):
        return f"ARXIV:{doi.split(':')[1]}"
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
    """清理文本使其在 Mermaid 中安全显示"""
    # 移除特殊字符
    for ch in ['"', "'", "(", ")", "[", "]", "{", "}", "|", "<", ">", "#", "&", ";"]:
        text = text.replace(ch, "")
    return text.strip()


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
    ref_fields = "title,authors,year,citationCount,externalIds"

    # 获取中心论文信息
    try:
        r = requests.get(
            f"{S2_API}/{paper_id}",
            params={"fields": fields},
            timeout=15,
        )
        if r.status_code != 200:
            return {"success": False, "error": f"paper not found: {doi} (HTTP {r.status_code})"}
        center = r.json()
    except Exception as e:
        return {"success": False, "error": f"API error: {str(e)}"}

    center_title = center.get("title", "Unknown")
    center_year = center.get("year", "")
    center_cited = center.get("citationCount", 0)
    center_doi = (center.get("externalIds") or {}).get("DOI", doi)

    nodes = [{
        "id": "center",
        "title": center_title,
        "year": center_year,
        "cited_by": center_cited,
        "doi": center_doi,
        "type": "center",
    }]
    edges = []

    # 获取参考文献 (references = 这篇论文引用了哪些)
    try:
        r = requests.get(
            f"{S2_API}/{paper_id}/references",
            params={"fields": ref_fields, "limit": max_per_level},
            timeout=15,
        )
        if r.status_code == 200:
            for i, item in enumerate(r.json().get("data") or []):
                cited_paper = item.get("citedPaper", {})
                if not cited_paper or not cited_paper.get("title"):
                    continue
                node_id = f"ref_{i}"
                ref_doi = (cited_paper.get("externalIds") or {}).get("DOI", "")
                nodes.append({
                    "id": node_id,
                    "title": cited_paper.get("title", "Unknown"),
                    "year": cited_paper.get("year", ""),
                    "cited_by": cited_paper.get("citationCount", 0),
                    "doi": ref_doi,
                    "type": "reference",
                })
                edges.append({"from": "center", "to": node_id, "type": "references"})
    except Exception:
        pass

    # 获取引用 (citations = 哪些论文引用了本文)
    try:
        r = requests.get(
            f"{S2_API}/{paper_id}/citations",
            params={"fields": ref_fields, "limit": max_per_level},
            timeout=15,
        )
        if r.status_code == 200:
            for i, item in enumerate(r.json().get("data") or []):
                citing_paper = item.get("citingPaper", {})
                if not citing_paper or not citing_paper.get("title"):
                    continue
                node_id = f"cit_{i}"
                cit_doi = (citing_paper.get("externalIds") or {}).get("DOI", "")
                nodes.append({
                    "id": node_id,
                    "title": citing_paper.get("title", "Unknown"),
                    "year": citing_paper.get("year", ""),
                    "cited_by": citing_paper.get("citationCount", 0),
                    "doi": cit_doi,
                    "type": "citation",
                })
                edges.append({"from": node_id, "to": "center", "type": "cites"})
    except Exception:
        pass

    # 深度 2：获取引用的引用（仅获取引用链，不递归全图）
    if depth >= 2:
        # 获取高被引引用论文的引用
        top_citations = [n for n in nodes if n["type"] == "citation"]
        top_citations.sort(key=lambda x: x.get("cited_by", 0), reverse=True)
        for node in top_citations[:3]:  # 最多扩展 3 个高被引节点
            if not node.get("doi"):
                continue
            try:
                pid = _s2_id(node["doi"])
                r = requests.get(
                    f"{S2_API}/{pid}/citations",
                    params={"fields": ref_fields, "limit": 5},
                    timeout=10,
                )
                if r.status_code == 200:
                    for j, item in enumerate(r.json().get("data") or []):
                        citing = item.get("citingPaper", {})
                        if not citing or not citing.get("title"):
                            continue
                        node_id = f"{node['id']}_cit_{j}"
                        cit_doi = (citing.get("externalIds") or {}).get("DOI", "")
                        nodes.append({
                            "id": node_id,
                            "title": citing.get("title", "Unknown"),
                            "year": citing.get("year", ""),
                            "cited_by": citing.get("citationCount", 0),
                            "doi": cit_doi,
                            "type": "citation_l2",
                        })
                        edges.append({"from": node_id, "to": node["id"], "type": "cites"})
            except Exception:
                continue

    # 生成 Mermaid 图谱
    mermaid = _generate_mermaid(nodes, edges, center_title)

    # 统计
    ref_count = sum(1 for n in nodes if n["type"] == "reference")
    cit_count = sum(1 for n in nodes if n["type"] in ("citation", "citation_l2"))

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

        if node["type"] == "center":
            lines.append(f'    {node["id"]}["{label}"]')
        elif node["type"] == "reference":
            lines.append(f'    {node["id"]}["{label}"]')
        else:
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
