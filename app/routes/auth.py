"""认证模块 — 已禁用（单用户模式，去除登录环节）。

多用户登录已移除：所有视图直接放行，login/logout 路由保留但不再强制。
"""

from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, g

auth_bp = Blueprint("auth", __name__)


# 默认账号配置（保留，兼容 CLI）
DEFAULT_USERS = {
    "admin": {"password": "admin", "name": "管理员", "role": "admin"},
    "user": {"password": "user", "name": "用户", "role": "user"},
}


def login_required(f):
    """登录装饰器 — 已禁用：直接放行（单用户模式）。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated


@auth_bp.route("/login", methods=["GET", "POST"])
def login_page():
    """登录页 — 已禁用：直接跳转首页。"""
    return redirect("/")


@auth_bp.route("/logout")
def logout():
    """注销 — 已禁用：直接跳转首页。"""
    return redirect("/")


@auth_bp.before_app_request
def load_logged_in_user():
    """每次请求前设置 g.user（单用户模式：恒为默认管理员）。"""
    g.user = {"username": "admin", "name": "管理员", "role": "admin"}
