"""搜索结果缓存 — 基于 SQLite

避免重复查询同一搜索词时打 9 个 API。
缓存默认 24 小时过期，可通过环境变量配置。
"""

import os
import json
import time
import sqlite3
import hashlib
from pathlib import Path

from logger import get_logger

log = get_logger("cache")

# 缓存配置
CACHE_DIR = os.environ.get("SCHOLAR_MCP_CACHE_DIR", str(Path.home() / ".scholar-mcp"))
CACHE_DB = os.path.join(CACHE_DIR, "cache.db")
CACHE_TTL = int(os.environ.get("SCHOLAR_MCP_CACHE_TTL", 86400))  # 默认 24 小时
CACHE_ENABLED = os.environ.get("SCHOLAR_MCP_CACHE", "1") != "0"


def _cache_key(query: str, rows: int) -> str:
    """生成缓存 key"""
    raw = f"{query.strip().lower()}|rows={rows}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _get_db() -> sqlite3.Connection:
    """获取数据库连接（自动创建表）"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB, timeout=5)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS search_cache (
            key TEXT PRIMARY KEY,
            query TEXT,
            rows INTEGER,
            result TEXT,
            created_at REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS download_cache (
            doi TEXT PRIMARY KEY,
            result TEXT,
            created_at REAL
        )
    """)
    return conn


def get_search(query: str, rows: int) -> dict | None:
    """从缓存获取搜索结果"""
    if not CACHE_ENABLED:
        return None

    key = _cache_key(query, rows)
    try:
        conn = _get_db()
        cur = conn.execute(
            "SELECT result, created_at FROM search_cache WHERE key = ?",
            (key,),
        )
        row = cur.fetchone()
        conn.close()

        if row:
            result_json, created_at = row
            age = time.time() - created_at
            if age < CACHE_TTL:
                log.debug("cache hit: %r (age %.0fs)", query[:40], age)
                return json.loads(result_json)
            else:
                log.debug("cache expired: %r (age %.0fs > TTL %ds)", query[:40], age, CACHE_TTL)
    except Exception as e:
        log.debug("cache read error: %s", e)
    return None


def set_search(query: str, rows: int, result: dict):
    """缓存搜索结果"""
    if not CACHE_ENABLED:
        return
    if not result.get("success"):
        return  # 不缓存失败结果

    key = _cache_key(query, rows)
    try:
        conn = _get_db()
        conn.execute(
            "INSERT OR REPLACE INTO search_cache (key, query, rows, result, created_at) VALUES (?, ?, ?, ?, ?)",
            (key, query.strip().lower(), rows, json.dumps(result, ensure_ascii=False), time.time()),
        )
        conn.commit()
        conn.close()
        log.debug("cache set: %r", query[:40])
    except Exception as e:
        log.debug("cache write error: %s", e)


def clear_expired():
    """清理过期缓存"""
    try:
        conn = _get_db()
        cutoff = time.time() - CACHE_TTL
        conn.execute("DELETE FROM search_cache WHERE created_at < ?", (cutoff,))
        conn.execute("DELETE FROM download_cache WHERE created_at < ?", (cutoff,))
        conn.commit()
        deleted = conn.total_changes
        conn.close()
        if deleted:
            log.info("cleared %d expired cache entries", deleted)
    except Exception as e:
        log.debug("cache cleanup error: %s", e)


def clear_all():
    """清空所有缓存"""
    try:
        conn = _get_db()
        conn.execute("DELETE FROM search_cache")
        conn.execute("DELETE FROM download_cache")
        conn.commit()
        conn.close()
        log.info("all cache cleared")
    except Exception as e:
        log.debug("cache clear error: %s", e)


def stats() -> dict:
    """获取缓存统计"""
    try:
        conn = _get_db()
        search_count = conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
        valid_count = conn.execute(
            "SELECT COUNT(*) FROM search_cache WHERE created_at > ?",
            (time.time() - CACHE_TTL,),
        ).fetchone()[0]
        conn.close()
        return {
            "enabled": CACHE_ENABLED,
            "ttl_seconds": CACHE_TTL,
            "total_entries": search_count,
            "valid_entries": valid_count,
            "cache_dir": CACHE_DIR,
        }
    except Exception as e:
        return {"enabled": CACHE_ENABLED, "error": str(e)}
