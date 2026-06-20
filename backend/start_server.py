"""启动脚本 - 把所有输出写入文件便于诊断

生产环境部署：
- Linux: BACKEND_DIR=/opt/app/knowledge-base/backend LOG_DIR=/var/log/knowledge-base
- Windows: 直接 python start_server.py
"""
import sys
import os
import warnings
from pathlib import Path
warnings.filterwarnings("ignore")

# 修复：不再硬编码 Windows 路径，使用 BACKEND_DIR 环境变量
BACKEND_DIR = Path(os.getenv("BACKEND_DIR", Path(__file__).resolve().parent))
LOG_DIR = Path(os.getenv("LOG_DIR", BACKEND_DIR / "data"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "start_server.log"

def log(msg):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg, flush=True)

log("=== 启动后端服务 ===")
log(f"Python: {sys.executable}")
log(f"BACKEND_DIR: {BACKEND_DIR}")

# 切到 backend 目录
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
log(f"切换到: {os.getcwd()}")

# 单独测试关键模块
try:
    log("导入 main 模块...")
    import main
    log("main 模块导入成功")
    log(f"FastAPI app: {main.app}")
except Exception as e:
    import traceback
    log(f"导入失败: {e}")
    log(traceback.format_exc())
    sys.exit(1)

if __name__ == "__main__":
    # 任务 Z：启动时自动初始化 system_faq 入库
    # 失败不影响服务启动（内部 try/except + 日志）
    try:
        log("=== 初始化 system_faq ===")
        from app.core.system_faq_importer import init_system_faq
        n = init_system_faq(force=False)
        log(f"system_faq 初始化完成 | 入库 {n} 条")
    except Exception as e:
        import traceback
        log(f"system_faq 初始化失败（不影响服务）: {e}")
        log(traceback.format_exc())

    log("=== 启动 uvicorn ===")
    import uvicorn
    # 差异 #2/#16：host/port 可通过环境变量配置
    # 生产环境：HOST=127.0.0.1 PORT=8000（仅本机监听，外部经 Nginx 反代）
    # 开发环境：HOST=0.0.0.0 PORT=8000（允许直接调试）
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    log(f"监听地址: {host}:{port}")
    try:
        uvicorn.run(
            "main:app",
            host=host,
            port=port,
            log_level="info",
        )
    except Exception as e:
        import traceback
        log(f"uvicorn 异常: {e}")
        log(traceback.format_exc())
