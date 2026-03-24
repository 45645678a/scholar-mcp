# Scholar MCP Server

Local academic paper tool MCP server — **9-source search**, multi-source download, AI-powered analysis, citation graph, code-based paper recommendation.

[![PyPI](https://img.shields.io/pypi/v/scholar-mcp-server)](https://pypi.org/project/scholar-mcp-server/)
[![Python](https://img.shields.io/pypi/pyversions/scholar-mcp-server)](https://pypi.org/project/scholar-mcp-server/)
[![Tests](https://github.com/45645678a/scholar-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/45645678a/scholar-mcp/actions/workflows/test.yml)
[![License](https://img.shields.io/github/license/45645678a/scholar-mcp)](LICENSE)

## Quick Install

```bash
pip install scholar-mcp-server[all]
scholar-mcp-install --all
```

That's it. Restart your IDE and start using it.

## Features

| Tool | Description |
|---|---|
| `paper_search` | 9-source concurrent search with relevance scoring (Semantic Scholar, OpenAlex, Crossref, PubMed, arXiv, CORE, Europe PMC, DOAJ, dblp) |
| `paper_download` | Multi-source PDF download: Unpaywall → Publisher OA → arXiv → Sci-Hub → scidownl |
| `paper_batch_download` | Batch download multiple papers by DOI list |
| `paper_ai_analyze` | AI analysis — downloads PDF, extracts full text (up to 20 pages / 12k chars), sends to any OpenAI-compatible API |
| `paper_recommend` | Scan your workspace code → multi-query auto-recommend related papers |
| `paper_citation_graph` | Generate Mermaid citation/reference network visualization |
| `paper_health` | Check download source availability |

### Search Quality

Search results are ranked by a **4-factor composite score**:

| Factor | Weight | Description |
|---|---|---|
| Query relevance | 0–40 | Title + abstract term matching |
| Citation impact | 0–30 | Log-scaled citation count |
| Source quality | 0–10 | Data source reliability weighting |
| Year recency | 0–15 | Boost for recent publications |

Deduplication uses **DOI matching + Jaccard title similarity** (≥0.7 threshold) across all 9 sources. Each source connector has built-in **retry with exponential backoff**.

## AI Analysis

`paper_ai_analyze` works with **any OpenAI-compatible API**. Set `AI_API_BASE`, `AI_API_KEY`, and `AI_MODEL` to point to your preferred provider.

## Alternative Install (Git Clone)

```bash
git clone https://github.com/45645678a/scholar-mcp.git
cd scholar-mcp
pip install -r requirements.txt
python install.py --all
```

## Environment Variables

| Variable | Description | Required |
|---|---|---|
| `AI_API_KEY` | API key for AI analysis | For `paper_ai_analyze` |
| `AI_API_BASE` | API base URL (any OpenAI-compatible endpoint) | Optional (default: `https://api.deepseek.com`) |
| `AI_MODEL` | Model name | Optional (default: `deepseek-chat`) |
| `UNPAYWALL_EMAIL` | Email for Unpaywall API | Optional |

## Supported IDEs

- **Antigravity** (Gemini)
- **Cursor**
- **Windsurf**
- **Claude Code** / Claude Desktop
- **VS Code** (Copilot)

## Search Sources (9)

All free, no API keys required:

| Source | Coverage |
|---|---|
| Semantic Scholar | Broad academic (primary) |
| OpenAlex | 250M+ works, global |
| Crossref | DOI metadata |
| PubMed | Biomedical |
| arXiv | Physics, CS, Math |
| CORE | Open Access aggregator |
| Europe PMC | European biomedical |
| DOAJ | Open Access journals |
| dblp | Computer Science |

## Development

```bash
pip install .[all] pytest
pytest tests/ -v
```

40 tests covering search dedup, download chain, keyword extraction, and connector mocking.

## ⚠️ Disclaimer

This tool includes optional Sci-Hub integration for personal academic use. Sci-Hub may be illegal in some jurisdictions. **Users are solely responsible for ensuring compliance with local laws and institutional policies.** The authors do not endorse copyright infringement. If you are in a compliance-sensitive environment (university, company, lab), consult your institution's policy before using the Sci-Hub download source.

## License

MIT
