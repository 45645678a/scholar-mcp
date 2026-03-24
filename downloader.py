"""多源论文下载引擎 — 本地直连，无需远程 API

下载源优先级：Unpaywall (合法OA) → Sci-Hub → arXiv
"""

import os
import re
import json
import requests

# Sci-Hub 镜像列表（按可用性排序，可随时更新）
SCIHUB_MIRRORS = [
    "https://sci-hub.se",
    "https://sci-hub.st",
    "https://sci-hub.ru",
    "https://sci-hub.mksa.top",
]

UNPAYWALL_EMAIL = os.environ.get("UNPAYWALL_EMAIL", "scholar-mcp@example.com")
ARXIV_PDF_BASE = "https://arxiv.org/pdf/"
ARXIV_ABS_BASE = "https://arxiv.org/abs/"

# arXiv ID 正则
ARXIV_ID_RE = re.compile(r"(?:arXiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)
ARXIV_OLD_RE = re.compile(r"(?:arXiv:)?([a-z\-]+/\d{7}(?:v\d+)?)", re.IGNORECASE)


def _safe_name(doi: str) -> str:
    """DOI -> 安全文件名"""
    return doi.replace("/", "_").replace(":", "_") + ".pdf"


# 出版商 DOI 前缀 → PDF URL 模板
# {doi} 会被替换为完整 DOI
PUBLISHER_PDF_TEMPLATES = {
    "10.1088/": "https://iopscience.iop.org/article/{doi}/pdf",          # IOP
    "10.3390/": "https://www.mdpi.com/{doi}/pdf",                        # MDPI (非标准，走 DOI redirect)
    "10.3389/": "https://doi.org/{doi}",                                 # Frontiers (OA, DOI redirect 到 PDF)
    "10.1155/": "https://doi.org/{doi}",                                 # Hindawi (OA)
    "10.1371/": "https://doi.org/{doi}",                                 # PLOS (OA)
}

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
}


def _try_publisher_oa(doi: str, timeout: int = 30) -> bytes | None:
    """尝试从出版商网站直接下载 OA 论文 PDF"""
    # 1. 已知出版商模板
    for prefix, template in PUBLISHER_PDF_TEMPLATES.items():
        if doi.startswith(prefix):
            url = template.format(doi=doi)
            try:
                r = requests.get(url, timeout=timeout, allow_redirects=True, headers=BROWSER_HEADERS)
                if r.content[:5] == b"%PDF-":
                    return r.content
            except Exception:
                pass
            break  # 只匹配第一个前缀

    # 2. 通用: 通过 DOI redirect 看最终页面是否有 PDF
    try:
        r = requests.get(f"https://doi.org/{doi}", timeout=timeout, allow_redirects=True, headers=BROWSER_HEADERS)
        if r.content[:5] == b"%PDF-":
            return r.content
        # 某些 OA 出版商在页面中有直接 PDF 链接
        import re as _re
        match = _re.search(
            r'<a[^>]*href="([^"]*)"[^>]*>.*?(?:Download|PDF|Full.Text).*?</a>',
            r.text[:20000], _re.IGNORECASE
        )
        if match:
            pdf_link = match.group(1)
            if not pdf_link.startswith("http"):
                from urllib.parse import urljoin
                pdf_link = urljoin(r.url, pdf_link)
            pr = requests.get(pdf_link, timeout=timeout, allow_redirects=True, headers=BROWSER_HEADERS)
            if pr.content[:5] == b"%PDF-":
                return pr.content
    except Exception:
        pass

    return None


def _try_unpaywall(doi: str, timeout: int = 15) -> str | None:
    """通过 Unpaywall 查找合法开放获取 PDF 链接"""
    try:
        url = f"https://api.unpaywall.org/v2/{doi}?email={UNPAYWALL_EMAIL}"
        r = requests.get(url, timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
        best = data.get("best_oa_location")
        if best:
            return best.get("url_for_pdf") or best.get("url")
        # 尝试所有 OA locations
        for loc in (data.get("oa_locations") or []):
            pdf_url = loc.get("url_for_pdf") or loc.get("url")
            if pdf_url:
                return pdf_url
    except Exception:
        pass
    return None


def _try_scihub(doi: str, timeout: int = 30) -> bytes | None:
    """通过 Sci-Hub 镜像下载 PDF"""
    for mirror in SCIHUB_MIRRORS:
        try:
            url = f"{mirror}/{doi}"
            r = requests.get(url, timeout=timeout, allow_redirects=True)

            # 如果直接返回 PDF
            if r.content[:5] == b"%PDF-":
                return r.content

            # 从 HTML 中提取 PDF 链接
            pdf_url = None

            # 方法 1: citation_pdf_url meta 标签（Sci-Hub 最常用的方式）
            match = re.search(
                r'name=["\']citation_pdf_url["\'][^>]*content=["\']([^"\']+)["\']',
                r.text, re.IGNORECASE
            )
            if not match:
                match = re.search(
                    r'content=["\']([^"\']+)["\'][^>]*name=["\']citation_pdf_url["\']',
                    r.text, re.IGNORECASE
                )
            if match:
                pdf_url = match.group(1)

            # 方法 2: /storage/ 路径的 href（Sci-Hub 存储路径）
            if not pdf_url:
                match = re.search(
                    r'href=["\']([^"\']*?/storage/[^"\']*\.pdf[^"\']*)["\']',
                    r.text, re.IGNORECASE
                )
                if match:
                    pdf_url = match.group(1)

            # 方法 3: iframe/embed src（旧版 Sci-Hub 布局）
            if not pdf_url:
                match = re.search(
                    r'(?:iframe|embed)[^>]*src=["\']([^"\']+)["\']',
                    r.text, re.IGNORECASE
                )
                if match:
                    pdf_url = match.group(1)

            # 方法 4: 通用 .pdf href
            if not pdf_url:
                match = re.search(
                    r'href=["\']([^"\']*\.pdf[^"\']*)["\']',
                    r.text, re.IGNORECASE
                )
                if match:
                    pdf_url = match.group(1)

            # 方法 5: location.href 跳转
            if not pdf_url:
                match = re.search(
                    r'location\.href\s*=\s*["\']([^"\']*\.pdf[^"\']*)["\']',
                    r.text, re.IGNORECASE
                )
                if match:
                    pdf_url = match.group(1)

            if pdf_url:
                if pdf_url.startswith("//"):
                    pdf_url = "https:" + pdf_url
                elif pdf_url.startswith("/"):
                    pdf_url = mirror + pdf_url
                elif not pdf_url.startswith("http"):
                    pdf_url = mirror + "/" + pdf_url
                pr = requests.get(pdf_url, timeout=timeout)
                if pr.content[:5] == b"%PDF-":
                    return pr.content
        except (requests.Timeout, requests.ConnectionError):
            continue
        except Exception:
            continue
    return None


def _try_scidownl(doi: str, output_dir: str, timeout: int = 60) -> str | None:
    """使用 scidownl 库作为 Sci-Hub 备用下载方案"""
    try:
        from scidownl import scihub_download

        out_file = os.path.join(output_dir, _safe_name(doi))
        scihub_download(doi, paper_type="doi", out=out_file)

        if os.path.exists(out_file) and os.path.getsize(out_file) > 1024:
            with open(out_file, "rb") as f:
                if f.read(5) == b"%PDF-":
                    return out_file
            # 不是有效 PDF，删除
            os.remove(out_file)
    except Exception:
        pass
    return None


def _try_arxiv(identifier: str, timeout: int = 30) -> bytes | None:
    """通过 arXiv 直接下载 PDF"""
    # 从 DOI 或标识符中提取 arXiv ID
    arxiv_id = None

    # 检查是否是 arXiv DOI
    if identifier.startswith("10.48550/arXiv."):
        arxiv_id = identifier.replace("10.48550/arXiv.", "")
    elif identifier.startswith("10.48550/"):
        arxiv_id = identifier.replace("10.48550/", "")

    # 检查新格式 arXiv ID
    if not arxiv_id:
        m = ARXIV_ID_RE.search(identifier)
        if m:
            arxiv_id = m.group(1)

    # 检查旧格式 arXiv ID
    if not arxiv_id:
        m = ARXIV_OLD_RE.search(identifier)
        if m:
            arxiv_id = m.group(1)

    if not arxiv_id:
        return None

    try:
        url = f"{ARXIV_PDF_BASE}{arxiv_id}"
        r = requests.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200 and r.content[:5] == b"%PDF-":
            return r.content
    except Exception:
        pass
    return None


def download_paper(doi: str, output_dir: str = ".") -> dict:
    """下载论文的主入口，按优先级尝试多个来源

    优先级：Unpaywall (合法OA) → arXiv → Sci-Hub (自定义) → Sci-Hub (scidownl)
    """
    os.makedirs(output_dir, exist_ok=True)
    output = os.path.join(output_dir, _safe_name(doi))

    # 已存在则跳过
    if os.path.exists(output):
        size_mb = os.path.getsize(output) / 1024 / 1024
        return {
            "success": True,
            "doi": doi,
            "path": os.path.abspath(output),
            "size_mb": round(size_mb, 2),
            "source": "cached",
        }

    # 1. Unpaywall (合法 OA)
    oa_url = _try_unpaywall(doi)
    if oa_url:
        try:
            r = requests.get(oa_url, timeout=30, allow_redirects=True)
            if r.content[:5] == b"%PDF-":
                with open(output, "wb") as f:
                    f.write(r.content)
                return {
                    "success": True,
                    "doi": doi,
                    "path": os.path.abspath(output),
                    "size_mb": round(len(r.content) / 1024 / 1024, 2),
                    "source": "unpaywall_oa",
                }
        except Exception:
            pass

    # 2. Publisher OA (IOP, MDPI, Frontiers 等出版商直链)
    pub_data = _try_publisher_oa(doi)
    if pub_data:
        with open(output, "wb") as f:
            f.write(pub_data)
        return {
            "success": True,
            "doi": doi,
            "path": os.path.abspath(output),
            "size_mb": round(len(pub_data) / 1024 / 1024, 2),
            "source": "publisher_oa",
        }

    # 3. arXiv
    arxiv_data = _try_arxiv(doi)
    if arxiv_data:
        with open(output, "wb") as f:
            f.write(arxiv_data)
        return {
            "success": True,
            "doi": doi,
            "path": os.path.abspath(output),
            "size_mb": round(len(arxiv_data) / 1024 / 1024, 2),
            "source": "arxiv",
        }

    # 3. Sci-Hub (自定义镜像抓取)
    scihub_data = _try_scihub(doi)
    if scihub_data:
        with open(output, "wb") as f:
            f.write(scihub_data)
        return {
            "success": True,
            "doi": doi,
            "path": os.path.abspath(output),
            "size_mb": round(len(scihub_data) / 1024 / 1024, 2),
            "source": "sci-hub",
        }

    # 4. scidownl 库 (备用 Sci-Hub 方案)
    scidownl_path = _try_scidownl(doi, output_dir)
    if scidownl_path:
        size_mb = os.path.getsize(scidownl_path) / 1024 / 1024
        return {
            "success": True,
            "doi": doi,
            "path": os.path.abspath(scidownl_path),
            "size_mb": round(size_mb, 2),
            "source": "scidownl",
        }

    return {"success": False, "doi": doi, "error": "all sources failed (unpaywall/arxiv/sci-hub)"}


def batch_download(dois: list[str], output_dir: str = ".") -> dict:
    """批量下载论文"""
    os.makedirs(output_dir, exist_ok=True)
    results = []
    success_count = 0
    fail_count = 0
    skip_count = 0

    for doi in dois:
        doi = doi.strip()
        if not doi or doi.startswith("#"):
            continue

        r = download_paper(doi, output_dir)
        if r["success"]:
            if r.get("source") == "cached":
                skip_count += 1
                results.append({"doi": doi, "status": "skipped", "reason": "already exists"})
            else:
                success_count += 1
                results.append({
                    "doi": doi, "status": "ok",
                    "path": r["path"], "size_mb": r["size_mb"], "source": r["source"]
                })
        else:
            fail_count += 1
            results.append({"doi": doi, "status": "failed", "error": r["error"]})

    return {
        "total": len(dois),
        "success": success_count,
        "failed": fail_count,
        "skipped": skip_count,
        "output_dir": os.path.abspath(output_dir),
        "details": results,
    }


def health_check() -> dict:
    """检查各下载源的可用性"""
    status = {"overall": "ok", "sources": {}}

    # 检查 Unpaywall
    try:
        r = requests.get(
            f"https://api.unpaywall.org/v2/10.1038/nature12373?email={UNPAYWALL_EMAIL}",
            timeout=10,
        )
        status["sources"]["unpaywall"] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception as e:
        status["sources"]["unpaywall"] = f"error: {str(e)[:60]}"

    # 检查 arXiv
    try:
        r = requests.head(f"{ARXIV_PDF_BASE}2301.00001", timeout=10, allow_redirects=True)
        status["sources"]["arxiv"] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception as e:
        status["sources"]["arxiv"] = f"error: {str(e)[:60]}"

    # 检查 Sci-Hub 镜像
    scihub_status = {}
    for mirror in SCIHUB_MIRRORS:
        try:
            r = requests.get(mirror, timeout=10)
            scihub_status[mirror] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
        except Exception as e:
            scihub_status[mirror] = f"error: {str(e)[:50]}"
    status["sources"]["scihub_mirrors"] = scihub_status

    # 如果所有源都失败则标记
    all_failed = all(
        v != "ok" for k, v in status["sources"].items()
        if k != "scihub_mirrors"
    ) and all(v != "ok" for v in scihub_status.values())

    if all_failed:
        status["overall"] = "degraded"

    return status
