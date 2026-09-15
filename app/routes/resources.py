"""资源库路由 —— 对标书资源的管理与语义检索 API。"""
from flask import Blueprint, render_template, request, jsonify
from app.models import db
from app.models.resource import ResourceBook
from app.services.resource_service import semantic_search
from app.routes.auth import login_required

resources_bp = Blueprint("resources", __name__)


@resources_bp.route("/resources/")
@login_required
def resource_list():
    """资源库列表页"""
    books = ResourceBook.query.order_by(ResourceBook.created_at.desc()).all()
    return render_template("resources/list.html", books=books)


@resources_bp.route("/resources/api/search", methods=["POST"])
@login_required
def api_search():
    """语义检索 API:POST {query, novel_id?, top_k?} → 相关片段列表"""
    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()
    if not query:
        return jsonify({"ok": False, "message": "请输入检索内容"}), 400
    novel_id = body.get("novel_id")
    top_k = min(max(int(body.get("top_k", 5)), 1), 20)
    results = semantic_search(query, novel_id=novel_id, top_k=top_k)
    return jsonify({"ok": True, "results": results})


@resources_bp.route("/resources/api/<int:book_id>", methods=["GET"])
@login_required
def api_detail(book_id):
    """资源详情(含分段列表)"""
    book = ResourceBook.query.get_or_404(book_id)
    return jsonify({"ok": True, "book": {
        "id": book.id, "title": book.title, "author": book.author,
        "total_chars": book.total_chars, "chapter_count": book.chapter_count,
        "embedded": book.embedded,
        "chunks": [{"index": c.chunk_index, "title": c.title,
                     "chars": len(c.content or "")} for c in book.chunks],
    }})


@resources_bp.route("/resources/<int:book_id>/delete", methods=["POST"])
@login_required
def delete_resource(book_id):
    book = ResourceBook.query.get_or_404(book_id)
    title = book.title
    db.session.delete(book)
    db.session.commit()
    return jsonify({"ok": True, "message": f"已删除「{title}」"})

