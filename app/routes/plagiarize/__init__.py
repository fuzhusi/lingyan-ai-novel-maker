"""拆书复刻模块 —— 对标书拆解 → 待确认采纳 → 复刻生成。

旧版风格模仿/情节借鉴/三档洗稿已由拆书复刻覆盖并下线（style.py/plot.py/rewrite.py 已删除）。
"""
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from app.models import db, PlagiarizeTask, Novel, Chapter, ShortStory
from app.routes.auth import login_required

plagiarize_bp = Blueprint("plagiarize", __name__, url_prefix="/plagiarize")

# 导入子模块（拆书路由 + 文件上传）
from app.routes.plagiarize import deconstruct  # noqa: F401, E402
from app.routes.plagiarize import upload       # noqa: F401, E402

_MODE_LABELS = {
    "deconstruct": "拆书复刻",
    "style": "风格模仿(已下线)",
    "plot": "情节借鉴(已下线)",
    "rewrite": "改写洗稿(已下线)",
}


@plagiarize_bp.route("/")
@login_required
def task_list():
    """拆书任务列表页"""
    from app.models.long_task import LongTask
    tasks = PlagiarizeTask.query.order_by(PlagiarizeTask.created_at.desc()).all()
    running_map = {}
    for lt in LongTask.query.filter_by(status="running").all():
        if lt.ref_id and (lt.ref_id not in running_map):
            running_map[lt.ref_id] = {"kind": lt.kind, "tail": (lt.progress or "")[-80:]}
    novel_titles = {n.id: n.title for n in Novel.query.all()}
    story_titles = {st.id: st.title for st in ShortStory.query.all()}
    return render_template("plagiarize/list.html", tasks=tasks, mode_labels=_MODE_LABELS,
                           running_map=running_map, novel_titles=novel_titles,
                           story_titles=story_titles)


@plagiarize_bp.route("/new")
@login_required
def new_task():
    """新建拆书任务页"""
    return render_template("plagiarize/new.html")


@plagiarize_bp.route("/create", methods=["POST"])
@login_required
def create_task():
    """创建拆书任务"""
    source_text = request.form.get("source_text", "")
    if not source_text.strip():
        # 服务端防呆：HTML required 可被绕过，空任务到工作台点拆书才报错是滞后反馈
        return render_template("plagiarize/new.html",
                               error="请先粘贴对标书文本或上传文件"), 400
    title = request.form.get("title", "").strip()
    task = PlagiarizeTask(
        title=title or "未命名对标书",
        mode="deconstruct",
        source_text=source_text,
        source_type="paste",
        modifications_text=request.form.get("modifications_text", ""),
        status="pending",
    )
    db.session.add(task)
    db.session.commit()
    return redirect(url_for("plagiarize.task_detail", task_id=task.id))


@plagiarize_bp.route("/<int:task_id>")
@login_required
def task_detail(task_id):
    """拆书工作台页"""
    from app.models.long_task import LongTask
    task = PlagiarizeTask.query.get_or_404(task_id)
    items = task.items  # 级联排序：id 升序
    adopted_count = sum(1 for i in items if i.status == "adopted")
    novels = Novel.query.order_by(Novel.created_at.desc()).all()
    running_lt = LongTask.query.filter_by(
        ref_id=task.id, status="running").order_by(LongTask.id.desc()).first()
    steps = [
        {"label": "① 拆书", "done": task.status == "done",
         "active": task.status in ("summarizing", "deconstructing")},
        {"label": "② 微创新方向", "done": bool(task.modifications_text),
         "active": task.status == "done" and not task.modifications_text},
        {"label": "③ AI 改写 / 采纳", "done": adopted_count > 0,
         "active": task.status == "done" and adopted_count == 0
                   and bool(task.elements_json and task.elements_json != "[]")},
        {"label": "④ 复刻生成", "done": bool(task.target_novel_id or task.target_short_story_id)},
    ]
    return render_template("plagiarize/detail.html", task=task, items=items,
                           adopted_count=adopted_count, novels=novels,
                           running_lt=running_lt, steps=steps,
                           mode_label=_MODE_LABELS.get(task.mode, task.mode))


@plagiarize_bp.route("/<int:task_id>/delete", methods=["POST"])
@login_required
def delete_task(task_id):
    """删除任务（级联删除待确认条目）"""
    task = PlagiarizeTask.query.get_or_404(task_id)
    db.session.delete(task)
    db.session.commit()
    return redirect(url_for("plagiarize.task_list"))


@plagiarize_bp.route("/<int:task_id>/save-to-chapter", methods=["POST"])
@login_required
def save_to_chapter(task_id):
    """（旧版兼容）保存旧任务 result_content 为长篇章节"""
    task = PlagiarizeTask.query.get_or_404(task_id)
    novel_id = request.form.get("novel_id", type=int)

    if not novel_id or not task.result_content:
        return jsonify({"error": "缺少小说ID或内容"}), 400

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
    """（旧版兼容）保存旧任务 result_content 为短篇"""
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
