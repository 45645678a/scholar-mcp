"""论文搜索引擎 v2 — Semantic Scholar (主) + OpenAlex + Crossref 三源搜索

改进：
- Semantic Scholar 作为主搜索源（相关性更好，有 abstract）
- OpenAlex 作为补充（全球最大免费学术元数据库）
- Crossref 作为 DOI 精确查询源
- 按引用数 + 年份智能排序
- open_access_url 字段
"""

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

CROSSREF = "https://api.crossref.org/works"
S2_API = "https://api.semanticscholar.org/graph/v1/paper"
OPENALEX_API = "https://api.openalex.org/works"


# ─── Crossref ───

def _parse_crossref_item(item: dict) -> dict:
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
        .replace("<jats:p>", "").replace("</jats:p>", "")
        .replace("<jats:title>", "").replace("</jats:title>", "")
        .strip()
    )
    return {
        "title": title, "authors": authors, "journal": journal,
        "year": year, "doi": doi, "cited_by": cited,
        "abstract": abstract[:500] if abstract else "",
        "open_access_url": "",
        "source": "crossref",
    }


def _search_crossref(query: str, rows: int = 8) -> list[dict]:
    is_doi = query.strip().startswith("10.")
    if is_doi:
        url = f"{CROSSREF}/{requests.utils.quote(query.strip())}"
    else:
        url = f"{CROSSREF}?query={requests.utils.quote(query)}&rows={rows}&sort=relevance"

    r = requests.get(url, timeout=15)
    data = r.json()
    items = [data["message"]] if is_doi else (data.get("message", {}).get("items") or [])
    return [_parse_crossref_item(item) for item in items]


# ─── Semantic Scholar ───

def _search_s2(query: str, rows: int = 10) -> list[dict]:
    fields = "title,authors,year,venue,externalIds,citationCount,abstract,isOpenAccess,openAccessPdf"
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
        oa_pdf = (item.get("openAccessPdf") or {}).get("url", "")
        results.append({
            "title": item.get("title", "Untitled"),
            "authors": authors,
            "journal": item.get("venue", ""),
            "year": str(item.get("year", "")),
            "doi": doi,
            "cited_by": item.get("citationCount", 0) or 0,
            "abstract": (item.get("abstract") or "")[:500],
            "open_access_url": oa_pdf,
            "source": "semantic_scholar",
        })
    return results


# ─── OpenAlex ───

def _search_openalex(query: str, rows: int = 10) -> list[dict]:
    r = requests.get(
        OPENALEX_API,
        params={
            "search": query,
            "per_page": rows,
            "select": "id,doi,title,authorships,publication_year,cited_by_count,primary_location,open_access,abstract_inverted_index",
        },
        headers={"User-Agent": "scholar-mcp/1.0 (mailto:scholar-mcp@example.com)"},
        timeout=15,
    )
    data = r.json()
    results = []
    for item in data.get("results") or []:
        # 恢复 abstract (OpenAlex 用倒排索引存储)
        abstract = _reconstruct_abstract(item.get("abstract_inverted_index"))

        authors = ", ".join(
            (a.get("author") or {}).get("display_name", "")
            for a in (item.get("authorships") or [])
        )
        doi_raw = item.get("doi") or ""
        doi = doi_raw.replace("https://doi.org/", "") if doi_raw else ""
        journal = ""
        loc = item.get("primary_location") or {}
        src = loc.get("source") or {}
        journal = src.get("display_name", "")

        oa = item.get("open_access") or {}
        oa_url = oa.get("oa_url", "") or ""

        results.append({
            "title": item.get("title", "Untitled") or "Untitled",
            "authors": authors,
            "journal": journal,
            "year": str(item.get("publication_year", "")),
            "doi": doi,
            "cited_by": item.get("cited_by_count", 0) or 0,
            "abstract": abstract[:500] if abstract else "",
            "open_access_url": oa_url,
            "source": "openalex",
        })
    return results


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """从 OpenAlex 倒排索引恢复 abstract 文本"""
    if not inverted_index:
        return ""
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)


# ─── 合并 & 排序 ───

def _merge_results(all_sources: list[list[dict]], limit: int) -> list[dict]:
    """合并多源结果，按 DOI 去重，按引用数排序"""
    by_key = {}

    for source_results in all_sources:
        for r in source_results:
            key = r.get("doi") or r["title"].lower().strip()
            if key in by_key:
                existing = by_key[key]
                # 合并缺失字段
                if not existing.get("abstract") and r.get("abstract"):
                    existing["abstract"] = r["abstract"]
                if not existing.get("authors") and r.get("authors"):
                    existing["authors"] = r["authors"]
                if not existing.get("open_access_url") and r.get("open_access_url"):
                    existing["open_access_url"] = r["open_access_url"]
                # 取较高引用数
                existing["cited_by"] = max(existing.get("cited_by", 0), r.get("cited_by", 0))
            else:
                by_key[key] = r

    # 按引用数降序 → 年份降序排序
    merged = sorted(
        by_key.values(),
        key=lambda x: (x.get("cited_by", 0), int(x.get("year") or "0")),
        reverse=True,
    )[:limit]

    for i, r in enumerate(merged):
        r["index"] = i + 1
    return merged


# ─── 主入口 ───

def search_papers(query: str, rows: int = 8) -> dict:
    """搜索论文主入口 — 三源并发搜索 + 去重 + 排序"""
    is_doi = query.strip().startswith("10.")

    # DOI 精确查询只走 Crossref
    if is_doi:
        try:
            cr_results = _search_crossref(query, 1)
            if cr_results:
                cr_results[0]["index"] = 1
                return {"success": True, "count": 1, "results": cr_results}
        except Exception:
            pass
        return {"success": False, "error": f"DOI not found: {query}"}

    # 关键词搜索：三源并发
    all_results = []
    errors = []
    fetch_rows = min(rows * 2, 20)  # 多取一些用于去重后仍有足够结果

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_search_s2, query, fetch_rows): "semantic_scholar",
            executor.submit(_search_openalex, query, fetch_rows): "openalex",
            executor.submit(_search_crossref, query, fetch_rows): "crossref",
        }
        for future in as_completed(futures, timeout=20):
            source = futures[future]
            try:
                result = future.result()
                all_results.append(result)
            except Exception as e:
                errors.append(f"{source}: {str(e)[:60]}")

    if all_results:
        merged = _merge_results(all_results, rows)
        return {
            "success": True,
            "count": len(merged),
            "sources_used": [s for s, f in futures.items()
                           if f not in [e.split(":")[0] for e in errors]],
            "results": merged,
        }
    else:
        return {"success": False, "error": f"all sources failed: {'; '.join(errors)}"}
