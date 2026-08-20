#!/usr/bin/env python3
"""灵砚 MCP Server — 让 AI 通过 MCP 协议操作系统。

启动: python mcp_server.py
配置: 在 Claude Code 的 .claude/settings.json 中添加:
{
  "mcpServers": {
    "lingyan": {
      "command": "python",
      "args": ["d:\\\\document\\\\Ai novel system\\\\mcp_server.py"]
    }
  }
}
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
from app import create_app
from app.models import (
    db, Novel, Chapter, ChapterVersion, CriticReview, Character,
    WorldSetting, OutlineNode, Foreshadowing, ChapterSummary,
    ChapterMemory, CharacterRelation, StoryState, StoryStateSnapshot,
    ShortStory, Setting,
)

app = create_app()
mcp = FastMCP("灵砚小说系统", instructions="AI小说创作系统的MCP接口，可以管理小说、章节、角色、世界观、伏笔等。")


VALID_FS_STATUSES = ["planned", "buried", "advancing", "reclaimable", "resolved", "abandoned"]


# ---------------------------------------------------------------------------
# 小说管理
# ---------------------------------------------------------------------------

@mcp.tool()
def list_novels() -> str:
    """列出所有长篇小说，返回小说ID、标题、类型、章节数、角色数。"""
    with app.app_context():
        novels = Novel.query.order_by(Novel.created_at.desc()).all()
        if not novels:
            return "暂无小说"
        result = []
        for n in novels:
            ch = Chapter.query.filter_by(novel_id=n.id).count()
            char = Character.query.filter_by(novel_id=n.id).count()
            result.append(f"[{n.id}] {n.title} | {n.genre or '未分类'} | {ch}章 | {char}角色")
        return "\n".join(result)


@mcp.tool()
def create_novel(title: str, genre: str = "", synopsis: str = "", world_intro: str = "") -> str:
    """创建新长篇小说。"""
    with app.app_context():
        novel = Novel(title=title, genre=genre, synopsis=synopsis, world_intro=world_intro)
        db.session.add(novel)
        db.session.commit()
        return f"已创建小说 [{novel.id}] {title}"


@mcp.tool()
def delete_novel(novel_id: int) -> str:
    """删除小说及其所有关联数据（章节、角色、世界观、伏笔等）。"""
    with app.app_context():
        novel = db.session.get(Novel, novel_id)
        if not novel:
            return f"小说 {novel_id} 不存在"
        title = novel.title
        try:
            for ch in novel.chapters:
                for v in ChapterVersion.query.filter_by(chapter_id=ch.id).all():
                    CriticReview.query.filter_by(version_id=v.id).delete()
                ChapterVersion.query.filter_by(chapter_id=ch.id).delete()
                ChapterSummary.query.filter_by(chapter_id=ch.id).delete()
                ChapterMemory.query.filter_by(chapter_id=ch.id).delete()
                db.session.delete(ch)
            Character.query.filter_by(novel_id=novel_id).delete()
            CharacterRelation.query.filter_by(novel_id=novel_id).delete()
            WorldSetting.query.filter_by(novel_id=novel_id).delete()
            OutlineNode.query.filter_by(novel_id=novel_id).delete()
            Foreshadowing.query.filter_by(novel_id=novel_id).delete()
            StoryState.query.filter_by(novel_id=novel_id).delete()
            StoryStateSnapshot.query.filter_by(novel_id=novel_id).delete()
            ChapterMemory.query.filter_by(novel_id=novel_id).delete()
            db.session.delete(novel)
            db.session.commit()
            return f"已删除小说「{title}」及所有关联数据"
        except Exception as e:
            db.session.rollback()
            return f"删除失败: {e}"


@mcp.tool()
def get_novel_info(novel_id: int) -> str:
    """获取小说的详细信息，包括简介、世界观、统计数据。"""
    with app.app_context():
        novel = db.session.get(Novel, novel_id)
        if not novel:
            return f"小说 {novel_id} 不存在"
        ch = Chapter.query.filter_by(novel_id=novel_id).count()
        char = Character.query.filter_by(novel_id=novel_id).count()
        ws = WorldSetting.query.filter_by(novel_id=novel_id).count()
        fs = Foreshadowing.query.filter_by(novel_id=novel_id).count()
        return (
            f"【{novel.title}】\n"
            f"ID: {novel.id}\n"
            f"类型: {novel.genre or '未设置'}\n"
            f"简介: {novel.synopsis or '无'}\n"
            f"世界观: {novel.world_intro or '无'}\n"
            f"章节数: {ch} | 角色数: {char} | 世界观条目: {ws} | 伏笔数: {fs}"
        )


# ---------------------------------------------------------------------------
# 章节管理
# ---------------------------------------------------------------------------

@mcp.tool()
def list_chapters(novel_id: int) -> str:
    """列出小说的所有章节，显示版本数和审批状态。"""
    with app.app_context():
        chapters = Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.chapter_number).all()
        if not chapters:
            return "暂无章节"
        result = []
        for ch in chapters:
            ver = ChapterVersion.query.filter_by(chapter_id=ch.id).count()
            appr = ChapterVersion.query.filter_by(chapter_id=ch.id, approved=True).count()
            result.append(f"第{ch.chapter_number}章 [{ch.id}] {ch.title or '无标题'} | {ver}版本 | {appr}已审批")
        return "\n".join(result)


@mcp.tool()
def create_chapter(novel_id: int, chapter_number: int, title: str = "", outline: str = "") -> str:
    """创建新章节。"""
    with app.app_context():
        if Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first():
            return f"第{chapter_number}章已存在"
        ch = Chapter(novel_id=novel_id, chapter_number=chapter_number, title=title, outline=outline)
        db.session.add(ch)
        db.session.commit()
        return f"已创建第{chapter_number}章 [{ch.id}] {title}"


@mcp.tool()
def get_chapter_content(novel_id: int, chapter_number: int) -> str:
    """获取章节的最新版本内容。"""
    with app.app_context():
        ch = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first()
        if not ch:
            return f"第{chapter_number}章不存在"
        ver = ChapterVersion.query.filter_by(chapter_id=ch.id).order_by(
            ChapterVersion.version_number.desc()).first()
        if not ver:
            return f"第{chapter_number}章暂无内容"
        return (
            f"第{chapter_number}章 {ch.title} (V{ver.version_number}, {len(ver.content)}字)\n\n"
            f"{ver.content}"
        )


@mcp.tool()
def approve_chapter(novel_id: int, chapter_number: int) -> str:
    """审批通过章节的最新版本。"""
    with app.app_context():
        ch = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first()
        if not ch:
            return f"第{chapter_number}章不存在"
        ver = ChapterVersion.query.filter_by(chapter_id=ch.id).order_by(
            ChapterVersion.version_number.desc()).first()
        if not ver:
            return f"第{chapter_number}章暂无内容"
        ver.approved = True
        db.session.commit()
        return f"已审批: 第{chapter_number}章 V{ver.version_number}"


@mcp.tool()
def save_chapter_content(novel_id: int, chapter_number: int, content: str, source: str = "human") -> str:
    """保存章节内容（创建新版本）。source: "ai" 或 "human"。"""
    with app.app_context():
        ch = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first()
        if not ch:
            return f"第{chapter_number}章不存在"
        max_ver = db.session.query(db.func.max(ChapterVersion.version_number)).filter_by(chapter_id=ch.id).scalar()
        ver = ChapterVersion(
            chapter_id=ch.id,
            version_number=(max_ver or 0) + 1,
            content=content,
            source=source,
        )
        db.session.add(ver)
        db.session.commit()
        return f"已保存: 第{chapter_number}章 V{ver.version_number} ({len(content)}字)"


# ---------------------------------------------------------------------------
# 角色管理
# ---------------------------------------------------------------------------

@mcp.tool()
def list_characters(novel_id: int) -> str:
    """列出小说的所有角色。"""
    with app.app_context():
        chars = Character.query.filter_by(novel_id=novel_id).all()
        if not chars:
            return "暂无角色"
        result = []
        for c in chars:
            result.append(f"[{c.id}] {c.name} | {c.personality or '未设置'} | {c.background or ''}")
        return "\n".join(result)


@mcp.tool()
def create_character(novel_id: int, name: str, personality: str = "", speaking_style: str = "",
                     appearance: str = "", background: str = "", motivation: str = "",
                     arc_direction: str = "") -> str:
    """创建新角色。"""
    with app.app_context():
        char = Character(
            novel_id=novel_id, name=name, personality=personality,
            speaking_style=speaking_style, appearance=appearance,
            background=background, motivation=motivation, arc_direction=arc_direction,
        )
        db.session.add(char)
        db.session.commit()
        return f"已创建角色 [{char.id}] {name}"


@mcp.tool()
def update_character(character_id: int, name: str = "", personality: str = "",
                     speaking_style: str = "", appearance: str = "", background: str = "",
                     motivation: str = "", arc_direction: str = "") -> str:
    """更新角色信息。只传入需要修改的字段。"""
    with app.app_context():
        char = db.session.get(Character, character_id)
        if not char:
            return f"角色 {character_id} 不存在"
        if name:
            char.name = name
        if personality:
            char.personality = personality
        if speaking_style:
            char.speaking_style = speaking_style
        if appearance:
            char.appearance = appearance
        if background:
            char.background = background
        if motivation:
            char.motivation = motivation
        if arc_direction:
            char.arc_direction = arc_direction
        db.session.commit()
        return f"已更新角色「{char.name}」"


# ---------------------------------------------------------------------------
# 世界观管理
# ---------------------------------------------------------------------------

@mcp.tool()
def list_world_settings(novel_id: int) -> str:
    """列出小说的世界观设定。"""
    with app.app_context():
        settings = WorldSetting.query.filter_by(novel_id=novel_id).all()
        if not settings:
            return "暂无世界观设定"
        result = []
        for ws in settings:
            result.append(f"[{ws.id}] [{ws.category}] {ws.title}: {ws.content[:80]}")
        return "\n".join(result)


@mcp.tool()
def create_world_setting(novel_id: int, category: str, title: str, content: str) -> str:
    """创建世界观设定。category: 地图/势力/规则/时间线 等。"""
    with app.app_context():
        ws = WorldSetting(novel_id=novel_id, category=category, title=title, content=content)
        db.session.add(ws)
        db.session.commit()
        return f"已创建世界观设定 [{ws.id}] {title}"


# ---------------------------------------------------------------------------
# 伏笔管理
# ---------------------------------------------------------------------------

@mcp.tool()
def list_foreshadowing(novel_id: int) -> str:
    """列出小说的所有伏笔及其状态。"""
    with app.app_context():
        items = Foreshadowing.query.filter_by(novel_id=novel_id).all()
        if not items:
            return "暂无伏笔"
        result = []
        for f in items:
            result.append(f"[{f.id}] {f.title or (f.description or '')[:30]} | 状态:{f.status} | 重要度:{f.importance}")
        return "\n".join(result)


@mcp.tool()
def create_foreshadowing(novel_id: int, title: str, description: str, importance: int = 5) -> str:
    """创建伏笔。importance: 1-10，越高越重要。"""
    with app.app_context():
        threshold = 30 if importance >= 9 else 20 if importance >= 7 else 15 if importance >= 4 else 10
        fs = Foreshadowing(
            novel_id=novel_id, title=title, description=description,
            importance=importance, timeout_threshold=threshold,
        )
        db.session.add(fs)
        db.session.commit()
        return f"已创建伏笔 [{fs.id}] {title}"


@mcp.tool()
def update_foreshadowing_status(foreshadow_id: int, new_status: str) -> str:
    """更新伏笔状态。合法状态: planned, buried, advancing, reclaimable, resolved, abandoned"""
    with app.app_context():
        if new_status not in VALID_FS_STATUSES:
            return f"无效状态: {new_status}，合法值: {', '.join(VALID_FS_STATUSES)}"
        fs = db.session.get(Foreshadowing, foreshadow_id)
        if not fs:
            return f"伏笔 {foreshadow_id} 不存在"
        old = fs.status
        fs.status = new_status
        db.session.commit()
        return f"伏笔「{fs.title or fs.description[:20]}」: {old} → {new_status}"


# ---------------------------------------------------------------------------
# 大纲管理
# ---------------------------------------------------------------------------

@mcp.tool()
def list_outline(novel_id: int) -> str:
    """列出小说的大纲树。"""
    with app.app_context():
        nodes = OutlineNode.query.filter_by(novel_id=novel_id).order_by(
            OutlineNode.parent_id.nullsfirst(), OutlineNode.sort_order).all()
        if not nodes:
            return "暂无大纲"
        result = []
        for n in nodes:
            indent = "  " if n.parent_id else ""
            result.append(f"{indent}[{n.id}] [{n.node_type}] {n.title}: {(n.summary or '')[:60]}")
        return "\n".join(result)


@mcp.tool()
def create_outline_node(novel_id: int, title: str, summary: str = "",
                        node_type: str = "chapter", parent_id: int = 0) -> str:
    """创建大纲节点。node_type: volume/chapter/scene。"""
    with app.app_context():
        max_order = db.session.query(db.func.max(OutlineNode.sort_order)).filter_by(
            novel_id=novel_id, parent_id=parent_id or None).scalar()
        node = OutlineNode(
            novel_id=novel_id, parent_id=parent_id or None,
            sort_order=(max_order or 0) + 1,
            node_type=node_type, title=title, summary=summary,
        )
        db.session.add(node)
        db.session.commit()
        return f"已创建大纲节点 [{node.id}] {title}"


# ---------------------------------------------------------------------------
# 短篇创作
# ---------------------------------------------------------------------------

@mcp.tool()
def list_short_stories() -> str:
    """列出所有短篇。"""
    with app.app_context():
        stories = ShortStory.query.order_by(ShortStory.created_at.desc()).all()
        if not stories:
            return "暂无短篇"
        result = []
        for s in stories:
            result.append(f"[{s.id}] {s.title} | {s.mode} | {s.status} | {len(s.content or '')}字")
        return "\n".join(result)


@mcp.tool()
def create_short_story(title: str, inspiration: str = "", mode: str = "inspiration",
                       genre: str = "", theme: str = "", character_desc: str = "",
                       scene_desc: str = "", tone: str = "", word_target: int = 2000) -> str:
    """创建短篇。mode: inspiration(灵感)/setting(设定)/careful(细心)。"""
    with app.app_context():
        story = ShortStory(
            title=title, mode=mode, inspiration=inspiration,
            genre=genre, theme=theme, character_desc=character_desc,
            scene_desc=scene_desc, tone=tone, word_target=word_target,
        )
        db.session.add(story)
        db.session.commit()
        return f"已创建短篇 [{story.id}] {title} (模式:{mode})"


@mcp.tool()
def get_short_story(story_id: int) -> str:
    """获取短篇内容。"""
    with app.app_context():
        story = db.session.get(ShortStory, story_id)
        if not story:
            return f"短篇 {story_id} 不存在"
        return (
            f"【{story.title}】\n"
            f"模式: {story.mode} | 状态: {story.status} | 字数: {len(story.content or '')}\n\n"
            f"{story.content or '暂无内容'}"
        )


# ---------------------------------------------------------------------------
# 系统设置
# ---------------------------------------------------------------------------

@mcp.tool()
def get_settings() -> str:
    """获取当前系统设置。"""
    with app.app_context():
        settings = Setting.query.all()
        if not settings:
            return "暂无设置"
        result = []
        for s in settings:
            val = s.value
            if 'key' in s.key.lower() and len(val) > 10:
                val = val[:10] + '...'
            result.append(f"{s.key}: {val}")
        return "\n".join(result)


@mcp.tool()
def update_setting(key: str, value: str) -> str:
    """更新系统设置。"""
    with app.app_context():
        s = db.session.get(Setting, key)
        if s:
            s.value = value
        else:
            s = Setting(key=key, value=value)
            db.session.add(s)
        db.session.commit()
        return f"已设置: {key}"


# ---------------------------------------------------------------------------
# 知识库
# ---------------------------------------------------------------------------

@mcp.tool()
def get_knowledge_context(novel_id: int) -> str:
    """获取小说的完整知识库上下文（人物+世界观+活跃伏笔）。"""
    with app.app_context():
        characters = Character.query.filter_by(novel_id=novel_id).all()
        world_settings = WorldSetting.query.filter_by(novel_id=novel_id).all()
        foreshadowing = Foreshadowing.query.filter_by(novel_id=novel_id).filter(
            Foreshadowing.status.in_(["open", "planned", "buried", "advancing", "reclaimable"])
        ).all()

        parts = []
        if characters:
            parts.append("【人物】")
            for c in characters:
                parts.append(f"  {c.name}: {c.personality or ''} {c.background or ''}")
        if world_settings:
            parts.append("\n【世界观】")
            for ws in world_settings:
                parts.append(f"  [{ws.category}] {ws.title}: {(ws.content or '')[:100]}")
        if foreshadowing:
            parts.append("\n【活跃伏笔】")
            for f in foreshadowing:
                parts.append(f"  [{f.status}] {f.title or (f.description or '')[:50]}")
        return "\n".join(parts) if parts else "知识库为空"


@mcp.tool()
def quick_audit(novel_id: int, chapter_number: int) -> str:
    """对章节进行快速质量审计（AI痕迹检查）。"""
    with app.app_context():
        ch = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first()
        if not ch:
            return f"第{chapter_number}章不存在"
        ver = ChapterVersion.query.filter_by(chapter_id=ch.id).order_by(
            ChapterVersion.version_number.desc()).first()
        if not ver:
            return f"第{chapter_number}章暂无内容"

        from app.services.deai_agent import deai_process, get_deai_stats
        original = ver.content
        processed = deai_process(original)
        stats = get_deai_stats(original, processed)

        return (
            f"第{chapter_number}章 审计结果:\n"
            f"字数: {stats['original_length']}\n"
            f"检测到AI模式: {stats['patterns_found']}处\n"
            f"字数变化: {stats['reduction_pct']}%\n"
            f"内容已变化: {'是' if original != processed else '否'}"
        )


# ---------------------------------------------------------------------------
# 运行
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
