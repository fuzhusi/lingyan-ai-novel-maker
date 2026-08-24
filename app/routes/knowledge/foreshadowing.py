"""伏笔管理路由：CRUD + 超时检测 + 状态推进。"""
from flask import render_template, request, redirect, url_for, jsonify
from app.models import db, Novel, Foreshadowing, Chapter
from app.routes.knowledge import knowledge_bp


@knowledge_bp.route("/foreshadowing")
def foreshadowing_page(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    items = Foreshadowing.query.filter_by(novel_id=novel_id).order_by(
        Foreshadowing.status, Foreshadowing.created_at.desc()
    ).all()
    chapters = db.session.execute(
        db.text("SELECT chapter_number FROM chapters WHERE novel_id = :nid ORDER BY chapter_number"),
        {"nid": novel_id}
    ).fetchall()
    chapter_nums = [r[0] for r in chapters]
    return render_template("foreshadowing.html", novel=novel, items=items, chapter_nums=chapter_nums)


@knowledge_bp.route("/foreshadowing/create", methods=["POST"])
def create_foreshadowing(novel_id):
    importance = request.form.get("importance", type=int) or 5
    if importance >= 9:
        threshold = 30
    elif importance >= 7:
        threshold = 20
    elif importance >= 4:
        threshold = 15
    else:
        threshold = 10

    item = Foreshadowing(
        novel_id=novel_id,
        title=request.form.get("title", "").strip(),
        description=request.form.get("description", ""),
        planted_chapter=request.form.get("planted_chapter", type=int) or None,
        resolve_chapter=request.form.get("resolve_chapter", type=int) or None,
        status=request.form.get("status", "open"),
        importance=importance,
        timeout_threshold=request.form.get("timeout_threshold", type=int) or threshold,
        notes=request.form.get("notes", ""),
    )
    db.session.add(item)
    db.session.commit()
    return redirect(url_for("knowledge.foreshadowing_page", novel_id=novel_id))


@knowledge_bp.route("/foreshadowing/<int:fs_id>/edit", methods=["POST"])
def edit_foreshadowing(novel_id, fs_id):
    # 归属校验：伏笔必须属于当前小说
    fs = Foreshadowing.query.filter_by(id=fs_id, novel_id=novel_id).first_or_404()
    # status 不在可编辑字段中：状态推进必须走 /advance 的状态机校验，
    # 直接表单改状态会绕过转移合法性检查（如 resolved → open 回退）
    for field in ["title", "description", "notes"]:
        val = request.form.get(field, "")
        if val:
            setattr(fs, field, val)
    for field in ["planted_chapter", "resolve_chapter", "importance", "timeout_threshold"]:
        val = request.form.get(field, type=int)
        if val is not None:
            setattr(fs, field, val if val > 0 else None)
    db.session.commit()
    return redirect(url_for("knowledge.foreshadowing_page", novel_id=novel_id))


@knowledge_bp.route("/foreshadowing/<int:fs_id>/delete", methods=["POST"])
def delete_foreshadowing(novel_id, fs_id):
    # 归属校验：防止跨小说删除伏笔
    fs = Foreshadowing.query.filter_by(id=fs_id, novel_id=novel_id).first_or_404()
    db.session.delete(fs)
    db.session.commit()
    return redirect(url_for("knowledge.foreshadowing_page", novel_id=novel_id))


# ---------------------------------------------------------------------------
# API 端点
# ---------------------------------------------------------------------------

@knowledge_bp.route("/api/kb-context")
def api_kb_context(novel_id):
    """Return JSON of all knowledge base items for a novel (used by chapter form)."""
    from app.models import Character, WorldSetting

    characters = Character.query.filter_by(novel_id=novel_id).order_by(Character.name).all()
    world_settings = WorldSetting.query.filter_by(novel_id=novel_id).order_by(
        WorldSetting.category, WorldSetting.title
    ).all()
    foreshadowing = Foreshadowing.query.filter_by(
        novel_id=novel_id, status="open"
    ).all()

    return jsonify({
        "characters": [
            {"id": c.id, "name": c.name} for c in characters
        ],
        "world_settings": [
            {"id": ws.id, "category": ws.category, "title": ws.title} for ws in world_settings
        ],
        "foreshadowing": [
            {"id": f.id, "description": f.description} for f in foreshadowing
        ],
    })


@knowledge_bp.route("/api/foreshadowing/timeout-check")
def foreshadow_timeout_check(novel_id):
    """Check for foreshadowing items that have exceeded their timeout threshold."""
    current_chapter = request.args.get("current_chapter", type=int)
    if not current_chapter:
        latest = Chapter.query.filter_by(novel_id=novel_id).order_by(
            Chapter.chapter_number.desc()).first()
        current_chapter = latest.chapter_number if latest else 0

    # reclaimable 同样在等回收，超时检测必须包含（此前遗漏导致
    # "已可回收但一直没人收"的伏笔永远不会出现在警告里）
    active = Foreshadowing.query.filter_by(novel_id=novel_id).filter(
        Foreshadowing.status.in_(["open", "planned", "buried", "advancing", "reclaimable"])
    ).all()

    warnings = []
    for fs in active:
        planted = fs.planted_chapter or 0
        threshold = fs.timeout_threshold or 15
        age = current_chapter - planted if planted else 0

        if age > threshold and planted > 0:
            severity = "critical" if fs.importance >= 9 else "high" if fs.importance >= 7 else "medium"
            warnings.append({
                "id": fs.id,
                "title": fs.title or fs.description[:50],
                "importance": fs.importance,
                "plantedChapter": planted,
                "age": age,
                "threshold": threshold,
                "status": fs.status,
                "severity": severity,
            })

    warnings.sort(key=lambda x: -x["importance"])

    return jsonify({
        "currentChapter": current_chapter,
        "timeoutWarnings": warnings,
        "totalWarnings": len(warnings),
    })


@knowledge_bp.route("/api/foreshadowing/<int:fs_id>/advance", methods=["POST"])
def advance_foreshadow(novel_id, fs_id):
    """Advance foreshadowing state: open→planned→buried→advancing→reclaimable→resolved."""
    # 归属校验：防止跨小说推进伏笔状态机
    fs = Foreshadowing.query.filter_by(id=fs_id, novel_id=novel_id).first_or_404()
    data = request.get_json(silent=True) or {}
    new_status = data.get("status", "")

    valid_transitions = {
        "open": ["planned", "buried"],
        "planned": ["buried", "abandoned"],
        "buried": ["advancing", "abandoned"],
        "advancing": ["reclaimable", "buried", "abandoned"],
        "reclaimable": ["resolved", "abandoned"],
        "resolved": [],
        "abandoned": [],
    }

    allowed = valid_transitions.get(fs.status, [])
    if new_status not in allowed:
        return jsonify({
            "error": f"Invalid transition: {fs.status} → {new_status}",
            "allowed": allowed,
        }), 400

    old_status = fs.status
    fs.status = new_status

    if new_status == "resolved":
        latest = Chapter.query.filter_by(novel_id=novel_id).order_by(
            Chapter.chapter_number.desc()).first()
        if latest:
            fs.resolve_chapter = latest.chapter_number

    db.session.commit()

    return jsonify({
        "ok": True,
        "id": fs.id,
        "oldStatus": old_status,
        "newStatus": new_status,
    })
