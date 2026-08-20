"""抄袭/借鉴模块 — 风格模仿、情节借鉴、改写洗稿。"""
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from app.models import db, PlagiarizeTask, Novel, Chapter, ShortStory
from app.routes.auth import login_required

plagiarize_bp = Blueprint("plagiarize", __name__, url_prefix="/plagiarize")

# 导入子模块
from app.routes.plagiarize import style  # noqa: F401, E402
from app.routes.plagiarize import plot   # noqa: F401, E402
from app.routes.plagiarize import rewrite  # noqa: F401, E402


@plagiarize_bp.route("/")
@login_required
def task_list():
    """任务列表页"""
    tasks = PlagiarizeTask.query.order_by(PlagiarizeTask.created_at.desc()).all()
    return render_template("plagiarize/list.html", tasks=tasks)


@plagiarize_bp.route("/new")
@login_required
def new_task():
    """新建任务页"""
    mode = request.args.get("mode", "rewrite")
    novels = Novel.query.order_by(Novel.created_at.desc()).all()
    short_stories = ShortStory.query.order_by(ShortStory.created_at.desc()).all()
    return render_template("plagiarize/new.html", mode=mode, novels=novels, short_stories=short_stories)


@plagiarize_bp.route("/create", methods=["POST"])
@login_required
def create_task():
    """创建任务"""
    mode = request.form.get("mode", "rewrite")
    
    task = PlagiarizeTask(
        mode=mode,
        source_text=request.form.get("source_text", ""),
        rewrite_level=request.form.get("rewrite_level", "medium"),
        extra_instructions=request.form.get("extra_instructions", ""),
        target_novel_id=request.form.get("target_novel_id", type=int),
        target_short_story_id=request.form.get("target_short_story_id", type=int),
        status="pending",
    )
    db.session.add(task)
    db.session.commit()
    
    return redirect(url_for("plagiarize.task_detail", task_id=task.id))


@plagiarize_bp.route("/<int:task_id>")
@login_required
def task_detail(task_id):
    """任务详情页"""
    task = PlagiarizeTask.query.get_or_404(task_id)
    novels = Novel.query.order_by(Novel.created_at.desc()).all()
    short_stories = ShortStory.query.order_by(ShortStory.created_at.desc()).all()
    return render_template("plagiarize/detail.html", task=task, novels=novels, short_stories=short_stories)


@plagiarize_bp.route("/<int:task_id>/delete", methods=["POST"])
@login_required
def delete_task(task_id):
    """删除任务"""
    task = PlagiarizeTask.query.get_or_404(task_id)
    db.session.delete(task)
    db.session.commit()
    return redirect(url_for("plagiarize.task_list"))


@plagiarize_bp.route("/<int:task_id>/save-to-chapter", methods=["POST"])
@login_required
def save_to_chapter(task_id):
    """保存为长篇章节"""
    task = PlagiarizeTask.query.get_or_404(task_id)
    novel_id = request.form.get("novel_id", type=int)
    
    if not novel_id or not task.result_content:
        return jsonify({"error": "缺少小说ID或内容"}), 400
    
    # 获取下一个章节号
    last_chapter = Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.chapter_number.desc()).first()
    next_number = (last_chapter.chapter_number + 1) if last_chapter else 1
    
    chapter = Chapter(
        novel_id=novel_id,
        chapter_number=next_number,
        title=f"借鉴改写 - 任务#{task.id}",
    )
    db.session.add(chapter)
    db.session.flush()
    
    from app.models import ChapterVersion
    version = ChapterVersion(
        chapter_id=chapter.id,
        version_number=1,
        content=task.result_content,
        source="ai",
    )
    db.session.add(version)
    
    task.result_chapter_id = chapter.id
    db.session.commit()
    
    return jsonify({"ok": True, "chapter_id": chapter.id})


@plagiarize_bp.route("/<int:task_id>/save-to-short", methods=["POST"])
@login_required
def save_to_short(task_id):
    """保存为短篇"""
    task = PlagiarizeTask.query.get_or_404(task_id)
    
    if not task.result_content:
        return jsonify({"error": "缺少内容"}), 400
    
    story = ShortStory(
        title=f"借鉴改写 - 任务#{task.id}",
        mode="setting",
        content=task.result_content,
        status="done",
    )
    db.session.add(story)
    db.session.flush()
    
    task.target_short_story_id = story.id
    db.session.commit()
    
    return jsonify({"ok": True, "story_id": story.id})
