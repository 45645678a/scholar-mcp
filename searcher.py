"""论文搜索引擎 v3 — 9 源并发搜索

数据源：Semantic Scholar / OpenAlex / Crossref / PubMed / arXiv / CORE / Europe PMC / DOAJ / dblp
所有 API 均免费，无需 API Key 即可使用。
"""

import re
import math
import time
import datetime
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError

from logger import get_logger
import cache as _cache

log = get_logger("searcher")

# 预编译正则：标题规范化时保留 + 号（C++ 等）
_TITLE_NORM_RE = re.compile(r'[^\w\s+]')


def _retry_request(method, url, retries=2, backoff=1.0, **kwargs):
    """带指数退避重试的 HTTP 请求"""
    kwargs.setdefault("timeout", 15)
    for i in range(retries + 1):
        try:
            r = method(url, **kwargs)
            r.raise_for_status()
            return r
        except (requests.RequestException, Exception):
            if i >= retries:
                raise
            time.sleep(backoff * (2 ** i))

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
            if isinstance(pos, int):
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
        # 安全提取 OA URL
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
            open_access_url=oa_url,
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


def _normalize_title(title: str) -> str:
    """标题归一化：小写、去标点（保留 +）、去多余空格"""
    t = title.lower().strip()
    t = _TITLE_NORM_RE.sub(' ', t)
    return ' '.join(t.split())


def _jaccard_sim(a: str, b: str) -> float:
    """计算两个标题的 Jaccard 相似度（基于单词集合）"""
    sa = set(a.split())
    sb = set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _merge_results(all_sources: list[list[dict]], limit: int) -> list[dict]:
    """合并去重：DOI 精确匹配 + 标题 Jaccard 相似度 (≥0.7) 模糊匹配"""
    merged = []  # list of merged papers

    for source_results in all_sources:
        for r in source_results:
            doi = (r.get("doi") or "").strip().lower()
            title_norm = _normalize_title(r.get("title") or "")
            if not title_norm:
                continue

            # 查找是否已有重复
            found = None
            for existing in merged:
                edoi = (existing.get("doi") or "").strip().lower()
                # DOI 精确匹配
                if doi and edoi and doi == edoi:
                    found = existing
                    break
                # 标题 Jaccard 相似度匹配
                etitle = _normalize_title(existing.get("title") or "")
                if _jaccard_sim(title_norm, etitle) >= 0.7:
                    found = existing
                    break

            if found:
                # 合并补充信息
                if not found.get("abstract") and r.get("abstract"):
                    found["abstract"] = r["abstract"]
                if not found.get("authors") and r.get("authors"):
                    found["authors"] = r["authors"]
                if not found.get("open_access_url") and r.get("open_access_url"):
                    found["open_access_url"] = r["open_access_url"]
                if not found.get("doi") and r.get("doi"):
                    found["doi"] = r["doi"]
                found["cited_by"] = max(found.get("cited_by", 0), r.get("cited_by", 0))
            else:
                merged.append(r)

    # 默认按引用排序
    merged.sort(
        key=lambda x: (x.get("cited_by", 0), int(x.get("year") or "0")),
        reverse=True,
    )
    merged = merged[:limit]

    for i, r in enumerate(merged):
        r["index"] = i + 1
    return merged


def _relevance_score(paper: dict, query: str) -> float:
    """计算论文的综合相关性得分，融合查询匹配、引用数、源质量和年份"""
    score = 0.0
    query_terms = set(query.lower().split())

    # 1. 查询词匹配 (0-40 分)
    title_norm = _normalize_title(paper.get("title") or "")
    abstract_norm = (paper.get("abstract") or "").lower()
    title_words = set(title_norm.split())
    abstract_words = set(abstract_norm.split())

    if query_terms:
        title_match = len(query_terms & title_words) / len(query_terms)
        abstract_match = len(query_terms & abstract_words) / len(query_terms) if abstract_words else 0
        score += title_match * 25 + abstract_match * 15  # title更重要

    # 2. 引用影响力 (0-30 分) — log scaled，减少高被引垄断
    cited = paper.get("cited_by", 0) or 0
    if cited > 0:
        score += min(math.log10(cited + 1) * 8, 30)  # log(10k+1)*8 ≈ 32 → capped at 30

    # 3. 数据源质量加权 (0-10 分)
    source_weights = {
        "semantic_scholar": 10, "openalex": 9, "crossref": 8,
        "pubmed": 8, "core": 6, "europe_pmc": 6,
        "arxiv": 7, "doaj": 5, "dblp": 7,
    }
    score += source_weights.get(paper.get("source", ""), 4)

    # 4. 年份新度 (0-15 分) — 最近3年加成
    try:
        year = int(paper.get("year") or "0")
        if year > 0:
            current_year = datetime.datetime.now().year
            age = max(current_year - year, 0)
            if age <= 1:
                score += 15
            elif age <= 3:
                score += 10
            elif age <= 5:
                score += 5
            elif age <= 10:
                score += 2
    except ValueError:
        pass

    return round(score, 2)


def _merge_and_rank(all_sources: list[list[dict]], query: str, limit: int) -> list[dict]:
    """合并去重 + 综合相关性排序"""
    merged = _merge_results(all_sources, limit * 3)  # 先取更多再排序

    # 计算相关性得分并排序
    for paper in merged:
        paper["_score"] = _relevance_score(paper, query)

    merged.sort(key=lambda x: x.get("_score", 0), reverse=True)
    merged = merged[:limit]

    for i, r in enumerate(merged):
        r["index"] = i + 1
        r.pop("_score", None)  # 清理内部字段
    return merged


def search_papers(query: str, rows: int = 8) -> dict:
    """搜索论文 — 9 源并发搜索 + 智能去重 + 综合相关性排序（支持缓存）"""
    # 检查缓存
    cached = _cache.get_search(query, rows)
    if cached:
        cached["from_cache"] = True
        return cached

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

    def _call_connector(fn, query, rows):
        """单 connector 调用"""
        try:
            return fn(query, rows)
        except Exception:
            raise

    with ThreadPoolExecutor(max_workers=9) as executor:
        futures = {
            executor.submit(_call_connector, fn, query, fetch_rows): name
            for name, fn in ALL_CONNECTORS.items()
        }
        try:
            for future in as_completed(futures, timeout=30):
                name = futures[future]
                try:
                    result = future.result(timeout=5)
                    if result:
                        all_results.append(result)
                        sources_ok.append(name)
                except Exception as e:
                    sources_fail.append(f"{name}: {str(e)[:40]}")
        except FuturesTimeoutError:
            # 部分 connector 超时，收集已完成的结果
            for future, name in futures.items():
                if future.done() and not future.cancelled():
                    try:
                        result = future.result(timeout=0)
                        if result and name not in sources_ok:
                            all_results.append(result)
                            sources_ok.append(name)
                    except Exception:
                        if name not in [s.split(":")[0] for s in sources_fail]:
                            sources_fail.append(f"{name}: timeout")
                elif not future.done():
                    future.cancel()
                    sources_fail.append(f"{name}: timeout")

    log.info("search done: ok=%s fail=%s total_papers=%d",
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
        return {"success": False, "error": f"all {len(ALL_CONNECTORS)} sources failed", "sources_fail": sources_fail}
