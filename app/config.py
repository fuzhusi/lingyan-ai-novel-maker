import os
from dotenv import load_dotenv

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_project_root, ".env"))


class AppConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-v4-pro")

    # 数据库默认落 data/ 目录（2026-10-03 起统一收纳数据文件）；
    # 旧根目录 data.db 首次启动自动迁移（WAL 边车先移、主库最后，失败整组
    # 回退并继续用旧路径——评审 P0：迁移失败绝不能静默指向空新库）
    db_path = os.getenv("DATABASE_PATH", os.path.join("data", "data.db"))
    if not os.path.isabs(db_path):
        db_path = os.path.join(_project_root, db_path)
    if os.getenv("DATABASE_PATH") is None:
        _legacy = os.path.join(_project_root, "data.db")
        if not os.path.exists(db_path) and os.path.exists(_legacy):
            import shutil
            try:
                os.makedirs(os.path.dirname(db_path), exist_ok=True)
                moved = []
                for suffix in ("-wal", "-shm", ""):   # 边车先移，主库最后
                    src = _legacy + suffix
                    if os.path.exists(src):
                        shutil.move(src, db_path + suffix)
                        moved.append((src, db_path + suffix))
                print(f"✓ 已将数据库从项目根目录迁移至 {db_path}")
            except OSError as exc:
                for src, dst in moved:               # 整组回退，不留半迁移态
                    try:
                        shutil.move(dst, src)
                    except OSError:
                        pass
                db_path = _legacy                    # 失败：继续用旧路径旧数据
                print(f"⚠ 数据库自动迁移失败（{exc}），继续使用 {_legacy}")
    else:
        try:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        except OSError:
            pass
    # 大写 key 显式落 config：cli 的 sys info/backup 由此取真实库路径
    # （此前只写进 SQLALCHEMY_DATABASE_URI，cli 的 config.get("DATABASE_PATH")
    #   永远拿到 None，backup 会静默备份 CWD 下的陈旧 data.db）
    DATABASE_PATH = db_path
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TEMPLATES_AUTO_RELOAD = True
    # 上传体积上限：防止超大文件 / 解压炸弹耗尽内存与磁盘
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024
