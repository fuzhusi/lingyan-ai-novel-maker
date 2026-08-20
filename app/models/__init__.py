"""数据库模型包 — 统一导出所有模型。

所有模型按领域拆分到子模块，此文件提供向后兼容的统一导入。
"""
from app.models.base import db, now

# 核心小说结构
from app.models.novel import (
    Novel, Chapter, ChapterVersion, CriticReview, PromptTemplate, Setting,
)

# 知识库
from app.models.knowledge import (
    Character, WorldSetting, OutlineNode, Foreshadowing, CharacterRelation,
)

# 故事状态
from app.models.state import (
    StoryState, StoryStateSnapshot, ChapterMemory, ChapterSummary,
)

# 短篇小说
from app.models.short_story import (
    ShortStory, ShortStoryVersion, ShortStoryReview,
)

# 抄袭/借鉴模块
from app.models.plagiarize import PlagiarizeTask

# LLM 厂商与模型
from app.models.llm_provider import LLMProvider, LLMModel


def init_db(app):
    with app.app_context():
        db.create_all()
        # Migration: add columns added after initial schema
        migrations = [
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
        ]
        for sql in migrations:
            try:
                db.session.execute(db.text(sql))
            except Exception:
                pass
        db.session.commit()


__all__ = [
    "db", "now", "init_db",
    "Novel", "Chapter", "ChapterVersion", "CriticReview", "PromptTemplate", "Setting",
    "Character", "WorldSetting", "OutlineNode", "Foreshadowing", "CharacterRelation",
    "StoryState", "StoryStateSnapshot", "ChapterMemory", "ChapterSummary",
    "ShortStory", "ShortStoryVersion", "ShortStoryReview",
    "PlagiarizeTask",
    "LLMProvider", "LLMModel",
]
