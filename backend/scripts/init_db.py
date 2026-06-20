"""初始化数据库（建表）

用法：
    python scripts/init_db.py
"""
import sys
from pathlib import Path

# 让脚本能 import app.* 模块
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import init_db, engine, DB_PATH
from sqlalchemy import text

if __name__ == "__main__":
    print(f"[init_db] creating tables at {DB_PATH}...", flush=True)
    init_db()

    # 验证表已创建
    with engine.connect() as conn:
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
        tables = [row[0] for row in result]
        print(f"[init_db] created {len(tables)} tables:", flush=True)
        for t in tables:
            print(f"  - {t}", flush=True)
