"""数据库基础实例和工具函数。"""
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
