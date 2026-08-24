from flask import Blueprint, render_template
from datetime import datetime
from app.models import (db, Novel, Chapter, ChapterVersion, Character,
                        WorldSetting, OutlineNode, Foreshadowing, ChapterSummary)

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/novel/<int:novel_id>/dashboard")


def _parse_date(s):
    """解析日期字符串。"""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


@dashboard_bp.route("/")
def dashboard_page(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    chapters = Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.chapter_number).all()

    total_chars = 0
    total_words = 0
    approved_count = 0
    chapter_stats = []
    char_trend = []  # 字数趋势数据

    for ch in chapters:
        versions = ChapterVersion.query.filter_by(chapter_id=ch.id).all()
        approved = [v for v in versions if v.approved]

        # Get the best content: approved latest, or latest version
        content = ""
        if approved:
            content = max(approved, key=lambda v: v.version_number).content
        elif versions:
            content = max(versions, key=lambda v: v.version_number).content

        char_count = len(content)
        chinese_chars = sum(1 for c in content if '一' <= c <= '鿿')

        total_chars += char_count
        total_words += chinese_chars

        if approved:
            approved_count += 1

        chapter_stats.append({
            "chapter": ch,
            "version_count": len(versions),
            "approved": bool(approved),
            "char_count": char_count,
            "word_count": chinese_chars,
            "latest_version": max(versions, key=lambda v: v.version_number).version_number if versions else 0,
        })

        char_trend.append({
            "chapter_number": ch.chapter_number,
            "chars": chinese_chars,
            "title": ch.title or f"第{ch.chapter_number}章",
        })

    # Knowledge base stats
    characters = Character.query.filter_by(novel_id=novel_id).all()
    world_settings = WorldSetting.query.filter_by(novel_id=novel_id).all()
    outline_nodes = OutlineNode.query.filter_by(novel_id=novel_id).all()
    foreshadowing_items = Foreshadowing.query.filter_by(novel_id=novel_id).all()
    open_foreshadowing = [f for f in foreshadowing_items
                          if f.status not in ("resolved", "abandoned")]
    # 超时口径与 /api/foreshadowing/timeout-check 对齐：
    # 全部未回收状态 + 以最新章节号为基准（此前用"现有章节数"，
    # 章节号不从 1 开始或有跳号时全部错位）
    latest_chapter_number = max((ch.chapter_number for ch in chapters), default=0)
    timeout_foreshadowing = [
        f for f in open_foreshadowing
        if f.planted_chapter
        and (latest_chapter_number - f.planted_chapter) > (f.timeout_threshold or 15)
    ]
    summaries = ChapterSummary.query.join(Chapter).filter(Chapter.novel_id == novel_id).all()

    # 收集本小说全部版本创建日期（UTC 口径，与 models.now() 一致）
    all_versions = ChapterVersion.query.join(Chapter).filter(
        Chapter.novel_id == novel_id).all()
    creation_dates = set()
    for v in all_versions:
        d = _parse_date(v.created_at)
        if d:
            creation_dates.add(d.date())

    # 写作连续天数：从今天（或昨天）起往回数连续有创作的天数。
    # 此前恒为 0/1 的"简化版"与卡片文案"连续创作 N 天"不符
    today = datetime.now().date()
    streak = 0
    cursor = today if today in creation_dates else (
        today.fromordinal(today.toordinal() - 1) if
        today.fromordinal(today.toordinal() - 1) in creation_dates else None)
    while cursor is not None and cursor in creation_dates:
        streak += 1
        cursor = today.fromordinal(cursor.toordinal() - 1)

    # 本周字数 = 近 7 天创建的版本正文字数之和。
    # 此前统计的是"摘要字符数"，语义完全不对（摘要是 AI 生成的压缩文本）
    week_chars = 0
    week_start = today.fromordinal(today.toordinal() - 7)
    for v in all_versions:
        d = _parse_date(v.created_at)
        if d and d.date() >= week_start:
            week_chars += len(v.content or "")

    # 进度（30 章目标）
    target_chapters = 30
    progress_pct = min(100, round(len(chapters) / target_chapters * 100, 1))
    remaining_chapters = max(0, target_chapters - len(chapters))
    avg_chars = int(total_words / max(len(chapters), 1)) if chapters else 0

    # 完成度
    completion_pct = round(approved_count / max(len(chapters), 1) * 100, 1) if chapters else 0

    return render_template("dashboard.html",
                           novel=novel,
                           chapter_stats=chapter_stats,
                           total_chars=total_chars,
                           total_words=total_words,
                           approved_count=approved_count,
                           character_count=len(characters),
                           world_setting_count=len(world_settings),
                           outline_node_count=len(outline_nodes),
                           foreshadowing_total=len(foreshadowing_items),
                           foreshadowing_open=len(open_foreshadowing),
                           foreshadowing_timeout=len(timeout_foreshadowing),
                           summary_count=len(summaries),
                           # 新增统计
                           streak=streak,
                           week_chars=week_chars,
                           avg_chars=avg_chars,
                           remaining_chapters=remaining_chapters,
                           progress_pct=progress_pct,
                           completion_pct=completion_pct,
                           target_chapters=target_chapters,
                           char_trend=char_trend,
                           timeout_items=timeout_foreshadowing[:5])