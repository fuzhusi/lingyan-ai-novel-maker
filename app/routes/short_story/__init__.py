"""短篇模块 — 轻量级单篇创作，支持 3 种模式。

Modes:
- inspiration: 一句话灵感 → 发散Agent扩展构思 → 创作Agent写故事（双Agent协作）
- setting: 用户输入角色+场景+主题 → AI 生成
- careful: 用户详细设定 → AI 精心生成，支持多次微调
"""
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
import json
from app.models import db, ShortStory
from app.services.short_story_templates import get_all_templates

short_story_bp = Blueprint("short_story", __name__, url_prefix="/short")

# Import sub-modules to register their routes on the blueprint
from app.routes.short_story import generate  # noqa: F401, E402
from app.routes.short_story import review     # noqa: F401, E402
from app.routes.short_story import versioning # noqa: F401, E402
from app.routes.short_story import export     # noqa: F401, E402


# ---------------------------------------------------------------------------
# 核心 CRUD
# ---------------------------------------------------------------------------

@short_story_bp.route("/")
def story_list():
    """短篇列表页"""
    stories = ShortStory.query.order_by(ShortStory.updated_at.desc()).all()
    items = []
    for s in stories:
        node_done = node_total = 0
        try:
            nodes = json.loads(s.outline_nodes or "[]")
            if isinstance(nodes, list) and nodes:
                node_total = len(nodes)
                node_done = sum(1 for n in nodes if isinstance(n, dict) and n.get("status") == "done")
        except (json.JSONDecodeError, TypeError):
            pass
        items.append({"story": s, "node_done": node_done, "node_total": node_total})
    return render_template("short_story/list.html", stories=items)


@short_story_bp.route("/templates")
def list_templates():
    """获取短篇结构模板列表"""
    return jsonify(get_all_templates())


@short_story_bp.route("/new")
def new_story():
    """选择创作模式"""
    mode = request.args.get("mode", "")
    return render_template("short_story/new.html", mode=mode)


@short_story_bp.route("/create", methods=["POST"])
def create_story():
    """创建短篇"""
    mode = request.form.get("mode", "inspiration")

    story = ShortStory(
        title=request.form.get("title", "").strip() or "无题短篇",
        mode=mode,
        inspiration=request.form.get("inspiration", ""),
        genre=request.form.get("genre", ""),
        theme=request.form.get("theme", ""),
        character_desc=request.form.get("character_desc", ""),
        scene_desc=request.form.get("scene_desc", ""),
        structure_template=request.form.get("structure_template", ""),
        tone=request.form.get("tone", ""),
        word_target=request.form.get("word_target", type=int) or 2000,
        extra_instructions=request.form.get("extra_instructions", ""),
        status="draft",
    )
    db.session.add(story)
    db.session.commit()

    return redirect(url_for("short_story.write_story", story_id=story.id))


@short_story_bp.route("/<int:story_id>")
def write_story(story_id):
    """短篇编辑/写作页"""
    story = ShortStory.query.get_or_404(story_id)
    # 解析剧情大纲节点，供前端渲染进度条
    nodes = []
    try:
        parsed = json.loads(story.outline_nodes or "[]")
        if isinstance(parsed, list) and parsed:
            nodes = parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return render_template("short_story/write.html", story=story, outline_nodes=nodes)


@short_story_bp.route("/<int:story_id>/nodes")
def story_nodes(story_id):
    """返回短篇剧情大纲节点及状态（前端进度条刷新 / 单节点重写后同步全文用）"""
    story = ShortStory.query.get_or_404(story_id)
    nodes = []
    try:
        parsed = json.loads(story.outline_nodes or "[]")
        if isinstance(parsed, list):
            nodes = parsed
    except (json.JSONDecodeError, TypeError):
        pass
    done = [n for n in nodes if isinstance(n, dict) and n.get("status") == "done"]
    return jsonify({
        "story_id": story_id,
        "nodes": nodes,
        "content": story.content or "",
        "content_len": len(story.content or ""),
        # 所有已完成节点是否存有独立正文（决定单节点重写是否可用）
        "node_content_ready": bool(done) and all(n.get("content") for n in done),
    })


@short_story_bp.route("/<int:story_id>/edit", methods=["POST"])
def edit_story(story_id):
    """编辑短篇设定"""
    story = ShortStory.query.get_or_404(story_id)
    for field in ["title", "inspiration", "genre", "theme", "character_desc",
                  "scene_desc", "tone", "extra_instructions", "concept"]:
        val = request.form.get(field)
        if val is not None:
            setattr(story, field, val)
    wt = request.form.get("word_target", type=int)
    if wt:
        story.word_target = wt
    db.session.commit()
    return redirect(url_for("short_story.write_story", story_id=story.id))


@short_story_bp.route("/<int:story_id>/save", methods=["POST"])
def save_content(story_id):
    """保存编辑后的故事内容"""
    story = ShortStory.query.get_or_404(story_id)
    content = request.form.get("content", "")
    story.content = content
    story.status = "done"

    # 一致性处理：手动编辑导致全文与节点正文不一致时，
    # 清空节点独立正文（保留元数据/状态），避免单节点重写覆盖用户编辑
    from app.routes.short_story.generate import load_outline_nodes, _rebuild_content_from_nodes
    nodes = load_outline_nodes(story)
    if nodes:
        rebuilt = _rebuild_content_from_nodes(nodes)
        norm = lambda t: "".join((t or "").split())
        if norm(content) != norm(rebuilt):
            for n in nodes:
                n.pop("content", None)
            story.outline_nodes = json.dumps(nodes, ensure_ascii=False)

    db.session.commit()
    return jsonify({"ok": True})


@short_story_bp.route("/<int:story_id>/save-concept", methods=["POST"])
def save_concept(story_id):
    """保存编辑后的大纲"""
    story = ShortStory.query.get_or_404(story_id)
    concept = request.form.get("concept", "")
    story.concept = concept
    # 大纲被编辑后，重新解析节点
    from app.routes.short_story.generate import parse_outline_nodes
    nodes = parse_outline_nodes(concept, story.word_target)
    story.outline_nodes = json.dumps(nodes, ensure_ascii=False) if nodes else "[]"
    story.status = "concept_ready"
    # 大纲重置后旧全文与新节点失配，清空防止「继续生成」整篇重复拼接
    story.content = ""
    db.session.commit()
    return jsonify({"ok": True, "nodes": nodes})


@short_story_bp.route("/<int:story_id>/save-plan", methods=["POST"])
def save_plan(story_id):
    """保存编辑后的策划阶段产出（角色/场景/主题）。

    Body: field=plan_characters&content=...
    """
    story = ShortStory.query.get_or_404(story_id)
    field = request.form.get("field", "")
    content = request.form.get("content", "")
    allowed = {"plan_characters", "plan_theme"}
    if field not in allowed:
        return jsonify({"ok": False, "error": f"未知字段: {field}"}), 400
    setattr(story, field, content)
    db.session.commit()
    return jsonify({"ok": True})


@short_story_bp.route("/<int:story_id>/delete", methods=["POST"])
def delete_story(story_id):
    """删除短篇"""
    story = ShortStory.query.get_or_404(story_id)
    db.session.delete(story)
    db.session.commit()
    return redirect(url_for("short_story.story_list"))
