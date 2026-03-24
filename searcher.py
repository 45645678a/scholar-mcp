"""论文搜索引擎 — Crossref + Semantic Scholar 双源搜索、去重合并"""

import requests


CROSSREF = "https://api.crossref.org/works"
S2_API = "https://api.semanticscholar.org/graph/v1/paper"


def _parse_crossref_item(item: dict) -> dict:
    """将 Crossref 单条结果解析为统一格式"""
    title = (item.get("title") or ["Untitled"])[0]
    authors = ", ".join(
        f"{a.get('given', '')} {a.get('family', '')}"
        for a in (item.get("author") or [])
    )
    journal = (item.get("container-title") or [""])[0]
    year = ""
    if item.get("published") and item["published"].get("date-parts"):
        year = str(item["published"]["date-parts"][0][0])
    doi = item.get("DOI", "")
    cited = item.get("is-referenced-by-count", 0)
    abstract = (
        (item.get("abstract") or "")
        .replace("<jats:p>", "")
        .replace("</jats:p>", "")
        .replace("<jats:title>", "")
        .replace("</jats:title>", "")
        .strip()
    )
    return {
        "title": title,
        "authors": authors,
        "journal": journal,
        "year": year,
        "doi": doi,
        "cited_by": cited,
        "abstract": abstract[:500] if abstract else "",
        "source": "crossref",
    }


def _search_crossref(query: str, rows: int = 8) -> list[dict]:
    """搜索 Crossref"""
    is_doi = query.strip().startswith("10.")
    if is_doi:
        params = f"/{requests.utils.quote(query.strip())}"
    else:
        params = f"?query={requests.utils.quote(query)}&rows={rows}&sort=relevance"

    r = requests.get(f"{CROSSREF}{params}", timeout=15)
    data = r.json()
    items = [data["message"]] if is_doi else (data.get("message", {}).get("items") or [])
    return [_parse_crossref_item(item) for item in items]


def _search_s2(query: str, rows: int = 8) -> list[dict]:
    """搜索 Semantic Scholar"""
    fields = "title,authors,year,venue,externalIds,citationCount,abstract"
    r = requests.get(
        f"{S2_API}/search",
        params={"query": query, "limit": rows, "fields": fields},
        timeout=15,
    )
    data = r.json()
    results = []
    for item in data.get("data") or []:
        authors = ", ".join(a.get("name", "") for a in (item.get("authors") or []))
        doi = (item.get("externalIds") or {}).get("DOI", "")
        results.append({
            "title": item.get("title", "Untitled"),
            "authors": authors,
            "journal": item.get("venue", ""),
            "year": str(item.get("year", "")),
            "doi": doi,
            "cited_by": item.get("citationCount", 0),
            "abstract": (item.get("abstract") or "")[:500],
            "source": "semantic_scholar",
        })
    return results


def _merge_results(crossref: list[dict], s2: list[dict], limit: int) -> list[dict]:
    """合并两个来源，按 DOI 去重"""
    by_doi = {}
    for r in crossref:
        key = r.get("doi") or r["title"]
        by_doi[key] = r

    for r in s2:
        key = r.get("doi") or r["title"]
        if key in by_doi:
            existing = by_doi[key]
            if not existing.get("abstract") and r.get("abstract"):
                existing["abstract"] = r["abstract"]
            if not existing.get("authors") and r.get("authors"):
                existing["authors"] = r["authors"]
        else:
            by_doi[key] = r

    merged = list(by_doi.values())[:limit]
    for i, r in enumerate(merged):
        r["index"] = i + 1
    return merged


def search_papers(query: str, rows: int = 8) -> dict:
    """搜索论文主入口"""
    is_doi = query.strip().startswith("10.")
    cr_results = []
    s2_results = []

    try:
        cr_results = _search_crossref(query, rows)
    except Exception:
        pass

    if not is_doi:
        try:
            s2_results = _search_s2(query, rows)
        except Exception:
            pass

    if cr_results or s2_results:
        results = _merge_results(cr_results, s2_results, rows)
        return {"success": True, "count": len(results), "results": results}
    else:
        return {"success": False, "error": "both Crossref and Semantic Scholar failed"}
