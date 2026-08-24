"""pytest 全局 fixture。

关键约束：必须在导入 app 之前把 DATABASE_PATH 指到临时库，
否则 conftest 一旦触发 app.models 导入链就会在项目根创建/污染 data.db。
"""
import os
import sys
import tempfile

import pytest

# 独立临时数据库，与开发库完全隔离。放在仓库内 .tmp-test/ 下：
# sqlite URI 对 Windows 反斜杠处理不稳定，统一转正斜杠；
# 且沙箱环境通常只放行工作区写入，系统 TEMP 不可用
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP_DIR = os.path.join(_REPO_ROOT, ".tmp-test")
os.makedirs(_TMP_DIR, exist_ok=True)
os.environ["DATABASE_PATH"] = os.path.join(_TMP_DIR, "test.db").replace("\\", "/")
os.environ["DATABASE_PATH"] = _TMP_DB
os.environ.setdefault("LINGYAN_DEBUG", "0")
# 测试环境不读真实 .env，防止误用真实 API key
os.environ["DEEPSEEK_API_KEY"] = os.environ.get("DEEPSEEK_API_KEY", "test-key-placeholder")

# 保证从仓库根导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402  (须在 env 设置之后)
from app.models import db as _db  # noqa: E402


@pytest.fixture(scope="session")
def app():
    application = create_app()
    application.config["TESTING"] = True
    with application.app_context():
        _db.create_all()
        yield application


@pytest.fixture()
def client(app):
    return app.test_client()
