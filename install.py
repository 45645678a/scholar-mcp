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
        entry = {
            "command": "scholar-mcp",
            "args": [],
        }
    else:
        entry = {
            "command": sys.executable,
            "args": [str(SERVER_SCRIPT)],
        }

    # 仅写入已设置的环境变量，避免泄漏空白占位
    env = {}
    for var in ("AI_API_KEY", "AI_API_BASE", "AI_MODEL", "UNPAYWALL_EMAIL"):
        val = os.environ.get(var, "")
        if val:
            env[var] = val
    # 兼容旧 DS_KEY
    if not env.get("AI_API_KEY"):
        ds_key = os.environ.get("DS_KEY", "")
        if ds_key:
            env["AI_API_KEY"] = ds_key

    if env:
        entry["env"] = env
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
        for p in Path.home().glob("AppData/Roaming/Python/*/Scripts"):
            if (p / "scholar-mcp.exe").exists() or (p / "scholar-mcp").exists():
                user_scripts = p
                break

    scholar_exe = user_scripts / ("scholar-mcp.exe" if sys.platform == "win32" else "scholar-mcp")
    if not scholar_exe.exists():
        return  # 找不到，跳过

    scripts_dir = str(user_scripts)
    print(f"\n[PATH] scholar-mcp not in PATH")
    print(f"  Scripts dir: {scripts_dir}")

    if sys.platform == "win32":
        _fix_path_windows(scripts_dir)
    else:
        _fix_path_unix(scripts_dir)

    # 临时加入当前进程 PATH
    os.environ["PATH"] = scripts_dir + os.pathsep + os.environ.get("PATH", "")


def _fix_path_windows(scripts_dir: str):
    """Windows: 通过注册表添加到用户 PATH"""
    try:
        import winreg
    except ImportError:
        print(f"  [!] winreg not available, please add manually: {scripts_dir}")
        return

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_ALL_ACCESS)
    except PermissionError:
        print(f"  [!] No permission to modify user PATH. Please add manually: {scripts_dir}")
        return
    except OSError as e:
        print(f"  [!] Cannot open registry: {e}")
        return

    try:
        try:
            current_path, _ = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current_path = ""

        if scripts_dir.lower() not in current_path.lower():
            new_path = f"{current_path};{scripts_dir}" if current_path else scripts_dir
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
            # 通知系统 PATH 已更新
            try:
                import ctypes
                HWND_BROADCAST = 0xFFFF
                WM_SETTINGCHANGE = 0x1A
                ctypes.windll.user32.SendMessageTimeoutW(
                    HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", 2, 5000, None
                )
            except Exception:
                pass
            print(f"  [OK] Added to user PATH (restart terminal to take effect)")
        else:
            print(f"  [OK] Already in PATH (current terminal may need restart)")
    except PermissionError:
        print(f"  [!] No permission to write PATH. Run as administrator or add manually: {scripts_dir}")
    except Exception as e:
        print(f"  [!] Failed to update PATH: {e}")
    finally:
        winreg.CloseKey(key)


def _fix_path_unix(scripts_dir: str):
    """Linux/macOS: 添加到 shell rc 文件"""
    shell_rc = Path.home() / (".zshrc" if (Path.home() / ".zshrc").exists() else ".bashrc")
    export_line = f'export PATH="{scripts_dir}:$PATH"'
    try:
        content = shell_rc.read_text(encoding="utf-8") if shell_rc.exists() else ""
        if scripts_dir not in content:
            with open(shell_rc, "a", encoding="utf-8") as f:
                f.write(f"\n# Scholar MCP\n{export_line}\n")
            print(f"  [OK] Added to {shell_rc.name} (source {shell_rc.name} or restart terminal)")
    except PermissionError:
        print(f"  [!] No permission to write {shell_rc}. Please add manually: {export_line}")
    except Exception as e:
        print(f"  [!] Failed: {e}. Please add manually: {export_line}")


# ─── 安装依赖 ───

def install_deps():
    """安装 Python 依赖"""
    print("\n[DEPS] Installing dependencies...")
    deps = ["mcp", "requests"]
    for dep in deps:
        try:
            __import__(dep.replace("-", "_"))
            print(f"  [OK] {dep} (installed)")
        except ImportError:
            print(f"  [..] Installing {dep}...")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", dep, "-q"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                print(f"  [OK] {dep}")
            except subprocess.CalledProcessError as e:
                print(f"  [FAIL] {dep}: pip install failed (exit code {e.returncode})")

    # scidownl 是可选的
    try:
        import scidownl
        print(f"  [OK] scidownl (optional, installed)")
    except ImportError:
        print(f"  [--] scidownl (optional, skipped)")


# ─── MCP 注册 ───

def _read_config(path: Path) -> dict:
    """读取 JSON 配置文件，保留原始编码"""
    if not path.exists():
        return {}
    try:
        raw = path.read_bytes()
        # 尝试多种编码
        for enc in ["utf-8-sig", "utf-8", "latin-1"]:
            try:
                text = raw.decode(enc)
                return json.loads(text)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
    except OSError as e:
        print(f"  [!] Cannot read {path}: {e}")
    return {}


def _write_config(path: Path, config: dict):
    """写入 JSON 配置文件（写前自动备份，避免备份覆盖）"""
    path.parent.mkdir(parents=True, exist_ok=True)

    # 写前检查权限
    if path.exists() and not os.access(path, os.W_OK):
        raise PermissionError(f"No write permission: {path}")

    # 备份原文件（避免覆盖已有备份）
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        if backup.exists():
            # 已有备份，用带时间戳的名称
            import time
            ts = time.strftime("%Y%m%d_%H%M%S")
            backup = path.with_suffix(f".{ts}.bak")
        try:
            shutil.copy2(path, backup)
        except OSError:
            pass  # 备份失败不阻止写入

    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def detect_ides() -> list[str]:
    """检测已安装的 IDE"""
    found = []
    for ide_id, info in IDE_CONFIGS.items():
        config_path = info["config_path"]()
        if config_path.exists() or config_path.parent.exists():
            found.append(ide_id)
    return found


def register_ide(ide_id: str) -> bool:
    """向指定 IDE 注册 MCP"""
    if ide_id not in IDE_CONFIGS:
        raise ValueError(f"Unknown IDE: {ide_id}")

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
    if ide_id not in IDE_CONFIGS:
        return False

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
    print("\n[VERIFY] Checking installation...")
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from scholar_mcp_server import mcp
        print(f"  [OK] MCP server loaded: {mcp.name}")
        return True
    except Exception as e:
        print(f"  [FAIL] Load error: {e}")
        return False


# ─── 主流程 ───

def main():
    parser = argparse.ArgumentParser(description="Scholar MCP installer")
    parser.add_argument("--all", action="store_true", help="Register to all detected IDEs")
    parser.add_argument("--ide", nargs="+", choices=list(IDE_CONFIGS.keys()), help="Register to specific IDEs")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall (remove MCP config)")
    parser.add_argument("--skip-deps", action="store_true", help="Skip dependency installation")
    args = parser.parse_args()

    print("=" * 50)
    print("  Scholar MCP — Local Paper Tool")
    print("=" * 50)
    print(f"\n  Project: {SCRIPT_DIR}")

    # 卸载模式
    if args.uninstall:
        print("\n[UNINSTALL] Removing Scholar MCP...")
        for ide_id, info in IDE_CONFIGS.items():
            try:
                if unregister_ide(ide_id):
                    print(f"  [OK] Removed from {info['name']}")
            except Exception as e:
                print(f"  [!] {info['name']}: {e}")
        print("\n[DONE] Uninstall complete. Restart IDE to take effect.")
        return

    # 安装依赖
    if not args.skip_deps:
        install_deps()

    # 自动修复 PATH
    fix_path()

    # 验证
    if not verify():
        print("\n[FAIL] Verification failed, check dependencies.")
        sys.exit(1)

    # 检测 IDE
    detected = detect_ides()
    print(f"\n[DETECT] Found IDEs:")
    for ide_id in detected:
        print(f"  - {IDE_CONFIGS[ide_id]['name']}")
    if not detected:
        print("  (none)")

    # 确定要注册的 IDE
    if args.all:
        targets = detected
    elif args.ide:
        targets = args.ide
    else:
        # 交互模式
        print(f"\nAvailable IDEs:")
        for i, ide_id in enumerate(detected):
            print(f"  [{i+1}] {IDE_CONFIGS[ide_id]['name']}")
        print(f"  [a] All")
        print(f"  [q] Skip")

        choice = input("\nSelect (Enter=all): ").strip().lower()
        if choice == "q":
            targets = []
        elif choice == "a" or choice == "":
            targets = detected
        else:
            try:
                indices = [int(x) - 1 for x in choice.replace(",", " ").split()]
                targets = [detected[i] for i in indices if 0 <= i < len(detected)]
            except (ValueError, IndexError):
                print("  [!] Invalid selection, registering all.")
                targets = detected

    # 注册
    if targets:
        print(f"\n[REGISTER] Writing MCP config...")
        for ide_id in targets:
            try:
                register_ide(ide_id)
                print(f"  [OK] {IDE_CONFIGS[ide_id]['name']}")
            except PermissionError as e:
                print(f"  [FAIL] {IDE_CONFIGS[ide_id]['name']}: {e}")
            except Exception as e:
                print(f"  [FAIL] {IDE_CONFIGS[ide_id]['name']}: {e}")

    print("\n" + "=" * 50)
    print("  Installation complete! Restart IDE to use.")
    print("=" * 50)
    print(f"\n  Usage examples:")
    print(f'   "search papers about transformer"')
    print(f'   "download 10.1038/s41586-021-03819-2"')
    print(f'   "analyze my code, recommend papers"')
    print(f'   "generate citation graph for this paper"')


if __name__ == "__main__":
    main()
