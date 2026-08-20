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


def _cjk_tokenize(text):
    """为 FTS5 unicode61 分词器预处理中文文本。

    SQLite FTS5 的 unicode61 不识别 CJK 词边界，会把连续中文当成一个
    不可分的超长 token，导致中文检索几乎失效。这里把每个 CJK 字符前后
    加空格，使 unicode61 按单字分词，从而支持中文逐字检索。
    英文/数字保持原样（unicode61 本就能正确按空白/标点分词）。
    """
    if not text:
        return ""
    out = []
    for ch in text:
        cp = ord(ch)
        # CJK 统一汉字 + 扩展A + 兼容汉字 + 日文假名 + 韩文音节
        if (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF
                or 0x3040 <= cp <= 0x30FF or 0xAC00 <= cp <= 0xD7AF):
            out.append(" " + ch + " ")
        else:
            out.append(ch)
    return " ".join("".join(out).split())


def _cjk_detokenize(text):
    """还原 _cjk_tokenize 加的空格：删去非 ASCII 字符（CJK/标点）之间的空格。

    保留 ASCII 与非 ASCII 之间的空格（中英混排边界），只删两个非 ASCII
    字符之间的空格（这些是 tokenize 时给 CJK 加的）。
    """
    if not text:
        return ""
    out = []
    for i, ch in enumerate(text):
        if ch == " ":
            prev_nonascii = i > 0 and ord(text[i - 1]) > 127
            next_nonascii = i + 1 < len(text) and ord(text[i + 1]) > 127
            if prev_nonascii and next_nonascii:
                continue
        out.append(ch)
    return "".join(out)


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
                ), {"content": _cjk_tokenize(summary.summary), "nid": novel_id, "sid": ch.id, "cn": ch.chapter_number})

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
                                ), {"content": _cjk_tokenize(scene["summary"]), "nid": novel_id, "sid": ch.id, "cn": ch.chapter_number})
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
                ), {"content": _cjk_tokenize(content), "nid": novel_id, "sid": c.id})

        # Index world settings
        ws_items = WorldSetting.query.filter_by(novel_id=novel_id).all()
        for ws in ws_items:
            content = f"{ws.category} {ws.title} {ws.content}"
            if content.strip():
                conn.execute(db.text(
                    "INSERT INTO memory_fts (content, memory_type, novel_id, source_id) "
                    "VALUES (:content, 'world_setting', :nid, :sid)"
                ), {"content": _cjk_tokenize(content), "nid": novel_id, "sid": ws.id})

        # Index foreshadowing
        fs_items = Foreshadowing.query.filter_by(novel_id=novel_id).all()
        for fs in fs_items:
            content = f"{fs.title or ''} {fs.description or ''}"
            if content.strip():
                conn.execute(db.text(
                    "INSERT INTO memory_fts (content, memory_type, novel_id, source_id) "
                    "VALUES (:content, 'foreshadowing', :nid, :sid)"
                ), {"content": _cjk_tokenize(content), "nid": novel_id, "sid": fs.id})

        conn.commit()


def _sanitize_fts_query(query):
    """Sanitize user input for FTS5 MATCH to prevent syntax errors.

    配合 _cjk_tokenize：中文内容已按单字加空格索引，查询也先按字加空格，
    再按空白拆成单字短语用 OR 连接 —— 任一字命中即可召回（中文逐字检索）。
    英文/数字保留原词作为短语。
    """
    clean = query.replace('"', '""').replace('*', '').replace('(', '').replace(')', '').strip()
    if not clean:
        return '""'
    # 中文按字拆开（与索引侧 _cjk_tokenize 一致），英文保持
    tokenized = _cjk_tokenize(clean)
    terms = [t for t in tokenized.split() if t.strip()]
    if not terms:
        return '""'
    return " OR ".join('"' + t + '"' for t in terms)


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
            "content": _cjk_detokenize(row[0]),
            "memoryType": row[1],
            "sourceId": row[2],
            "chapterNumber": row[3],
            "relevance": abs(row[4]) if row[4] else 0,
        } for row in rows]


def build_context_for_chapter(novel_id, chapter_number, query="", limit=10):
    """Build context for chapter generation using memory search.

    只负责 FTS 语义检索（按本章大纲/相关性召回历史片段）。
    近章摘要、活跃伏笔等结构化上下文已由 assemble_chapter_context +
    build_writer_prompt 统一负责，此处不再重复注入，避免同一内容在
    prompt 中出现两次。
    """
    if not query:
        return ""
    results = search_memory(novel_id, query, limit=limit)
    if not results:
        return ""
    # 直接列片段（外层 build_writer_prompt 已用 _section 加标题）
    search_lines = [f"- {r['content'][:150]}" for r in results[:5]]
    return "\n".join(search_lines)


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
