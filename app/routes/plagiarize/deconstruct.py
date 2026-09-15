"""拆书复刻路由 —— 对标书拆解 → 待确认采纳 → 复刻生成（长篇/短篇）。"""
from flask import request, jsonify
from app.models import db, PlagiarizeTask, DeconstructItem
from app.routes.auth import login_required
from app.routes.plagiarize import plagiarize_bp
from app.services.book_deconstruct import (
    deconstruct_source, adopt_item, adopt_all_items,
    apply_blueprint_long, apply_blueprint_short, _load_elements,
    materialized_items_count, rework_item, rework_all_items,
    CHARACTER_KEYS, WORLD_KEYS, OUTLINE_KEYS, FORESHADOW_KEYS,
)
from app.services.llm import LLMError
from app.services import long_task

_KEYS_BY_KIND = {"character": CHARACTER_KEYS, "world": WORLD_KEYS,
                 "outline": OUTLINE_KEYS, "foreshadow": FORESHADOW_KEYS}


@plagiarize_bp.route("/<int:task_id>/deconstruct", methods=["POST"])
@login_required
def run_deconstruct(task_id):
    """启动拆书(P0-3 后台任务+P0-6 原子认领),前端轮询进度。"""
    task = PlagiarizeTask.query.get_or_404(task_id)
    if not task.source_text:
        return jsonify({"ok": False, "message": "请先提供对标书文本"}), 400
    if long_task.has_running("deconstruct", task_id) or task.status in ("summarizing", "deconstructing"):
        return jsonify({"ok": False, "message": "拆书正在进行中，请勿重复触发"}), 409
    # 已有落库条目时禁止重拆：重拆会清空队列，但知识库行无法级联回收，必然产生重复
    materialized = materialized_items_count(task_id)
    if materialized:
        return jsonify({"ok": False, "message": (
            f"该任务已有 {materialized} 条条目写入目标书知识库，重新拆书会造成队列与知识库不一致。"
            "如需重拆：先在知识库删除对应的人物/世界观/大纲，或新建拆书任务。")}), 409
    # P0-6 原子认领:UPDATE ... WHERE status NOT IN,杜绝双标签页竞窗
    claimed = db.session.query(PlagiarizeTask).filter(
        PlagiarizeTask.id == task_id,
        PlagiarizeTask.status.notin_(("summarizing", "deconstructing")),
    ).update({PlagiarizeTask.status: "deconstructing"}, synchronize_session=False)
    db.session.commit()
    if not claimed:
        return jsonify({"ok": False, "message": "拆书正在进行中，请勿重复触发"}), 409
    lt = long_task.start_long_task("deconstruct", task_id, lambda: deconstruct_source(task_id))
    return jsonify({"ok": True, "task_id": lt.id, "long_task_id": lt.id})


@plagiarize_bp.route("/long-tasks/<int:lt_id>", methods=["GET"])
@login_required
def long_task_status(lt_id):
    """长任务进度轮询。"""
    data = long_task.task_progress(lt_id)
    if data is None:
        return jsonify({"ok": False, "message": "任务不存在"}), 404
    return jsonify({"ok": True, **data})


@plagiarize_bp.route("/long-tasks/<int:lt_id>/cancel", methods=["POST"])
@login_required
def long_task_cancel(lt_id):
    """取消进行中的长任务（协作式：当前批次完成后停止）。"""
    ok, msg = long_task.cancel_task(lt_id)
    return jsonify({"ok": ok, "message": msg})


@plagiarize_bp.route("/items/<int:item_id>/restore", methods=["POST"])
@login_required
def restore_item_route(item_id):
    """恢复已丢弃的条目为待确认（反悔通道）。"""
    item = DeconstructItem.query.get_or_404(item_id)
    if item.status != "discarded":
        return jsonify({"ok": False, "message": "仅已丢弃的条目可恢复"}), 400
    item.status = "pending"
    db.session.commit()
    return jsonify({"ok": True, "message": f"已恢复「{item.title}」为待确认"})


@plagiarize_bp.route("/<int:task_id>/save-report", methods=["POST"])
@login_required
def save_report(task_id):
    """保存拆书报告与微创新指令（表单提交了字段就落值，可显式清空）。"""
    task = PlagiarizeTask.query.get_or_404(task_id)
    if "report_text" in request.form:
        task.report_text = request.form.get("report_text", "")
    if "modifications_text" in request.form:
        task.modifications_text = request.form.get("modifications_text", "")
    db.session.commit()
    return jsonify({"ok": True})


@plagiarize_bp.route("/items/<int:item_id>/adopt", methods=["POST"])
@login_required
def adopt_item_route(item_id):
    """采纳一条待确认条目（可携带用户修改后的字段；空值=用户清空该字段）。"""
    item = DeconstructItem.query.get_or_404(item_id)
    keys = _KEYS_BY_KIND.get(item.kind, ())
    modified = {k: (request.form.get(k) or "") for k in keys}
    # 全部字段为空视为「原样采纳」（未携带修改），否则整体作为修改稿
    if not any(str(v).strip() for v in modified.values()):
        modified = None
    ok, msg, target_id = adopt_item(item_id, modified=modified)
    return jsonify({"ok": ok, "message": msg, "target_id": target_id})


@plagiarize_bp.route("/items/<int:item_id>/discard", methods=["POST"])
@login_required
def discard_item_route(item_id):
    """丢弃一条待确认条目（已落库的条目不可丢弃，保持与知识库一致）。"""
    item = DeconstructItem.query.get_or_404(item_id)
    if item.status == "adopted" and item.target_id:
        return jsonify({"ok": False,
                        "message": "该条目已写入知识库，请到目标书的知识库页面删除对应条目"}), 400
    item.status = "discarded"
    # 保留 modified_content:「恢复」才是完整反悔(改写稿/编辑稿一并找回)
    db.session.commit()
    return jsonify({"ok": True, "message": f"已丢弃「{item.title}」"})


@plagiarize_bp.route("/<int:task_id>/items/adopt-all", methods=["POST"])
@login_required
def adopt_all_route(task_id):
    """全部待确认条目按拆解原稿采纳。"""
    ok, msg = adopt_all_items(task_id)
    return jsonify({"ok": ok, "message": msg})


@plagiarize_bp.route("/items/<int:item_id>/reset", methods=["POST"])
@login_required
def reset_item_route(item_id):
    """还原条目为拆解原稿（清空修改稿；已落库的不可还原）。"""
    item = DeconstructItem.query.get_or_404(item_id)
    if item.status == "adopted" and item.target_id:
        return jsonify({"ok": False, "message": "该条目已写入知识库，不可还原"}), 400
    item.modified_content = ""
    db.session.commit()
    return jsonify({"ok": True, "message": f"已还原「{item.title}」为拆解原稿"})


@plagiarize_bp.route("/items/<int:item_id>/rework", methods=["POST"])
@login_required
def rework_item_route(item_id):
    """AI 差异化改写单条条目：改写稿写入修改稿，人工复核后采纳。"""
    ok, msg, warnings = rework_item(item_id)
    return jsonify({"ok": ok, "message": msg, "warnings": warnings})


@plagiarize_bp.route("/<int:task_id>/items/rework-all", methods=["POST"])
@login_required
def rework_all_route(task_id):
    """AI 批量成套改写(P0-3 后台任务):映射表+差异轴+逐条改写,前端轮询进度。"""
    PlagiarizeTask.query.get_or_404(task_id)
    if long_task.has_running("rework_all", task_id):
        return jsonify({"ok": False, "message": "批量改写正在进行中，请勿重复触发"}), 409
    lt = long_task.start_long_task("rework_all", task_id, lambda: rework_all_items(task_id))
    return jsonify({"ok": True, "task_id": lt.id, "long_task_id": lt.id})


@plagiarize_bp.route("/<int:task_id>/generate-long", methods=["POST"])
@login_required
def generate_long(task_id):
    """复刻为长篇(P0-3 后台任务):建/选小说 + 采纳条目入知识库 + 大纲树 + 章节。

    run=1 时串行跑章节流水线(逐章门禁+AI味收敛+停人工审阅)。前端轮询进度,
    进度尾部 [NOVEL_ID: n] 供跳转。
    """
    task = PlagiarizeTask.query.get_or_404(task_id)
    if not _load_elements(task):
        return jsonify({"ok": False, "message": "该任务尚未完成拆书，请先「开始拆书」"}), 400
    if long_task.has_running("generate_long", task_id):
        return jsonify({"ok": False, "message": "复刻生成正在进行中，请勿重复触发"}), 409
    title = request.form.get("title", "").strip()
    genre = request.form.get("genre", "").strip()
    chapters = min(max(request.form.get("chapters", type=int) or 5, 1), 200)
    target_novel_id = request.form.get("target_novel_id", type=int)
    run = request.form.get("run", "0") == "1"

    def _gen():
        try:
            novel, created, message = apply_blueprint_long(task_id, title=title, genre=genre,
                                                           novel_id=target_novel_id,
                                                           fallback_chapters=chapters)
        except Exception as e:  # 统一转为进度流失败标记(执行器会置任务失败)
            db.session.rollback()
            yield f"[失败: {e}]\n"
            raise
        if novel is None:
            yield f"[失败: {message}]\n"
            raise RuntimeError(message)
        yield f"[落地] {message}\n"
        to_generate = list(created)
        if to_generate:
            yield f"[大纲] 已写入 {len(to_generate)} 个新章节\n"
        else:
            adopted_outline = DeconstructItem.query.filter_by(
                task_id=task_id, kind="outline", status="adopted").count()
            if adopted_outline:
                yield "[大纲] 已采纳的大纲此前已全部入书，本次没有新增章节\n"
            else:
                yield "[大纲] 没有已采纳的大纲条目（待确认区的大纲可逐条编辑后采纳）\n"
        if run and not to_generate:
            from app.services.book_deconstruct import unwritten_chapters
            to_generate = unwritten_chapters(novel.id, limit=chapters)
            if to_generate:
                yield f"[补生成] 目标书有 {len(to_generate)} 章尚无正文，本次逐章生成\n"
        if run and to_generate:
            from app.services.chapter_runner import run_chapter_pipeline
            from app.services.similarity_check import check_chapter_vs_blueprint
            directive = (task.modifications_text or "").strip()
            for i, ch in enumerate(to_generate, start=1):
                yield f"[第{i}/{len(to_generate)}章] {ch.title} 生成中...\n"
                try:
                    result = run_chapter_pipeline(novel.id, ch.chapter_number,
                                                  user_directive=directive, auto_save=True)
                    yield f"✓ 第{i}章完成，人味分 {result.get('human_score')}\n"
                    # 生成期差异化闭环:雷同检测(advisory)→ 超标触发式重生一次(jarvis-write 毙+重生语义)
                    rep = check_chapter_vs_blueprint(task.id, result.get("text") or "")
                    if rep:
                        pct = int(rep["containment"] * 100)
                        if rep["verdict"] == "alarm":
                            yield (f"⚠ 雷同检测[第{i}章]：雷同度 {pct}%（对标书第{rep['ref_chapter']}章摘要），"
                                   f"连续13字相同 {len(rep['redlines'])} 处——自动带整改清单重生一次\n")
                            bans = "；".join(h["quote"][:30] for h in rep["redlines"][:3]) or "情节骨架紧跟原书"
                            stronger = ((directive + "\n") if directive else "") + (
                                f"【上一稿雷同整改（必须执行）】上一稿与对标书雷同度 {pct}%。"
                                f"以下片段必须换成全新设计：{bans}。"
                                "只换承载方式，节拍功能保持不变。")
                            result2 = run_chapter_pipeline(novel.id, ch.chapter_number,
                                                           user_directive=stronger, auto_save=True)
                            rep2 = check_chapter_vs_blueprint(task.id, result2.get("text") or "")
                            pct2 = int((rep2 or {}).get("containment", 0) * 100)
                            if rep2 and rep2["verdict"] != "alarm":
                                yield f"✓ 雷同检测[第{i}章]：重生后雷同度从 {pct}% 降至 {pct2}%，保留新稿\n"
                            else:
                                yield f"⚠ 雷同检测[第{i}章]：重生后仍为 alarm 级（{pct2 if rep2 else pct}%），请人工审阅本章\n"
                        elif rep["verdict"] == "warn":
                            yield f"⚠ 雷同检测[第{i}章]：雷同度 {pct}% 偏高，建议人工审阅\n"
                        else:
                            yield f"✓ 雷同检测[第{i}章]：通过（{pct}%）\n"
                except Exception as e:
                    yield f"✗ 第{i}章失败: {e}（可在章节页单独重跑）\n"
        yield f"[NOVEL_ID: {novel.id}]\n"

    lt = long_task.start_long_task("generate_long", task_id, _gen)
    return jsonify({"ok": True, "task_id": lt.id, "long_task_id": lt.id})


@plagiarize_bp.route("/<int:task_id>/generate-short", methods=["POST"])
@login_required
def generate_short(task_id):
    """复刻为短篇：建短篇，已采纳条目进策划字段 + 大纲节点。"""
    PlagiarizeTask.query.get_or_404(task_id)
    title = request.form.get("title", "").strip()
    genre = request.form.get("genre", "").strip()
    word_target = request.form.get("word_target", type=int) or 3000
    try:
        story, message = apply_blueprint_short(task_id, title=title, genre=genre, word_target=word_target)
    except LLMError as e:
        return jsonify({"ok": False, "message": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(e)}), 400
    return jsonify({"ok": True, "message": message, "story_id": story.id})
