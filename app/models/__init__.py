"""数据库模型包 — 统一导出所有模型。

所有模型按领域拆分到子模块，此文件提供向后兼容的统一导入。
"""
import sqlite3

from sqlalchemy import event as sa_event
from sqlalchemy.engine import Engine

from app.models.base import db, now


@sa_event.listens_for(Engine, "connect")
def _sqlite_connect_pragmas(dbapi_conn, _rec):
    """SQLite 连接级 PRAGMA:外键强制 + 忙等待 + WAL 下安全的同步策略。

    foreign_keys=ON:此前全库从未开启,所有 FK 只是装饰——配合 ORM 级联
    与孤儿清理迁移,让引用完整性由数据库兜底而非手工枚举。
    """
    if isinstance(dbapi_conn, sqlite3.Connection):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

# 核心小说结构
from app.models.novel import (
    Novel, Chapter, ChapterVersion, CriticReview, BlindReview, PromptTemplate, Setting,
)

# 知识库
from app.models.knowledge import (
    Character, WorldSetting, OutlineNode, Foreshadowing, CharacterRelation,
    PendingExtraction, ReaderKnowledge,
)

# 故事状态
from app.models.state import (
    StoryState, StoryStateSnapshot, ChapterMemory, ChapterSummary,
)

# 短篇小说
from app.models.short_story import (
    ShortStory, ShortStoryVersion, ShortStoryReview,
)

# 抄袭/借鉴模块（拆书复刻）
from app.models.plagiarize import PlagiarizeTask, DeconstructItem

# LLM 厂商与模型
from app.models.llm_provider import LLMProvider, LLMModel

# 进程内长任务
from app.models.long_task import LongTask

# LLM 调用计量
from app.models.llm_call import LLMCall

# 资源库
from app.models.resource import ResourceBook, ResourceChunk

# 实体嵌入（语义检索索引层）
from app.models.entity_embedding import EntityEmbedding


def init_db(app):
    with app.app_context():
        db.create_all()
        _apply_migrations(app)
        _recover_stale_states()


def _migration_key(sql):
    import hashlib
    return "m" + hashlib.md5(sql.encode("utf-8")).hexdigest()[:12]


def _apply_migrations(app):
    """带版本表的迁移:已应用跳过;首次引导(旧库)宽松降级;此后新迁移失败即抛。"""
    import hashlib
    db.session.execute(db.text(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(key VARCHAR(100) PRIMARY KEY, applied_at VARCHAR(20))"))
    applied = {r[0] for r in db.session.execute(db.text("SELECT key FROM schema_migrations"))}
    first_time = not applied  # 版本表为空 = 存量旧库首次引导
    for sql in MIGRATIONS:
        key = "m" + hashlib.md5(sql.encode("utf-8")).hexdigest()[:12]
        if key in applied:
            continue
        try:
            db.session.execute(db.text(sql))
            db.session.execute(
                db.text("INSERT OR IGNORE INTO schema_migrations (key, applied_at) VALUES (:k, :t)"),
                {"k": key, "t": now()})
            db.session.commit()
        except Exception:
            db.session.rollback()
            if not first_time:
                # 新增迁移在真库上失败:暴露问题而不是吞掉(schema 漂移延后爆发的根源)
                raise
            # 引导期:存量列已存在等无害冲突,标记已应用避免每次重试
            try:
                db.session.execute(
                    db.text("INSERT OR IGNORE INTO schema_migrations (key, applied_at) VALUES (:k, :t)"),
                    {"k": key, "t": now()})
                db.session.commit()
            except Exception:
                db.session.rollback()


def _recover_stale_states():
    """启动恢复:进程死亡后卡在「进行中」的长任务与拆书任务置为可重试的失败态。"""
    from app.models.plagiarize import PlagiarizeTask
    from app.models.long_task import LongTask
    n1 = LongTask.query.filter_by(status="running").update(
        {LongTask.status: "failed", LongTask.error: "服务重启中断,请重新发起"})
    n2 = PlagiarizeTask.query.filter(PlagiarizeTask.status.in_(("summarizing", "deconstructing"))).update(
        {PlagiarizeTask.status: "failed",
         PlagiarizeTask.error_message: "服务重启中断，拆解未完成（可直接重新拆书，已完成的摘要会断点续用）"},
        synchronize_session=False)
    if n1 or n2:
        db.session.commit()


# 迁移清单:只追加不重排(key 为 SQL 内容哈希)。新增迁移放列表尾部,失败即抛。
MIGRATIONS = [
    "ALTER TABLE novels ADD COLUMN genre VARCHAR(100) DEFAULT ''",
            "ALTER TABLE novels ADD COLUMN synopsis TEXT DEFAULT ''",
            "ALTER TABLE novels ADD COLUMN world_intro TEXT DEFAULT ''",
            "ALTER TABLE novels ADD COLUMN model_override TEXT DEFAULT '{}'",
            "ALTER TABLE chapter_versions ADD COLUMN approved BOOLEAN DEFAULT 0",
            "ALTER TABLE chapters ADD COLUMN outline_node_id INTEGER REFERENCES outline_nodes(id)",
            "ALTER TABLE critic_reviews ADD COLUMN overall_score FLOAT",
            "ALTER TABLE critic_reviews ADD COLUMN annotations_json TEXT DEFAULT '[]'",
            "ALTER TABLE critic_reviews ADD COLUMN user_feedback TEXT DEFAULT ''",
            # Foreshadowing enhancements (StoryForge)
            "ALTER TABLE foreshadowing ADD COLUMN title VARCHAR(200) DEFAULT ''",
            "ALTER TABLE foreshadowing ADD COLUMN importance INTEGER DEFAULT 5",
            "ALTER TABLE foreshadowing ADD COLUMN last_mentioned_chapter INTEGER",
            "ALTER TABLE foreshadowing ADD COLUMN timeout_threshold INTEGER DEFAULT 15",
            "ALTER TABLE foreshadowing ADD COLUMN notes TEXT DEFAULT ''",
            # Short story concept column
            "ALTER TABLE short_stories ADD COLUMN concept TEXT DEFAULT ''",
            "ALTER TABLE short_stories ADD COLUMN structure_template VARCHAR(30) DEFAULT ''",
            # Short story outline nodes (JSON)
            "ALTER TABLE short_stories ADD COLUMN outline_nodes TEXT DEFAULT '[]'",
            # Short story planning stages (角色/场景/主题)
            "ALTER TABLE short_stories ADD COLUMN plan_characters TEXT DEFAULT ''",
            "ALTER TABLE short_stories ADD COLUMN plan_setting TEXT DEFAULT ''",
            "ALTER TABLE short_stories ADD COLUMN plan_theme TEXT DEFAULT ''",
            # Short story review audit result (JSON, 17-dimension)
            "ALTER TABLE short_story_reviews ADD COLUMN audit_json TEXT DEFAULT ''",
            # Prompt template constraints column
            "ALTER TABLE prompt_templates ADD COLUMN constraints TEXT DEFAULT ''",
            # Causal chain column
            "ALTER TABLE chapter_summaries ADD COLUMN causal_chain_json TEXT DEFAULT ''",
            # 创作罗盘（借鉴 OpenWrite）：全书承诺 + 当前阶段目标
            "ALTER TABLE novels ADD COLUMN author_intent TEXT DEFAULT ''",
            "ALTER TABLE novels ADD COLUMN current_focus TEXT DEFAULT ''",
            # 大纲失配标记（merge-assessment A1v1）：正文生成时的大纲指纹
            "ALTER TABLE chapters ADD COLUMN outline_hash VARCHAR(64) DEFAULT ''",
            # P4 风格备忘录（B3）
            "ALTER TABLE novels ADD COLUMN style_memo_json TEXT DEFAULT '[]'",
            # 拆书复刻（V3.8）：对标书拆解字段
            "ALTER TABLE plagiarize_tasks ADD COLUMN title VARCHAR(200) DEFAULT ''",
            "ALTER TABLE plagiarize_tasks ADD COLUMN source_type VARCHAR(20) DEFAULT 'paste'",
            "ALTER TABLE plagiarize_tasks ADD COLUMN report_text TEXT DEFAULT ''",
            "ALTER TABLE plagiarize_tasks ADD COLUMN elements_json TEXT DEFAULT '[]'",
            "ALTER TABLE plagiarize_tasks ADD COLUMN chapters_summary_json TEXT DEFAULT '[]'",
            "ALTER TABLE plagiarize_tasks ADD COLUMN volumes_summary_json TEXT DEFAULT '[]'",
            "ALTER TABLE plagiarize_tasks ADD COLUMN modifications_text TEXT DEFAULT ''",
            # 拆书复刻时间轴（V3.8 落库计划值）：伏笔双锚点 + 证据
            "ALTER TABLE foreshadowing ADD COLUMN earliest_resolve_chapter INTEGER",
            "ALTER TABLE foreshadowing ADD COLUMN expected_resolve_chapter INTEGER",
            "ALTER TABLE foreshadowing ADD COLUMN source_event TEXT DEFAULT ''",
            "ALTER TABLE foreshadowing ADD COLUMN evidence TEXT DEFAULT ''",
            # WAL 模式（读写并发友好；journal_mode 持久化在库文件里，重复执行无害）
            "PRAGMA journal_mode=WAL",
            # 热路径外键索引（SQLite 不自动为外键建索引；唯一约束已覆盖
            # chapters.novel_id / chapter_versions.chapter_id 等复合键首列，这里补齐裸外键）
            "CREATE INDEX IF NOT EXISTS ix_characters_novel ON characters(novel_id)",
            "CREATE INDEX IF NOT EXISTS ix_world_settings_novel ON world_settings(novel_id)",
            "CREATE INDEX IF NOT EXISTS ix_outline_nodes_novel ON outline_nodes(novel_id)",
            "CREATE INDEX IF NOT EXISTS ix_foreshadowing_novel ON foreshadowing(novel_id)",
            "CREATE INDEX IF NOT EXISTS ix_chapter_summaries_chapter ON chapter_summaries(chapter_id)",
            "CREATE INDEX IF NOT EXISTS ix_chapter_memories_chapter ON chapter_memories(chapter_id)",
            "CREATE INDEX IF NOT EXISTS ix_critic_reviews_version ON critic_reviews(version_id)",
            "CREATE INDEX IF NOT EXISTS ix_deconstruct_items_task ON deconstruct_items(task_id)",
            "CREATE INDEX IF NOT EXISTS ix_short_story_versions_story ON short_story_versions(story_id)",
            "CREATE INDEX IF NOT EXISTS ix_character_relations_novel ON character_relations(novel_id)",
            "CREATE INDEX IF NOT EXISTS ix_pending_extractions_novel ON pending_extractions(novel_id)",
            # 孤儿清理(FK 开启前的一次性大扫除;此后引用完整性由 PRAGMA foreign_keys 兜底)
            "DELETE FROM critic_reviews WHERE version_id NOT IN (SELECT id FROM chapter_versions)",
            "DELETE FROM chapter_versions WHERE chapter_id NOT IN (SELECT id FROM chapters)",
            "DELETE FROM chapter_summaries WHERE chapter_id NOT IN (SELECT id FROM chapters)",
            "DELETE FROM chapter_memories WHERE chapter_id NOT IN (SELECT id FROM chapters)",
            "DELETE FROM blind_reviews WHERE version_id IS NOT NULL AND version_id NOT IN (SELECT id FROM chapter_versions)",
            "DELETE FROM blind_reviews WHERE story_id IS NOT NULL AND story_id NOT IN (SELECT id FROM short_stories)",
            "DELETE FROM short_story_reviews WHERE version_id NOT IN (SELECT id FROM short_story_versions)",
            "DELETE FROM short_story_versions WHERE story_id NOT IN (SELECT id FROM short_stories)",
            "DELETE FROM chapters WHERE novel_id NOT IN (SELECT id FROM novels)",
            "DELETE FROM characters WHERE novel_id NOT IN (SELECT id FROM novels)",
            "DELETE FROM world_settings WHERE novel_id NOT IN (SELECT id FROM novels)",
            "DELETE FROM outline_nodes WHERE novel_id NOT IN (SELECT id FROM novels)",
            "DELETE FROM foreshadowing WHERE novel_id NOT IN (SELECT id FROM novels)",
            "DELETE FROM character_relations WHERE novel_id NOT IN (SELECT id FROM novels)",
            "DELETE FROM pending_extractions WHERE novel_id NOT IN (SELECT id FROM novels)",
            "DELETE FROM story_state_snapshots WHERE novel_id NOT IN (SELECT id FROM novels)",
            "DELETE FROM story_states WHERE novel_id NOT IN (SELECT id FROM novels)",
            "DELETE FROM deconstruct_items WHERE task_id NOT IN (SELECT id FROM plagiarize_tasks)",
            # 长任务协作式取消（P0-3 补全）
            "ALTER TABLE long_tasks ADD COLUMN cancel_requested BOOLEAN DEFAULT 0",
            # 差异轴（生成期差异化指令块的数据源）
            "ALTER TABLE plagiarize_tasks ADD COLUMN axes_text TEXT DEFAULT ''",
            # 本章事件清单（StoryWriter planning 层）
            "ALTER TABLE chapters ADD COLUMN event_plan TEXT DEFAULT ''",
            # 跨章 Reflexion 笔记
            "ALTER TABLE chapters ADD COLUMN reflexion_notes TEXT DEFAULT ''",
        ]


__all__ = [
    "db", "now", "init_db",
    "Novel", "Chapter", "ChapterVersion", "CriticReview", "BlindReview", "PromptTemplate", "Setting",
    "Character", "WorldSetting", "OutlineNode", "Foreshadowing", "CharacterRelation",
    "PendingExtraction", "ReaderKnowledge",
    "StoryState", "StoryStateSnapshot", "ChapterMemory", "ChapterSummary",
    "ShortStory", "ShortStoryVersion", "ShortStoryReview",
    "PlagiarizeTask", "DeconstructItem",
    "LLMProvider", "LLMModel",
    "LongTask",
    "LLMCall",
    "ResourceBook", "ResourceChunk",
    "EntityEmbedding",
]
