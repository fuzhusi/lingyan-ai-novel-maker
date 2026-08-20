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
    open_foreshadowing = [f for f in foreshadowing_items if f.status == "open"]
    timeout_foreshadowing = [
        f for f in open_foreshadowing
        if f.planted_chapter and len(chapters) - f.planted_chapter > f.timeout_threshold
    ]
    summaries = ChapterSummary.query.join(Chapter).filter(Chapter.novel_id == novel_id).all()

    # 写作连续天数（简化版：检查今天是否有创作）
    today = datetime.now().date()
    streak = 0
    has_today_creation = False
    for ch in chapters:
        for v in ChapterVersion.query.filter_by(chapter_id=ch.id).all():
            d = _parse_date(v.created_at)
            if d and d.date() == today:
                has_today_creation = True
                break
        if has_today_creation:
            break
    streak = 1 if has_today_creation else 0

    # 本周字数
    week_chars = 0
    for cs in summaries:
        d = _parse_date(cs.generated_at)
        if d and (today - d.date()).days <= 7:
            week_chars += cs.summary and len(cs.summary) or 0

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