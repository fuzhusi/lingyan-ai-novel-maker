"""Full Book Optimization — post-completion quality pass.

Inspired by show-me-the-story's full-book optimization:
1. Diagnosis — scan all chapters for issues
2. Consistency check — cross-chapter fact verification
3. Optimization tickets — list all issues to fix
4. Per-chapter auto-revision — fix issues with diff viewing

This is meant to be run after all chapters are written/approved.
"""
import json
import concurrent.futures
from app.models import (db, Novel, Chapter, ChapterVersion, ChapterSummary,
                        Character, WorldSetting, Foreshadowing, StoryState)
from app.services.llm import call_llm_sync, stream_llm_tokens, LLMError
from app.services.audit import run_full_audit
from app.services.deai_agent import deai_process


def _diagnose_chapter(chapter_id, novel_id, chapter_number, cfg):
    """Diagnose a single chapter: audit + de-AI check + causal chain check."""
    chapter = Chapter.query.get(chapter_id)
    if not chapter:
        return None

    version = (ChapterVersion.query
               .filter_by(chapter_id=chapter_id)
               .order_by(ChapterVersion.version_number.desc()).first())
    if not version:
        return None

    content = version.content

    # 1. Run audit
    from app.services.prompt_builder import assemble_chapter_context
    ctx = assemble_chapter_context(novel_id, chapter_number, db)

    audit_result = run_full_audit(
        chapter_content=content,
        outline=chapter.outline,
        chapter_number=chapter_number,
        characters=ctx.get("characters", []),
        world_settings=ctx.get("world_settings", []),
        summaries=ctx.get("summaries", []),
        foreshadowing_items=ctx.get("foreshadowing_items", []),
        novel_title="",
        cfg=cfg,
    )

    # 2. De-AI check
    deai_text = deai_process(content)
    deai_changed = deai_text != content

    # 3. Collect issues
    issues = []
    for dim_id, dim in audit_result.get("dimensions", {}).items():
        if dim.get("score", 10) <= 5:
            for issue in dim.get("issues", []):
                issues.append({
                    "chapter": chapter_number,
                    "dimension": dim.get("name", dim_id),
                    "issue": issue,
                    "severity": "high" if dim.get("score", 10) <= 3 else "medium",
                })

    if deai_changed:
        issues.append({
            "chapter": chapter_number,
            "dimension": "AI痕迹",
            "issue": "检测到AI写作痕迹，需要去AI化处理",
            "severity": "medium",
        })

    return {
        "chapter_id": chapter_id,
        "chapter_number": chapter_number,
        "title": chapter.title,
        "audit_score": audit_result.get("overall_score", 0),
        "grade": audit_result.get("grade", "?"),
        "issues": issues,
        "deai_changed": deai_changed,
        "content_length": len(content),
    }


def diagnose_book(novel_id, cfg=None):
    """Diagnose all chapters of a novel. Returns optimization report."""
    if cfg is None:
        from app.config_utils import get_effective_config
        novel = Novel.query.get(novel_id)
        cfg = get_effective_config(novel, agent_type="optimizer")

    chapters = Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.chapter_number).all()
    if not chapters:
        return {"error": "没有章节"}

    # Run diagnostics sequentially (SQLite doesn't support concurrent writes)
    results = []
    for ch in chapters:
        try:
            result = _diagnose_chapter(ch.id, novel_id, ch.chapter_number, cfg)
            if result:
                results.append(result)
        except Exception as e:
            results.append({
                "chapter_number": ch.chapter_number,
                    "error": str(e),
                    "issues": [],
                })

    # Sort by chapter number
    results.sort(key=lambda x: x.get("chapter_number", 0))

    # Aggregate
    total_issues = sum(len(r.get("issues", [])) for r in results)
    high_issues = sum(1 for r in results for i in r.get("issues", []) if i.get("severity") == "high")
    avg_score = round(sum(r.get("audit_score", 0) for r in results) / max(len(results), 1), 1)
    chapters_needing_fix = sum(1 for r in results if r.get("issues"))

    return {
        "novel_id": novel_id,
        "total_chapters": len(results),
        "total_issues": total_issues,
        "high_issues": high_issues,
        "average_score": avg_score,
        "chapters_needing_fix": chapters_needing_fix,
        "chapters": results,
    }


def auto_revise_chapter(chapter_id, novel_id, chapter_number, issues, cfg):
    """Auto-revise a chapter to fix identified issues."""
    chapter = Chapter.query.get(chapter_id)
    if not chapter:
        return None

    version = (ChapterVersion.query
               .filter_by(chapter_id=chapter_id)
               .order_by(ChapterVersion.version_number.desc()).first())
    if not version:
        return None

    content = version.content

    # Build revision prompt
    issue_descriptions = []
    for issue in issues:
        issue_descriptions.append(f"- [{issue.get('dimension', '')}] {issue.get('issue', '')}")

    system = (
        "你是一位专业的小说编辑。根据以下问题清单修改这篇章节。\n"
        "要求：修复所有指出的问题，保持原文风格和优点。\n"
        "输出修改后的完整章节正文，不要输出其他内容。"
    )
    user = (
        f"【问题清单】\n" + "\n".join(issue_descriptions) + "\n\n"
        f"【原文】\n{content}"
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    try:
        revised = call_llm_sync(
            model=cfg["model_name"],
            messages=messages,
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
        )

        # Apply de-AI processing
        revised = deai_process(revised)

        return {
            "original": content,
            "revised": revised,
            "changes": len(revised) != len(content),
        }
    except LLMError as e:
        return {"error": str(e), "original": content, "revised": content}
    except Exception as e:
        return {"error": str(e), "original": content, "revised": content}
