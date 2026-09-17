import os
from dotenv import load_dotenv

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_project_root, ".env"))


class AppConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-v4-pro")

    db_path = os.getenv("DATABASE_PATH", "data.db")
    if not os.path.isabs(db_path):
        db_path = os.path.join(_project_root, db_path)
    # 大写 key 显式落 config：cli 的 sys info/backup 由此取真实库路径
    # （此前只写进 SQLALCHEMY_DATABASE_URI，cli 的 config.get("DATABASE_PATH")
    #   永远拿到 None，backup 会静默备份 CWD 下的陈旧 data.db）
    DATABASE_PATH = db_path
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TEMPLATES_AUTO_RELOAD = True
    # 上传体积上限：防止超大文件 / 解压炸弹耗尽内存与磁盘
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024
