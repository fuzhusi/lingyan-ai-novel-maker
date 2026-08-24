"""Temporal Truth Database — tracks what is "true" at each point in the story.

Inspired by knowrite's Temporal Truth Database.

Tracks facts that change over time:
- Character states (alive/dead/missing/injured)
- Relationship statuses
- World states (factions active/destroyed)
- Item locations
- Knowledge states (who knows what)

Each truth has:
- A subject (character/item/faction)
- A property (status/location/relationship)
- A value (alive/dead/in_castle/etc.)
- Valid from chapter X to chapter Y (or ongoing)
"""
import json
from flask import Blueprint, request, jsonify
from app.models import db, Novel, Chapter, ChapterMemory, Setting
from app.services.llm import call_llm_sync, stream_llm_tokens, LLMError

truth_bp = Blueprint("truth", __name__, url_prefix="/api")


def _get_truths(novel_id):
    """Get all truths for a novel."""
    setting = Setting.query.get(f"temporal_truths_{novel_id}")
    if setting and setting.value:
        try:
            return json.loads(setting.value)
        except json.JSONDecodeError:
            pass
    return []


def _save_truths(novel_id, truths):
    """Save truths for a novel."""
    key = f"temporal_truths_{novel_id}"
    value = json.dumps(truths, ensure_ascii=False)
    setting = Setting.query.get(key)
    if setting:
        setting.value = value
    else:
        setting = Setting(key=key, value=value)
        db.session.add(setting)
    db.session.commit()


def add_truth(novel_id, subject, property_name, value, from_chapter, to_chapter=None):
    """Add a temporal truth.

    同一 (subject, property) 若已有进行中记录，先闭合并写入 to_chapter，
    否则同一属性会同时存在两条"ongoing"记录，时序查询无法判定哪条为真。

    Args:
        novel_id: Novel ID
        subject: What (character name, item, faction)
        property_name: What aspect (status, location, relationship)
        value: The truth value (alive, in_castle, allied)
        from_chapter: When this became true
        to_chapter: When this stopped being true (None = ongoing)
    """
    truths = _get_truths(novel_id)

    # 闭合同主体同属性的旧进行中记录（与 update_truth 的闭合逻辑对齐）
    for truth in truths:
        if (truth.get("subject") == subject and
                truth.get("property") == property_name and
                truth.get("to_chapter") is None):
            truth["to_chapter"] = max((from_chapter - 1), truth.get("from_chapter", from_chapter))

    truths.append({
        "subject": subject,
        "property": property_name,
        "value": value,
        "from_chapter": from_chapter,
        "to_chapter": to_chapter,
    })
    _save_truths(novel_id, truths)


def update_truth(novel_id, subject, property_name, new_value, chapter_number):
    """Update a truth — close the old one and create a new one."""
    truths = _get_truths(novel_id)

    # Close existing truth
    for truth in truths:
        if (truth["subject"] == subject and
            truth["property"] == property_name and
            truth.get("to_chapter") is None):
            truth["to_chapter"] = chapter_number - 1

    # Add new truth
    truths.append({
        "subject": subject,
        "property": property_name,
        "value": new_value,
        "from_chapter": chapter_number,
        "to_chapter": None,
    })
    _save_truths(novel_id, truths)


def get_truths_at_chapter(novel_id, chapter_number):
    """Get all truths that are valid at a specific chapter."""
    truths = _get_truths(novel_id)
    active = []
    for truth in truths:
        from_ch = truth.get("from_chapter", 0)
        to_ch = truth.get("to_chapter")
        if from_ch <= chapter_number and (to_ch is None or to_ch >= chapter_number):
            active.append(truth)
    return active


def get_truth_changes(novel_id, chapter_number):
    """Get truths that changed at a specific chapter."""
    truths = _get_truths(novel_id)
    changes = []
    for truth in truths:
        if truth.get("from_chapter") == chapter_number:
            changes.append({"type": "new", **truth})
        elif truth.get("to_chapter") == chapter_number:
            changes.append({"type": "ended", **truth})
    return changes


def format_truths_for_prompt(novel_id, chapter_number):
    """Format current truths into a prompt injection string."""
    truths = get_truths_at_chapter(novel_id, chapter_number)
    if not truths:
        return ""

    # Group by subject
    subjects = {}
    for truth in truths:
        subj = truth["subject"]
        if subj not in subjects:
            subjects[subj] = []
        subjects[subj].append(f"{truth['property']}={truth['value']}")

    lines = []
    for subj, props in subjects.items():
        lines.append(f"- {subj}: {', '.join(props)}")

    return "【当前真相状态】\n" + "\n".join(lines)


def extract_truths_from_chapter(chapter_content, chapter_number, novel_id, cfg=None):
    """Use AI to extract truth changes from a chapter."""
    if cfg is None:
        from app.config_utils import get_model_config
        cfg = get_model_config(agent_type="temporal_truth")

    system = (
        "你是一位叙事分析专家。从章节内容中提取事实变化。\n"
        "关注：角色状态变化、关系变化、物品位置变化、势力变化。\n"
        "输出JSON数组：\n"
        '[{"subject": "角色名", "property": "status", "value": "新状态", "from_chapter": N}]\n'
        "只输出JSON，不要其他内容。"
    )
    user = f"第{chapter_number}章\n\n{chapter_content}"

    try:
        text = call_llm_sync(
            model=cfg["model_name"],
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            api_key=cfg.get("api_key", ""),
            base_url=cfg.get("base_url", ""),
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=cfg.get("temperature", 0.3),
            max_tokens=cfg.get("max_tokens", 1000),
        )
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            json_lines = [l for l in lines[1:] if not l.startswith("```")]
            text = "\n".join(json_lines)
        changes = json.loads(text)
        if isinstance(changes, list):
            for change in changes:
                change["from_chapter"] = chapter_number
                add_truth(
                    novel_id,
                    change.get("subject", ""),
                    change.get("property", "status"),
                    change.get("value", ""),
                    chapter_number,
                )
            return changes
    except LLMError as e:
        return [{"error": str(e)}]
    except Exception as e:
        return [{"error": str(e)}]
    return []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@truth_bp.route("/novels/<int:novel_id>/truths")
def list_truths(novel_id):
    """List all truths for a novel."""
    chapter = request.args.get("chapter", type=int)
    if chapter:
        truths = get_truths_at_chapter(novel_id, chapter)
    else:
        truths = _get_truths(novel_id)
    return jsonify(truths)


@truth_bp.route("/novels/<int:novel_id>/truths", methods=["POST"])
def add_truth_api(novel_id):
    """Add a truth manually."""
    data = request.get_json(silent=True) or {}
    add_truth(
        novel_id,
        data.get("subject", ""),
        data.get("property", "status"),
        data.get("value", ""),
        data.get("from_chapter", 1),
        data.get("to_chapter"),
    )
    return jsonify({"ok": True})


@truth_bp.route("/novels/<int:novel_id>/truths/extract", methods=["POST"])
def extract_truths(novel_id):
    """Extract truth changes from a chapter using AI."""
    chapter_number = request.form.get("chapter_number", type=int)
    if not chapter_number:
        return jsonify({"error": "chapter_number required"}), 400

    chapter = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first_or_404()
    from app.models import ChapterVersion
    version = ChapterVersion.query.filter_by(chapter_id=chapter.id).order_by(
        ChapterVersion.version_number.desc()).first()
    if not version:
        return jsonify({"error": "no version"}), 400

    from app.config_utils import get_model_config
    cfg = get_model_config(agent_type="temporal_truth")
    changes = extract_truths_from_chapter(version.content, chapter_number, novel_id, cfg)
    return jsonify(changes)


@truth_bp.route("/novels/<int:novel_id>/truths/context")
def truth_context(novel_id):
    """Get truth context for chapter generation."""
    chapter_number = request.args.get("chapter_number", type=int)
    if not chapter_number:
        return jsonify({"error": "chapter_number required"}), 400

    formatted = format_truths_for_prompt(novel_id, chapter_number)
    return jsonify({"context": formatted})
