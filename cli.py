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
    优化: optimize diagnose
    系统: sys info/backup/reset

用法示例:
    python cli.py novel list
    python cli.py novel create --title "我的小说"
    python cli.py chapter list --novel 1
    python cli.py character create --novel 1 --name "张三"
    python cli.py short create --title "深夜来客" --mode inspiration
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


# ---------------------------------------------------------------------------
# 世界观管理
# ---------------------------------------------------------------------------

def cmd_world(args):
    with app.app_context():
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
                for param in ["model_name", "temperature", "max_tokens"]:
                    key = f"{param}_{agent_type}"
                    existing = db.session.get(Setting, key)
                    if existing:
                        db.session.delete(existing)
                        count += 1
            db.session.commit()
            print(f"✓ 已清除 {count} 条 Agent 自定义配置")


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
    p_novel.add_argument("action", choices=["list", "create", "delete", "info"])
    p_novel.add_argument("--id", type=int, help="小说 ID")
    p_novel.add_argument("--title", help="小说标题")
    p_novel.add_argument("--genre", help="小说类型")
    p_novel.add_argument("--synopsis", help="小说简介")
    p_novel.add_argument("--world-intro", dest="world_intro", help="世界观介绍")
    p_novel.add_argument("-y", "--yes", action="store_true", help="跳过确认")

    # ========== 章节 ==========
    p_chapter = subparsers.add_parser("chapter", help="章节管理")
    p_chapter.add_argument("action", choices=["list", "create", "content", "approve"])
    p_chapter.add_argument("--novel", type=int, required=True, help="小说 ID")
    p_chapter.add_argument("--number", type=int, help="章节号")
    p_chapter.add_argument("--title", help="章节标题")
    p_chapter.add_argument("--outline", help="章节大纲")
    p_chapter.add_argument("--directive", help="用户指示")
    p_chapter.add_argument("--full", action="store_true", help="显示完整内容")
    p_chapter.add_argument("--length", type=int, help="预览长度")

    # ========== 角色 ==========
    p_char = subparsers.add_parser("character", help="角色管理")
    p_char.add_argument("action", choices=["list", "create", "info"])
    p_char.add_argument("--novel", type=int, help="小说 ID")
    p_char.add_argument("--id", type=int, help="角色 ID")
    p_char.add_argument("--name", help="角色名")
    p_char.add_argument("--personality", help="性格")
    p_char.add_argument("--speaking-style", dest="speaking_style", help="说话风格")
    p_char.add_argument("--appearance", help="外貌")
    p_char.add_argument("--background", help="背景")
    p_char.add_argument("--motivation", help="动机")
    p_char.add_argument("--arc", help="角色弧光")

    # ========== 世界观 ==========
    p_world = subparsers.add_parser("world", help="世界观管理")
    p_world.add_argument("action", choices=["list", "create"])
    p_world.add_argument("--novel", type=int, required=True)
    p_world.add_argument("--category", help="类别")
    p_world.add_argument("--title", help="标题")
    p_world.add_argument("--content", help="内容")

    # ========== 伏笔 ==========
    p_fs = subparsers.add_parser("foreshadow", help="伏笔管理")
    p_fs.add_argument("action", choices=["list", "create", "status"])
    p_fs.add_argument("--novel", type=int, help="小说 ID")
    p_fs.add_argument("--id", type=int, help="伏笔 ID")
    p_fs.add_argument("--title", help="伏笔标题")
    p_fs.add_argument("--description", help="伏笔描述")
    p_fs.add_argument("--importance", type=int, default=5, help="重要度 (1-10)")
    p_fs.add_argument("--planted", type=int, help="埋设章节")
    p_fs.add_argument("--status", help="新状态")

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
    p_rel.add_argument("action", choices=["list", "create"])
    p_rel.add_argument("--novel", type=int, required=True)
    p_rel.add_argument("--char-a", type=int, help="角色 A 的 ID")
    p_rel.add_argument("--char-b", type=int, help="角色 B 的 ID")
    p_rel.add_argument("--type", default="ordinary", help="关系类型")
    p_rel.add_argument("--desc", help="关系描述")

    # ========== 短篇 ==========
    p_short = subparsers.add_parser("short", help="短篇管理")
    p_short.add_argument("action", choices=["list", "create", "content"])
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
        "optimize": cmd_optimize,
        "sys": cmd_sys,
        "whoami": cmd_whoami,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()