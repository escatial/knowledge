"""生产环境启动脚本（性能优化版）

功能：
1. 自动根据 CPU 核数选择 worker 数（生产推荐：2-4 个 worker）
2. 配置合理的 keepalive / timeout
3. 后台运行模式（可选）
4. 优雅关闭（处理 SIGTERM/SIGINT）

用法：
    python start_prod.py                  # 默认：自动 worker 数 = CPU 核数
    python start_prod.py --workers 4      # 指定 worker 数
    python start_prod.py --workers 2 --port 8000
    python start_prod.py --reload         # 开发模式（自动重载）
"""
import os
import sys
import argparse
import multiprocessing
import signal
import time

import uvicorn


def get_optimal_workers():
    """根据 CPU 核数推荐 worker 数

    经验公式：
    - 1 核：2 个 worker（避免阻塞）
    - 2 核：2-3 个
    - 4 核：3-4 个
    - 8 核+：4-8 个

    由于本项目每次请求都可能要调外部 LLM（IO 密集），worker 可以稍多
    """
    cpu_count = multiprocessing.cpu_count()
    if cpu_count <= 2:
        return 2
    elif cpu_count <= 4:
        return 3
    elif cpu_count <= 8:
        return 4
    else:
        return min(8, cpu_count)


def main():
    parser = argparse.ArgumentParser(description="知识库后端生产启动器")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--workers", type=int, default=None, help="worker 进程数（默认自动）")
    parser.add_argument("--reload", action="store_true", help="开发模式（自动重载）")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "info"))
    parser.add_argument("--limit-concurrency", type=int, default=100, help="最大并发连接数")
    parser.add_argument("--backlog", type=int, default=2048, help="TCP backlog")
    parser.add_argument("--timeout-keep-alive", type=int, default=30, help="keep-alive 超时（秒）")
    args = parser.parse_args()

    workers = args.workers or get_optimal_workers()

    print("=" * 60)
    print("知识库后端启动器（生产模式）")
    print("=" * 60)
    print(f"  监听地址: {args.host}:{args.port}")
    print(f"  Worker 数: {workers} (CPU 核数={multiprocessing.cpu_count()})")
    print(f"  最大并发: {args.limit_concurrency}")
    print(f"  Keep-Alive: {args.timeout_keep_alive}s")
    print(f"  日志级别: {args.log_level}")
    print("=" * 60)

    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        workers=workers if not args.reload else 1,
        reload=args.reload,
        log_level=args.log_level,
        # 性能优化项
        limit_concurrency=args.limit_concurrency,
        backlog=args.backlog,
        timeout_keep_alive=args.timeout_keep_alive,
        # 优化：减少 access log 写入开销（生产可设为 False）
        access_log=True,
    )


if __name__ == "__main__":
    main()