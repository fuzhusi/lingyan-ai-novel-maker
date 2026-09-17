"""大纲管理路由：树形 CRUD + 章节自动/手动创建 + 双向同步。"""
from flask import render_template, request, redirect, url_for, jsonify
from app.models import db, Novel, OutlineNode, Chapter
from app.routes.knowledge import knowledge_bp
from app.services.outline_sync import (
    sync_chapter_from_node, ensure_chapter_for_node,
)


@knowledge_bp.route("/outline")
def outline_page(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    nodes = OutlineNode.query.filter_by(novel_id=novel_id).order_by(
        OutlineNode.parent_id.nullsfirst(), OutlineNode.sort_order
    ).all()
    chapters = Chapter.query.filter_by(novel_id=novel_id).all()
    node_chapter_map = {}
    for ch in chapters:
        if ch.outline_node_id:
            node_chapter_map[ch.outline_node_id] = ch
    return render_template("outline.html", novel=novel, nodes=nodes,
                           node_chapter_map=node_chapter_map, chapters=chapters)


@knowledge_bp.route("/outline/<int:node_id>/create-chapter", methods=["POST"])
def create_chapter_from_outline(novel_id, node_id):
    """Create a chapter from an outline node, pre-filling title and outline."""
    node = OutlineNode.query.filter_by(id=node_id, novel_id=novel_id).first_or_404()
    chapter = ensure_chapter_for_node(node)
    db.session.commit()
    return redirect(url_for("chapter.write_chapter",
                            novel_id=novel_id,
                            chapter_number=chapter.chapter_number))


@knowledge_bp.route("/outline/create", methods=["POST"])
def create_outline_node(novel_id):
    parent_id = request.form.get("parent_id", type=int) or None
    # 父节点归属校验：parent_id 必须指向同一本小说的大纲节点，
    # 否则会产生跨书父子关系，删除父书时子节点成孤儿/级联错乱
    if parent_id is not None:
        OutlineNode.query.filter_by(id=parent_id, novel_id=novel_id).first_or_404()
    max_order = db.session.query(db.func.max(OutlineNode.sort_order)).filter_by(
        novel_id=novel_id, parent_id=parent_id
    ).scalar()
    node = OutlineNode(
        novel_id=novel_id,
        parent_id=parent_id,
        sort_order=(max_order or 0) + 1,
        node_type=request.form.get("node_type", "chapter"),
        title=request.form.get("title", "").strip(),
        summary=request.form.get("summary", ""),
    )
    db.session.add(node)
    # 先 flush 拿到 node.id，ensure_chapter_for_node 才能把章节挂到节点上
    db.session.flush()
    # 「章」节点即章节：建节点的同时自动落写作章节，
    # 章节列表即刻可见，无需再逐节点点「创建章节」
    chapter = ensure_chapter_for_node(node)
    db.session.commit()
    if request.accept_mimetypes.best == "application/json":
        return jsonify({"ok": True, "node_id": node.id,
                        "chapter_number": chapter.chapter_number if chapter else None})
    return redirect(url_for("knowledge.outline_page", novel_id=novel_id))


@knowledge_bp.route("/outline/<int:node_id>/edit", methods=["POST"])
def edit_outline_node(novel_id, node_id):
    # 归属校验：防止跨小说编辑大纲节点
    node = OutlineNode.query.filter_by(id=node_id, novel_id=novel_id).first_or_404()
    for field in ["title", "summary", "node_type"]:
        val = request.form.get(field, "")
        if val:
            setattr(node, field, val)
    # 单一事实源：节点改动实时同步到关联章节，两边永远一致
    chapter = Chapter.query.filter_by(outline_node_id=node.id).first()
    if chapter:
        sync_chapter_from_node(chapter, node)
    db.session.commit()
    return redirect(url_for("knowledge.outline_page", novel_id=novel_id))


@knowledge_bp.route("/outline/<int:node_id>/edit-summary", methods=["POST"])
def edit_node_summary(novel_id, node_id):
    """章节创作页内联编辑大纲：写回节点并同步关联章节，返回 JSON。"""
    node = OutlineNode.query.filter_by(id=node_id, novel_id=novel_id).first_or_404()
    summary = request.form.get("summary")
    title = (request.form.get("title") or "").strip()
    if summary is None:
        return jsonify({"ok": False, "error": "缺少 summary 字段"}), 400
    node.summary = summary
    if title:
        node.title = title
    chapter = Chapter.query.filter_by(outline_node_id=node.id).first()
    outline_text = ""
    if chapter:
        sync_chapter_from_node(chapter, node)
        outline_text = chapter.outline
    db.session.commit()
    return jsonify({"ok": True, "summary": node.summary,
                    "title": node.title, "outline_text": outline_text})


@knowledge_bp.route("/outline/<int:node_id>/ai-summary", methods=["POST"])
def ai_node_summary(novel_id, node_id):
    """为大纲树节点 AI 生成固定格式摘要。

    只返回文本填回前端编辑框，不直接落库——人工确认后走既有保存链
    （edit/edit-summary，内含固定格式软校验）。prompt 的字段契约与
    AI 章节大纲、CLI 模板同源（outline_template.OUTLINE_FIELDS）。
    """
    from app.config_utils import get_effective_config
    from app.models import Character, Foreshadowing
    from app.services.llm import call_llm_sync, LLMError
    from app.services.outline_template import OUTLINE_FIELDS

    node = OutlineNode.query.filter_by(id=node_id, novel_id=novel_id).first_or_404()
    novel = db.session.get(Novel, novel_id)
    if node.node_type not in ("chapter", "scene"):
        return jsonify({"ok": False, "error": "卷节点不生成摘要"}), 400

    # 上下文：父卷 → 前两个兄弟章摘要 → 角色卡 → 活跃伏笔
    parent = db.session.get(OutlineNode, node.parent_id) if node.parent_id else None
    siblings = (OutlineNode.query.filter_by(novel_id=novel_id, parent_id=node.parent_id)
                .order_by(OutlineNode.sort_order).all())
    prev = [s for s in siblings
            if s.id != node.id and s.sort_order < (node.sort_order or 0)
            and (s.summary or "").strip()][-2:]

    char_lines = [f"- {c.name}：{(c.personality or '')[:40]}"
                  for c in Character.query.filter_by(novel_id=novel_id).limit(12)
                  if c.name]
    fs_rows = (Foreshadowing.query.filter_by(novel_id=novel_id)
               .filter(Foreshadowing.status.notin_(("resolved", "abandoned")))
               .limit(6).all())
    fs_lines = [f"- {f.title or (f.description or '')[:20]}" for f in fs_rows]

    system = (
        "你是一位资深小说大纲策划师。为大纲树的章节节点撰写摘要，"
        "必须严格按以下固定字段逐行输出（字段名原样保留，一个都不能少）：\n"
        + "\n".join(OUTLINE_FIELDS) + "\n\n"
        "硬性要求：出场人物与人物卡姓名完全一致（仅提及的标（背景提及），"
        "龙套不起名）；除场景节拍外全文不超过250字；"
        "禁止对白、心理与环境渲染；只输出摘要本身，不要任何解释。"
    )
    blocks = [f"小说：{novel.title}（{novel.genre or '未分类'}）"]
    if novel.synopsis:
        blocks.append("简介：" + novel.synopsis[:300])
    if novel.world_intro:
        blocks.append("世界观：" + novel.world_intro[:200])
    if parent:
        vol = f"所属卷：{parent.title}"
        if (parent.summary or "").strip():
            vol += f"（{parent.summary[:100]}）"
        blocks.append(vol)
    if prev:
        blocks.append("前情摘要：\n" + "\n".join(
            f"- {s.title}：{s.summary[:120]}" for s in prev))
    if char_lines:
        blocks.append("人物卡：\n" + "\n".join(char_lines))
    if fs_lines:
        blocks.append("活跃伏笔：\n" + "\n".join(fs_lines))
    node_line = f"当前节点：{node.title}"
    if (node.summary or "").strip():
        node_line += f"（旧摘要供参考，可重写：{node.summary[:150]}）"
    blocks.append(node_line)
    blocks.append("请输出该节点的固定格式摘要。")

    cfg = get_effective_config(novel, agent_type="outline")
    try:
        text = call_llm_sync(
            model=cfg["model_name"], messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": "\n\n".join(blocks)},
            ],
            api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=cfg.get("temperature", 0.7),
            max_tokens=cfg.get("max_tokens", 1024),
        )
    except LLMError as e:
        return jsonify({"ok": False, "error": str(e)}), 502
    summary = (text or "").strip()
    if not summary:
        return jsonify({"ok": False, "error": "AI 返回为空，请重试"}), 502
    return jsonify({"ok": True, "summary": summary})


@knowledge_bp.route("/outline/<int:node_id>/delete", methods=["POST"])
def delete_outline_node(novel_id, node_id):
    # 归属校验：防止跨小说删除大纲节点
    node = OutlineNode.query.filter_by(id=node_id, novel_id=novel_id).first_or_404()

    # 迭代式子树收集（BFS）：递归实现在深层大纲上会触发 Python 递归上限，
    # 且每层一次查询效率低；一次取全小说节点在内存里按 parent 指针闭包
    all_nodes = OutlineNode.query.filter_by(novel_id=novel_id).all()
    children_map = {}
    for n in all_nodes:
        children_map.setdefault(n.parent_id, []).append(n)
    to_delete = [node]
    stack = [node.id]
    while stack:
        pid = stack.pop()
        for child in children_map.get(pid, []):
            to_delete.append(child)
            stack.append(child.id)
    for n in to_delete:
        # 先解链章节(FK ON 下删除被引用节点会被拦截;viewonly 关系不做自动置空)
        Chapter.query.filter_by(outline_node_id=n.id).update({"outline_node_id": None})
        db.session.delete(n)
    db.session.commit()
    return redirect(url_for("knowledge.outline_page", novel_id=novel_id))
