"""统一评审服务 — 将评审 (review) 和多维审计 (audit) 合并为一个流程。

工作流：
    Step 1: 评审 (流式) → AI 整体文学评论
    Step 2: 多维审计 (并行) → 17 维度结构化问题
    Step 3: 合并报告 → 综合分数 + 问题清单 + 修改建议
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
from app.services.audit import run_full_audit
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
            "overall_score": float,
            "grade": str,  # S/A/B+/B/C/D
            "critic_comment": str,  # 整体评论
            "dimensions": {  # 17 维度分数
                "personality_consistency": {"score": 8.5, "issues": [...], "weight": 1.2},
                ...
            },
            "groups": {  # 5 分组分数
                "character": 8.2,
                "plot": 7.5,
                ...
            },
            "issues": [  # 完整问题清单（按严重度排序）
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

    # 4. Step 2: 多维审计（并行 6 Agent）
    audit_result = run_full_audit(
        chapter_content=version.content,
        outline=chapter.outline or "",
        chapter_number=chapter_number,
        characters=ctx.get("characters", []),
        world_settings=ctx.get("world_settings", []),
        summaries=ctx.get("summaries", []),
        foreshadowing_items=ctx.get("foreshadowing_items", []),
        novel_title=novel.title,
        cfg=cfg,
    )

    # 5. Step 3: 合并报告
    report = _merge_report(critic_result, audit_result, version.content)

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


def _merge_report(critic_result, audit_result, original_content):
    """合并 Critic 评审和 Audit 审计为统一报告。"""
    # 从 audit_result 提取数据
    audit_dimensions = audit_result.get("dimensions", {})
    audit_groups = audit_result.get("groups", {})
    audit_issues = audit_result.get("issues", [])
    audit_score = audit_result.get("overall_score", 0)
    audit_grade = audit_result.get("grade", "?")

    # 从 critic_result 提取数据
    critic_score = critic_result.get("overall_score")
    critic_comment = critic_result.get("overall_comment", "")
    critic_dimensions = critic_result.get("dimensions", [])
    critic_annotations = critic_result.get("annotations", [])

    # 综合分数：critic (40%) + audit (60%)
    if critic_score is not None and audit_score:
        combined_score = round(critic_score * 0.4 + audit_score * 0.6, 2)
    elif critic_score is not None:
        combined_score = critic_score
    else:
        combined_score = audit_score

    # 合并维度信息
    merged_dimensions = {}
    for dim_id, dim_data in audit_dimensions.items():
        merged_dimensions[dim_id] = {
            "score": dim_data.get("score", 0),
            "weight": dim_data.get("weight", 1.0),
            "name": dim_data.get("name", dim_id),
            "group": dim_data.get("group", ""),
            "issues": dim_data.get("issues", []),
        }

    # 合并所有 issues（从 critic annotations + audit issues）
    all_issues = list(audit_issues)
    for ann in critic_annotations:
        all_issues.append({
            "dimension": ann.get("name", "综合评论"),
            "dimension_name": ann.get("name", "综合评论"),
            "severity": ann.get("severity", "medium"),
            "issue": ann.get("quote", ann.get("issue", "")),
            "suggestion": ann.get("suggestion", ""),
            "location": f"第{ann.get('paragraph_index', 0) + 1}段" if ann.get("paragraph_index") else "",
        })

    # 按严重度排序
    severity_order = {"high": 0, "medium": 1, "low": 2}
    all_issues.sort(key=lambda x: severity_order.get(x.get("severity", "medium"), 1))

    high_count = sum(1 for i in all_issues if i.get("severity") == "high")
    total_count = len(all_issues)

    return {
        "overall_score": combined_score,
        "grade": audit_grade,
        "critic_comment": critic_comment,
        "dimensions": merged_dimensions,
        "groups": audit_groups,
        "issues": all_issues,
        "high_issue_count": high_count,
        "total_issue_count": total_count,
        "summary": _generate_summary(combined_score, high_count, total_count),
    }


def _generate_summary(score, high_count, total_count):
    """生成综合评语。"""
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
        # 提取维度分数（兼容原 CriticReview 的 dimension_scores_json 格式）
        dim_scores = []
        for dim_id, dim_data in report.get("dimensions", {}).items():
            dim_scores.append({
                "name": dim_data.get("name", dim_id),
                "score": dim_data.get("score", 0),
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
        db.session.rollback()


def unified_review_stream(novel_id, chapter_number, version_id=None, include_rewrite=False):
    """统一评审流程（流式版本）。

    用于前端 SSE 流式输出。

    Yields:
        SSE 事件:
        {"type": "start", "chapter": 1}
        {"type": "review_token", "token": "..."}
        {"type": "review_done", "comment": "..."}
        {"type": "audit_group", "group": "character", "score": 8.2}
        {"type": "audit_issue", "issue": {...}}
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