# Scholar MCP — 本地论文工具

在 AI IDE 中直接搜索、下载、分析学术论文。所有下载在本地执行，支持 Sci-Hub / arXiv / Unpaywall 多源回退。

## ✨ 功能

| 工具 | 说明 |
|---|---|
| `paper_search` | 搜索论文 (Crossref + Semantic Scholar 双源) |
| `paper_download` | 通过 DOI 下载 PDF (Unpaywall → arXiv → Sci-Hub) |
| `paper_batch_download` | 批量下载多篇论文 |
| `paper_ai_analyze` | 用 DeepSeek AI 分析论文（核心贡献/方法/发现） |
| `paper_recommend` | 扫描你的代码工作区，自动推荐相关论文 |
| `paper_citation_graph` | 生成论文引用图谱 (Mermaid 可视化) |
| `paper_health` | 检查各下载源可用性 |

## 🚀 一键安装

```bash
git clone <repo-url> scholar-mcp
cd scholar-mcp
python install.py
```

脚本会自动：
1. ✅ 安装 Python 依赖 (`mcp`, `requests`)
2. ✅ 检测你电脑上已安装的 AI IDE
3. ✅ 注册 MCP 到所有检测到的 IDE
4. ✅ 验证安装是否成功

支持的 IDE：**Antigravity** / **Cursor** / **Windsurf** / **Claude Code** / **VS Code Copilot**

### 安装选项

```bash
python install.py              # 交互模式（推荐）
python install.py --all        # 自动注册到所有 IDE
python install.py --ide cursor # 只注册到指定 IDE
python install.py --uninstall  # 卸载（移除所有配置）
```

### 手动安装

如果你更喜欢手动配置，在 IDE 的 MCP 配置文件中添加：

```json
"scholar-mcp": {
  "command": "python",
  "args": ["/path/to/scholar-mcp/scholar_mcp_server.py"],
  "env": {
    "DS_KEY": "你的DeepSeek API Key（可选，用于AI分析）",
    "UNPAYWALL_EMAIL": "你的邮箱"
  }
}
```

各 IDE 配置文件位置：

| IDE | 配置文件路径 |
|---|---|
| Antigravity | `~/.gemini/antigravity/mcp_config.json` |
| Cursor | `~/.cursor/mcp.json` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| Claude Code | `~/.claude/claude_desktop_config.json` |
| VS Code | `~/.vscode/mcp.json` |

## 📖 使用示例

配置好后，在 AI 对话中直接说：

```
搜索关于 "gradient coil optimization" 的论文
```
```
下载这篇论文：10.1109/tim.2021.3106677
```
```
分析一下我当前工作区的代码，推荐相关论文
```
```
生成 10.1109/tim.2021.3106677 的引用图谱
```

## 🔧 环境变量

| 变量 | 必选 | 说明 |
|---|---|---|
| `DS_KEY` | 否 | DeepSeek API Key，用于 `paper_ai_analyze` |
| `UNPAYWALL_EMAIL` | 否 | 邮箱地址，Unpaywall API 要求提供 |

## 📁 项目结构

```
scholar-mcp/
├── scholar_mcp_server.py   # MCP 入口，注册所有工具
├── downloader.py           # 多源下载引擎
├── searcher.py             # 论文搜索
├── recommender.py          # 代码分析 → 论文推荐
├── citation_graph.py       # 引用图谱
└── requirements.txt        # 依赖
```

## ⚠️ 注意事项

- Sci-Hub 镜像可能因网络环境不同而可用性不同，可通过 `paper_health` 检查
- `paper_ai_analyze` 需要有效的 DeepSeek API Key
- 下载优先使用合法 OA 源 (Unpaywall)，Sci-Hub 作为备用
