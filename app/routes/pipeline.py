"""Multi-Agent Pipeline — StoryForge-inspired parallel keeper checks + editor.

Flow: Writer → [Critic | Character Keeper | Lore Keeper | Foreshadow Keeper] → Editor

The pipeline runs the three keepers in parallel (using threads), aggregates results,
and if any issues are found, triggers the Editor for final polish.
"""
import json
import concurrent.futures
from flask import Blueprint, request, Response, jsonify
from app.models import (db, Novel, Character, WorldSetting, Foreshadowing,
                        Chapter, ChapterVersion, CriticReview, StoryState)
from app.services.prompt_builder import (
    build_character_keeper_prompt, build_lore_keeper_prompt,
    build_foreshadow_keeper_prompt, build_editor_prompt,
    assemble_chapter_context, build_critic_prompt,
)
from app.config_utils import get_effective_config
from app.services.llm import call_llm_sync, stream_llm_tokens, LLMError

pipeline_bp = Blueprint("pipeline", __name__, url_prefix="/api")


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _call_ai(messages, cfg, stream=False):
    """Call AI API (non-streaming) and return the response text."""
    try:
        if stream:
            return "".join(stream_llm_tokens(
                cfg["model_name"], messages,
                cfg["api_key"], cfg["base_url"],
                cfg.get("provider_type", "deepseek"),
                cfg["temperature"], cfg["max_tokens"],
            ))
        return call_llm_sync(
            cfg["model_name"], messages,
            cfg["api_key"], cfg["base_url"],
            cfg.get("provider_type", "deepseek"),
            cfg["temperature"], cfg["max_tokens"],
        )
    except LLMError as e:
        return json.dumps({"error": str(e), "pass": False})


def _parse_keeper_result(raw_text):
    """Parse keeper JSON response, with fallback for non-JSON output."""
    try:
        # Try to extract JSON from the response
        text = raw_text.strip()
        # Handle markdown code blocks
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

        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"pass": True, "raw_response": raw_text, "issues": [], "parse_error": True}


def _run_keeper(keeper_type, messages, cfg):
    """Run a single keeper agent and return parsed result."""
    raw = _call_ai(messages, cfg)
    result = _parse_keeper_result(raw)
    result["agent"] = keeper_type
    return result


@pipeline_bp.route("/pipeline/check", methods=["POST"])
def pipeline_check():
    """Run the multi-agent pipeline: parallel keepers + optional editor.

    Form params:
        version_id: chapter version to check
        novel_id: novel ID
        chapter_number: chapter number
        novel_title: novel title
        run_editor: whether to run editor if issues found (default: true)
    """
    version_id = request.form.get("version_id", type=int)
    novel_id = request.form.get("novel_id", type=int)
    chapter_number = request.form.get("chapter_number", type=int)
    novel_title = request.form.get("novel_title", "")
    run_editor = request.form.get("run_editor", "true").lower() == "true"

    if not version_id:
        return jsonify({"error": "version_id required"}), 400

    version = ChapterVersion.query.get_or_404(version_id)
    chapter = version.chapter
    novel = Novel.query.get(novel_id) if novel_id else chapter.novel

    # 按 Agent 类型分别获取配置
    cfg_character = get_effective_config(novel, agent_type="character_check")
    cfg_lore = get_effective_config(novel, agent_type="lore_check")
    cfg_foreshadow = get_effective_config(novel, agent_type="foreshadow_check")
    cfg_critic = get_effective_config(novel, agent_type="critic")
    cfg_editor = get_effective_config(novel, agent_type="editor")

    # Gather context
    ctx = {}
    if novel_id and chapter_number:
        ctx = assemble_chapter_context(novel_id, chapter_number, db)

    # Build keeper prompts
    character_messages = build_character_keeper_prompt(
        chapter_content=version.content,
        characters=ctx.get("characters", []),
        novel_title=novel_title or (novel.title if novel else ""),
        db=db,
    )

    lore_messages = build_lore_keeper_prompt(
        chapter_content=version.content,
        world_settings=ctx.get("world_settings", []),
        novel_title=novel_title or (novel.title if novel else ""),
        db=db,
    )

    # Get all foreshadowing items (not just open)
    all_fs = Foreshadowing.query.filter_by(novel_id=novel_id).filter(
        Foreshadowing.status.in_(["open", "planned", "buried", "advancing", "reclaimable"])
    ).all() if novel_id else []
    fs_data = [{
        "id": f.id,
        "description": f.description,
        "status": f.status,
        "planted_chapter": f.planted_chapter,
        "importance": f.importance,
    } for f in all_fs]

    foreshadow_messages = build_foreshadow_keeper_prompt(
        chapter_content=version.content,
        foreshadowing_items=fs_data,
        chapter_number=chapter_number or chapter.chapter_number,
        novel_title=novel_title or (novel.title if novel else ""),
        db=db,
    )

    # Also run critic
    critic_messages = build_critic_prompt(
        novel_title=novel_title or (novel.title if novel else ""),
        chapter_title=chapter.title,
        chapter_content=version.content,
        outline=chapter.outline,
        user_directive=chapter.user_directive,
        characters=ctx.get("characters", []),
        world_settings=ctx.get("world_settings", []),
        foreshadowing_items=ctx.get("foreshadowing_items", []),
        db=db,
    )

    # Run all 4 agents in parallel
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_run_keeper, "character_keeper", character_messages, cfg_character): "character_keeper",
            executor.submit(_run_keeper, "lore_keeper", lore_messages, cfg_lore): "lore_keeper",
            executor.submit(_run_keeper, "foreshadow_keeper", foreshadow_messages, cfg_foreshadow): "foreshadow_keeper",
            executor.submit(_run_keeper, "critic", critic_messages, cfg_critic): "critic",
        }
        for future in concurrent.futures.as_completed(futures):
            agent_name = futures[future]
            try:
                results[agent_name] = future.result()
            except Exception as e:
                results[agent_name] = {"pass": True, "error": str(e), "agent": agent_name}

    # Determine if any keeper found issues
    has_issues = any(
        not r.get("pass", True) and r.get("issues")
        for k, r in results.items() if k != "critic"
    )

    # Apply foreshadow updates from foreshadow keeper
    foreshadow_updates = results.get("foreshadow_keeper", {}).get("foreshadow_updates", [])
    for update in foreshadow_updates:
        fs_id = update.get("id")
        new_status = update.get("new_status")
        if fs_id and new_status:
            fs = Foreshadowing.query.get(fs_id)
            if fs:
                valid = {
                    "open": ["planned", "buried"],
                    "planned": ["buried"],
                    "buried": ["advancing"],
                    "advancing": ["reclaimable", "buried"],
                    "reclaimable": ["resolved"],
                }
                if new_status in valid.get(fs.status, []):
                    fs.status = new_status
    db.session.commit()

    # Run editor if issues found
    editor_result = None
    if has_issues and run_editor:
        editor_messages = build_editor_prompt(
            chapter_content=version.content,
            check_results=results,
            novel_title=novel_title or (novel.title if novel else ""),
            chapter_title=chapter.title,
            outline=chapter.outline,
            db=db,
        )
        editor_raw = _call_ai(editor_messages, cfg_editor)
        editor_result = {
            "agent": "editor",
            "polished_content": editor_raw,
        }

    # Save critic review if we got a score
    critic_result = results.get("critic", {})
    overall_score = critic_result.get("overall_score")
    if overall_score is not None:
        review = CriticReview(
            version_id=version_id,
            overall_score=overall_score,
            dimension_scores_json=json.dumps(critic_result.get("dimensions", []), ensure_ascii=False),
            annotations_json=json.dumps(critic_result.get("annotations", []), ensure_ascii=False),
            overall_comment=critic_result.get("overall_comment", ""),
            full_response=json.dumps(critic_result, ensure_ascii=False),
        )
        db.session.add(review)
        db.session.commit()

    return jsonify({
        "results": results,
        "hasIssues": has_issues,
        "editorResult": editor_result,
        "criticScore": overall_score,
    })


@pipeline_bp.route("/pipeline/check-stream", methods=["POST"])
def pipeline_check_stream():
    """SSE streaming version of the pipeline check.

    Streams progress updates as each agent completes.
    """
    version_id = request.form.get("version_id", type=int)
    novel_id = request.form.get("novel_id", type=int)
    chapter_number = request.form.get("chapter_number", type=int)
    novel_title = request.form.get("novel_title", "")

    if not version_id:
        return Response(_sse_event({"error": "version_id required"}), mimetype="text/event-stream")

    version = ChapterVersion.query.get_or_404(version_id)
    chapter = version.chapter
    novel = Novel.query.get(novel_id) if novel_id else chapter.novel

    # 按 Agent 类型分别获取配置（流式模式不含 editor，见 /pipeline/check）
    cfg_character = get_effective_config(novel, agent_type="character_check")
    cfg_lore = get_effective_config(novel, agent_type="lore_check")
    cfg_foreshadow = get_effective_config(novel, agent_type="foreshadow_check")
    cfg_critic = get_effective_config(novel, agent_type="critic")

    # 按 Agent 类型映射 cfg
    agent_cfg_map = {
        "character_keeper": cfg_character,
        "lore_keeper": cfg_lore,
        "foreshadow_keeper": cfg_foreshadow,
        "critic": cfg_critic,
    }

    ctx = {}
    if novel_id and chapter_number:
        ctx = assemble_chapter_context(novel_id, chapter_number, db)

    novel_t = novel_title or (novel.title if novel else "")

    # Build all prompts
    character_messages = build_character_keeper_prompt(
        chapter_content=version.content,
        characters=ctx.get("characters", []),
        novel_title=novel_t, db=db,
    )
    lore_messages = build_lore_keeper_prompt(
        chapter_content=version.content,
        world_settings=ctx.get("world_settings", []),
        novel_title=novel_t, db=db,
    )
    all_fs = Foreshadowing.query.filter_by(novel_id=novel_id).filter(
        Foreshadowing.status.in_(["open", "planned", "buried", "advancing", "reclaimable"])
    ).all() if novel_id else []
    fs_data = [{"id": f.id, "description": f.description, "status": f.status,
                "planted_chapter": f.planted_chapter, "importance": f.importance} for f in all_fs]
    foreshadow_messages = build_foreshadow_keeper_prompt(
        chapter_content=version.content, foreshadowing_items=fs_data,
        chapter_number=chapter_number or chapter.chapter_number,
        novel_title=novel_t, db=db,
    )
    critic_messages = build_critic_prompt(
        novel_title=novel_t, chapter_title=chapter.title,
        chapter_content=version.content, outline=chapter.outline,
        user_directive=chapter.user_directive,
        characters=ctx.get("characters", []),
        world_settings=ctx.get("world_settings", []),
        foreshadowing_items=ctx.get("foreshadowing_items", []),
        db=db,
    )

    def generate():
        results = {}
        agents = [
            ("character_keeper", character_messages),
            ("lore_keeper", lore_messages),
            ("foreshadow_keeper", foreshadow_messages),
            ("critic", critic_messages),
        ]

        # Run in parallel, stream as each completes
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(_run_keeper, name, msgs, agent_cfg_map[name]): name
                for name, msgs in agents
            }
            for future in concurrent.futures.as_completed(futures):
                agent_name = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = {"pass": True, "error": str(e)}
                result["agent"] = agent_name
                results[agent_name] = result
                yield _sse_event({"type": "agent_complete", "agent": agent_name, "result": result})

        # Check for issues
        has_issues = any(
            not r.get("pass", True) and r.get("issues")
            for k, r in results.items() if k != "critic"
        )
        yield _sse_event({"type": "check_complete", "hasIssues": has_issues, "results": results})

    return Response(generate(), mimetype="text/event-stream")
