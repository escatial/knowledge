"""SQLite 数据库连接管理（任务 P0-2：JSON → SQLite 迁移）

设计要点：
1. 单例 engine + sessionmaker
2. WAL 模式（更好的并发）
3. 上下文管理器（自动 commit/rollback）
4. 失败友好（错误时自动 rollback，不污染数据）
"""
import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

# 数据库文件位置：backend/data/kb.db
_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DB_PATH = _DATA_DIR / "kb.db"
DB_URL = f"sqlite:///{DB_PATH}"

# 任务 P0-2: SQLAlchemy engine（单例）
# - check_same_thread=False: 允许多线程访问（FastAPI 用）
# - echo=False: 生产不打印 SQL
# - pool_size=10 / max_overflow=20: 连接池，避免每次新建连接
# - pool_recycle=3600: 防止长时间空闲连接被服务端关闭
engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False},
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
    pool_timeout=10,
)


# 任务 P0-2: 启用 SQLite WAL 模式（更好的读写并发）
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


# Session 工厂
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

# ORM 基类
Base = declarative_base()


@contextmanager
def get_db_session() -> Session:
    """获取数据库 session 的上下文管理器

    用法：
        with get_db_session() as session:
            user = session.query(User).filter_by(id=uid).first()
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"[db] session rollback: {e}")
        raise
    finally:
        session.close()


def init_db():
    """初始化数据库（建表）"""
    from app.core import models  # noqa: F401  # 注册所有 models

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    logger.info(f"[db] initialized | path={DB_PATH} | tables={Base.metadata.tables.keys()}")


if __name__ == "__main__":
    init_db()
    print(f"[db] created at {DB_PATH}")
