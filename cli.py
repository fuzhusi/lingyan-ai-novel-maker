#!/usr/bin/env python3
"""灵砚 CLI — 命令行操作小说系统。

完整命令列表:
    小说: novel list/create/info/delete
    章节: chapter list/create/content/approve
    角色: character list/create/info/update
    世界观: world list/create
    伏笔: foreshadow list/create/status
    大纲: outline list/create
    关系: relation list/create
    短篇: short list/create/content
    模板: template list/create/delete
    审计: audit run
    设置: setting list/set/get
    技巧: skill list/active/toggle/enable/disable/info/preview/create/delete
    优化: optimize diagnose
    系统: sys info/backup/reset

用法示例:
    python cli.py novel list
    python cli.py novel create --title "我的小说"
    python cli.py chapter list --novel 1
    python cli.py character create --novel 1 --name "张三"
    python cli.py short create --title "深夜来客" --mode inspiration
    python cli.py skill list --verbose
    python cli.py skill toggle --skill jiangnan_fingerprint
    python cli.py skill preview --task-type write
"""
import sys
import os
import argparse
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.models import (
    db, Novel, Chapter, ChapterVersion, CriticReview, Character,
    WorldSetting, OutlineNode, Foreshadowing, ChapterSummary,
    ChapterMemory, CharacterRelation, StoryState, StoryStateSnapshot,
    ShortStory, ShortStoryVersion, ShortStoryReview, PromptTemplate, Setting,
)
from app.routes.settings import AGENT_TYPES, get_model_config
from app.routes.auth import DEFAULT_USERS

app = create_app()


# ---------------------------------------------------------------------------
# CLI 认证
# ---------------------------------------------------------------------------

# 认证状态文件 (存储当前登录用户)
AUTH_FILE = os.path.expanduser("~/.lingyan_cli_auth.json")


def load_cli_auth():
    """从文件加载 CLI 认证状态。"""
    if not os.path.exists(AUTH_FILE):
        return None
    try:
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def save_cli_auth(username):
    """保存 CLI 认证状态到文件。"""
    with open(AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump({"username": username, "logged_in_at": datetime.now().isoformat()}, f)


def clear_cli_auth():
    """清除 CLI 认证状态。"""
    if os.path.exists(AUTH_FILE):
        os.remove(AUTH_FILE)


def check_cli_auth():
    """检查 CLI 认证 — 已禁用（单用户模式）：直接放行默认用户。"""
    user = DEFAULT_USERS.get("admin", {})
    return {"username": "admin", "name": user.get("name", "管理员"), "role": user.get("role", "admin")}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def truncate(text, max_len=60):
    """截断文本用于显示。"""
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def print_table(headers, rows):
    """简单的表格输出。"""
    if not rows:
        print("  (空)")
        return
    # 计算列宽
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    # 打印表头
    header_line = "  " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("  " + "-+-".join("-" * w for w in col_widths))
    # 打印数据
    for row in rows:
        print("  " + " | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)))


def confirm(prompt):
    """确认操作。"""
    resp = input(f"{prompt} [y/N]: ").strip().lower()
    return resp in ("y", "yes")


# ---------------------------------------------------------------------------
# 小说管理
# ---------------------------------------------------------------------------

def cmd_novel(args):
    with app.app_context():
        if args.action == "list":
            novels = Novel.query.order_by(Novel.created_at.desc()).all()
            if not novels:
                print("暂无小说")
                return
            rows = []
            for n in novels:
                ch = Chapter.query.filter_by(novel_id=n.id).count()
                char = Character.query.filter_by(novel_id=n.id).count()
                ws = WorldSetting.query.filter_by(novel_id=n.id).count()
                rows.append([f"[{n.id}]", n.title, n.genre or "未分类", f"{ch}章", f"{char}角色", f"{ws}世界观"])
            print_table(["ID", "标题", "类型", "章节", "角色", "世界观"], rows)

        elif args.action == "create":
            novel = Novel(
                title=args.title,
                genre=getattr(args, 'genre', '') or '',
                synopsis=getattr(args, 'synopsis', '') or '',
                world_intro=getattr(args, 'world_intro', '') or '',
            )
            db.session.add(novel)
            db.session.commit()
            print(f"✓ 已创建: [{novel.id}] {novel.title}")

        elif args.action == "delete":
            novel = db.session.get(Novel, args.id)
            if not novel:
                print(f"✗ 小说 {args.id} 不存在")
                return
            if not args.yes and not confirm(f"确定删除小说「{novel.title}」及其所有数据?"):
                print("已取消")
                return
            title = novel.title
            for ch in novel.chapters:
                for v in ChapterVersion.query.filter_by(chapter_id=ch.id).all():
                    CriticReview.query.filter_by(version_id=v.id).delete()
                ChapterVersion.query.filter_by(chapter_id=ch.id).delete()
                ChapterSummary.query.filter_by(chapter_id=ch.id).delete()
                ChapterMemory.query.filter_by(chapter_id=ch.id).delete()
                db.session.delete(ch)
            Character.query.filter_by(novel_id=args.id).delete()
            CharacterRelation.query.filter_by(novel_id=args.id).delete()
            WorldSetting.query.filter_by(novel_id=args.id).delete()
            OutlineNode.query.filter_by(novel_id=args.id).delete()
            Foreshadowing.query.filter_by(novel_id=args.id).delete()
            StoryState.query.filter_by(novel_id=args.id).delete()
            StoryStateSnapshot.query.filter_by(novel_id=args.id).delete()
            db.session.delete(novel)
            db.session.commit()
            print(f"✓ 已删除: {title}")

        elif args.action == "info":
            novel = db.session.get(Novel, args.id)
            if not novel:
                print(f"✗ 小说 {args.id} 不存在")
                return
            ch = Chapter.query.filter_by(novel_id=novel.id).count()
            char = Character.query.filter_by(novel_id=novel.id).count()
            ws = WorldSetting.query.filter_by(novel_id=novel.id).count()
            fs_open = Foreshadowing.query.filter_by(novel_id=novel.id).filter(
                Foreshadowing.status.in_(["open", "planned", "buried", "advancing", "reclaimable"])
            ).count()
            print(f"【{novel.title}】")
            print(f"  ID: {novel.id}")
            print(f"  类型: {novel.genre or '未设置'}")
            print(f"  简介: {novel.synopsis or '无'}")
            print(f"  世界观: {truncate(novel.world_intro, 80) or '无'}")
            print(f"  创建时间: {novel.created_at}")
            print(f"  ---")
            print(f"  章节: {ch}")
            print(f"  角色: {char}")
            print(f"  世界观条目: {ws}")
            print(f"  活跃伏笔: {fs_open}")

        elif args.action == "update":
            novel = db.session.get(Novel, args.id)
            if not novel:
                print(f"✗ 小说 {args.id} 不存在")
                return
            changed = []
            for field in ["title", "genre", "synopsis", "world_intro"]:
                val = getattr(args, field, None)
                if val is not None and str(val).strip():
                    setattr(novel, field, val)
                    changed.append(field)
            if changed:
                db.session.commit()
                print(f"✓ 已更新小说 [{novel.id}] {novel.title}：{', '.join(changed)}")
            else:
                print("（未指定要更新的字段）")


# ---------------------------------------------------------------------------
# 章节管理
# ---------------------------------------------------------------------------

def cmd_chapter(args):
    with app.app_context():
        if args.action == "list":
            chapters = Chapter.query.filter_by(novel_id=args.novel).order_by(Chapter.chapter_number).all()
            if not chapters:
                print(f"小说 {args.novel} 暂无章节")
                return
            rows = []
            for ch in chapters:
                ver = ChapterVersion.query.filter_by(chapter_id=ch.id).count()
                appr = ChapterVersion.query.filter_by(chapter_id=ch.id, approved=True).count()
                latest = ChapterVersion.query.filter_by(chapter_id=ch.id).order_by(
                    ChapterVersion.version_number.desc()).first()
                size = f"{len(latest.content)}字" if latest else "-"
                rows.append([f"第{ch.chapter_number}章", f"[{ch.id}]", truncate(ch.title, 20) or "无标题",
                            f"{ver}版本", f"{appr}已审批", size])
            print_table(["序号", "ID", "标题", "版本", "审批", "最新字数"], rows)

        elif args.action == "create":
            # 检查是否已存在
            existing = Chapter.query.filter_by(novel_id=args.novel, chapter_number=args.number).first()
            if existing:
                print(f"✗ 第{args.number}章已存在")
                return
            ch = Chapter(
                novel_id=args.novel,
                chapter_number=args.number,
                title=getattr(args, 'title', '') or '',
                outline=getattr(args, 'outline', '') or '',
                user_directive=getattr(args, 'directive', '') or '',
            )
            db.session.add(ch)
            db.session.commit()
            print(f"✓ 已创建: 第{args.number}章 [{ch.id}]")

        elif args.action == "content":
            ch = Chapter.query.filter_by(novel_id=args.novel, chapter_number=args.number).first()
            if not ch:
                print(f"✗ 第{args.number}章不存在")
                return
            ver = ChapterVersion.query.filter_by(chapter_id=ch.id).order_by(
                ChapterVersion.version_number.desc()).first()
            if not ver:
                print(f"第{args.number}章暂无内容")
                return
            print(f"第{args.number}章 {ch.title} (V{ver.version_number}, {len(ver.content)}字, "
                  f"来源:{ver.source}, {'已审批' if ver.approved else '未审批'})")
            print("-" * 60)
            if args.full:
                print(ver.content)
            else:
                print(ver.content[:args.length or 500])
                if len(ver.content) > (args.length or 500):
                    print(f"\n... (共{len(ver.content)}字, 使用 --full 查看完整内容)")

        elif args.action == "approve":
            ch = Chapter.query.filter_by(novel_id=args.novel, chapter_number=args.number).first()
            if not ch:
                print(f"✗ 第{args.number}章不存在")
                return
            ver = ChapterVersion.query.filter_by(chapter_id=ch.id).order_by(
                ChapterVersion.version_number.desc()).first()
            if not ver:
                print(f"第{args.number}章暂无内容")
                return
            ver.approved = True
            db.session.commit()
            print(f"✓ 已审批: 第{args.number}章 V{ver.version_number}")

        elif args.action == "update":
            ch = Chapter.query.filter_by(novel_id=args.novel, chapter_number=args.number).first()
            if not ch:
                print(f"✗ 第{args.number}章不存在")
                return
            changed = []
            if args.title is not None and str(args.title).strip():
                ch.title = args.title
                changed.append("title")
            if args.outline is not None and str(args.outline).strip():
                ch.outline = args.outline
                changed.append("outline")
            if args.directive is not None and str(args.directive).strip():
                ch.user_directive = args.directive
                changed.append("user_directive")
            if changed:
                db.session.commit()
                print(f"✓ 已更新第{args.number}章：{', '.join(changed)}")
            else:
                print("（未指定要更新的字段）")

        elif args.action == "delete":
            ch = Chapter.query.filter_by(novel_id=args.novel, chapter_number=args.number).first()
            if not ch:
                print(f"✗ 第{args.number}章不存在")
                return
            if not args.yes:
                confirm = input(f"确定删除第{args.number}章「{ch.title}」及其所有版本？(y/N) ").strip().lower()
                if confirm != "y":
                    print("已取消")
                    return
            for v in ChapterVersion.query.filter_by(chapter_id=ch.id).all():
                CriticReview.query.filter_by(version_id=v.id).delete()
            ChapterVersion.query.filter_by(chapter_id=ch.id).delete()
            ChapterSummary.query.filter_by(chapter_id=ch.id).delete()
            ChapterMemory.query.filter_by(chapter_id=ch.id).delete()
            db.session.delete(ch)
            db.session.commit()
            print(f"✓ 已删除第{args.number}章「{ch.title}」")


# ---------------------------------------------------------------------------
# 角色管理
# ---------------------------------------------------------------------------

def cmd_character(args):
    with app.app_context():
        if args.action == "list":
            chars = Character.query.filter_by(novel_id=args.novel).all()
            if not chars:
                print(f"小说 {args.novel} 暂无角色")
                return
            rows = []
            for c in chars:
                rows.append([f"[{c.id}]", c.name, truncate(c.personality, 30) or "未设置",
                            truncate(c.background, 30) or "-"])
            print_table(["ID", "姓名", "性格", "背景"], rows)

        elif args.action == "create":
            char = Character(
                novel_id=args.novel,
                name=args.name,
                personality=getattr(args, 'personality', '') or '',
                speaking_style=getattr(args, 'speaking_style', '') or '',
                appearance=getattr(args, 'appearance', '') or '',
                background=getattr(args, 'background', '') or '',
                motivation=getattr(args, 'motivation', '') or '',
                arc_direction=getattr(args, 'arc', '') or '',
            )
            db.session.add(char)
            db.session.commit()
            print(f"✓ 已创建角色: [{char.id}] {char.name}")

        elif args.action == "info":
            char = db.session.get(Character, args.id)
            if not char:
                print(f"✗ 角色 {args.id} 不存在")
                return
            print(f"【{char.name}】")
            print(f"  ID: {char.id} | 小说 ID: {char.novel_id}")
            print(f"  性格: {char.personality or '未设置'}")
            print(f"  说话风格: {char.speaking_style or '未设置'}")
            print(f"  外貌: {char.appearance or '未设置'}")
            print(f"  背景: {char.background or '未设置'}")
            print(f"  动机: {char.motivation or '未设置'}")
            print(f"  角色弧光: {char.arc_direction or '未设置'}")

        elif args.action == "update":
            char = db.session.get(Character, args.id)
            if not char:
                print(f"✗ 角色 {args.id} 不存在")
                return
            changed = []
            for field, attr in [("name", "name"), ("personality", "personality"),
                                ("speaking_style", "speaking_style"), ("appearance", "appearance"),
                                ("background", "background"), ("motivation", "motivation"),
                                ("arc", "arc_direction")]:
                val = getattr(args, attr, None) if attr != "arc" else getattr(args, "arc", None)
                if val is not None and str(val).strip():
                    setattr(char, attr, val)
                    changed.append(attr)
            if changed:
                db.session.commit()
                print(f"✓ 已更新角色 [{char.id}] {char.name}：{', '.join(changed)}")
            else:
                print("（未指定要更新的字段）")

        elif args.action == "delete":
            char = db.session.get(Character, args.id)
            if not char:
                print(f"✗ 角色 {args.id} 不存在")
                return
            if not args.yes:
                confirm = input(f"确定删除角色 [{char.id}] {char.name}？(y/N) ").strip().lower()
                if confirm != "y":
                    print("已取消")
                    return
            db.session.delete(char)
            db.session.commit()
            print(f"✓ 已删除角色 [{char.id}] {char.name}")


# ---------------------------------------------------------------------------
# 世界观管理
# ---------------------------------------------------------------------------

def cmd_world(args):
    with app.app_context():
        if args.action in ("list", "create") and not args.novel:
            print("✗ list/create 需要 --novel")
            return
        if args.action in ("update", "delete") and not args.id:
            print("✗ update/delete 需要 --id")
            return
        if args.action == "list":
            wss = WorldSetting.query.filter_by(novel_id=args.novel).all()
            if not wss:
                print(f"小说 {args.novel} 暂无世界观设定")
                return
            rows = []
            for ws in wss:
                rows.append([f"[{ws.id}]", ws.category, ws.title, truncate(ws.content, 40)])
            print_table(["ID", "类别", "标题", "内容预览"], rows)

        elif args.action == "create":
            ws = WorldSetting(
                novel_id=args.novel,
                category=args.category,
                title=args.title,
                content=getattr(args, 'content', '') or '',
            )
            db.session.add(ws)
            db.session.commit()
            print(f"✓ 已创建世界观设定: [{ws.id}] {ws.title}")

        elif args.action == "update":
            ws = db.session.get(WorldSetting, args.id)
            if not ws:
                print(f"✗ 世界观设定 {args.id} 不存在")
                return
            changed = []
            for field in ["category", "title", "content"]:
                val = getattr(args, field, None)
                if val is not None and str(val).strip():
                    setattr(ws, field, val)
                    changed.append(field)
            if changed:
                db.session.commit()
                print(f"✓ 已更新世界观设定 [{ws.id}] {ws.title}：{', '.join(changed)}")
            else:
                print("（未指定要更新的字段）")

        elif args.action == "delete":
            ws = db.session.get(WorldSetting, args.id)
            if not ws:
                print(f"✗ 世界观设定 {args.id} 不存在")
                return
            if not args.yes:
                confirm = input(f"确定删除世界观设定 [{ws.id}] {ws.title}？(y/N) ").strip().lower()
                if confirm != "y":
                    print("已取消")
                    return
            db.session.delete(ws)
            db.session.commit()
            print(f"✓ 已删除世界观设定 [{ws.id}] {ws.title}")


# ---------------------------------------------------------------------------
# 伏笔管理
# ---------------------------------------------------------------------------

VALID_FS_STATUSES = ["planned", "buried", "advancing", "reclaimable", "resolved", "abandoned"]


def cmd_foreshadow(args):
    with app.app_context():
        if args.action == "list":
            fss = Foreshadowing.query.filter_by(novel_id=args.novel).all()
            if not fss:
                print(f"小说 {args.novel} 暂无伏笔")
                return
            rows = []
            for f in fss:
                rows.append([f"[{f.id}]", truncate(f.title, 20), f.status,
                            f"重要度{f.importance}",
                            f"第{f.planted_chapter or '?'}章埋" if f.planted_chapter else "未埋"])
            print_table(["ID", "标题", "状态", "重要度", "埋设"], rows)

        elif args.action == "create":
            fs = Foreshadowing(
                novel_id=args.novel,
                title=args.title,
                description=getattr(args, 'description', '') or '',
                importance=getattr(args, 'importance', 5) or 5,
                planted_chapter=getattr(args, 'planted', None),
            )
            db.session.add(fs)
            db.session.commit()
            print(f"✓ 已创建伏笔: [{fs.id}] {fs.title}")

        elif args.action == "status":
            fs = db.session.get(Foreshadowing, args.id)
            if not fs:
                print(f"✗ 伏笔 {args.id} 不存在")
                return
            if args.status not in VALID_FS_STATUSES:
                print(f"✗ 无效状态: {args.status}")
                print(f"  合法状态: {', '.join(VALID_FS_STATUSES)}")
                return
            old = fs.status
            fs.status = args.status
            db.session.commit()
            print(f"✓ 伏笔 [{fs.id}] {fs.title}: {old} → {args.status}")

        elif args.action == "delete":
            fs = db.session.get(Foreshadowing, args.id)
            if not fs:
                print(f"✗ 伏笔 {args.id} 不存在")
                return
            if not args.yes:
                confirm = input(f"确定删除伏笔 [{fs.id}] {fs.title}？(y/N) ").strip().lower()
                if confirm != "y":
                    print("已取消")
                    return
            db.session.delete(fs)
            db.session.commit()
            print(f"✓ 已删除伏笔 [{fs.id}] {fs.title}")


# ---------------------------------------------------------------------------
# 大纲管理
# ---------------------------------------------------------------------------

def cmd_outline(args):
    with app.app_context():
        if args.action == "list":
            nodes = OutlineNode.query.filter_by(novel_id=args.novel).order_by(
                OutlineNode.parent_id.nullsfirst(), OutlineNode.sort_order).all()
            if not nodes:
                print(f"小说 {args.novel} 暂无大纲")
                return
            for n in nodes:
                indent = "  " * (1 if n.parent_id else 0)
                type_emoji = {"volume": "📚", "chapter": "📖", "scene": "🎬"}.get(n.node_type, "•")
                print(f"  {indent}{type_emoji} [{n.id}] [{n.node_type}] {n.title}: {truncate(n.summary or '', 50)}")

        elif args.action == "create":
            node = OutlineNode(
                novel_id=args.novel,
                title=args.title,
                summary=getattr(args, 'summary', '') or '',
                node_type=getattr(args, 'type', 'chapter') or 'chapter',
                parent_id=getattr(args, 'parent', None) or None,
            )
            db.session.add(node)
            db.session.commit()
            print(f"✓ 已创建大纲节点: [{node.id}] {node.title}")


# ---------------------------------------------------------------------------
# 角色关系管理
# ---------------------------------------------------------------------------

def cmd_relation(args):
    with app.app_context():
        if args.action == "list":
            rels = CharacterRelation.query.filter_by(novel_id=args.novel).all()
            if not rels:
                print(f"小说 {args.novel} 暂无角色关系")
                return
            rows = []
            for r in rels:
                a = Character.query.get(r.character_a_id)
                b = Character.query.get(r.character_b_id)
                rows.append([f"[{r.id}]", a.name if a else "?",
                            r.relation_type or "ordinary",
                            b.name if b else "?", f"综合分:{r.overall_score:.1f}"])
            print_table(["ID", "角色A", "关系", "角色B", "评分"], rows)

        elif args.action == "create":
            rel = CharacterRelation(
                novel_id=args.novel,
                character_a_id=args.char_a,
                character_b_id=args.char_b,
                relation_type=getattr(args, 'type', 'ordinary') or 'ordinary',
                description=getattr(args, 'desc', '') or '',
            )
            db.session.add(rel)
            db.session.commit()
            print(f"✓ 已创建关系: [{rel.id}]")

        elif args.action == "delete":
            rel = db.session.get(CharacterRelation, args.id)
            if not rel:
                print(f"✗ 关系 {args.id} 不存在")
                return
            if not args.yes:
                confirm = input(f"确定删除关系 [{rel.id}]？(y/N) ").strip().lower()
                if confirm != "y":
                    print("已取消")
                    return
            db.session.delete(rel)
            db.session.commit()
            print(f"✓ 已删除关系 [{rel.id}]")


# ---------------------------------------------------------------------------
# 短篇管理
# ---------------------------------------------------------------------------

def cmd_short(args):
    with app.app_context():
        if args.action == "list":
            stories = ShortStory.query.order_by(ShortStory.created_at.desc()).all()
            if not stories:
                print("暂无短篇")
                return
            rows = []
            for s in stories:
                rows.append([f"[{s.id}]", s.title, s.mode, s.status,
                            f"{len(s.content or '')}字", s.created_at])
            print_table(["ID", "标题", "模式", "状态", "字数", "创建时间"], rows)

        elif args.action == "create":
            story = ShortStory(
                title=args.title,
                mode=getattr(args, 'mode', 'inspiration') or 'inspiration',
                inspiration=getattr(args, 'inspiration', '') or '',
                genre=getattr(args, 'genre', '') or '',
                theme=getattr(args, 'theme', '') or '',
                character_desc=getattr(args, 'character', '') or '',
                scene_desc=getattr(args, 'scene', '') or '',
                tone=getattr(args, 'tone', '') or '',
                word_target=getattr(args, 'word_target', 2000) or 2000,
            )
            db.session.add(story)
            db.session.commit()
            print(f"✓ 已创建短篇: [{story.id}] {story.title} (模式:{story.mode})")

        elif args.action == "content":
            story = db.session.get(ShortStory, args.id)
            if not story:
                print(f"✗ 短篇 {args.id} 不存在")
                return
            print(f"【{story.title}】({story.mode}, {story.status}, {len(story.content or '')}字)")
            print("-" * 60)
            if args.full:
                print(story.content or "(暂无内容)")
            else:
                content = story.content or "(暂无内容)"
                print(content[:args.length or 800])
                if len(content) > (args.length or 800):
                    print(f"\n... (共{len(content)}字, 使用 --full 查看完整内容)")

        elif args.action == "delete":
            story = db.session.get(ShortStory, args.id)
            if not story:
                print(f"✗ 短篇 {args.id} 不存在")
                return
            if not args.yes:
                confirm = input(f"确定删除短篇「{story.title}」及其所有版本？(y/N) ").strip().lower()
                if confirm != "y":
                    print("已取消")
                    return
            ShortStoryVersion.query.filter_by(short_story_id=args.id).delete()
            ShortStoryReview.query.filter_by(short_story_id=args.id).delete()
            db.session.delete(story)
            db.session.commit()
            print(f"✓ 已删除短篇 [{args.id}] {story.title}")


# ---------------------------------------------------------------------------
# 提示词模板管理
# ---------------------------------------------------------------------------

def cmd_template(args):
    with app.app_context():
        if args.action == "list":
            templates = PromptTemplate.query.order_by(
                PromptTemplate.template_type, PromptTemplate.name).all()
            if not templates:
                print("暂无自定义模板（使用系统默认）")
                return
            rows = []
            for t in templates:
                rows.append([f"[{t.id}]", t.template_type, t.name,
                            "✓" if t.constraints else "✗"])
            print_table(["ID", "类型", "名称", "约束"], rows)

        elif args.action == "create":
            t = PromptTemplate(
                name=args.name,
                template_type=args.type or "writer",
                template_content=getattr(args, 'content', '') or '',
                constraints=getattr(args, 'constraints', '') or '',
            )
            db.session.add(t)
            db.session.commit()
            print(f"✓ 已创建模板: [{t.id}] {t.name}")

        elif args.action == "delete":
            t = db.session.get(PromptTemplate, args.id)
            if not t:
                print(f"✗ 模板 {args.id} 不存在")
                return
            name = t.name
            db.session.delete(t)
            db.session.commit()
            print(f"✓ 已删除模板: {name}")


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------

def cmd_audit(args):
    with app.app_context():
        if args.action == "run":
            from app.services.deai_agent import deai_process, get_deai_stats
            ch = Chapter.query.filter_by(novel_id=args.novel, chapter_number=args.number).first()
            if not ch:
                print(f"✗ 第{args.number}章不存在")
                return
            ver = ChapterVersion.query.filter_by(chapter_id=ch.id).order_by(
                ChapterVersion.version_number.desc()).first()
            if not ver:
                print(f"第{args.number}章暂无内容")
                return
            original = ver.content
            processed = deai_process(original)
            stats = get_deai_stats(original, processed)

            print(f"【第{args.number}章 AI 痕迹审计】")
            print(f"  字数: {stats['original_length']}")
            print(f"  检测到 AI 模式: {stats['patterns_found']} 处")
            print(f"  字数变化: {stats['reduction_pct']}%")
            print(f"  禁用词库: {stats.get('banned_words_count', 0)} 个")
            print(f"  正则模式: {stats.get('regex_patterns_count', 0)} 个")
            print(f"  口语化规则: {stats.get('colloquial_rules_count', 0)} 个")
            print()
            if args.detailed and stats['patterns_found'] > 0:
                print("  详细问题:")
                # 简单列出前10个匹配
                from app.services.deai_agent import BANNED_REPLACEMENTS
                count = 0
                for pattern, _ in BANNED_REPLACEMENTS:
                    matches = original.count(pattern)
                    if matches > 0:
                        print(f"    - 「{pattern}」: {matches} 处")
                        count += 1
                        if count >= 10:
                            print(f"    ... (更多省略)")
                            break


# ---------------------------------------------------------------------------
# 设置管理
# ---------------------------------------------------------------------------

def cmd_setting(args):
    with app.app_context():
        if args.action == "list":
            cfg = get_model_config()
            print("【全局配置】")
            for k, v in cfg.items():
                if "key" in k.lower():
                    v_display = str(v)[:10] + "..." if len(str(v)) > 10 else v
                    print(f"  {k}: {v_display}")
                else:
                    print(f"  {k}: {v}")
            print()
            print("【Agent 类型配置】")
            for agent_type, meta in AGENT_TYPES.items():
                agent_cfg = get_model_config(agent_type=agent_type)
                is_custom = any(
                    Setting.query.get(f"{p}_{agent_type}") is not None
                    for p in ["model_name", "temperature", "max_tokens"]
                )
                marker = "●" if is_custom else "○"
                print(f"  {marker} {agent_type:20s} ({meta['name']}): model={agent_cfg['model_name']}")

        elif args.action == "get":
            cfg = get_model_config(agent_type=args.agent_type)
            if args.key:
                print(cfg.get(args.key, "(未设置)"))
            else:
                for k, v in cfg.items():
                    print(f"{k}: {v}")

        elif args.action == "set":
            s = db.session.get(Setting, args.key)
            if s:
                s.value = args.value
            else:
                s = Setting(key=args.key, value=args.value)
                db.session.add(s)
            db.session.commit()
            print(f"✓ 已设置: {args.key}")

        elif args.action == "apply-recommended":
            from app.routes.settings import RECOMMENDED_DEFAULTS, _save_setting
            count = 0
            for agent_type, defaults in RECOMMENDED_DEFAULTS.items():
                for param, val in defaults.items():
                    key = f"{param}_{agent_type}"
                    _save_setting(key, val)
                    count += 1
            db.session.commit()
            print(f"✓ 已应用 {count} 条推荐配置")

        elif args.action == "clear-agent":
            from app.routes.settings import _save_setting
            count = 0
            for agent_type in AGENT_TYPES:
                for param in ["model_name", "llm_model", "temperature", "max_tokens"]:
                    key = f"{param}_{agent_type}"
                    existing = db.session.get(Setting, key)
                    if existing:
                        db.session.delete(existing)
                        count += 1
            db.session.commit()
            print(f"✓ 已清除 {count} 条 Agent 自定义配置（含 llm_model_*）")


# ---------------------------------------------------------------------------
# LLM 厂商与模型配置（对齐 Web 的 /settings/llm）
# ---------------------------------------------------------------------------
def _mask_key(k):
    if not k:
        return ""
    if len(k) > 8:
        return k[:8] + "****"
    return k[:3] + "****"


def cmd_llm(args):
    with app.app_context():
        from app.models.llm_provider import LLMProvider, LLMModel
        from app.services.llm import fetch_models_from_provider, test_provider_connection
        from app.config_utils import get_effective_config, get_available_models_for_agent
        from app.routes.settings import AGENT_TYPES, _save_setting

        action = args.action

        # ===== 厂商管理 =====
        if action == "provider-list":
            providers = LLMProvider.query.order_by(LLMProvider.id).all()
            if not providers:
                print("（尚未添加任何厂商，用 `llm provider-add` 添加）")
                return
            print(f"【LLM 厂商】（{len(providers)}）")
            for p in providers:
                en = "启用" if p.enabled else "禁用"
                mc = LLMModel.query.filter_by(provider_id=p.id).count()
                ec = LLMModel.query.filter_by(provider_id=p.id, enabled=True).count()
                print(f"  #{p.id} [{en}] {p.name} ({p.provider_type})")
                print(f"      base_url: {p.base_url}")
                print(f"      api_key:  {_mask_key(p.api_key)}")
                print(f"      模型: {ec}/{mc} 个已勾选")

        elif action == "provider-add":
            name = (args.name or "").strip()
            base_url = (args.base_url or "").strip()
            if not name or not base_url:
                print("✗ 需要 --name 和 --base-url")
                return
            p = LLMProvider(
                name=name,
                provider_type=args.provider_type or "custom",
                base_url=base_url,
                api_key=args.api_key or "",
            )
            db.session.add(p)
            db.session.commit()
            print(f"✓ 已添加厂商 #{p.id}: {name} ({p.provider_type})")
            print(f"  用 `llm fetch-models --provider {p.id}` 拉取模型列表")

        elif action == "provider-update":
            p = db.session.get(LLMProvider, args.provider)
            if not p:
                print(f"✗ 厂商不存在: #{args.provider}")
                return
            if args.name:
                p.name = args.name
            if args.base_url:
                p.base_url = args.base_url
            if args.api_key is not None:
                p.api_key = args.api_key
            if args.provider_type:
                p.provider_type = args.provider_type
            if args.enabled is not None:
                p.enabled = args.enabled.lower() in ("true", "1", "on", "yes")
            db.session.commit()
            print(f"✓ 已更新厂商 #{p.id}: {p.name}")

        elif action == "provider-delete":
            p = db.session.get(LLMProvider, args.provider)
            if not p:
                print(f"✗ 厂商不存在: #{args.provider}")
                return
            mc = LLMModel.query.filter_by(provider_id=p.id).count()
            db.session.delete(p)  # cascade 删除模型
            db.session.commit()
            print(f"✓ 已删除厂商 #{p.id}: {p.name}（连带 {mc} 个模型）")

        elif action == "fetch-models":
            p = db.session.get(LLMProvider, args.provider)
            if not p:
                print(f"✗ 厂商不存在: #{args.provider}")
                return
            print(f"正在从 {p.name} 拉取模型列表...")
            try:
                models = fetch_models_from_provider(p.base_url, p.api_key, p.provider_type)
            except Exception as e:
                print(f"✗ 拉取失败: {str(e)[:300]}")
                return
            existing = {m.model_id: m for m in LLMModel.query.filter_by(provider_id=p.id).all()}
            added = 0
            for m in models:
                mid = m["id"]
                if mid not in existing:
                    db.session.add(LLMModel(provider_id=p.id, model_id=mid, display_name=mid, enabled=False))
                    added += 1
            db.session.commit()
            total = LLMModel.query.filter_by(provider_id=p.id).count()
            print(f"✓ 新增 {added} 个模型，当前共 {total} 个（均未勾选）")
            print(f"  用 `llm model-list --provider {p.id}` 查看，`llm model-toggle --model <mid>` 勾选")

        elif action == "model-list":
            q = LLMModel.query
            if args.provider:
                q = q.filter_by(provider_id=args.provider)
            models = q.all()
            if not models:
                print("（无模型，先 `llm fetch-models --provider <pid>` 拉取）")
                return
            print(f"【模型列表】（{len(models)}）")
            for m in models:
                p = db.session.get(LLMProvider, m.provider_id)
                pname = p.name if p else "?"
                en = "●" if m.enabled else "○"
                print(f"  {en} #{m.id} [{pname}] {m.model_id}" + (f" ({m.display_name})" if m.display_name and m.display_name != m.model_id else ""))

        elif action == "model-toggle":
            m = db.session.get(LLMModel, args.model)
            if not m:
                print(f"✗ 模型不存在: #{args.model}")
                return
            if args.enabled is not None:
                m.enabled = args.enabled.lower() in ("true", "1", "on", "yes")
            else:
                m.enabled = not m.enabled
            db.session.commit()
            p = db.session.get(LLMProvider, m.provider_id)
            state = "已勾选" if m.enabled else "已取消"
            print(f"✓ {state}: [{p.name}] {m.model_id}（#{m.id}）")

        elif action == "model-toggle-all":
            if not args.provider:
                print("✗ 需要 --provider")
                return
            enabled = args.enabled.lower() in ("true", "1", "on", "yes") if args.enabled else True
            LLMModel.query.filter_by(provider_id=args.provider).update({"enabled": enabled})
            db.session.commit()
            print(f"✓ 已{'全选' if enabled else '全不选'}厂商 #{args.provider} 下所有模型")

        elif action == "test":
            p = db.session.get(LLMProvider, args.provider)
            if not p:
                print(f"✗ 厂商不存在: #{args.provider}")
                return
            print(f"测试 {p.name} ({p.base_url}) 连接...")
            result = test_provider_connection(p.base_url, p.api_key, p.provider_type)
            if result.get("ok"):
                print(f"✓ 连接成功" + (f" · {result.get('detail','')}" if result.get('detail') else ""))
            else:
                print(f"✗ 连接失败: {result.get('error', '未知错误')}")

        # ===== Per-Agent 模型配置 =====
        elif action == "agent-list":
            print("【Per-Agent 模型配置】（16 个 Agent）")
            print(f"{'Agent':<20} {'名称':<12} {'组':<6} {'生效模型':<28} {'来源'}")
            print("-" * 90)
            for agent_type, meta in AGENT_TYPES.items():
                cfg = get_effective_config(agent_type=agent_type)
                model = cfg.get("model_name", "?")
                # 判断来源：显式 llm_model_{agent} > 自动默认 > 全局
                llm_key = db.session.get(Setting, f"llm_model_{agent_type}")
                has_explicit = bool(llm_key and llm_key.value and llm_key.value.strip())
                if has_explicit:
                    src = f"显式({llm_key.value})"
                elif get_available_models_for_agent():
                    src = "自动默认"
                else:
                    src = "全局/.env"
                print(f"  {agent_type:<18} {meta['name']:<12} {meta['group']:<6} {model:<28} {src}")

        elif action == "agent-set":
            agent_type = args.agent_type
            if agent_type not in AGENT_TYPES:
                print(f"✗ 未知 Agent: {agent_type}")
                print("  可用: " + ", ".join(AGENT_TYPES.keys()))
                return
            llm_val = (args.llm_model or "").strip()  # 格式 provider_id:model_id
            if llm_val:
                # 校验格式与厂商存在性；模型名不限制（langchain 直接透传给 API）
                try:
                    pid_s, model_id = llm_val.split(":", 1)
                    pid = int(pid_s)
                except ValueError:
                    print(f"✗ 格式错误，应为 provider_id:model_id（如 1:deepseek-v4-flash）")
                    return
                p = db.session.get(LLMProvider, pid)
                if not p:
                    print(f"✗ 厂商不存在: #{pid}")
                    print("  先 `llm provider-add` 添加厂商（模型需通过厂商拿到 api_key/base_url）")
                    return
                if not p.enabled:
                    print(f"⚠ 厂商 {p.name} 当前已禁用，配置保存但不会生效（`llm provider-update --provider {pid} --enabled true` 启用）")
                if not p.api_key:
                    print(f"⚠ 厂商 {p.name} 未配置 api_key")
                m = LLMModel.query.filter_by(provider_id=pid, model_id=model_id).first()
                if not m:
                    print(f"ℹ {model_id} 不在厂商模型列表中（自定义/未拉取模型），按原样保存直接透传给 API")
                    print(f"  若需拉取列表: `llm fetch-models --provider {pid}`")
                elif not m.enabled:
                    print(f"ℹ 模型 {model_id} 未勾选（勾选仅影响自动默认池，不影响此显式指定）")
                _save_setting(f"llm_model_{agent_type}", llm_val)
                _save_setting(f"model_name_{agent_type}", model_id)  # 兼容旧逻辑
                db.session.commit()
                print(f"✓ 已为 {agent_type} 指定模型: {llm_val}")
            else:
                print(f"✗ 需要 --llm-model provider_id:model_id")
                avail = get_available_models_for_agent()
                if avail:
                    print("  可用模型:")
                    for grp in avail:
                        print(f"    [{grp['provider_name']}] " + ", ".join(f"{m['key']}" for m in grp['models']))

        elif action == "agent-clear":
            agent_type = args.agent_type
            if agent_type not in AGENT_TYPES:
                print(f"✗ 未知 Agent: {agent_type}")
                return
            cleared = 0
            for key in [f"llm_model_{agent_type}", f"model_name_{agent_type}",
                        f"temperature_{agent_type}", f"max_tokens_{agent_type}"]:
                existing = db.session.get(Setting, key)
                if existing:
                    db.session.delete(existing)
                    cleared += 1
            db.session.commit()
            print(f"✓ 已清除 {agent_type} 的 {cleared} 条自定义配置（回退到自动默认/全局）")

        elif action == "agent-param":
            agent_type = args.agent_type
            if agent_type not in AGENT_TYPES:
                print(f"✗ 未知 Agent: {agent_type}")
                return
            if args.temperature is None and args.max_tokens is None:
                # 显示当前参数
                cfg = get_effective_config(agent_type=agent_type)
                print(f"【{agent_type}】temperature={cfg.get('temperature')} max_tokens={cfg.get('max_tokens')}")
                return
            if args.temperature is not None:
                try:
                    float(args.temperature)
                except ValueError:
                    print("✗ --temperature 需为数字")
                    return
                _save_setting(f"temperature_{agent_type}", args.temperature)
                print(f"✓ {agent_type}.temperature = {args.temperature}")
            if args.max_tokens is not None:
                try:
                    int(args.max_tokens)
                except ValueError:
                    print("✗ --max-tokens 需为整数")
                    return
                _save_setting(f"max_tokens_{agent_type}", args.max_tokens)
                print(f"✓ {agent_type}.max_tokens = {args.max_tokens}")
            db.session.commit()

        elif action == "effective":
            # 查看某 Agent 实际生效的完整配置（含解析后的 api_key/base_url/model）
            agent_type = args.agent_type
            cfg = get_effective_config(agent_type=agent_type)
            print(f"【{agent_type or '全局'} 实际生效配置】")
            for k in ["model_name", "provider_type", "base_url", "temperature", "max_tokens"]:
                print(f"  {k}: {cfg.get(k)}")
            print(f"  api_key: {_mask_key(cfg.get('api_key',''))}")
            if args.novel:
                novel = db.session.get(Novel, args.novel)
                if novel:
                    cfg2 = get_effective_config(novel=novel, agent_type=agent_type)
                    print(f"\n【叠加小说 #{novel.id} model_override 后】")
                    for k in ["model_name", "base_url", "temperature", "max_tokens"]:
                        if cfg2.get(k) != cfg.get(k):
                            print(f"  {k}: {cfg2.get(k)}  (被覆盖)")


# ---------------------------------------------------------------------------
# 写作技巧（Skill）
# ---------------------------------------------------------------------------
def cmd_skill(args):
    with app.app_context():
        from app.services.skill_system import (
            get_all_skills, get_active_skills, set_active_skills,
            build_skill_prompt, _load_protocol_pack,
            save_custom_skill, delete_custom_skill, get_custom_skills,
        )
        all_skills = get_all_skills()
        active = get_active_skills()

        if args.action == "list":
            # 按分类分组：作者文风协议 / 通用技法 / 自定义
            groups = {}
            for key, skill in all_skills.items():
                cat = skill.get("category", "通用技法")
                groups.setdefault(cat, []).append((key, skill))
            cat_order = ["作者文风协议", "通用技法", "自定义"]
            cats = sorted(groups.keys(), key=lambda c: cat_order.index(c) if c in cat_order else 99)
            for cat in cats:
                items = groups[cat]
                print(f"\n【{'🖋 ' if cat == '作者文风协议' else ''}{cat}】（{len(items)}）")
                for key, skill in items:
                    mark = "●" if key in active else "○"
                    author = f"  {skill.get('author','')}" if skill.get("author") else ""
                    pack = "  [完整协议]" if skill.get("protocol_pack") else ""
                    tag = f"  <{skill.get('tag')}>" if skill.get("tag") else ""
                    builtin = "" if skill.get("builtin", True) else "  (自定义)"
                    print(f"  {mark} {key:28s} {skill.get('name', key)}{author}{pack}{tag}{builtin}")
                    if args.verbose and skill.get("description"):
                        print(f"      {skill['description']}")
            print(f"\n共 {len(all_skills)} 个技巧，已激活 {len(active)} 个")
            if active:
                print(f"已激活: {', '.join(active)}")

        elif args.action == "active":
            print(f"已激活技巧（{len(active)} 个）:")
            for key in active:
                skill = all_skills.get(key, {})
                print(f"  ● {key:28s} {skill.get('name', key)}")

        elif args.action == "toggle":
            key = args.skill
            if key not in all_skills:
                print(f"✗ 技巧不存在: {key}")
                print("  可用技巧: " + ", ".join(all_skills.keys()))
                return
            new_active = [k for k in active if k != key]
            toggled_on = False
            if key not in active:
                new_active.append(key)
                toggled_on = True
            set_active_skills(new_active)
            name = all_skills[key].get("name", key)
            print(f"✓ {'已激活' if toggled_on else '已关闭'}: {name}（{key}）")
            print(f"  当前激活 {len(new_active)} 个: {', '.join(new_active) if new_active else '(无)'}")

        elif args.action == "enable":
            key = args.skill
            if key not in all_skills:
                print(f"✗ 技巧不存在: {key}")
                return
            if key not in active:
                new_active = active + [key]
                set_active_skills(new_active)
                print(f"✓ 已激活: {all_skills[key].get('name', key)}（{key}）")
            else:
                print(f"  已是激活状态: {key}")

        elif args.action == "disable":
            key = args.skill
            if key in active:
                new_active = [k for k in active if k != key]
                set_active_skills(new_active)
                print(f"✓ 已关闭: {all_skills.get(key, {}).get('name', key)}（{key}）")
            else:
                print(f"  已是关闭状态: {key}")

        elif args.action == "info":
            key = args.skill
            skill = all_skills.get(key)
            if not skill:
                print(f"✗ 技巧不存在: {key}")
                return
            print(f"技巧: {skill.get('name', key)}")
            print(f"key:  {key}")
            print(f"分类: {skill.get('category', '通用技法')}")
            if skill.get("author"):
                print(f"作者: {skill['author']}")
            if skill.get("source"):
                print(f"来源: {skill['source']}")
            if skill.get("tag"):
                print(f"标签: {skill['tag']}")
            if skill.get("protocol_pack"):
                print(f"协议包: {skill['protocol_pack']}（动态加载完整协议）")
            print(f"内置: {'是' if skill.get('builtin', True) else '否'}")
            print(f"激活: {'是' if key in active else '否'}")
            print(f"\n描述: {skill.get('description', '(无)')}")
            print(f"\n约束: {skill.get('constraints', '(无)')}")
            print(f"\n提示词:")
            print("-" * 40)
            print(skill.get("prompt", "(无)"))
            print("-" * 40)
            # 若是协议包技巧，展示实际加载的完整协议
            pack = skill.get("protocol_pack")
            if pack:
                task_type = args.task_type or "write"
                full = _load_protocol_pack(pack, task_type=task_type)
                if full:
                    print(f"\n[动态加载的完整协议 · task_type={task_type}]")
                    print(f"长度: {len(full)} 字符（{len(full)/1024:.1f}KB）")
                    if args.verbose:
                        print("-" * 40)
                        print(full)
                        print("-" * 40)
                else:
                    print(f"\n[协议包 {pack} 文件缺失，将回退静态浓缩 prompt]")

        elif args.action == "preview":
            # 预览当前激活技巧实际注入 Writer 的完整提示词
            task_type = args.task_type or "write"
            prompt = build_skill_prompt(task_type=task_type)
            if not prompt:
                print("（未激活任何技巧，build_skill_prompt 返回空）")
                return
            print(f"【build_skill_prompt 预览 · task_type={task_type}】")
            print(f"长度: {len(prompt)} 字符（{len(prompt)/1024:.1f}KB）")
            print(f"激活技巧: {', '.join(active)}")
            print("=" * 60)
            print(prompt)
            print("=" * 60)

        elif args.action == "create":
            name = (args.name or "").strip()
            if not name:
                print("✗ 需要 --name")
                return
            prompt = (args.prompt or "").strip()
            if not prompt:
                print("✗ 需要 --prompt")
                return
            skill_data = {
                "name": name,
                "description": args.description or "",
                "prompt": prompt,
                "constraints": args.constraints or "",
            }
            save_custom_skill(name, skill_data)
            print(f"✓ 已创建自定义技巧: {name}")
            print("  用 `python cli.py skill enable --skill <name>` 激活")

        elif args.action == "delete":
            name = (args.name or "").strip()
            if not name:
                print("✗ 需要 --name")
                return
            custom = get_custom_skills()
            # name 可能是显示名或 key；自定义技巧 key=显示名
            if name in custom:
                delete_custom_skill(name)
                # 若该技巧在激活列表则一并移除
                if name in active:
                    set_active_skills([k for k in active if k != name])
                print(f"✓ 已删除自定义技巧: {name}")
            else:
                print(f"✗ 自定义技巧不存在: {name}")
                print("  现有自定义技巧: " + (", ".join(custom.keys()) if custom else "(无)"))


# ---------------------------------------------------------------------------
# 全书优化
# ---------------------------------------------------------------------------

def cmd_optimize(args):
    with app.app_context():
        if args.action == "diagnose":
            from app.services.book_optimizer import diagnose_book
            from app.routes.settings import get_effective_config
            novel = db.session.get(Novel, args.novel)
            if not novel:
                print(f"✗ 小说 {args.novel} 不存在")
                return
            cfg = get_effective_config(novel, agent_type="optimizer")
            print(f"正在诊断小说「{novel.title}」...")
            report = diagnose_book(args.novel, cfg)
            if "error" in report:
                print(f"✗ {report['error']}")
                return
            print()
            print(f"【诊断报告】")
            print(f"  总章节: {report['total_chapters']}")
            print(f"  总问题: {report['total_issues']}")
            print(f"  高严重度: {report['high_issues']}")
            print(f"  平均分: {report['average_score']}")
            print(f"  需要修复: {report['chapters_needing_fix']}")
            print()
            for ch in report['chapters']:
                if ch.get('issues'):
                    print(f"  第{ch['chapter_number']}章 [{ch.get('grade', '?')}] {len(ch['issues'])} 个问题:")
                    for issue in ch['issues'][:3]:
                        print(f"    - [{issue['severity']}] {issue['dimension']}: {truncate(issue['issue'], 50)}")


# ---------------------------------------------------------------------------
# 系统管理
# ---------------------------------------------------------------------------

def cmd_sys(args):
    with app.app_context():
        if args.action == "info":
            print("【系统信息】")
            print(f"  小说总数: {Novel.query.count()}")
            print(f"  章节总数: {Chapter.query.count()}")
            print(f"  角色总数: {Character.query.count()}")
            print(f"  世界观条目: {WorldSetting.query.count()}")
            print(f"  伏笔总数: {Foreshadowing.query.count()}")
            print(f"  短篇总数: {ShortStory.query.count()}")
            print(f"  提示模板: {PromptTemplate.query.count()}")

            import os
            db_path = "data.db"
            if os.path.exists(db_path):
                size_mb = os.path.getsize(db_path) / (1024 * 1024)
                print(f"  数据库大小: {size_mb:.2f} MB")
            print()

            # 模型配置
            cfg = get_model_config()
            print(f"  当前模型: {cfg['model_name']}")
            print(f"  API 地址: {cfg['base_url']}")

        elif args.action == "backup":
            import shutil
            if not args.output:
                args.output = f"data_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            try:
                shutil.copy2("data.db", args.output)
                print(f"✓ 已备份到: {args.output}")
            except Exception as e:
                print(f"✗ 备份失败: {e}")

        elif args.action == "reset":
            print("⚠️  危险操作: 这将删除所有数据!")
            if not args.yes and not confirm("确定要重置数据库吗?"):
                print("已取消")
                return
            print("重置功能尚未实现 (出于安全考虑)")
            print("如需重置，请手动删除 data.db 文件后重启")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 认证命令
# ---------------------------------------------------------------------------

def cmd_auth(args):
    """认证管理。"""
    if args.action == "login":
        username = args.username
        password = args.password
        user = DEFAULT_USERS.get(username)
        if not user:
            print(f"✗ 用户 '{username}' 不存在")
            return
        if user["password"] != password:
            print("✗ 密码错误")
            return
        save_cli_auth(username)
        print(f"✓ 已登录: {user['name']} ({username})")
    elif args.action == "logout":
        clear_cli_auth()
        print("✓ 已注销")
    elif args.action == "status":
        auth = load_cli_auth()
        if auth:
            print(f"✓ 已登录: {auth.get('username')}")
            print(f"  登录时间: {auth.get('logged_in_at')}")
        else:
            print("✗ 未登录")
    elif args.action == "list":
        print("可用用户:")
        for username, info in DEFAULT_USERS.items():
            print(f"  - {username} ({info['name']}, {info['role']})")


def cmd_whoami(args):
    """显示当前登录用户。"""
    user = check_cli_auth()
    print(f"用户: {user['name']} ({user['username']})")
    print(f"角色: {user['role']}")


def main():
    parser = argparse.ArgumentParser(
        description="灵砚 CLI — AI小说创作系统命令行工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python cli.py novel list
  python cli.py novel create --title "我的小说"
  python cli.py chapter generate --novel 1 --number 1
  python cli.py character list --novel 1
  python cli.py short list
  python cli.py setting list
  python cli.py sys info
""")
    subparsers = parser.add_subparsers(dest="command")

    # ========== 认证 ==========
    p_auth = subparsers.add_parser("auth", help="用户认证")
    p_auth.add_argument("action", choices=["login", "logout", "status", "list"])
    p_auth.add_argument("--username", help="用户名")
    p_auth.add_argument("--password", help="密码")

    # ========== whoami ==========
    subparsers.add_parser("whoami", help="显示当前登录用户")

    # 全局参数
    for sub in subparsers._parser_groups if hasattr(subparsers, '_parser_groups') else []:
        pass

    # ========== 小说 ==========
    p_novel = subparsers.add_parser("novel", help="小说管理")
    p_novel.add_argument("action", choices=["list", "create", "delete", "info", "update"])
    p_novel.add_argument("--id", type=int, help="小说 ID")
    p_novel.add_argument("--title", help="小说标题")
    p_novel.add_argument("--genre", help="小说类型")
    p_novel.add_argument("--synopsis", help="小说简介")
    p_novel.add_argument("--world-intro", dest="world_intro", help="世界观介绍")
    p_novel.add_argument("-y", "--yes", action="store_true", help="跳过确认")

    # ========== 章节 ==========
    p_chapter = subparsers.add_parser("chapter", help="章节管理")
    p_chapter.add_argument("action", choices=["list", "create", "content", "approve", "update", "delete"])
    p_chapter.add_argument("--novel", type=int, required=True, help="小说 ID")
    p_chapter.add_argument("--number", type=int, help="章节号")
    p_chapter.add_argument("--title", help="章节标题")
    p_chapter.add_argument("--outline", help="章节大纲")
    p_chapter.add_argument("--directive", help="用户指示")
    p_chapter.add_argument("--full", action="store_true", help="显示完整内容")
    p_chapter.add_argument("--length", type=int, help="预览长度")
    p_chapter.add_argument("-y", "--yes", action="store_true", help="跳过删除确认")

    # ========== 角色 ==========
    p_char = subparsers.add_parser("character", help="角色管理")
    p_char.add_argument("action", choices=["list", "create", "info", "update", "delete"])
    p_char.add_argument("--novel", type=int, help="小说 ID")
    p_char.add_argument("--id", type=int, help="角色 ID")
    p_char.add_argument("--name", help="角色名")
    p_char.add_argument("--personality", help="性格")
    p_char.add_argument("--speaking-style", dest="speaking_style", help="说话风格")
    p_char.add_argument("--appearance", help="外貌")
    p_char.add_argument("--background", help="背景")
    p_char.add_argument("--motivation", help="动机")
    p_char.add_argument("--arc", help="角色弧光")
    p_char.add_argument("-y", "--yes", action="store_true", help="跳过删除确认")

    # ========== 世界观 ==========
    p_world = subparsers.add_parser("world", help="世界观管理")
    p_world.add_argument("action", choices=["list", "create", "update", "delete"])
    p_world.add_argument("--novel", type=int, help="小说 ID（list/create 需要）")
    p_world.add_argument("--id", type=int, help="世界观 ID（update/delete 用）")
    p_world.add_argument("--category", help="类别")
    p_world.add_argument("--title", help="标题")
    p_world.add_argument("--content", help="内容")
    p_world.add_argument("-y", "--yes", action="store_true", help="跳过删除确认")

    # ========== 伏笔 ==========
    p_fs = subparsers.add_parser("foreshadow", help="伏笔管理")
    p_fs.add_argument("action", choices=["list", "create", "status", "delete"])
    p_fs.add_argument("--novel", type=int, help="小说 ID")
    p_fs.add_argument("--id", type=int, help="伏笔 ID")
    p_fs.add_argument("--title", help="伏笔标题")
    p_fs.add_argument("--description", help="伏笔描述")
    p_fs.add_argument("--importance", type=int, default=5, help="重要度 (1-10)")
    p_fs.add_argument("--planted", type=int, help="埋设章节")
    p_fs.add_argument("--status", help="新状态")
    p_fs.add_argument("-y", "--yes", action="store_true", help="跳过删除确认")

    # ========== 大纲 ==========
    p_outline = subparsers.add_parser("outline", help="大纲管理")
    p_outline.add_argument("action", choices=["list", "create"])
    p_outline.add_argument("--novel", type=int, required=True)
    p_outline.add_argument("--title", help="节点标题")
    p_outline.add_argument("--summary", help="节点摘要")
    p_outline.add_argument("--type", choices=["volume", "chapter", "scene"], default="chapter", help="节点类型")
    p_outline.add_argument("--parent", type=int, help="父节点 ID")

    # ========== 关系 ==========
    p_rel = subparsers.add_parser("relation", help="角色关系管理")
    p_rel.add_argument("action", choices=["list", "create", "delete"])
    p_rel.add_argument("--novel", type=int, required=True)
    p_rel.add_argument("--id", type=int, help="关系 ID（delete 用）")
    p_rel.add_argument("--char-a", type=int, help="角色 A 的 ID")
    p_rel.add_argument("--char-b", type=int, help="角色 B 的 ID")
    p_rel.add_argument("--type", default="ordinary", help="关系类型")
    p_rel.add_argument("--desc", help="关系描述")
    p_rel.add_argument("-y", "--yes", action="store_true", help="跳过删除确认")

    # ========== 短篇 ==========
    p_short = subparsers.add_parser("short", help="短篇管理")
    p_short.add_argument("action", choices=["list", "create", "content", "delete"])
    p_short.add_argument("--id", type=int, help="短篇 ID")
    p_short.add_argument("--title", help="短篇标题")
    p_short.add_argument("--mode", choices=["inspiration", "setting", "careful"], help="创作模式")
    p_short.add_argument("--inspiration", help="灵感")
    p_short.add_argument("--genre", help="体裁")
    p_short.add_argument("--theme", help="主题")
    p_short.add_argument("--character", dest="character", help="角色描述")
    p_short.add_argument("--scene", help="场景描述")
    p_short.add_argument("--tone", help="情感基调")
    p_short.add_argument("--word-target", type=int, dest="word_target", help="目标字数")
    p_short.add_argument("--full", action="store_true", help="显示完整内容")
    p_short.add_argument("--length", type=int, help="预览长度")
    p_short.add_argument("-y", "--yes", action="store_true", help="跳过删除确认")

    # ========== 模板 ==========
    p_tmpl = subparsers.add_parser("template", help="提示词模板")
    p_tmpl.add_argument("action", choices=["list", "create", "delete"])
    p_tmpl.add_argument("--id", type=int, help="模板 ID")
    p_tmpl.add_argument("--name", help="模板名")
    p_tmpl.add_argument("--type", choices=["writer", "critic", "summary", "outline",
                        "rewrite", "character_check", "lore_check", "foreshadow_check", "editor"],
                        help="模板类型")
    p_tmpl.add_argument("--content", help="模板内容")
    p_tmpl.add_argument("--constraints", help="写作约束")

    # ========== 审计 ==========
    p_audit = subparsers.add_parser("audit", help="质量审计")
    p_audit.add_argument("action", choices=["run"], help="操作类型")
    p_audit.add_argument("--novel", type=int, required=True, help="小说 ID")
    p_audit.add_argument("--number", type=int, required=True, help="章节号")
    p_audit.add_argument("--detailed", action="store_true", help="详细模式")

    # ========== 设置 ==========
    p_set = subparsers.add_parser("setting", help="系统设置")
    p_set.add_argument("action", choices=["list", "get", "set", "apply-recommended", "clear-agent"])
    p_set.add_argument("--key", help="设置键")
    p_set.add_argument("--value", help="设置值")
    p_set.add_argument("--agent-type", dest="agent_type", help="Agent 类型")

    # ========== LLM 厂商与模型配置 ==========
    p_llm = subparsers.add_parser("llm", help="LLM 厂商/模型/Per-Agent 配置（对齐 Web /settings/llm）")
    p_llm.add_argument("action", choices=[
        "provider-list", "provider-add", "provider-update", "provider-delete",
        "fetch-models", "model-list", "model-toggle", "model-toggle-all", "test",
        "agent-list", "agent-set", "agent-clear", "agent-param", "effective",
    ], help="厂商: provider-list/add/update/delete · 模型: fetch-models/model-list/toggle/toggle-all/test · Agent: agent-list/set/clear/param/effective")
    p_llm.add_argument("--provider", type=int, help="厂商 ID")
    p_llm.add_argument("--model", type=int, help="模型 ID（数据库主键）")
    p_llm.add_argument("--name", help="厂商/模型名")
    p_llm.add_argument("--base-url", dest="base_url", help="厂商 API 地址")
    p_llm.add_argument("--api-key", dest="api_key", help="厂商 API Key")
    p_llm.add_argument("--provider-type", dest="provider_type", help="厂商类型 (deepseek/openai/ollama/custom)")
    p_llm.add_argument("--enabled", help="true/false（启用状态）")
    p_llm.add_argument("--agent-type", dest="agent_type", help="Agent 类型 (writer/critic/...)")
    p_llm.add_argument("--llm-model", dest="llm_model", help="厂商模型，格式 provider_id:model_id（agent-set 用）")
    p_llm.add_argument("--temperature", help="温度（agent-param 用）")
    p_llm.add_argument("--max-tokens", dest="max_tokens", help="最大 token（agent-param 用）")
    p_llm.add_argument("--novel", type=int, help="小说 ID（effective 叠加 per-novel 覆盖）")

    # ========== 写作技巧 ==========
    p_skill = subparsers.add_parser("skill", help="写作技巧管理（内置/作者文风协议/自定义）")
    p_skill.add_argument("action", choices=[
        "list", "active", "toggle", "enable", "disable", "info", "preview", "create", "delete"
    ], help="操作: list列出全部/active已激活/toggle切换/enable激活/disable关闭/info详情/preview预览注入/create自建/delete删除")
    p_skill.add_argument("--skill", help="技巧 key（toggle/enable/disable/info 用）")
    p_skill.add_argument("--name", help="自定义技巧名（create/delete 用）")
    p_skill.add_argument("--description", help="自定义技巧描述（create 用）")
    p_skill.add_argument("--prompt", help="自定义技巧提示词（create 用）")
    p_skill.add_argument("--constraints", help="自定义技巧约束（create 用）")
    p_skill.add_argument("--task-type", dest="task_type",
                         choices=["write", "diagnose", "polish", "full"],
                         help="协议包加载模式（info/preview 用，默认 write）")
    p_skill.add_argument("-v", "--verbose", action="store_true", help="显示描述/完整协议原文")

    # ========== 优化 ==========
    p_opt = subparsers.add_parser("optimize", help="全书优化")
    p_opt.add_argument("action", choices=["diagnose"], help="操作类型")
    p_opt.add_argument("--novel", type=int, required=True, help="小说 ID")

    # ========== 系统 ==========
    p_sys = subparsers.add_parser("sys", help="系统管理")
    p_sys.add_argument("action", choices=["info", "backup", "reset"], help="操作类型")
    p_sys.add_argument("--output", help="备份输出路径")
    p_sys.add_argument("-y", "--yes", action="store_true", help="跳过确认")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 需要登录的命令 (auth 命令本身除外)
    auth_only_commands = {"auth", "whoami"}
    if args.command not in auth_only_commands:
        user = check_cli_auth()
        # 可以在这里输出当前用户信息（可选）
        # print(f"当前用户: {user['name']} ({user['username']})")

    handlers = {
        "auth": cmd_auth,
        "novel": cmd_novel,
        "chapter": cmd_chapter,
        "character": cmd_character,
        "world": cmd_world,
        "foreshadow": cmd_foreshadow,
        "outline": cmd_outline,
        "relation": cmd_relation,
        "short": cmd_short,
        "template": cmd_template,
        "audit": cmd_audit,
        "setting": cmd_setting,
        "llm": cmd_llm,
        "skill": cmd_skill,
        "optimize": cmd_optimize,
        "sys": cmd_sys,
        "whoami": cmd_whoami,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()