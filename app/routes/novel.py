from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from app.models import (
    db, Novel, Chapter, ChapterVersion, CriticReview, Character, WorldSetting,
    OutlineNode, Foreshadowing, ChapterSummary,
    ChapterMemory, CharacterRelation, StoryState, StoryStateSnapshot,
)

novel_bp = Blueprint("novel", __name__)


@novel_bp.route("/")
def index():
    """Gateway page — choose between long-form and short-form."""
    return render_template("gateway.html")


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


@novel_bp.route("/novel/<int:novel_id>/delete", methods=["POST"])
def delete_novel(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    for ch in novel.chapters:
        # Delete reviews first (foreign key to chapter_versions)
        for v in ChapterVersion.query.filter_by(chapter_id=ch.id).all():
            CriticReview.query.filter_by(version_id=v.id).delete()
        ChapterVersion.query.filter_by(chapter_id=ch.id).delete()
        ChapterSummary.query.filter_by(chapter_id=ch.id).delete()
        ChapterMemory.query.filter_by(chapter_id=ch.id).delete()
        db.session.delete(ch)
    Character.query.filter_by(novel_id=novel_id).delete()
    CharacterRelation.query.filter_by(novel_id=novel_id).delete()
    WorldSetting.query.filter_by(novel_id=novel_id).delete()
    OutlineNode.query.filter_by(novel_id=novel_id).delete()
    Foreshadowing.query.filter_by(novel_id=novel_id).delete()
    StoryStateSnapshot.query.filter_by(novel_id=novel_id).delete()
    StoryState.query.filter_by(novel_id=novel_id).delete()
    db.session.delete(novel)
    db.session.commit()

    # 同步清理 FTS 记忆索引（SQLite 无 FK，残留会被跨小说检索命中）
    from app.services.vector_memory import delete_novel_memory
    delete_novel_memory(novel_id)
    return redirect(url_for("novel.index"))


@novel_bp.route("/novel/delete-all", methods=["POST"])
def delete_all_novels():
    # 破坏性操作：要求显式确认参数，防止误触/纯 CSRF 型请求
    if request.form.get("confirm", "").strip().upper() != "YES":
        return jsonify({"error": "缺少 confirm=YES 确认参数，已拒绝删除全部小说"}), 400
    novels = Novel.query.all()
    for novel in novels:
        for ch in novel.chapters:
            for v in ChapterVersion.query.filter_by(chapter_id=ch.id).all():
                CriticReview.query.filter_by(version_id=v.id).delete()
            ChapterVersion.query.filter_by(chapter_id=ch.id).delete()
            ChapterSummary.query.filter_by(chapter_id=ch.id).delete()
            ChapterMemory.query.filter_by(chapter_id=ch.id).delete()
            db.session.delete(ch)
        Character.query.filter_by(novel_id=novel.id).delete()
        CharacterRelation.query.filter_by(novel_id=novel.id).delete()
        WorldSetting.query.filter_by(novel_id=novel.id).delete()
        OutlineNode.query.filter_by(novel_id=novel.id).delete()
        Foreshadowing.query.filter_by(novel_id=novel.id).delete()
        StoryStateSnapshot.query.filter_by(novel_id=novel.id).delete()
        StoryState.query.filter_by(novel_id=novel.id).delete()
        db.session.delete(novel)
        # 同步清理该小说的 FTS 记忆索引
        from app.services.vector_memory import delete_novel_memory
        delete_novel_memory(novel.id)
    db.session.commit()
    return redirect(url_for("novel.index"))
