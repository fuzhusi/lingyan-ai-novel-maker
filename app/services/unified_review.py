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
import concurrent.futures
from app.services.llm import call_llm_sync, stream_llm_tokens, LLMError
from app.models import (db, ChapterVersion, CriticReview, Chapter, Novel,
                        Character, WorldSetting, Foreshadowing, ChapterSummary)
from app.services.blind_review import run_dual_review
from app.services.prompt_builder import (build_critic_prompt, build_rewrite_prompt,
                                          assemble_chapter_context)
from app.config_utils import get_effective_config


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
    chapter = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first()
    if not chapter:
        return {"error": f"第{chapter_number}章不存在"}

    if version_id:
        version = ChapterVersion.query.get(version_id)
        # 归属校验：版本必须属于该章节，防止 A 章上下文 + B 章正文混合审计
        if version and version.chapter_id != chapter.id:
            return {"error": "version_id 与指定章节不匹配"}
    else:
        version = (ChapterVersion.query
                   .filter_by(chapter_id=chapter.id)
                   .order_by(ChapterVersion.version_number.desc()).first())

    if not version:
        return {"error": f"第{chapter_number}章暂无内容"}

    novel = Novel.query.get(novel_id)

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

    # 4. Step 2: 双盲审（两位编辑并行，零上下文只看正文）
    try:
        blind_result = run_dual_review(version.content)
    except Exception:
        # 盲审失败不阻断评审：critic 结果照常返回
        blind_result = {"editors": [], "elapsed": 0.0}

    # 5. Step 3: 合并报告（critic 结构化评分 + 双盲审文本报告）
    report = _merge_report(critic_result, blind_result)

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

    # issues 全部来自 critic annotations（结构化、可定位、可喂改写）
    all_issues = []
    for ann in critic_annotations:
        all_issues.append({
            "dimension": ann.get("name", "综合评论"),
            "dimension_name": ann.get("name", "综合评论"),
            "severity": ann.get("severity", "medium"),
            "issue": ann.get("quote", ann.get("issue", "")),
            "suggestion": ann.get("suggestion", ""),
            "location": f"第{ann.get('paragraph_index') + 1}段" if ann.get("paragraph_index") is not None else "",
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


def _auto_rewrite(content, issues, novel_title, chapter_title, outline, user_directive, cfg):
    """基于问题清单自动改写。"""
    issue_descriptions = []
    for issue in issues[:10]:  # 最多取 10 个问题
        issue_descriptions.append(
            f"- [{issue.get('severity', 'medium')}] {issue.get('dimension_name', '')}: {issue.get('issue', '')}"
            + (f" → 建议: {issue['suggestion']}" if issue.get('suggestion') else "")
        )

    messages = build_rewrite_prompt(
        original_content=content,
        critic_feedback="\n".join(issue_descriptions) if issue_descriptions else "无",
        novel_title=novel_title,
        chapter_title=chapter_title,
        outline=outline,
        user_directive=user_directive,
        db=db,  # 不传会导致用户自定义 rewrite 模板被静默忽略
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

        # 提取注释
        annotations = []
        for issue in report.get("issues", []):
            annotations.append({
                "paragraph_index": 0,
                "quote": issue.get("issue", "")[:100],
                "issue": issue.get("dimension_name", ""),
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


def unified_review_stream(novel_id, chapter_number, version_id=None, include_rewrite=False):
    """统一评审流程（流式版本）。

    用于前端 SSE 流式输出。

    Yields:
        SSE 事件:
        {"type": "start", "chapter": 1}
        {"type": "review_token", "token": "..."}
        {"type": "review_done", "comment": "..."}
        {"type": "blind_done", "editors": [...], "elapsed": 12.3}
        {"type": "report", "report": {...}}
        {"type": "rewrite_token", "token": "..."}
        {"type": "rewrite_done", "rewritten": "..."}
        {"type": "done"}
    """
    # 简化版：先同步完成，再分阶段推送
    yield f"data: {json.dumps({'type': 'start', 'chapter': chapter_number}, ensure_ascii=False)}\n\n"

    # 这里可以做更复杂的流式逻辑，先做简化版
    report = unified_review(novel_id, chapter_number, version_id, include_rewrite)

    yield f"data: {json.dumps({'type': 'report', 'report': report}, ensure_ascii=False)}\n\n"

    if report.get("rewrite"):
        yield f"data: {json.dumps({'type': 'rewrite_done', 'rewritten': report['rewrite'].get('rewritten_content', '')}, ensure_ascii=False)}\n\n"

    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"