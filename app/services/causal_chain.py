"""Causal Chain Engine — tracks cause → event → effect → decision for every chapter.

Inspired by Dramatica-Flow's causal chain engine.

Each chapter's events are decomposed into:
- Cause (起因): What triggered this event
- Event (经过): What happened
- Effect (结果): What changed as a result
- Decision (决策): What characters decided to do next

The chain links chapters together: the Decision of chapter N becomes
the Cause of chapter N+1.
"""
import json
from flask import Blueprint, request, jsonify
from app.models import db, Chapter, ChapterSummary, Novel
from app.services.llm import call_llm_sync, stream_llm_tokens, LLMError

causal_bp = Blueprint("causal", __name__, url_prefix="/api")


def _build_extraction_prompt(chapter_content, chapter_number, novel_title, previous_decisions=""):
    """Build prompt to extract causal chain from chapter content."""
    system = (
        "你是一位叙事结构分析专家。从章节内容中提取因果链。\n"
        "每个章节的核心事件分解为：\n"
        "- 起因(cause): 触发本章事件的原因\n"
        "- 经过(event): 发生了什么\n"
        "- 结果(effect): 产生了什么后果/变化\n"
        "- 决策(decision): 角色做出的关键决定（这将成为下一章的起因）\n\n"
        "输出JSON格式：\n"
        '{"cause": "起因描述", "event": "事件描述", "effect": "结果描述", '
        '"decision": "决策描述", "key_changes": ["变化1", "变化2"], '
        '"conflicts": ["冲突1"], "character_states": {"角色名": "当前状态"}}'
    )

    user = f"小说：{novel_title}\n第{chapter_number}章\n\n"
    if previous_decisions:
        user += f"【上一章的决策】\n{previous_decisions}\n\n"
    user += f"【本章正文】\n{chapter_content}\n\n请提取因果链，输出JSON。"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def extract_causal_chain(chapter_content, chapter_number, novel_title="", previous_decisions="", cfg=None):
    """Extract causal chain from a chapter using AI."""
    if cfg is None:
        from app.config_utils import get_model_config
        cfg = get_model_config(agent_type="causal_chain")

    messages = _build_extraction_prompt(chapter_content, chapter_number, novel_title, previous_decisions)

    try:
        text = call_llm_sync(
            model=cfg["model_name"],
            messages=messages,
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
        )
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            json_lines = [l for l in lines[1:] if not l.startswith("```")]
            text = "\n".join(json_lines)
        return json.loads(text)
    except LLMError as e:
        return {
            "cause": "", "event": "", "effect": "", "decision": "",
            "key_changes": [], "conflicts": [], "character_states": {},
            "error": str(e),
        }
    except Exception as e:
        return {
            "cause": "", "event": "", "effect": "", "decision": "",
            "key_changes": [], "conflicts": [], "character_states": {},
            "error": str(e),
        }


def get_chain_context(novel_id, up_to_chapter, max_chapters=5):
    """Get the causal chain context for generating a new chapter.

    Returns the last N chapters' causal chains as context.
    """
    chapters = (Chapter.query
                .filter_by(novel_id=novel_id)
                .filter(Chapter.chapter_number < up_to_chapter)
                .order_by(Chapter.chapter_number.desc())
                .limit(max_chapters)
                .all())

    chains = []
    for ch in reversed(chapters):
        summary = ChapterSummary.query.filter_by(chapter_id=ch.id).first()
        if summary and hasattr(summary, 'causal_chain_json') and summary.causal_chain_json:
            try:
                chain = json.loads(summary.causal_chain_json)
                chain["chapter_number"] = ch.chapter_number
                chains.append(chain)
            except json.JSONDecodeError:
                pass

    return chains


def format_chain_for_prompt(chains):
    """Format causal chains into a prompt-friendly string."""
    if not chains:
        return ""

    lines = []
    for chain in chains:
        lines.append(f"第{chain.get('chapter_number', '?')}章:")
        if chain.get("cause"):
            lines.append(f"  起因: {chain['cause']}")
        if chain.get("event"):
            lines.append(f"  经过: {chain['event']}")
        if chain.get("effect"):
            lines.append(f"  结果: {chain['effect']}")
        if chain.get("decision"):
            lines.append(f"  决策: {chain['decision']}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@causal_bp.route("/novels/<int:novel_id>/causal-chain/extract", methods=["POST"])
def extract_chain(novel_id):
    """Extract causal chain from a chapter."""
    chapter_number = request.form.get("chapter_number", type=int)
    if not chapter_number:
        return jsonify({"error": "chapter_number required"}), 400

    chapter = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first_or_404()
    novel = Novel.query.get(novel_id)

    # Get content from latest version
    from app.models import ChapterVersion
    version = ChapterVersion.query.filter_by(chapter_id=chapter.id).order_by(
        ChapterVersion.version_number.desc()).first()
    if not version:
        return jsonify({"error": "no version"}), 400

    # Get previous chapter's decision
    prev_decision = ""
    if chapter_number > 1:
        prev_ch = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number - 1).first()
        if prev_ch:
            prev_summary = ChapterSummary.query.filter_by(chapter_id=prev_ch.id).first()
            if prev_summary and hasattr(prev_summary, 'causal_chain_json') and prev_summary.causal_chain_json:
                try:
                    prev_chain = json.loads(prev_summary.causal_chain_json)
                    prev_decision = prev_chain.get("decision", "")
                except json.JSONDecodeError:
                    pass

    chain = extract_causal_chain(
        version.content, chapter_number,
        novel.title if novel else "", prev_decision,
    )

    # Only save if extraction succeeded (no error)
    if not chain.get("error"):
        summary = ChapterSummary.query.filter_by(chapter_id=chapter.id).first()
        if not summary:
            summary = ChapterSummary(chapter_id=chapter.id, summary="")
            db.session.add(summary)
        summary.causal_chain_json = json.dumps(chain, ensure_ascii=False)
        db.session.commit()

    return jsonify(chain)


@causal_bp.route("/novels/<int:novel_id>/causal-chain/context")
def chain_context(novel_id):
    """Get causal chain context for a chapter."""
    chapter_number = request.args.get("chapter_number", type=int)
    if not chapter_number:
        return jsonify({"error": "chapter_number required"}), 400

    chains = get_chain_context(novel_id, chapter_number)
    return jsonify({
        "chains": chains,
        "formatted": format_chain_for_prompt(chains),
    })


@causal_bp.route("/novels/<int:novel_id>/causal-chain/full")
def full_chain(novel_id):
    """Get the full causal chain for the entire novel."""
    chapters = Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.chapter_number).all()

    full = []
    for ch in chapters:
        summary = ChapterSummary.query.filter_by(chapter_id=ch.id).first()
        chain = {"chapter_number": ch.chapter_number, "title": ch.title}
        if summary and hasattr(summary, 'causal_chain_json') and summary.causal_chain_json:
            try:
                chain.update(json.loads(summary.causal_chain_json))
            except json.JSONDecodeError:
                pass
        full.append(chain)

    return jsonify(full)
