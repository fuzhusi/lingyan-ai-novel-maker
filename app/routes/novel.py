from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from app.models import db, Novel, Chapter, Character, WorldSetting

novel_bp = Blueprint("novel", __name__)


@novel_bp.route("/")
def index():
    """Gateway page — choose between long-form and short-form."""
    # 配置检测(PM C3):新人第一次价值体验卡在配 API key——首屏直接给出去向
    from app.models import LLMProvider, LLMModel
    has_provider = LLMProvider.query.count() > 0
    has_model = LLMModel.query.filter_by(enabled=True).count() > 0
    return render_template("gateway.html",
                           has_llm_provider=has_provider, has_enabled_model=has_model)


@novel_bp.route("/novel/")
def novel_list():
    """Long-form novel list."""
    novels = Novel.query.order_by(Novel.created_at.desc()).all()
    novel_data = []
    for novel in novels:
        chapter_count = Chapter.query.filter_by(novel_id=novel.id).count()
        character_count = Character.query.filter_by(novel_id=novel.id).count()
        novel_data.append({
            "novel": novel,
            "chapter_count": chapter_count,
            "character_count": character_count,
        })
    return render_template("novel_list.html", novel_data=novel_data)


@novel_bp.route("/novel/create", methods=["POST"])
def create_novel():
    title = request.form.get("title", "").strip()
    if not title:
        return redirect(url_for("novel.index"))

    genre = request.form.get("genre", "").strip()
    synopsis = request.form.get("synopsis", "").strip()
    world_intro = request.form.get("world_intro", "").strip()
    char_name = request.form.get("char_name", "").strip()
    char_personality = request.form.get("char_personality", "").strip()
    char_background = request.form.get("char_background", "").strip()

    novel = Novel(
        title=title,
        genre=genre,
        synopsis=synopsis,
        world_intro=world_intro,
    )
    db.session.add(novel)
    db.session.flush()  # get novel.id

    if char_name:
        char = Character(
            novel_id=novel.id,
            name=char_name,
            personality=char_personality,
            background=char_background,
        )
        db.session.add(char)

    if world_intro:
        ws = WorldSetting(
            novel_id=novel.id,
            category="世界观概述",
            title=f"《{title}》世界观",
            content=world_intro,
        )
        db.session.add(ws)

    db.session.commit()
    return redirect(url_for("novel.index"))


@novel_bp.route("/novel/<int:novel_id>/compass", methods=["POST"])
def save_compass(novel_id):
    """保存创作罗盘：作者意图（全书承诺）+ 当前重心（阶段目标）。

    罗盘注入每一次生成且豁免上下文压缩，必须限长，防止长文本无界膨胀 prompt。
    """
    MAX_AUTHOR_INTENT = 500
    MAX_CURRENT_FOCUS = 300
    novel = Novel.query.get_or_404(novel_id)
    novel.author_intent = request.form.get("author_intent", "").strip()[:MAX_AUTHOR_INTENT]
    novel.current_focus = request.form.get("current_focus", "").strip()[:MAX_CURRENT_FOCUS]
    db.session.commit()
    return redirect(url_for("chapter.chapter_list", novel_id=novel_id))


@novel_bp.route("/novel/<int:novel_id>/delete", methods=["POST"])
def delete_novel(novel_id):
    # 删除单一真源:外围引用清理 + bulk 级联(app/services/delete_service.py)
    from app.services.delete_service import delete_novel_full
    ok, _ = delete_novel_full(novel_id)
    # 删完回长篇列表（用户从这里点的删除），不跳网关页
    return redirect(url_for("novel.novel_list"))


@novel_bp.route("/novel/delete-all", methods=["POST"])
def delete_all_novels():
    # 破坏性操作：要求显式确认参数，防止误触/纯 CSRF 型请求
    if request.form.get("confirm", "").strip().upper() != "YES":
        return jsonify({"error": "缺少 confirm=YES 确认参数，已拒绝删除全部小说"}), 400
    # 删除单一真源级联：与单本删除同源（外围引用→FTS→本体），FK ON 下安全。
    # 此前这里是手写的第二套级联，盲审/关系顺序错误在 FK ON 后必炸，
    # 且 FTS 先行物理删除后随整体回滚造成"数据在、索引没了"的不一致。
    from app.services.delete_service import delete_novel_full
    for n in Novel.query.all():
        delete_novel_full(n.id)
    return redirect(url_for("novel.index"))
