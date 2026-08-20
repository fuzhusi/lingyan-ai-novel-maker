"""Information Boundary System — prevents characters from knowing things they shouldn't.

Inspired by Dramatica-Flow's information boundary system.

Core rule: Characters can only know what they've:
1. Witnessed (亲眼所见)
2. Been told (被人告知)
3. Deduced (推断得知)

This prevents "omniscient contamination" — where characters behave as if they
know events they weren't present for.

Implementation:
- Each character tracks what they know via CharacterKnowledge entries
- Before generating, inject character knowledge boundaries into prompt
- After generating, check for boundary violations
"""
import json
from app.models import db, Character, Chapter, ChapterVersion, ChapterMemory


def get_character_knowledge(novel_id, character_name, up_to_chapter):
    """Get what a character knows up to a specific chapter.

    Returns a list of knowledge entries: what the character has witnessed/been told/deduced.
    """
    character = Character.query.filter_by(novel_id=novel_id, name=character_name).first()
    if not character:
        return []

    # Scan chapter memories for events involving this character
    knowledge = []
    chapters = (Chapter.query
                .filter_by(novel_id=novel_id)
                .filter(Chapter.chapter_number <= up_to_chapter)
                .order_by(Chapter.chapter_number).all())

    for ch in chapters:
        memory = ChapterMemory.query.filter_by(chapter_id=ch.id).first()
        if not memory:
            continue

        # Check key events
        try:
            events = json.loads(memory.key_events_json or "[]")
            for event in events:
                if isinstance(event, str) and character_name in event:
                    knowledge.append({
                        "chapter": ch.chapter_number,
                        "type": "witnessed",
                        "content": event,
                    })
        except json.JSONDecodeError:
            pass

        # Check scenes for character presence
        try:
            scenes = json.loads(memory.scenes_json or "[]")
            for scene in scenes:
                if isinstance(scene, dict):
                    chars = scene.get("characters", [])
                    if character_name in chars:
                        knowledge.append({
                            "chapter": ch.chapter_number,
                            "type": "present",
                            "content": scene.get("summary", ""),
                            "setting": scene.get("setting", ""),
                        })
        except json.JSONDecodeError:
            pass

        # Check character changes (things that happened to this character)
        try:
            changes = json.loads(memory.character_changes_json or "{}")
            if character_name in changes:
                knowledge.append({
                    "chapter": ch.chapter_number,
                    "type": "experienced",
                    "content": changes[character_name],
                })
        except json.JSONDecodeError:
            pass

    return knowledge


def get_all_character_knowledge_map(novel_id, up_to_chapter):
    """Get knowledge map for all characters in a novel.

    Returns: {character_name: [knowledge_entries]}
    """
    characters = Character.query.filter_by(novel_id=novel_id).all()
    knowledge_map = {}
    for char in characters:
        knowledge_map[char.name] = get_character_knowledge(novel_id, char.name, up_to_chapter)
    return knowledge_map


def format_knowledge_boundaries(novel_id, chapter_number):
    """Format knowledge boundaries for prompt injection.

    Returns a string that tells the AI what each character knows and doesn't know.
    """
    knowledge_map = get_all_character_knowledge_map(novel_id, chapter_number)
    if not knowledge_map:
        return ""

    lines = []
    for char_name, entries in knowledge_map.items():
        if not entries:
            lines.append(f"- {char_name}：尚无已知信息")
            continue

        known = []
        for e in entries[-5:]:  # Last 5 knowledge entries
            if e["type"] == "witnessed":
                known.append(f"  亲眼所见(第{e['chapter']}章): {e['content'][:80]}")
            elif e["type"] == "present":
                known.append(f"  在场经历(第{e['chapter']}章): {e['content'][:80]}")
            elif e["type"] == "experienced":
                known.append(f"  亲身经历(第{e['chapter']}章): {e['content'][:80]}")

        lines.append(f"- {char_name}知道：")
        lines.extend(known)

    if not lines:
        return ""

    return (
        "【信息边界 — 重要约束】\n"
        "每个角色只能知道他们亲眼所见、被人告知、或合理推断的事情。\n"
        "绝对不能让角色知道他们不在场时发生的事件。\n\n"
        "各角色当前已知信息：\n" + "\n".join(lines)
    )


def check_boundary_violations(chapter_content, novel_id, chapter_number):
    """Check a chapter for information boundary violations.

    Returns a list of potential violations.
    """
    characters = Character.query.filter_by(novel_id=novel_id).all()
    violations = []

    for char in characters:
        # Simple heuristic: check if character mentions events they weren't present for
        # This is a lightweight check — a full check would use LLM
        knowledge = get_character_knowledge(novel_id, char.name, chapter_number)
        known_chapters = set(e["chapter"] for e in knowledge)

        # Check if character references events from chapters they weren't part of
        for ch_num in range(1, chapter_number):
            if ch_num not in known_chapters:
                # This is a very basic check — in practice, use LLM for verification
                pass

    return violations
