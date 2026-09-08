"""chapter_runner（P3）——把写作链串成带人工闸门的流水线。

阶段：outline（缺才生成）→ body → gates（skill_gate ∥ ai_metric）→
converge（人味分不达标时定向收敛，回滚兜底）→ 人工闸门（默认停在这里；
auto_save=True 时落 AI 版本，仍不自动审批）。

纪律：自动化到「待人工审阅」为止；任一阶段失败即停，不跨闸门。
"""
import logging

from app import db
from app.models import Novel, Chapter
from app.config_utils import get_effective_config
from app.services.writer_chain import (
    build_writer_kwargs, collect_full_text, CHAPTER_WORD_TARGET,
)

logger = logging.getLogger(__name__)


def run_chapter_pipeline(novel_id, chapter_number, user_directive="",
                         auto_save=False, converge=True,
                         word_target=CHAPTER_WORD_TARGET):
    """一键本章流水线。

    Returns:
        {"text", "stages": [{stage, ok, ...}], "human_score"?, "outline"?,
         "saved_version_id"?} 或 {"error", "stages"}。
    """
    from app.services.prompt_builder import (
        build_outline_prompt, build_writer_prompt, assemble_chapter_context)
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
    if not (chapter.outline or "").strip():
        cfg_o = get_effective_config(novel, agent_type="outline")
        ctx = assemble_chapter_context(novel_id, chapter_number, db)
        messages = build_outline_prompt(
            novel_title=novel.title, genre=novel.genre,
            synopsis=novel.synopsis, world_intro=novel.world_intro,
            chapter_title=chapter.title, chapter_number=chapter_number,
            characters=ctx["characters"], summaries=ctx["summaries"],
            foreshadowing_items=ctx["foreshadowing_items"], db=db,
            author_intent=novel.author_intent or "",
            current_focus=novel.current_focus or "",
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

    # ---- Stage 2: body ----
    kw, novel = build_writer_kwargs(novel_id, chapter_number, chapter.outline,
                                    user_directive=user_directive)
    cfg_w = get_effective_config(novel, agent_type="writer")
    messages = build_writer_prompt(
        novel_title=novel.title, chapter_title=chapter.title,
        outline=chapter.outline, user_directive=user_directive, db=db, **kw)
    try:
        text = collect_full_text(messages, cfg_w, word_target=word_target).strip()
    except Exception as e:
        stages.append({"stage": "body", "ok": False, "error": str(e)[:200]})
        return {"error": f"正文生成失败：{e}", "stages": stages}
    stages.append({"stage": "body", "ok": bool(text), "chars": len(text)})
    if not text:
        return {"error": "正文生成为空", "stages": stages}

    # ---- Stage 3: gates（确定性门禁束）----
    gate = run_gate(text)
    tone = analyze_ai_tone(text)
    human_score = tone.get("human_score")
    gate_passed = bool(gate.get("passed"))
    tone_passed = bool(tone.get("passed"))
    stages.append({"stage": "gates", "ok": gate_passed and tone_passed,
                   "gate_passed": gate.get("passed"),
                   "human_score": human_score})

    # ---- Stage 4: convergence（人味分不达标才触发，回滚兜底）----
    final_score = human_score
    should_converge = (
        converge
        and (not gate_passed
             or not tone_passed
             or (human_score is not None and human_score < 90))
    )
    if should_converge:
        from app.services.tone_convergence import converge_tone
        cfg_r = get_effective_config(novel, agent_type="rewrite")
        conv = converge_tone(text, cfg_r, max_rounds=1)
        text = conv["text"]
        final_score = conv["final_score"]
        # 收敛会重写全文，门禁必须对最终稿复测，不能沿用旧稿结果。
        gate = run_gate(text)
        tone = analyze_ai_tone(text)
        gate_passed = bool(gate.get("passed"))
        tone_passed = bool(tone.get("passed"))
        final_score = tone.get("human_score", final_score)
        stages.append({"stage": "converge", "ok": True,
                       "converged": conv["converged"],
                       "score": final_score,
                       "gate_passed": gate_passed})
    else:
        stages.append({"stage": "converge", "ok": True,
                       "skipped": "人味分达标/未开启"})

    if not gate_passed or not tone_passed:
        stages.append({"stage": "gates_final", "ok": False,
                       "gate_passed": gate_passed,
                       "tone_passed": tone_passed})
        return {
            "error": "终稿门禁未通过，已停在人工审阅前",
            "text": text,
            "stages": stages,
            "human_score": final_score,
            "outline": chapter.outline,
        }

    # ---- Stage 5: 人工闸门 ----
    result = {"text": text, "stages": stages, "human_score": final_score,
              "outline": chapter.outline}
    if auto_save:
        from app.services.chapter_approval import create_version_record
        try:
            version = create_version_record(novel_id, chapter_number, text,
                                            source="ai")
            result["saved_version_id"] = version.id
            stages.append({"stage": "save", "ok": True,
                           "version_id": version.id})
        except Exception as e:
            stages.append({"stage": "save", "ok": False, "error": str(e)[:200]})
    else:
        stages.append({"stage": "human_gate", "ok": True,
                       "action": "等待人工审阅/保存"})
    return result
