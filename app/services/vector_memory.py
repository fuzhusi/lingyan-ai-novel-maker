"""Vector Memory — semantic search for long-form novel context.

Uses SQLite FTS5 (Full Text Search) for tokenized semantic retrieval.
No external vector DB dependency — works with built-in SQLite.

Memory types:
- chapter_summary: Chapter-level summaries
- character: Character descriptions and states
- world_setting: World-building rules
- foreshadowing: Foreshadow items
- scene: Scene-level details (from ChapterMemory)
"""
import json
from flask import Blueprint, request, jsonify
from app.models import (db, Novel, Chapter, ChapterVersion, ChapterSummary,
                        Character, WorldSetting, Foreshadowing, ChapterMemory)

memory_bp = Blueprint("memory", __name__, url_prefix="/api")


def init_fts():
    """Create FTS5 virtual tables for memory search."""
    with db.engine.connect() as conn:
        conn.execute(db.text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                content,
                memory_type,
                novel_id UNINDEXED,
                source_id UNINDEXED,
                chapter_number UNINDEXED,
                tokenize='unicode61'
            )
        """))
        conn.commit()


def index_memory(novel_id):
    """Index all memory items for a novel into FTS5."""
    init_fts()

    with db.engine.connect() as conn:
        # Clear existing entries for this novel
        conn.execute(db.text("DELETE FROM memory_fts WHERE novel_id = :nid"), {"nid": novel_id})

        # Index chapter summaries
        chapters = Chapter.query.filter_by(novel_id=novel_id).all()
        for ch in chapters:
            summary = ChapterSummary.query.filter_by(chapter_id=ch.id).first()
            if summary and summary.summary:
                conn.execute(db.text(
                    "INSERT INTO memory_fts (content, memory_type, novel_id, source_id, chapter_number) "
                    "VALUES (:content, 'chapter_summary', :nid, :sid, :cn)"
                ), {"content": summary.summary, "nid": novel_id, "sid": ch.id, "cn": ch.chapter_number})

            # Index chapter memory scenes
            memory = ChapterMemory.query.filter_by(chapter_id=ch.id).first()
            if memory:
                if memory.scenes_json:
                    try:
                        scenes = json.loads(memory.scenes_json)
                        for scene in scenes:
                            if isinstance(scene, dict) and scene.get("summary"):
                                conn.execute(db.text(
                                    "INSERT INTO memory_fts (content, memory_type, novel_id, source_id, chapter_number) "
                                    "VALUES (:content, 'scene', :nid, :sid, :cn)"
                                ), {"content": scene["summary"], "nid": novel_id, "sid": ch.id, "cn": ch.chapter_number})
                    except json.JSONDecodeError:
                        pass

        # Index characters
        characters = Character.query.filter_by(novel_id=novel_id).all()
        for c in characters:
            parts = [c.name]
            if c.personality:
                parts.append(c.personality)
            if c.background:
                parts.append(c.background)
            if c.motivation:
                parts.append(c.motivation)
            content = " ".join(parts)
            if content.strip():
                conn.execute(db.text(
                    "INSERT INTO memory_fts (content, memory_type, novel_id, source_id) "
                    "VALUES (:content, 'character', :nid, :sid)"
                ), {"content": content, "nid": novel_id, "sid": c.id})

        # Index world settings
        ws_items = WorldSetting.query.filter_by(novel_id=novel_id).all()
        for ws in ws_items:
            content = f"{ws.category} {ws.title} {ws.content}"
            if content.strip():
                conn.execute(db.text(
                    "INSERT INTO memory_fts (content, memory_type, novel_id, source_id) "
                    "VALUES (:content, 'world_setting', :nid, :sid)"
                ), {"content": content, "nid": novel_id, "sid": ws.id})

        # Index foreshadowing
        fs_items = Foreshadowing.query.filter_by(novel_id=novel_id).all()
        for fs in fs_items:
            content = f"{fs.title or ''} {fs.description or ''}"
            if content.strip():
                conn.execute(db.text(
                    "INSERT INTO memory_fts (content, memory_type, novel_id, source_id) "
                    "VALUES (:content, 'foreshadowing', :nid, :sid)"
                ), {"content": content, "nid": novel_id, "sid": fs.id})

        conn.commit()


def _sanitize_fts_query(query):
    """Sanitize user input for FTS5 MATCH to prevent syntax errors."""
    # Strip special FTS5 operators and wrap in quotes for safe phrase matching
    clean = query.replace('"', '""').replace('*', '').replace('(', '').replace(')', '')
    return '"' + clean + '"'


def search_memory(novel_id, query, memory_type=None, limit=10):
    """Search memory using FTS5 full-text search."""
    init_fts()
    safe_query = _sanitize_fts_query(query)

    with db.engine.connect() as conn:
        if memory_type:
            result = conn.execute(db.text(
                "SELECT content, memory_type, source_id, chapter_number, "
                "rank FROM memory_fts "
                "WHERE memory_fts MATCH :query AND novel_id = :nid AND memory_type = :mt "
                "ORDER BY rank LIMIT :lim"
            ), {"query": safe_query, "nid": novel_id, "mt": memory_type, "lim": limit})
        else:
            result = conn.execute(db.text(
                "SELECT content, memory_type, source_id, chapter_number, "
                "rank FROM memory_fts "
                "WHERE memory_fts MATCH :query AND novel_id = :nid "
                "ORDER BY rank LIMIT :lim"
            ), {"query": safe_query, "nid": novel_id, "lim": limit})

        rows = result.fetchall()
        return [{
            "content": row[0],
            "memoryType": row[1],
            "sourceId": row[2],
            "chapterNumber": row[3],
            "relevance": abs(row[4]) if row[4] else 0,
        } for row in rows]


def build_context_for_chapter(novel_id, chapter_number, query="", limit=10):
    """Build context for chapter generation using memory search.

    Combines:
    1. Recent chapter summaries (time-based)
    2. FTS search results (relevance-based)
    3. Character states
    4. Active foreshadowing
    """
    context_parts = []

    # 1. Recent summaries (last 5 chapters)
    recent_chapters = (Chapter.query
                       .filter_by(novel_id=novel_id)
                       .filter(Chapter.chapter_number < chapter_number)
                       .order_by(Chapter.chapter_number.desc())
                       .limit(5).all())
    if recent_chapters:
        summaries = []
        for ch in reversed(recent_chapters):
            cs = ChapterSummary.query.filter_by(chapter_id=ch.id).first()
            if cs and cs.summary:
                summaries.append(f"第{ch.chapter_number}章：{cs.summary}")
        if summaries:
            context_parts.append("【前情提要】\n" + "\n".join(summaries))

    # 2. FTS search (if query provided)
    if query:
        results = search_memory(novel_id, query, limit=limit)
        if results:
            search_lines = [f"- {r['content'][:100]}" for r in results[:5]]
            context_parts.append("【相关记忆】\n" + "\n".join(search_lines))

    # 3. Active foreshadowing
    fs_items = Foreshadowing.query.filter_by(novel_id=novel_id).filter(
        Foreshadowing.status.in_(["open", "planned", "buried", "advancing", "reclaimable"])
    ).all()
    if fs_items:
        fs_lines = [f"- {f.title or (f.description or '')[:50]}" for f in fs_items[:5]]
        context_parts.append("【活跃伏笔】\n" + "\n".join(fs_lines))

    return "\n\n".join(context_parts)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@memory_bp.route("/novels/<int:novel_id>/memory/index", methods=["POST"])
def index_novel_memory(novel_id):
    """Index all memory for a novel."""
    Novel.query.get_or_404(novel_id)
    index_memory(novel_id)
    return jsonify({"ok": True})


@memory_bp.route("/novels/<int:novel_id>/memory/search")
def search_novel_memory(novel_id):
    """Search memory."""
    query = request.args.get("q", "")
    memory_type = request.args.get("type")
    limit = request.args.get("limit", 10, type=int)

    if not query:
        return jsonify({"error": "q required"}), 400

    results = search_memory(novel_id, query, memory_type, limit)
    return jsonify(results)


@memory_bp.route("/novels/<int:novel_id>/memory/context")
def memory_context(novel_id):
    """Get context for chapter generation."""
    chapter_number = request.args.get("chapter_number", type=int)
    query = request.args.get("q", "")

    if not chapter_number:
        return jsonify({"error": "chapter_number required"}), 400

    context = build_context_for_chapter(novel_id, chapter_number, query)
    return jsonify({"context": context})
