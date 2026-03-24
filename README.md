# Scholar MCP Server

Local academic paper tool MCP server — **9-source search**, multi-source download, AI-powered analysis, citation graph, code-based paper recommendation.

[![PyPI](https://img.shields.io/pypi/v/scholar-mcp-server)](https://pypi.org/project/scholar-mcp-server/)
[![Python](https://img.shields.io/pypi/pyversions/scholar-mcp-server)](https://pypi.org/project/scholar-mcp-server/)
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
| `paper_search` | 9-source concurrent search: Semantic Scholar, OpenAlex, Crossref, PubMed, arXiv, CORE, Europe PMC, DOAJ, dblp |
| `paper_download` | Multi-source PDF download: Unpaywall → Publisher OA → Sci-Hub → arXiv |
| `paper_batch_download` | Batch download multiple papers by DOI list |
| `paper_ai_analyze` | AI full-text analysis — downloads PDF, extracts text, sends to any OpenAI-compatible API |
| `paper_recommend` | Scan your workspace code → auto-recommend related papers |
| `paper_citation_graph` | Generate Mermaid citation/reference network visualization |
| `paper_health` | Check download source availability |

## AI Analysis Setup

`paper_ai_analyze` works with **any OpenAI-compatible API** — use your preferred provider:

| Provider | `AI_API_BASE` | `AI_MODEL` |
|---|---|---|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| Local (Ollama) | `http://localhost:11434/v1` | `llama3` |
| Azure OpenAI | `https://your-resource.openai.azure.com/openai/deployments/your-model` | `gpt-4o` |
| Any compatible | Your endpoint | Your model |

Set these via environment variables or in your IDE's MCP config.

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

## License

MIT
