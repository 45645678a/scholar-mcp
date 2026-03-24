# Scholar MCP Server

Local academic paper tool MCP server — **9-source search**, multi-source download, AI analysis, citation graph, code-based paper recommendation.

## Quick Install (PyPI)

```bash
pip install scholar-mcp-server[all]
scholar-mcp-install --all
```

This installs the server + auto-registers to all detected AI IDEs (Antigravity, Cursor, Windsurf, Claude Code, VS Code).

## Features

| Tool | Description |
|---|---|
| `paper_search` | 9-source concurrent search (Semantic Scholar, OpenAlex, Crossref, PubMed, arXiv, CORE, Europe PMC, DOAJ, dblp) |
| `paper_download` | Multi-source PDF download (Unpaywall → Publisher OA → Sci-Hub → arXiv) |
| `paper_batch_download` | Batch download by DOI list |
| `paper_ai_analyze` | AI-powered full-text paper analysis (any OpenAI-compatible API) |
| `paper_recommend` | Scan workspace code → recommend related papers |
| `paper_citation_graph` | Generate Mermaid citation network visualization |
| `paper_health` | Check download source availability |

## Alternative Install (Git Clone)

```bash
git clone https://github.com/45645678a/scholar-mcp.git
cd scholar-mcp
pip install -r requirements.txt
python install.py --all
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `AI_API_KEY` | API key for AI analysis (DeepSeek/OpenAI/etc.) | — |
| `AI_API_BASE` | API base URL | `https://api.deepseek.com` |
| `AI_MODEL` | Model name | `deepseek-chat` |
| `UNPAYWALL_EMAIL` | Email for Unpaywall API | `scholar-mcp@example.com` |

## Supported IDEs

- Antigravity (Gemini)
- Cursor
- Windsurf
- Claude Code / Claude Desktop
- VS Code (Copilot)

## License

MIT
