"""Scholar MCP 结构化日志模块

统一的日志配置，替代散落的 print 语句。
支持文件输出和 stderr 输出（MCP 使用 stdio，不能用 stdout）。
"""

import logging
import os
import sys

LOG_LEVEL = os.environ.get("SCHOLAR_MCP_LOG_LEVEL", "INFO").upper()
LOG_FILE = os.environ.get("SCHOLAR_MCP_LOG_FILE", "")


def get_logger(name: str) -> logging.Logger:
    """获取模块专用 logger

    Args:
        name: 模块名，如 "searcher", "downloader"

    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(f"scholar_mcp.{name}")

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    fmt = logging.Formatter(
        "[%(asctime)s] %(name)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # MCP 通信走 stdout/stdin，日志必须走 stderr
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(fmt)
    logger.addHandler(stderr_handler)

    # 可选：写入日志文件
    if LOG_FILE:
        try:
            file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)
        except OSError:
            pass

    logger.propagate = False
    return logger
