"""chapter_runner（P3）——把写作链串成带人工闸门的流水线。

阶段：outline（缺才生成）→ body → gates（skill_gate ∥ ai_metric）→
converge（人味分不达标时定向收敛，回滚兜底）→ 人工闸门（默认停在这里；
auto_save=True 时落 AI 版本，仍不自动审批）。

纪律：自动化到「待人工审阅」为止；任一阶段失败即停，不跨闸门。
"""
import json
import logging

from app import db
from app.models import Novel, Chapter, OutlineNode
from app.config_utils import get_effective_config
from app.services.writer_chain import (
    build_writer_kwargs, build_scene_plan, collect_full_text,
    CHAPTER_WORD_TARGET,
)

logger = logging.getLogger(__name__)

# 细纲硬门禁：低于此长度的大纲视为「没有细纲」，禁止进入正文阶段
_MIN_OUTLINE_CHARS = 50


def run_chapter_pipeline(novel_id, chapter_number, user_directive="",
                         auto_save=False, converge=True,
                         word_target=CHAPTER_WORD_TARGET,
                         character_ids=None):
    """一键本章流水线。

    character_ids: 本章出场角色 id 列表；None=全部角色（缺省），[]=不注入角色档案。
    传给大纲生成与正文生成两处，控制角色档案注入范围（对齐 Web 出场角色勾选）。

    Returns:
        {"text", "stages": [{stage, ok, ...}], "human_score"?, "outline"?,
         "saved_version_id"?} 或 {"error", "stages"}。
    """
    from app.services.prompt_builder import (
        build_outline_prompt, build_writer_prompt, assemble_chapter_context)
    from app.services.prompt_builder.context import get_excitement_recent
    from app.services.skill_gate import run_gate
    from app.services.ai_metric import analyze_ai_tone

    stages = []
    chapter = (Chapter.query
               .filter_by(novel_id=novel_id, chapter_number=chapter_number)
               .first())
    if not chapter:
        return {"error": f"第{chapter_number}章不存在", "stages": stages}
    novel = Novel.query.get(novel_id)

    # ---- Stage 1: outline（已有则跳过）----
    # 已关联大纲树节点：用节点实时组装的大纲（摘要+分幕指引），
    # 不再走 AI 现编——大纲树的规划就是本章大纲
    if chapter.outline_node_id and not (chapter.outline or "").strip():
        from app.services.outline_sync import compose_node_outline
        node = OutlineNode.query.get(chapter.outline_node_id)
        if node:
            chapter.outline = compose_node_outline(node)
            db.session.commit()
    if not (chapter.outline or "").strip():
        cfg_o = get_effective_config(novel, agent_type="outline")
        ctx = assemble_chapter_context(novel_id, chapter_number, db,
                                       character_ids=character_ids)
        messages = build_outline_prompt(
            novel_title=novel.title, genre=novel.genre,
            synopsis=novel.synopsis, world_intro=novel.world_intro,
            chapter_title=chapter.title, chapter_number=chapter_number,
            characters=ctx["characters"], summaries=ctx["summaries"],
            foreshadowing_items=ctx["foreshadowing_items"], db=db,
            author_intent=novel.author_intent or "",
            current_focus=novel.current_focus or "",
            world_settings=ctx["world_settings"],
            excitement_recent=get_excitement_recent(novel_id),
        )
        outline_text = collect_full_text(messages, cfg_o).strip()
        if not outline_text:
            stages.append({"stage": "outline", "ok": False})
            return {"error": "大纲生成为空", "stages": stages}
        chapter.outline = outline_text
        db.session.commit()
        stages.append({"stage": "outline", "ok": True, "chars": len(outline_text)})
    else:
        stages.append({"stage": "outline", "ok": True, "skipped": "已有大纲"})

    # 细纲硬门禁（戏剧字段，兼容旧格式软通过）：无戏不进正文
    from app.services.outline_drama import write_ready_outline, outline_gate_error
    outline_ready = (chapter.outline or "").strip()
    ready = write_ready_outline(outline_ready)
    stages.append({"stage": "outline_drama", "ok": ready["ok"],
                   "soft_pass": ready.get("soft_pass"),
                   "has": ready["has"], "warnings": ready["warnings"]})
    if not ready["ok"]:
        stages.append({"stage": "outline_gate", "ok": False,
                       "blocking": ready["blocking"]})
        return {
            "error": outline_gate_error(outline_ready),
            "stages": stages,
            "drama": ready,
        }
    # 软通过：把缺失字段转成戏剧备注，并入大纲注入写作包
    outline_for_write = ready.get("effective_outline") or outline_ready
    if ready.get("drama_notes"):
        chapter.outline = outline_for_write
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            outline_for_write = chapter.outline or outline_ready

    # ---- Stage 1b: event plan（StoryWriter planning 层）----
    # 从大纲提炼 2-4 个必须推进的事件（目标-冲突-微结局），落库供写作包注入
    events = []
    try:
        from app.services.chapter_events import ensure_event_plan
        events = ensure_event_plan(novel_id, chapter_number, outline=outline_for_write)
        stages.append({"stage": "event_plan", "ok": True, "count": len(events)})
    except Exception as e:
        logger.warning("事件清单提取降级: %s", e)
        stages.append({"stage": "event_plan", "ok": True, "skipped": str(e)[:120]})

    # ---- Stage 2: body ----
    kw, novel = build_writer_kwargs(novel_id, chapter_number, outline_for_write,
                                    user_directive=user_directive,
                                    character_ids=character_ids)
    cfg_w = get_effective_config(novel, agent_type="writer")
    # 注入观测层报告（纯观测，不进 prompt；进 stages 与版本 model_params_json）
    injection_report = kw.pop("injection_report", None) or {}
    if injection_report.get("dims"):
        stages.append({"stage": "injection_report",
                       "dims": injection_report["dims"],
                       "sizes": injection_report.get("sizes", {}),
                       "total_chars": injection_report.get("total_chars", 0),
                       "degraded": injection_report.get("degraded", [])})
    messages = build_writer_prompt(
        novel_title=novel.title, chapter_title=chapter.title,
        outline=outline_for_write, user_directive=user_directive, db=db,
        chapter_number=chapter_number, **kw)
    # 节拍级生成计划（大纲含 ≥2 拍时拆锅逐拍写；None 则整章一锅原路径）
    scene_plan = build_scene_plan(outline_for_write, kw=kw,
                                  word_target=word_target,
                                  novel_id=novel_id, chapter_number=chapter_number)
    if scene_plan is not None:
        scene_plan["prev_ending"] = kw.get("prev_ending", "")
        stages.append({"stage": "beat_plan", "ok": True,
                       "beats": len(scene_plan["beats"]),
                       "tension": scene_plan["tension"],
                       "beat_tensions": scene_plan["beat_tensions"]})
    try:
        text = collect_full_text(messages, cfg_w, word_target=word_target,
                                 scene_plan=scene_plan).strip()
    except Exception as e:
        stages.append({"stage": "body", "ok": False, "error": str(e)[:200]})
        return {"error": f"正文生成失败：{e}", "stages": stages}
    stages.append({"stage": "body", "ok": bool(text), "chars": len(text)})
    if not text:
        return {"error": "正文生成为空", "stages": stages}

    # ---- Stage 3: gates（确定性门禁束：人味双轨 = 去AI + 追读好看度）----
    from app.services.web_novel_gate import analyze_web_novel
    gate = run_gate(text)
    tone = analyze_ai_tone(text)
    protagonist_names = [c.get("name") for c in kw.get("characters", [])
                         if c.get("name")]
    readability = analyze_web_novel(
        text, outline=outline_for_write or "", event_count=len(events),
        is_first_chapter=(chapter_number == 1),
        protagonist_names=protagonist_names)
    human_score = tone.get("human_score")
    read_score = readability.get("readability_score")
    gate_passed = bool(gate.get("passed"))
    tone_passed = bool(tone.get("passed"))
    read_passed = bool(readability.get("passed"))
    stages.append({"stage": "gates", "ok": gate_passed and tone_passed and read_passed,
                   "gate_passed": gate.get("passed"),
                   "human_score": human_score,
                   "readability_score": read_score,
                   "readability_passed": read_passed})

    # ---- Stage 3b: 张力审计（零 LLM）----
    # 章张力档 vs 正文实测情绪强度：落差大说明"规划了强场面但写平了"，
    # 写入 Reflexion 供下一章主动修正（审计闭环，不改本章稿）。
    # 另做全书平线体检（jarvis-write is_flat 的章级版）：近几章实测强度
    # 极差过小 = 跨章平线，同样进 Reflexion。
    try:
        from app.services.tension_bus import (
            chapter_tension as _chapter_tension, measured_intensity,
            intensity_gap_note, parse_outline_field,
            pacing_debt, hook_progression,
        )
        from app.services.reflexion import add_reflexion_note
        level = (scene_plan or {}).get("tension") or _chapter_tension(
            novel_id, chapter_number, outline_for_write)
        measured = measured_intensity(text)
        gap = intensity_gap_note(
            level, measured,
            tone_text=parse_outline_field(outline_for_write, "情感基调"))
        audit = {"stage": "tension_audit", "ok": not gap,
                 "tension": level, "measured": measured}
        if gap:
            add_reflexion_note(novel_id, chapter_number, gap, source="tension")
        # 爽点间距账本：逐章密度序列 + 本章逐拍曲线
        try:
            from app.models import StoryState
            ss = StoryState.query.filter_by(novel_id=novel_id).first()
            hist = []
            if ss and (ss.excitement_history or "").strip():
                hist = json.loads(ss.excitement_history)
            debts = pacing_debt(
                hist, beat_tensions=(scene_plan or {}).get("beat_tensions"))
            audit["pacing_debts"] = debts
            for d in debts:
                add_reflexion_note(novel_id, chapter_number, d, source="tension")
            if debts:
                audit["ok"] = False
        except Exception as e:
            logger.warning("爽点账本降级: %s", e)
        # 钩子递进（advisory）：本章钩 vs 上章钩，沿三维应单调推进
        try:
            from app.models import Chapter as _Chapter
            prev_ch = (_Chapter.query
                       .filter_by(novel_id=novel_id,
                                  chapter_number=chapter_number - 1)
                       .first())
            prev_hook = (parse_outline_field(prev_ch.outline or "", "结尾钩子")
                         if prev_ch and prev_ch.outline else "")
            prog = hook_progression(
                prev_hook, parse_outline_field(outline_for_write, "结尾钩子"),
                protagonist_names=protagonist_names or [])
            if prog is not None:
                audit["hook_progression"] = prog["score"]
                if prog["score"] == 0:
                    note = "章尾钩零递进（更具体/更贴身/更难撤回一个都没占）：下一章钩子至少推进一维"
                    add_reflexion_note(novel_id, chapter_number, note,
                                       source="tension")
        except Exception as e:
            logger.warning("钩子递进降级: %s", e)
        try:
            from app.models import Chapter as _Chapter
            recent = (_Chapter.query
                      .filter(_Chapter.novel_id == novel_id,
                              _Chapter.chapter_number < chapter_number)
                      .order_by(_Chapter.chapter_number.desc())
                      .limit(5).all())
            vals = [measured_intensity(ch.versions[-1].content or "")
                    for ch in recent if ch.versions]
            vals = [v for v in vals if v is not None]
            if measured is not None:
                vals.append(measured)
            if len(vals) >= 3:
                # 阈值定标：书 1 实测 24 章情绪强度 5-15/千字、章间自然
                # 波动极差约 5+；极差 <3 且连续多章即"全书平线"（jarvis-write
                # is_flat 的章级版），误伤面小（仅提示，不阻断）
                spread = max(vals) - min(vals)
                audit["recent_spread"] = round(spread, 1)
                if spread < 3:
                    audit["ok"] = False
                    flat_note = (f"近 {len(vals)} 章情绪强度近乎平线"
                                 f"（极差 {spread:.1f}/千字）：节奏单调，"
                                 "下一章至少安排一场正面冲突并把峰值写足。")
                    add_reflexion_note(novel_id, chapter_number, flat_note,
                                       source="tension")
        except Exception as e:
            logger.warning("平线体检降级: %s", e)
        stages.append(audit)
    except Exception as e:
        logger.warning("张力审计降级: %s", e)

    # ---- Stage 4: convergence（人味分/好看度不达标才触发，回滚兜底）----
    final_score = human_score
    should_converge = (
        converge
        and (not gate_passed
             or not tone_passed
             or not read_passed
             or (human_score is not None and human_score < 90)
             or (read_score is not None and read_score < 70))
    )
    if should_converge:
        from app.services.tone_convergence import converge_tone
        cfg_r = get_effective_config(novel, agent_type="rewrite")
        conv = converge_tone(text, cfg_r, max_rounds=2, outline=outline_for_write or "")
        text = conv["text"]
        final_score = conv["final_score"]
        # 收敛会重写全文，门禁必须对最终稿复测，不能沿用旧稿结果。
        gate = run_gate(text)
        tone = analyze_ai_tone(text)
        readability = analyze_web_novel(
            text, outline=outline_for_write or "", event_count=len(events),
            is_first_chapter=(chapter_number == 1),
            protagonist_names=protagonist_names)
        gate_passed = bool(gate.get("passed"))
        tone_passed = bool(tone.get("passed"))
        read_passed = bool(readability.get("passed"))
        final_score = tone.get("human_score", final_score)
        read_score = readability.get("readability_score")
        stages.append({"stage": "converge", "ok": True,
                       "converged": conv["converged"],
                       "score": final_score,
                       "readability_score": read_score,
                       "gate_passed": gate_passed,
                       "readability_passed": read_passed})
        # 跨章 Reflexion：收敛失败时把原因写入章节笔记，下一章注入
        try:
            from app.services.reflexion import note_from_convergence
            note_from_convergence(conv, novel_id, chapter_number)
        except Exception as e:
            logger.warning("Reflexion 笔记写入降级: %s", e)
        # 好看度失败也进 Reflexion：下一章主动避开
        try:
            from app.services.reflexion import add_reflexion_note
            from app.services.web_novel_gate import build_readability_instructions
            rinstr = build_readability_instructions(text, outline_for_write or "")
            if not read_passed and rinstr:
                add_reflexion_note(novel_id, chapter_number,
                                   "追读结构：" + rinstr.split("\n", 1)[-1][:120],
                                   source="readability")
        except Exception as e:
            logger.warning("好看度 Reflexion 降级: %s", e)
    else:
        stages.append({"stage": "converge", "ok": True,
                       "skipped": "人味分/好看度达标或未开启"})

    if not gate_passed or not tone_passed or not read_passed:
        stages.append({"stage": "gates_final", "ok": False,
                       "gate_passed": gate_passed,
                       "tone_passed": tone_passed,
                       "readability_passed": read_passed,
                       "human_score": final_score,
                       "readability_score": read_score})
        hint = ""
        if not read_passed:
            hint = "（追读结构未达标：优先改大纲契约/钩子，而非只跑去AI收敛）"
        return {
            "error": f"终稿门禁未通过，已停在人工审阅前{hint}",
            "text": text,
            "stages": stages,
            "human_score": final_score,
            "readability_score": read_score,
            "readability": readability,
            "outline": outline_for_write,
        }

    # ---- Stage 5: 人工闸门 ----
    result = {"text": text, "stages": stages, "human_score": final_score,
              "outline": outline_for_write}
    if auto_save:
        from app.services.chapter_approval import create_version_record
        try:
            # prompt 留痕：审批页可查本章发模型的完整 prompt（透明度第一步）
            version = create_version_record(novel_id, chapter_number, text,
                                            source="ai",
                                            prompt_used=json.dumps(
                                                messages, ensure_ascii=False),
                                            model_params_json=json.dumps(
                                                {"injection_report": injection_report},
                                                ensure_ascii=False))
            result["saved_version_id"] = version.id
            stages.append({"stage": "save", "ok": True,
                           "version_id": version.id})
        except Exception as e:
            stages.append({"stage": "save", "ok": False, "error": str(e)[:200]})
    else:
        stages.append({"stage": "human_gate", "ok": True,
                       "action": "等待人工审阅/保存"})
    return result
