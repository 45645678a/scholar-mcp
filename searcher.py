"""论文搜索引擎 v3 — 9 源并发搜索

数据源：Semantic Scholar / OpenAlex / Crossref / PubMed / arXiv / CORE / Europe PMC / DOAJ / dblp
所有 API 均免费，无需 API Key 即可使用。
"""

import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─── 统一 Paper 格式 ───

def _paper(title="", authors="", journal="", year="", doi="",
           cited_by=0, abstract="", open_access_url="", source=""):
    return {
        "title": title, "authors": authors, "journal": journal,
        "year": str(year) if year else "", "doi": doi,
        "cited_by": cited_by or 0,
        "abstract": (abstract or "")[:500],
        "open_access_url": open_access_url or "",
        "source": source,
    }


# ═══════════════════════════════════════════════════
# Connector 1: Semantic Scholar (主搜索源)
# ═══════════════════════════════════════════════════

def _search_s2(query: str, rows: int = 10) -> list[dict]:
    fields = "title,authors,year,venue,externalIds,citationCount,abstract,openAccessPdf"
    r = requests.get(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={"query": query, "limit": rows, "fields": fields},
        timeout=15,
    )
    return [
        _paper(
            title=item.get("title", ""),
            authors=", ".join(a.get("name", "") for a in (item.get("authors") or [])),
            journal=item.get("venue", ""),
            year=item.get("year", ""),
            doi=(item.get("externalIds") or {}).get("DOI", ""),
            cited_by=item.get("citationCount", 0),
            abstract=item.get("abstract", ""),
            open_access_url=(item.get("openAccessPdf") or {}).get("url", ""),
            source="semantic_scholar",
        )
        for item in (r.json().get("data") or [])
    ]


# ═══════════════════════════════════════════════════
# Connector 2: OpenAlex
# ═══════════════════════════════════════════════════

def _reconstruct_abstract(inv_idx: dict | None) -> str:
    if not inv_idx:
        return ""
    pairs = []
    for word, positions in inv_idx.items():
        for pos in positions:
            pairs.append((pos, word))
    pairs.sort()
    return " ".join(w for _, w in pairs)


def _search_openalex(query: str, rows: int = 10) -> list[dict]:
    r = requests.get(
        "https://api.openalex.org/works",
        params={
            "search": query, "per_page": rows,
            "select": "doi,title,authorships,publication_year,cited_by_count,primary_location,open_access,abstract_inverted_index",
        },
        headers={"User-Agent": "scholar-mcp/1.0 (mailto:scholar-mcp@example.com)"},
        timeout=15,
    )
    results = []
    for item in r.json().get("results") or []:
        doi_raw = item.get("doi") or ""
        doi = doi_raw.replace("https://doi.org/", "") if doi_raw else ""
        loc = (item.get("primary_location") or {}).get("source") or {}
        oa = item.get("open_access") or {}
        results.append(_paper(
            title=item.get("title", ""),
            authors=", ".join((a.get("author") or {}).get("display_name", "") for a in (item.get("authorships") or [])),
            journal=loc.get("display_name", ""),
            year=item.get("publication_year", ""),
            doi=doi,
            cited_by=item.get("cited_by_count", 0),
            abstract=_reconstruct_abstract(item.get("abstract_inverted_index")),
            open_access_url=oa.get("oa_url", ""),
            source="openalex",
        ))
    return results


# ═══════════════════════════════════════════════════
# Connector 3: Crossref
# ═══════════════════════════════════════════════════

def _search_crossref(query: str, rows: int = 8) -> list[dict]:
    is_doi = query.strip().startswith("10.")
    if is_doi:
        url = f"https://api.crossref.org/works/{requests.utils.quote(query.strip())}"
    else:
        url = f"https://api.crossref.org/works?query={requests.utils.quote(query)}&rows={rows}&sort=relevance"

    r = requests.get(url, timeout=15)
    data = r.json()
    items = [data["message"]] if is_doi else (data.get("message", {}).get("items") or [])

    results = []
    for item in items:
        year = ""
        if item.get("published") and item["published"].get("date-parts"):
            year = item["published"]["date-parts"][0][0]
        abstract = (item.get("abstract") or "").replace("<jats:p>", "").replace("</jats:p>", "").replace("<jats:title>", "").replace("</jats:title>", "").strip()
        results.append(_paper(
            title=(item.get("title") or [""])[0],
            authors=", ".join(f"{a.get('given', '')} {a.get('family', '')}" for a in (item.get("author") or [])),
            journal=(item.get("container-title") or [""])[0],
            year=year, doi=item.get("DOI", ""),
            cited_by=item.get("is-referenced-by-count", 0),
            abstract=abstract, source="crossref",
        ))
    return results


# ═══════════════════════════════════════════════════
# Connector 4: PubMed (NCBI E-utilities)
# ═══════════════════════════════════════════════════

def _search_pubmed(query: str, rows: int = 8) -> list[dict]:
    # Step 1: Search for PMIDs
    sr = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params={"db": "pubmed", "term": query, "retmax": rows, "retmode": "json"},
        timeout=15,
    )
    ids = sr.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    # Step 2: Fetch summaries
    fr = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
        timeout=15,
    )
    result_data = fr.json().get("result", {})

    results = []
    for pmid in ids:
        item = result_data.get(pmid)
        if not item or not isinstance(item, dict):
            continue
        authors = ", ".join(a.get("name", "") for a in (item.get("authors") or []))
        # Extract DOI from articleids
        doi = ""
        for aid in (item.get("articleids") or []):
            if aid.get("idtype") == "doi":
                doi = aid.get("value", "")
                break
        results.append(_paper(
            title=item.get("title", ""),
            authors=authors,
            journal=item.get("fulljournalname", "") or item.get("source", ""),
            year=item.get("pubdate", "")[:4],
            doi=doi,
            source="pubmed",
        ))
    return results


# ═══════════════════════════════════════════════════
# Connector 5: arXiv API
# ═══════════════════════════════════════════════════

def _search_arxiv(query: str, rows: int = 8) -> list[dict]:
    import xml.etree.ElementTree as ET
    r = requests.get(
        "http://export.arxiv.org/api/query",
        params={"search_query": f"all:{query}", "max_results": rows, "sortBy": "relevance"},
        timeout=15,
    )
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(r.text)
    results = []
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", "", ns) or "").replace("\n", " ").strip()
        authors = ", ".join(a.findtext("atom:name", "", ns) for a in entry.findall("atom:author", ns))
        abstract = (entry.findtext("atom:summary", "", ns) or "").replace("\n", " ").strip()
        published = entry.findtext("atom:published", "", ns)[:4]
        # Extract arXiv ID and DOI
        arxiv_id = ""
        doi = ""
        pdf_url = ""
        for link in entry.findall("atom:link", ns):
            href = link.get("href", "")
            if link.get("title") == "pdf":
                pdf_url = href
            if "abs/" in href:
                arxiv_id = href.split("abs/")[-1]
        id_text = entry.findtext("atom:id", "", ns)
        if id_text and "abs/" in id_text:
            arxiv_id = id_text.split("abs/")[-1]
        # arXiv DOI format
        if arxiv_id:
            doi = f"10.48550/arXiv.{arxiv_id}"

        results.append(_paper(
            title=title, authors=authors, journal="arXiv",
            year=published, doi=doi, abstract=abstract,
            open_access_url=pdf_url, source="arxiv",
        ))
    return results


# ═══════════════════════════════════════════════════
# Connector 6: CORE (全球最大 OA 论文聚合)
# ═══════════════════════════════════════════════════

def _search_core(query: str, rows: int = 8) -> list[dict]:
    r = requests.get(
        "https://api.core.ac.uk/v3/search/works",
        params={"q": query, "limit": rows},
        headers={"User-Agent": "scholar-mcp/1.0"},
        timeout=15,
    )
    results = []
    for item in r.json().get("results") or []:
        try:
            # Authors: can be list[str], list[dict], or str
            authors_raw = item.get("authors") or []
            if isinstance(authors_raw, list):
                parts = []
                for a in authors_raw:
                    if isinstance(a, dict):
                        parts.append(a.get("name", ""))
                    elif isinstance(a, str):
                        parts.append(a)
                authors = ", ".join(parts)
            else:
                authors = str(authors_raw)

            # DOI
            doi_raw = item.get("doi") or ""
            if isinstance(doi_raw, list):
                doi_raw = doi_raw[0] if doi_raw else ""
            doi = str(doi_raw).replace("https://doi.org/", "")

            # Journal
            journals = item.get("journals") or []
            if isinstance(journals, list):
                journal = journals[0].get("title", "") if journals and isinstance(journals[0], dict) else str(journals[0]) if journals else ""
            else:
                journal = str(journals)

            # OA URL
            oa_url = item.get("downloadUrl", "") or ""
            if not oa_url:
                src_urls = item.get("sourceFulltextUrls") or []
                oa_url = src_urls[0] if src_urls else ""

            results.append(_paper(
                title=item.get("title", ""),
                authors=authors, journal=journal,
                year=item.get("yearPublished", ""),
                doi=doi, abstract=item.get("abstract", ""),
                open_access_url=oa_url, source="core",
            ))
        except Exception:
            continue
    return results


# ═══════════════════════════════════════════════════
# Connector 7: Europe PMC
# ═══════════════════════════════════════════════════

def _search_europe_pmc(query: str, rows: int = 8) -> list[dict]:
    r = requests.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": query, "format": "json", "pageSize": rows, "resultType": "core"},
        timeout=15,
    )
    results = []
    for item in r.json().get("resultList", {}).get("result", []):
        results.append(_paper(
            title=item.get("title", ""),
            authors=item.get("authorString", ""),
            journal=item.get("journalTitle", ""),
            year=item.get("pubYear", ""),
            doi=item.get("doi", ""),
            cited_by=item.get("citedByCount", 0),
            abstract=item.get("abstractText", ""),
            open_access_url=item.get("fullTextUrlList", {}).get("fullTextUrl", [{}])[0].get("url", "") if item.get("fullTextUrlList") else "",
            source="europe_pmc",
        ))
    return results


# ═══════════════════════════════════════════════════
# Connector 8: DOAJ (OA 期刊目录)
# ═══════════════════════════════════════════════════

def _search_doaj(query: str, rows: int = 8) -> list[dict]:
    r = requests.get(
        "https://doaj.org/api/search/articles/" + requests.utils.quote(query),
        params={"pageSize": rows},
        timeout=15,
    )
    results = []
    for item in r.json().get("results") or []:
        bib = item.get("bibjson", {})
        authors = ", ".join(a.get("name", "") for a in (bib.get("author") or []))
        journal = bib.get("journal", {}).get("title", "")
        doi = ""
        for ident in (bib.get("identifier") or []):
            if ident.get("type") == "doi":
                doi = ident.get("id", "")
                break
        oa_url = ""
        for link in (bib.get("link") or []):
            if link.get("type") == "fulltext":
                oa_url = link.get("url", "")
                break
        results.append(_paper(
            title=bib.get("title", ""),
            authors=authors, journal=journal,
            year=bib.get("year", ""),
            doi=doi, abstract=bib.get("abstract", ""),
            open_access_url=oa_url, source="doaj",
        ))
    return results


# ═══════════════════════════════════════════════════
# Connector 9: dblp (计算机科学)
# ═══════════════════════════════════════════════════

def _search_dblp(query: str, rows: int = 8) -> list[dict]:
    r = requests.get(
        "https://dblp.org/search/publ/api",
        params={"q": query, "h": rows, "format": "json"},
        timeout=15,
    )
    results = []
    for item in (r.json().get("result", {}).get("hits", {}).get("hit") or []):
        info = item.get("info", {})
        authors_raw = info.get("authors", {}).get("author", [])
        if isinstance(authors_raw, dict):
            authors_raw = [authors_raw]
        authors = ", ".join(a.get("text", "") if isinstance(a, dict) else str(a) for a in authors_raw)
        doi = info.get("doi", "")
        if doi and not doi.startswith("10."):
            doi = ""
        results.append(_paper(
            title=info.get("title", ""),
            authors=authors,
            journal=info.get("venue", ""),
            year=info.get("year", ""),
            doi=doi, source="dblp",
        ))
    return results


# ═══════════════════════════════════════════════════
# 搜索引擎：并发 + 去重 + 排序
# ═══════════════════════════════════════════════════

ALL_CONNECTORS = {
    "semantic_scholar": _search_s2,
    "openalex": _search_openalex,
    "crossref": _search_crossref,
    "pubmed": _search_pubmed,
    "arxiv": _search_arxiv,
    "core": _search_core,
    "europe_pmc": _search_europe_pmc,
    "doaj": _search_doaj,
    "dblp": _search_dblp,
}


def _merge_results(all_sources: list[list[dict]], limit: int) -> list[dict]:
    by_key = {}
    for source_results in all_sources:
        for r in source_results:
            key = r.get("doi") or r["title"].lower().strip()[:80]
            if not key:
                continue
            if key in by_key:
                existing = by_key[key]
                if not existing.get("abstract") and r.get("abstract"):
                    existing["abstract"] = r["abstract"]
                if not existing.get("authors") and r.get("authors"):
                    existing["authors"] = r["authors"]
                if not existing.get("open_access_url") and r.get("open_access_url"):
                    existing["open_access_url"] = r["open_access_url"]
                existing["cited_by"] = max(existing.get("cited_by", 0), r.get("cited_by", 0))
            else:
                by_key[key] = r

    merged = sorted(
        by_key.values(),
        key=lambda x: (x.get("cited_by", 0), int(x.get("year") or "0")),
        reverse=True,
    )[:limit]

    for i, r in enumerate(merged):
        r["index"] = i + 1
    return merged


def search_papers(query: str, rows: int = 8) -> dict:
    """搜索论文 — 9 源并发搜索 + 去重 + 按引用数排序"""
    is_doi = query.strip().startswith("10.")

    # DOI 精确查询只走 Crossref
    if is_doi:
        try:
            cr = _search_crossref(query, 1)
            if cr:
                cr[0]["index"] = 1
                return {"success": True, "count": 1, "results": cr}
        except Exception:
            pass
        return {"success": False, "error": f"DOI not found: {query}"}

    # 关键词搜索：9 源并发
    all_results = []
    sources_ok = []
    sources_fail = []
    fetch_rows = min(rows * 2, 20)

    with ThreadPoolExecutor(max_workers=9) as executor:
        futures = {
            executor.submit(fn, query, fetch_rows): name
            for name, fn in ALL_CONNECTORS.items()
        }
        for future in as_completed(futures, timeout=25):
            name = futures[future]
            try:
                result = future.result()
                if result:
                    all_results.append(result)
                    sources_ok.append(name)
            except Exception as e:
                sources_fail.append(f"{name}: {str(e)[:40]}")

    if all_results:
        merged = _merge_results(all_results, rows)
        return {
            "success": True,
            "count": len(merged),
            "sources_ok": sources_ok,
            "sources_fail": sources_fail,
            "results": merged,
        }
    else:
        return {"success": False, "error": f"all {len(ALL_CONNECTORS)} sources failed"}
