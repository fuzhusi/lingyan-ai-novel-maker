"""统一评审服务 — 将 critic 结构化评分和双盲审合并为一个流程。

工作流：
    Step 1: Critic 评审 (流式) → AI 整体文学评论 + 结构化评分
    Step 2: 双盲审 (并行) → 阎浮×白骨两角色零上下文盲审
    Step 3: 合并报告 → 综合分数 + 盲审意见 + 问题清单
    Step 4 (可选): 自动改写 → 基于报告生成改进版本

设计原则：
    - 用户一次点击完成全流程
    - 保留单步 API 作为高级功能
    - 统一结果格式，便于前端展示
"""

import json
import logging
import threading

from flask import current_app

from app.services.llm import call_llm_sync, stream_llm_tokens, LLMError
from app.models import (db, ChapterVersion, CriticReview, Chapter, Novel)
from app.services.blind_review import run_dual_review
from app.services.prompt_builder import (build_critic_prompt, build_rewrite_prompt,
                                          assemble_chapter_context)
from app.config_utils import get_effective_config

logger = logging.getLogger(__name__)


def _resolve_chapter_version(novel_id, chapter_number, version_id=None):
    """解析章节与版本，做归属校验。返回 (chapter, version, novel, error_dict)。"""
    chapter = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first()
    if not chapter:
        return None, None, None, {"error": f"第{chapter_number}章不存在"}

    if version_id:
        version = ChapterVersion.query.get(version_id)
        # 归属校验：版本必须属于该章节，防止 A 章上下文 + B 章正文混合审计
        if version and version.chapter_id != chapter.id:
            return None, None, None, {"error": "version_id 与指定章节不匹配"}
    else:
        version = (ChapterVersion.query
                   .filter_by(chapter_id=chapter.id)
                   .order_by(ChapterVersion.version_number.desc()).first())

    if not version:
        return None, None, None, {"error": f"第{chapter_number}章暂无内容"}

    novel = Novel.query.get(novel_id)
    return chapter, version, novel, None


def unified_review(novel_id, chapter_number, version_id=None, include_rewrite=False):
    """统一评审流程（同步）。

    Args:
        novel_id: 小说 ID
        chapter_number: 章节号
        version_id: 版本 ID（可选，默认取最新）
        include_rewrite: 是否包含自动改写

    Returns:
        {
            "overall_score": float,   # critic 链路评分（历史可比）
            "grade": str,             # S/A/B+/B/C/D（由分数推导）
            "critic_comment": str,    # 整体评论
            "blind_reviews": [        # 双盲审文本报告（不产数字分）
                {"key": "yafu", "name": "尖酸嘴 · 阎浮",
                 "verdict": "追读/弃稿", "review": "..."},
                ...
            ],
            "issues": [  # 完整问题清单（按严重度排序，来源 critic）
                {"dimension": "...", "severity": "high/medium/low", "issue": "...", "suggestion": "..."},
                ...
            ],
            "high_issue_count": int,
            "total_issue_count": int,
            "rewrite": {  # 自动改写（可选）
                "rewritten_content": str,
                "improvements": [str, ...],
            } 或 None,
            "timestamp": str,
        }
    """
    # 1. 获取章节内容
    chapter, version, novel, err = _resolve_chapter_version(novel_id, chapter_number, version_id)
    if err:
        return err

    # 2. 准备上下文
    ctx = assemble_chapter_context(novel_id, chapter_number, db)
    cfg = get_effective_config(novel, agent_type="critic")

    # 3. Step 1: 评审（同步版，流式版单独在 review.py）
    critic_result = _call_critic_sync(
        chapter_content=version.content,
        novel_title=novel.title,
        chapter_title=chapter.title,
        chapter_number=chapter_number,
        outline=chapter.outline or "",
        user_directive=chapter.user_directive or "",
        characters=ctx.get("characters", []),
        world_settings=ctx.get("world_settings", []),
        foreshadowing_items=ctx.get("foreshadowing_items", []),
        cfg=cfg,
    )

    # 4. Step 2: 双盲审（两位编辑并行，零上下文只看正文；与 critic 同源配置）
    try:
        blind_result = run_dual_review(version.content, novel=novel)
    except Exception:
        # 盲审失败不阻断评审：critic 结果照常返回，但必须留痕便于排查
        logger.exception("unified_review: 双盲审失败 (chapter=%s)", chapter_number)
        blind_result = {"editors": [], "elapsed": 0.0}

    # 5. Step 3: 合并报告（critic 结构化评分 + 双盲审文本报告）
    report = _merge_report(critic_result, blind_result)

    # 5.5 统一意见 Schema（P1）：三个意见源降维合并，供前端勾选后喂给改写链
    try:
        from app.services.opinions import build_merged_opinions
        report["merged_opinions"] = build_merged_opinions(
            critic_issues=report.get("issues"),
            critic_comment=report.get("critic_comment", ""),
            blind_reviews=report.get("blind_reviews"),
        )
    except Exception:
        report["merged_opinions"] = []

    # 6. Step 4 (可选): 自动改写
    if include_rewrite and report.get("total_issue_count", 0) > 0:
        rewrite_cfg = get_effective_config(novel, agent_type="rewrite")
        rewrite_result = _auto_rewrite(
            content=version.content,
            issues=report["issues"],
            novel_title=novel.title,
            chapter_title=chapter.title,
            outline=chapter.outline or "",
            user_directive=chapter.user_directive or "",
            cfg=rewrite_cfg,
            author_intent=(novel.author_intent or "") if novel else "",
            current_focus=(novel.current_focus or "") if novel else "",
        )
        report["rewrite"] = rewrite_result
    else:
        report["rewrite"] = None

    # 7. 保存评审结果到数据库
    _save_review(version.id, report, critic_result)

    return report


def _call_critic_sync(chapter_content, novel_title, chapter_title, chapter_number,
                     outline, user_directive, characters, world_settings,
                     foreshadowing_items, cfg):
    """同步调用 Critic 评审。"""
    messages = build_critic_prompt(
        novel_title=novel_title,
        chapter_title=chapter_title,
        chapter_content=chapter_content,
        outline=outline,
        user_directive=user_directive,
        characters=characters,
        world_settings=world_settings,
        foreshadowing_items=foreshadowing_items,
        db=db,  # 不传会导致用户自定义 critic 模板被静默忽略
    )

    try:
        text = call_llm_sync(
            cfg["model_name"], messages,
            cfg["api_key"], cfg["base_url"],
            cfg.get("provider_type", "deepseek"),
            cfg["temperature"], cfg["max_tokens"],
        )
        return _parse_critic_response(text)
    except LLMError as e:
        return {
            "overall_score": None,
            "overall_comment": f"评审失败: {e}",
            "dimensions": [],
            "annotations": [],
            "error": str(e),
        }
    except Exception as e:
        return {
            "overall_score": None,
            "overall_comment": f"评审失败: {e}",
            "dimensions": [],
            "annotations": [],
            "error": str(e),
        }


def _parse_critic_response(text):
    """解析 Critic 返回的 JSON 响应。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        json_lines = []
        in_block = False
        for line in lines:
            if line.startswith("```") and not in_block:
                in_block = True
                continue
            elif line.startswith("```") and in_block:
                break
            elif in_block:
                json_lines.append(line)
        text = "\n".join(json_lines)

    try:
        data = json.loads(text)
        return {
            "overall_score": data.get("overall_score"),
            "overall_comment": data.get("overall_comment", ""),
            "dimensions": data.get("dimensions", []),
            "annotations": data.get("annotations", []),
        }
    except (json.JSONDecodeError, ValueError):
        # 解析失败时返回原文作为评论
        return {
            "overall_score": None,
            "overall_comment": text[:500],  # 截断
            "dimensions": [],
            "annotations": [],
        }


def _score_grade(score):
    """0-10 分 → S/A/B+/B/C/D 等级。"""
    if score is None:
        return "?"
    if score >= 8.5:
        return "S"
    if score >= 7.5:
        return "A"
    if score >= 6.5:
        return "B+"
    if score >= 5.5:
        return "B"
    if score >= 4:
        return "C"
    return "D"


def _merge_report(critic_result, blind_result):
    """合并 Critic 结构化评分与双盲审文本报告为统一报告。

    盲审不产数字分——判决（追读/弃稿）与引用式批评以原样呈现，
    综合分沿用 critic 链路保证历史可比。
    """
    critic_score = critic_result.get("overall_score")
    critic_comment = critic_result.get("overall_comment", "")
    critic_annotations = critic_result.get("annotations", [])

    blind_editors = blind_result.get("editors", []) if blind_result else []

    # issues 全部来自 critic annotations（结构化、可定位、可喂改写）。
    # 注意 critic schema：annotation = {paragraph_index, quote, issue, suggestion}
    # （无 name/severity 字段，severity 仅在模型自愿多给时才存在）
    all_issues = []
    for ann in critic_annotations:
        all_issues.append({
            "dimension": "原文批注",
            "dimension_name": "原文批注",
            "severity": ann.get("severity", "medium"),
            # 问题描述优先，quote 只做兜底——此前把 quote 塞进 issue，
            # 真正的问题描述被丢弃，改写链拿到的全是引文
            "issue": (ann.get("issue") or ann.get("quote", "")).strip(),
            "quote": ann.get("quote", ""),
            "suggestion": ann.get("suggestion", ""),
            "paragraph_index": ann.get("paragraph_index"),
            "location": f"第{ann.get('paragraph_index') + 1}段"
                        if ann.get("paragraph_index") is not None else "",
        })
    severity_order = {"high": 0, "medium": 1, "low": 2}
    all_issues.sort(key=lambda x: severity_order.get(x.get("severity", "medium"), 1))
    high_count = sum(1 for i in all_issues if i.get("severity") == "high")
    total_count = len(all_issues)

    combined_score = critic_score
    grade = _score_grade(combined_score)

    return {
        "overall_score": combined_score,
        "grade": grade,
        "critic_comment": critic_comment,
        "blind_reviews": [
            {"key": e.get("key"), "name": e.get("name"),
             "verdict": e.get("verdict"), "review": e.get("review")}
            for e in blind_editors
        ],
        "issues": all_issues,
        "high_issue_count": high_count,
        "total_issue_count": total_count,
        "summary": _generate_summary(combined_score, high_count, total_count),
    }


def _generate_summary(score, high_count, total_count):
    """生成综合评语。"""
    if score is None:
        return ("critic 未产出有效评分（模型未返回结构化 JSON），"
                "请以下方两位编辑的盲审意见为准；重跑全面评审可再次尝试评分")
    parts = []
    if score >= 8.5:
        parts.append("📗 优秀")
    elif score >= 7.5:
        parts.append("📙 良好")
    elif score >= 6:
        parts.append("📒 一般")
    else:
        parts.append("📕 需要改进")

    parts.append(f"综合 {score}/10")
    parts.append(f"{total_count} 个问题（{high_count} 个高优先级）")

    if high_count > 3:
        parts.append("建议：先修复高优先级问题")
    elif high_count > 0:
        parts.append("建议：针对性修复")
    else:
        parts.append("建议：可继续优化细节")

    return " | ".join(parts)


def _issue_feedback(issues):
    """问题清单 → 改写链反馈文本（同步/流式改写共用）。"""
    descriptions = []
    for issue in issues[:10]:  # 最多取 10 个问题
        descriptions.append(
            f"- [{issue.get('severity', 'medium')}] {issue.get('dimension_name', '')}: {issue.get('issue', '')}"
            + (f" → 建议: {issue['suggestion']}" if issue.get("suggestion") else "")
        )
    return "\n".join(descriptions) if descriptions else "无"


def _auto_rewrite(content, issues, novel_title, chapter_title, outline, user_directive, cfg,
                  author_intent="", current_focus=""):
    """基于问题清单自动改写。"""
    messages = build_rewrite_prompt(
        original_content=content,
        critic_feedback=_issue_feedback(issues),
        novel_title=novel_title,
        chapter_title=chapter_title,
        outline=outline,
        user_directive=user_directive,
        db=db,  # 不传会导致用户自定义 rewrite 模板被静默忽略
        author_intent=author_intent,
        current_focus=current_focus,
    )

    try:
        rewritten = call_llm_sync(
            cfg["model_name"], messages,
            cfg["api_key"], cfg["base_url"],
            cfg.get("provider_type", "deepseek"),
            cfg["temperature"], cfg["max_tokens"],
        )
        return {
            "rewritten_content": rewritten,
            "improvements": [i.get("suggestion", "") for i in issues[:5] if i.get("suggestion")],
            "issues_addressed": len(issues),
        }
    except LLMError as e:
        return {
            "rewritten_content": content,  # 失败时返回原文
            "improvements": [],
            "error": str(e),
        }
    except Exception as e:
        return {
            "rewritten_content": content,  # 失败时返回原文
            "improvements": [],
            "error": str(e),
        }


def _save_review(version_id, report, critic_result):
    """保存评审结果到 CriticReview 表（保留原有数据结构）。"""
    try:
        # 提取维度分数（critic 返回的 dimensions 列表；兼容原 dimension_scores_json 格式）
        dim_scores = []
        for dim in (critic_result or {}).get("dimensions") or []:
            if isinstance(dim, dict):
                dim_scores.append({
                    "name": dim.get("name", dim.get("dimension", "")),
                    "score": dim.get("score", 0),
                })

        # 提取注释：字段一一对应回写，段落号保留真实值
        # （此前 paragraph_index 硬编码 0，历史评审的段落标注全部错位到第 1 段）
        annotations = []
        for issue in report.get("issues", []):
            annotations.append({
                "paragraph_index": issue.get("paragraph_index") or 0,
                "quote": (issue.get("quote") or "")[:100],
                "issue": issue.get("issue", ""),
                "suggestion": issue.get("suggestion", ""),
            })

        review = CriticReview(
            version_id=version_id,
            overall_score=report.get("overall_score"),
            dimension_scores_json=json.dumps(dim_scores, ensure_ascii=False),
            annotations_json=json.dumps(annotations, ensure_ascii=False),
            overall_comment=report.get("critic_comment", ""),
            full_response=json.dumps(report, ensure_ascii=False),
        )
        db.session.add(review)
        db.session.commit()
    except Exception:
        # 持久化失败必须留痕：花钱跑完的评审静默丢失是严重事故
        import logging
        logging.getLogger(__name__).exception(
            "unified_review: 保存评审结果失败 (version_id=%s)", version_id)
        db.session.rollback()


def _sse(obj) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def unified_review_stream(novel_id, chapter_number, version_id=None, include_rewrite=False):
    """统一评审流程（真流式）。

    critic 意见 token 级流出；双盲审与 critic 并行执行（盲审是纯 LLM 调用，
    自建 app context，与主链路零共享状态）；结束后推结构化报告；
    可选自动改写同样 token 级流出。

    事件契约（与 /static/js/lingyan-stream.js 的 sse() 对齐）:
        {"token": "...", "phase": "critic"|"rewrite"}
        {"status": {"stage": "review_start"|"critic_done"|"blind_done"
                    |"rewrite_start"|"rewrite_done"|"rewrite_error", ...}}
        {"report": {...}}          —— 合并报告（含 merged_opinions）
        {"error": "..."}           —— 致命错误（评审链失败）
        {"done": true}
    """
    chapter, version, novel, err = _resolve_chapter_version(novel_id, chapter_number, version_id)
    if err:
        yield _sse({"error": err["error"]})
        yield _sse({"done": True})
        return

    yield _sse({"status": {"stage": "review_start", "chapter": chapter_number}})

    # 双盲审与 critic 并行：critic 在主流式循环里逐 token 出，
    # 盲审在旁路线程里跑（run_dual_review 内部还需再并行两位编辑）
    app_obj = current_app._get_current_object()
    blind_box = {}

    def _blind_worker():
        try:
            with app_obj.app_context():
                # 与同章 critic 同源配置（含 novel.model_override）
                blind_box["result"] = run_dual_review(version.content, novel=novel)
        except Exception as exc:
            # 盲审失败不阻断评审，但必须留痕——静默丢两位编辑意见是严重损耗
            logger.warning("unified_review_stream: 盲审失败: %s", exc)
            blind_box["error"] = str(exc)

    blind_thread = threading.Thread(target=_blind_worker, name="blind-review", daemon=True)
    blind_thread.start()

    # ---- Step 1: critic 评审（token 级流出）----
    ctx = assemble_chapter_context(novel_id, chapter_number, db)
    cfg = get_effective_config(novel, agent_type="critic")
    messages = build_critic_prompt(
        novel_title=novel.title,
        chapter_title=chapter.title,
        chapter_content=version.content,
        outline=chapter.outline or "",
        user_directive=chapter.user_directive or "",
        characters=ctx.get("characters", []),
        world_settings=ctx.get("world_settings", []),
        foreshadowing_items=ctx.get("foreshadowing_items", []),
        db=db,  # 不传会导致用户自定义 critic 模板被静默忽略
    )
    collected = []
    try:
        for tok in stream_llm_tokens(
            model=cfg["model_name"], messages=messages,
            api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=cfg.get("temperature", 0.5), max_tokens=cfg.get("max_tokens", 4096),
        ):
            collected.append(tok)
            yield _sse({"token": tok, "phase": "critic"})
    except Exception as exc:
        yield _sse({"error": f"评审失败: {exc}"})
        yield _sse({"done": True})
        return
    critic_result = _parse_critic_response("".join(collected))

    # ---- Step 2: 收盲审结果 ----
    blind_thread.join()
    blind_result = blind_box.get("result") or {"editors": [], "elapsed": 0.0}

    yield _sse({"status": {"stage": "critic_done",
                           "score": critic_result.get("overall_score"),
                           "grade": _score_grade(critic_result.get("overall_score"))}})
    yield _sse({"status": {"stage": "blind_done", "elapsed": blind_result.get("elapsed", 0.0),
                           "editors": [e.get("name") for e in blind_result.get("editors", [])]}})

    # ---- Step 3: 合并报告并落库（与同步版同一套合并/意见/保存逻辑）----
    report = _merge_report(critic_result, blind_result)
    if blind_box.get("error"):
        report["blind_error"] = blind_box["error"]
    try:
        from app.services.opinions import build_merged_opinions
        report["merged_opinions"] = build_merged_opinions(
            critic_issues=report.get("issues"),
            critic_comment=report.get("critic_comment", ""),
            blind_reviews=report.get("blind_reviews"),
        )
    except Exception:
        report["merged_opinions"] = []
    _save_review(version.id, report, critic_result)
    yield _sse({"report": report})

    # ---- Step 4 (可选): 自动改写（token 级流出）----
    if include_rewrite and report.get("total_issue_count", 0) > 0:
        rewrite_cfg = get_effective_config(novel, agent_type="rewrite")
        yield _sse({"status": {"stage": "rewrite_start"}})
        r_messages = build_rewrite_prompt(
            original_content=version.content,
            critic_feedback=_issue_feedback(report["issues"]),
            novel_title=novel.title,
            chapter_title=chapter.title,
            outline=chapter.outline or "",
            user_directive=chapter.user_directive or "",
            db=db,
            author_intent=(novel.author_intent or "") if novel else "",
            current_focus=(novel.current_focus or "") if novel else "",
        )
        r_collected = []
        try:
            for tok in stream_llm_tokens(
                model=rewrite_cfg["model_name"], messages=r_messages,
                api_key=rewrite_cfg.get("api_key", ""), base_url=rewrite_cfg.get("base_url", ""),
                provider_type=rewrite_cfg.get("provider_type", "deepseek"),
                temperature=rewrite_cfg.get("temperature", 0.5),
                max_tokens=rewrite_cfg.get("max_tokens", 4096),
            ):
                r_collected.append(tok)
                yield _sse({"token": tok, "phase": "rewrite"})
        except Exception as exc:
            yield _sse({"status": {"stage": "rewrite_error", "error": str(exc)[:200]}})
        else:
            rewritten = "".join(r_collected)
            report["rewrite"] = {
                "rewritten_content": rewritten,
                "improvements": [i.get("suggestion", "") for i in report["issues"][:5]
                                 if i.get("suggestion")],
                "issues_addressed": len(report["issues"]),
            }
            yield _sse({"status": {"stage": "rewrite_done", "chars": len(rewritten)}})

    yield _sse({"done": True})