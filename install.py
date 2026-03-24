"""Scholar MCP — 一键安装脚本

自动安装依赖 + 注册 MCP 到所有支持的 AI IDE。

用法：
    python install.py                # 交互模式
    python install.py --all          # 注册到所有检测到的 IDE
    python install.py --ide cursor   # 只注册到 Cursor
    python install.py --uninstall    # 卸载（移除所有 MCP 配置）
"""

import os
import sys
import json
import subprocess
import argparse
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
SERVER_SCRIPT = SCRIPT_DIR / "scholar_mcp_server.py"

# ─── IDE MCP 配置路径 ───

def _home():
    return Path.home()

IDE_CONFIGS = {
    "antigravity": {
        "name": "Antigravity (Gemini)",
        "config_path": lambda: _home() / ".gemini" / "antigravity" / "mcp_config.json",
        "format": "mcpServers",  # { "mcpServers": { ... } }
    },
    "cursor": {
        "name": "Cursor",
        "config_path": lambda: _home() / ".cursor" / "mcp.json",
        "format": "mcpServers",
    },
    "windsurf": {
        "name": "Windsurf",
        "config_path": lambda: _home() / ".codeium" / "windsurf" / "mcp_config.json",
        "format": "mcpServers",
    },
    "claude-code": {
        "name": "Claude Code",
        "config_path": lambda: _home() / ".claude" / "claude_desktop_config.json",
        "format": "mcpServers",
    },
    "vscode": {
        "name": "VS Code (Copilot)",
        "config_path": lambda: _home() / ".vscode" / "mcp.json",
        "format": "servers",  # { "servers": { ... } }
    },
}

MCP_KEY = "scholar-mcp"

def _server_entry():
    """生成 MCP 服务器配置条目 — 自动检测 pip 安装 vs 本地 git clone"""
    # 检测是否通过 pip 安装（scholar-mcp 命令可用）
    scholar_cmd = shutil.which("scholar-mcp")
    if scholar_cmd:
        # pip 安装模式：直接用 CLI 命令
        entry = {
            "command": "scholar-mcp",
            "args": [],
        }
    else:
        # 本地 git clone 模式：用 python 执行脚本
        entry = {
            "command": "python",
            "args": [str(SERVER_SCRIPT)],
        }

    entry["env"] = {
        "AI_API_KEY": os.environ.get("AI_API_KEY", os.environ.get("DS_KEY", "")),
        "AI_API_BASE": os.environ.get("AI_API_BASE", "https://api.deepseek.com"),
        "AI_MODEL": os.environ.get("AI_MODEL", "deepseek-chat"),
        "UNPAYWALL_EMAIL": os.environ.get("UNPAYWALL_EMAIL", "scholar-mcp@example.com"),
    }
    return entry


# ─── PATH 自动修复 ───

def fix_path():
    """检测 scholar-mcp 命令是否可用，不可用则尝试将 Python Scripts 目录加入 PATH"""
    if shutil.which("scholar-mcp"):
        return  # 已在 PATH 中

    # 查找 pip --user 安装的 Scripts 目录
    import site
    user_scripts = Path(site.getusersitepackages()).parent / "Scripts"
    if not user_scripts.exists():
        # 尝试常见路径
        for p in Path.home().glob("AppData/Roaming/Python/*/Scripts"):
            if (p / "scholar-mcp.exe").exists() or (p / "scholar-mcp").exists():
                user_scripts = p
                break

    scholar_exe = user_scripts / ("scholar-mcp.exe" if sys.platform == "win32" else "scholar-mcp")
    if not scholar_exe.exists():
        return  # 找不到，跳过

    scripts_dir = str(user_scripts)
    print(f"\n🔧 检测到 scholar-mcp 不在 PATH 中")
    print(f"   脚本目录: {scripts_dir}")

    if sys.platform == "win32":
        # Windows: 永久添加到用户 PATH
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_ALL_ACCESS)
            try:
                current_path, _ = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current_path = ""
            if scripts_dir.lower() not in current_path.lower():
                new_path = f"{current_path};{scripts_dir}" if current_path else scripts_dir
                winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
                winreg.CloseKey(key)
                # 通知系统 PATH 已更新
                import ctypes
                HWND_BROADCAST = 0xFFFF
                WM_SETTINGCHANGE = 0x1A
                ctypes.windll.user32.SendMessageTimeoutW(
                    HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", 2, 5000, None
                )
                print(f"   ✅ 已自动添加到用户 PATH（新终端生效）")
            else:
                print(f"   ✅ 已在 PATH 中（当前终端可能需要重启）")
        except Exception as e:
            print(f"   ⚠️  无法自动添加 PATH: {e}")
            print(f"   请手动添加: {scripts_dir}")
    else:
        # Linux/macOS
        shell_rc = Path.home() / (".zshrc" if os.path.exists(Path.home() / ".zshrc") else ".bashrc")
        export_line = f'export PATH="{scripts_dir}:$PATH"'
        try:
            content = shell_rc.read_text() if shell_rc.exists() else ""
            if scripts_dir not in content:
                with open(shell_rc, "a") as f:
                    f.write(f"\n# Scholar MCP\n{export_line}\n")
                print(f"   ✅ 已添加到 {shell_rc.name}（source {shell_rc.name} 或重开终端生效）")
        except Exception as e:
            print(f"   ⚠️  无法自动添加: {e}")
            print(f"   请手动添加: {export_line}")

    # 临时加入当前进程 PATH
    os.environ["PATH"] = scripts_dir + os.pathsep + os.environ.get("PATH", "")


# ─── 安装依赖 ───

def install_deps():
    """安装 Python 依赖"""
    print("\n📦 安装依赖...")
    deps = ["mcp", "requests"]
    for dep in deps:
        try:
            __import__(dep.replace("-", "_"))
            print(f"  ✅ {dep} (已安装)")
        except ImportError:
            print(f"  ⬇️  安装 {dep}...")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", dep, "-q"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"  ✅ {dep}")

    # scidownl 是可选的
    try:
        import scidownl
        print(f"  ✅ scidownl (已安装，可选)")
    except ImportError:
        print(f"  ⏭️  scidownl (可选，跳过)")


# ─── MCP 注册 ───

def _read_config(path: Path) -> dict:
    """读取 JSON 配置文件"""
    if not path.exists():
        return {}
    try:
        raw = path.read_bytes()
        for enc in ["utf-8-sig", "utf-8", "latin-1"]:
            try:
                return json.loads(raw.decode(enc))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
    except Exception:
        pass
    return {}


def _write_config(path: Path, config: dict):
    """写入 JSON 配置文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def detect_ides() -> list[str]:
    """检测已安装的 IDE"""
    found = []
    for ide_id, info in IDE_CONFIGS.items():
        config_path = info["config_path"]()
        # 检查配置文件或其父目录是否存在
        if config_path.exists() or config_path.parent.exists():
            found.append(ide_id)
    return found


def register_ide(ide_id: str) -> bool:
    """向指定 IDE 注册 MCP"""
    info = IDE_CONFIGS[ide_id]
    config_path = info["config_path"]()
    fmt = info["format"]

    config = _read_config(config_path)

    # 确保顶层 key 存在
    if fmt not in config:
        config[fmt] = {}

    # 添加/更新 scholar-mcp
    config[fmt][MCP_KEY] = _server_entry()

    _write_config(config_path, config)
    return True


def unregister_ide(ide_id: str) -> bool:
    """从指定 IDE 移除 MCP"""
    info = IDE_CONFIGS[ide_id]
    config_path = info["config_path"]()
    fmt = info["format"]

    config = _read_config(config_path)
    servers = config.get(fmt, {})

    if MCP_KEY in servers:
        del servers[MCP_KEY]
        config[fmt] = servers
        _write_config(config_path, config)
        return True
    return False


# ─── 验证 ───

def verify():
    """验证安装"""
    print("\n🔍 验证安装...")
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from scholar_mcp_server import mcp
        print(f"  ✅ MCP 服务器加载成功: {mcp.name}")
        return True
    except Exception as e:
        print(f"  ❌ 加载失败: {e}")
        return False


# ─── 主流程 ───

def main():
    parser = argparse.ArgumentParser(description="Scholar MCP 一键安装")
    parser.add_argument("--all", action="store_true", help="注册到所有检测到的 IDE")
    parser.add_argument("--ide", nargs="+", choices=list(IDE_CONFIGS.keys()), help="指定注册到哪些 IDE")
    parser.add_argument("--uninstall", action="store_true", help="卸载（移除 MCP 配置）")
    parser.add_argument("--skip-deps", action="store_true", help="跳过依赖安装")
    args = parser.parse_args()

    print("=" * 50)
    print("  Scholar MCP — 本地论文工具")
    print("=" * 50)
    print(f"\n📂 项目路径: {SCRIPT_DIR}")

    # 卸载模式
    if args.uninstall:
        print("\n🗑️  卸载 Scholar MCP...")
        for ide_id, info in IDE_CONFIGS.items():
            if unregister_ide(ide_id):
                print(f"  ✅ 已从 {info['name']} 移除")
        print("\n✅ 卸载完成。重启 IDE 生效。")
        return

    # 安装依赖
    if not args.skip_deps:
        install_deps()

    # 自动修复 PATH
    fix_path()

    # 验证
    if not verify():
        print("\n❌ 验证失败，请检查依赖。")
        sys.exit(1)

    # 检测 IDE
    detected = detect_ides()
    print(f"\n🔎 检测到的 IDE:")
    for ide_id in detected:
        print(f"  • {IDE_CONFIGS[ide_id]['name']}")
    if not detected:
        print("  (无)")

    # 确定要注册的 IDE
    if args.all:
        targets = detected
    elif args.ide:
        targets = args.ide
    else:
        # 交互模式
        print(f"\n可注册的 IDE:")
        for i, ide_id in enumerate(detected):
            print(f"  [{i+1}] {IDE_CONFIGS[ide_id]['name']}")
        print(f"  [a] 全部注册")
        print(f"  [q] 跳过")

        choice = input("\n请选择 (回车=全部): ").strip().lower()
        if choice == "q":
            targets = []
        elif choice == "a" or choice == "":
            targets = detected
        else:
            try:
                indices = [int(x) - 1 for x in choice.replace(",", " ").split()]
                targets = [detected[i] for i in indices if 0 <= i < len(detected)]
            except ValueError:
                targets = detected

    # 注册
    if targets:
        print(f"\n📝 注册 MCP...")
        for ide_id in targets:
            try:
                register_ide(ide_id)
                print(f"  ✅ {IDE_CONFIGS[ide_id]['name']}")
            except Exception as e:
                print(f"  ❌ {IDE_CONFIGS[ide_id]['name']}: {e}")

    print("\n" + "=" * 50)
    print("  ✅ 安装完成！重启 IDE 即可使用。")
    print("=" * 50)
    print(f"\n💡 使用方法: 在 AI 对话中说：")
    print(f'   "搜索关于 transformer 的论文"')
    print(f'   "下载 10.1038/s41586-021-03819-2"')
    print(f'   "分析我的代码，推荐相关论文"')
    print(f'   "生成这篇论文的引用图谱"')


if __name__ == "__main__":
    main()
