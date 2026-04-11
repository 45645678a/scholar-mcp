"""异步搜索引擎 — 使用 aiohttp 并发请求 9 个数据源

相比线程池方案：更少的资源开销，更好的超时控制，更快的并发。
提供 async_search_papers() 异步接口，以及 search_papers_fast() 同步包装。
"""

import asyncio
import re

import cache as _cache
from logger import get_logger
from searcher import (
    _paper,
    _merge_and_rank,
    _reconstruct_abstract,
)

log = get_logger("async_searcher")

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    log.debug("aiohttp not installed, async search unavailable")


async def _fetch_json(session: "aiohttp.ClientSession", url: str,
                      params: dict = None, headers: dict = None,
                      timeout: int = 15) -> dict | None:
    """异步 GET JSON"""
    try:
        async with session.get(url, params=params, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status == 200:
                return await resp.json(content_type=None)
    except Exception as e:
        log.debug("fetch failed %s: %s", url[:60], e)
    return None


# ═══════════════════════════════════════════════════
# 异步 Connectors
# ═══════════════════════════════════════════════════

async def _async_search_s2(session, query: str, rows: int) -> list[dict]:
    fields = "title,authors,year,venue,externalIds,citationCount,abstract,openAccessPdf"
    data = await _fetch_json(
        session,
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={"query": query, "limit": rows, "fields": fields},
    )
    if not data:
        return []
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
        for item in (data.get("data") or [])
    ]


async def _async_search_openalex(session, query: str, rows: int) -> list[dict]:
    data = await _fetch_json(
        session,
        "https://api.openalex.org/works",
        params={
            "search": query, "per_page": rows,
            "select": "doi,title,authorships,publication_year,cited_by_count,primary_location,open_access,abstract_inverted_index",
        },
        headers={"User-Agent": "scholar-mcp/1.0 (mailto:scholar-mcp@example.com)"},
    )
    if not data:
        return []
    results = []
    for item in data.get("results") or []:
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


async def _async_search_crossref(session, query: str, rows: int) -> list[dict]:
    url = f"https://api.crossref.org/works?query={query}&rows={rows}&sort=relevance"
    data = await _fetch_json(session, url)
    if not data:
        return []
    results = []
    for item in data.get("message", {}).get("items") or []:
        year = ""
        if item.get("published") and item["published"].get("date-parts"):
            year = item["published"]["date-parts"][0][0]
        abstract = re.sub(r'</?jats:[^>]+>', '', item.get("abstract") or "").strip()
        results.append(_paper(
            title=(item.get("title") or [""])[0],
            authors=", ".join(f"{a.get('given', '')} {a.get('family', '')}" for a in (item.get("author") or [])),
            journal=(item.get("container-title") or [""])[0],
            year=year, doi=item.get("DOI", ""),
            cited_by=item.get("is-referenced-by-count", 0),
            abstract=abstract, source="crossref",
        ))
    return results


async def _async_search_pubmed(session, query: str, rows: int) -> list[dict]:
    sr_data = await _fetch_json(
        session,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params={"db": "pubmed", "term": query, "retmax": rows, "retmode": "json"},
    )
    if not sr_data:
        return []
    ids = sr_data.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    fr_data = await _fetch_json(
        session,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
    )
    if not fr_data:
        return []

    result_data = fr_data.get("result", {})
    results = []
    for pmid in ids:
        item = result_data.get(pmid)
        if not item or not isinstance(item, dict):
            continue
        authors = ", ".join(a.get("name", "") for a in (item.get("authors") or []))
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
            doi=doi, source="pubmed",
        ))
    return results


async def _async_search_arxiv(session, query: str, rows: int) -> list[dict]:
    import xml.etree.ElementTree as ET
    try:
        async with session.get(
            "http://export.arxiv.org/api/query",
            params={"search_query": f"all:{query}", "max_results": rows, "sortBy": "relevance"},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                return []
            text = await resp.text()
    except Exception:
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(text)
    results = []
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", "", ns) or "").replace("\n", " ").strip()
        authors = ", ".join(a.findtext("atom:name", "", ns) for a in entry.findall("atom:author", ns))
        abstract = (entry.findtext("atom:summary", "", ns) or "").replace("\n", " ").strip()
        published = entry.findtext("atom:published", "", ns)[:4]
        arxiv_id = ""
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
        doi = f"10.48550/arXiv.{arxiv_id}" if arxiv_id else ""
        results.append(_paper(
            title=title, authors=authors, journal="arXiv",
            year=published, doi=doi, abstract=abstract,
            open_access_url=pdf_url, source="arxiv",
        ))
    return results


async def _async_search_europe_pmc(session, query: str, rows: int) -> list[dict]:
    data = await _fetch_json(
        session,
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": query, "format": "json", "pageSize": rows, "resultType": "core"},
    )
    if not data:
        return []
    results = []
    for item in data.get("resultList", {}).get("result", []):
        oa_url = ""
        ft_list = item.get("fullTextUrlList")
        if ft_list and isinstance(ft_list, dict):
            ft_urls = ft_list.get("fullTextUrl", [])
            if ft_urls and isinstance(ft_urls, list) and ft_urls[0]:
                oa_url = ft_urls[0].get("url", "")
        results.append(_paper(
            title=item.get("title", ""),
            authors=item.get("authorString", ""),
            journal=item.get("journalTitle", ""),
            year=item.get("pubYear", ""),
            doi=item.get("doi", ""),
            cited_by=item.get("citedByCount", 0),
            abstract=item.get("abstractText", ""),
            open_access_url=oa_url, source="europe_pmc",
        ))
    return results


async def _async_search_doaj(session, query: str, rows: int) -> list[dict]:
    import urllib.parse
    data = await _fetch_json(
        session,
        f"https://doaj.org/api/search/articles/{urllib.parse.quote(query)}",
        params={"pageSize": rows},
    )
    if not data:
        return []
    results = []
    for item in data.get("results") or []:
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


async def _async_search_dblp(session, query: str, rows: int) -> list[dict]:
    data = await _fetch_json(
        session,
        "https://dblp.org/search/publ/api",
        params={"q": query, "h": rows, "format": "json"},
    )
    if not data:
        return []
    results = []
    for item in (data.get("result", {}).get("hits", {}).get("hit") or []):
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
            authors=authors, journal=info.get("venue", ""),
            year=info.get("year", ""), doi=doi, source="dblp",
        ))
    return results


async def _async_search_core(session, query: str, rows: int) -> list[dict]:
    data = await _fetch_json(
        session,
        "https://api.core.ac.uk/v3/search/works",
        params={"q": query, "limit": rows},
        headers={"User-Agent": "scholar-mcp/1.0"},
    )
    if not data:
        return []
    results = []
    for item in data.get("results") or []:
        try:
            authors_raw = item.get("authors") or []
            if isinstance(authors_raw, list):
                parts = [a.get("name", "") if isinstance(a, dict) else str(a) for a in authors_raw]
                authors = ", ".join(parts)
            else:
                authors = str(authors_raw)
            doi_raw = item.get("doi") or ""
            if isinstance(doi_raw, list):
                doi_raw = doi_raw[0] if doi_raw else ""
            doi = str(doi_raw).replace("https://doi.org/", "")
            journals = item.get("journals") or []
            if isinstance(journals, list):
                journal = journals[0].get("title", "") if journals and isinstance(journals[0], dict) else str(journals[0]) if journals else ""
            else:
                journal = str(journals)
            oa_url = item.get("downloadUrl", "") or ""
            if not oa_url:
                src_urls = item.get("sourceFulltextUrls") or []
                oa_url = src_urls[0] if src_urls else ""
            results.append(_paper(
                title=item.get("title", ""), authors=authors, journal=journal,
                year=item.get("yearPublished", ""), doi=doi,
                abstract=item.get("abstract", ""),
                open_access_url=oa_url, source="core",
            ))
        except Exception:
            continue
    return results


# 所有异步 connector
ASYNC_CONNECTORS = {
    "semantic_scholar": _async_search_s2,
    "openalex": _async_search_openalex,
    "crossref": _async_search_crossref,
    "pubmed": _async_search_pubmed,
    "arxiv": _async_search_arxiv,
    "core": _async_search_core,
    "europe_pmc": _async_search_europe_pmc,
    "doaj": _async_search_doaj,
    "dblp": _async_search_dblp,
}


async def async_search_papers(query: str, rows: int = 8) -> dict:
    """异步搜索论文 — 9 源并发"""
    # 检查缓存
    cached = _cache.get_search(query, rows)
    if cached:
        cached["from_cache"] = True
        return cached

    fetch_rows = min(rows * 2, 20)
    all_results = []
    sources_ok = []
    sources_fail = []

    async with aiohttp.ClientSession() as session:
        tasks = {
            name: asyncio.create_task(fn(session, query, fetch_rows))
            for name, fn in ASYNC_CONNECTORS.items()
        }

        # 等待所有任务，30 秒总超时
        done, pending = await asyncio.wait(
            tasks.values(), timeout=30, return_when=asyncio.ALL_COMPLETED
        )

        # 取消超时的任务
        for task in pending:
            task.cancel()

        # 收集结果
        for name, task in tasks.items():
            if task in done:
                try:
                    result = task.result()
                    if result:
                        all_results.append(result)
                        sources_ok.append(name)
                    else:
                        sources_fail.append(f"{name}: empty")
                except Exception as e:
                    sources_fail.append(f"{name}: {str(e)[:40]}")
            else:
                sources_fail.append(f"{name}: timeout")

    log.info("async search done: ok=%s fail=%s papers=%d",
             sources_ok, sources_fail, sum(len(r) for r in all_results))

    if all_results:
        merged = _merge_and_rank(all_results, query, rows)
        result = {
            "success": True,
            "count": len(merged),
            "sources_ok": sources_ok,
            "sources_fail": sources_fail,
            "results": merged,
        }
        _cache.set_search(query, rows, result)
        return result
    else:
        return {"success": False, "error": f"all {len(ASYNC_CONNECTORS)} sources failed", "sources_fail": sources_fail}


def search_papers_fast(query: str, rows: int = 8) -> dict:
    """异步搜索的同步包装 — 可替代 searcher.search_papers"""
    if not HAS_AIOHTTP:
        from searcher import search_papers
        return search_papers(query, rows)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # 已在事件循环中，退回同步版本
        from searcher import search_papers
        return search_papers(query, rows)

    return asyncio.run(async_search_papers(query, rows))
