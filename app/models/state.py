"""故事状态模型：状态引擎、快照、章节记忆、摘要。"""
from app.models.base import db, now


class StoryState(db.Model):
    """Story State Engine — maintains full-book state for long-form coherence."""
    __tablename__ = "story_states"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey("novels.id"), nullable=False, unique=True)

    # Main quest
    main_quest = db.Column(db.Text, default="")
    main_quest_progress = db.Column(db.String(50), default="")

    # Active subplots (JSON array)
    active_subplots = db.Column(db.Text, default="[]")

    # Active conflicts (JSON array)
    active_conflicts = db.Column(db.Text, default="[]")

    # Arc phase: setup → development → climax → resolution
    arc_phase = db.Column(db.String(20), default="setup")
    arc_intensity = db.Column(db.Integer, default=3)  # 1~10

    # Risk flags (JSON object)
    risk_flags = db.Column(db.Text, default="{}")

    # Excitement tracking
    excitement_history = db.Column(db.Text, default="[]")
    last_excitement_chapter = db.Column(db.Integer, nullable=True)
    current_excitement_density = db.Column(db.Float, default=0.0)

    # Pacing tracking
    recent_pacing = db.Column(db.Text, default="[]")

    current_chapter = db.Column(db.Integer, default=0)
    updated_at = db.Column(db.String(20), default=now, onupdate=now)

    novel = db.relationship("Novel", backref="story_state")


class StoryStateSnapshot(db.Model):
    """Snapshots of story state at each chapter for rollback capability."""
    __tablename__ = "story_state_snapshots"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey("novels.id"), nullable=False)
    chapter_id = db.Column(db.Integer, db.ForeignKey("chapters.id"), nullable=True)
    chapter_number = db.Column(db.Integer, nullable=False)
    state_json = db.Column(db.Text, default="{}")
    is_checkpoint = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.String(20), default=now)

    novel = db.relationship("Novel", backref="state_snapshots")
    chapter = db.relationship("Chapter", backref="state_snapshot")


class ChapterMemory(db.Model):
    """Structured chapter memory for long-term recall."""
    __tablename__ = "chapter_memories"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey("novels.id"), nullable=False)
    chapter_id = db.Column(db.Integer, db.ForeignKey("chapters.id"), nullable=False, unique=True)
    chapter_number = db.Column(db.Integer, nullable=False)
    summary = db.Column(db.Text, default="")  # 200-300 chars
    key_events_json = db.Column(db.Text, default="[]")
    character_changes_json = db.Column(db.Text, default="{}")
    foreshadow_events_json = db.Column(db.Text, default="[]")
    new_characters_json = db.Column(db.Text, default="[]")
    scenes_json = db.Column(db.Text, default="[]")  # Scene-level summaries
    created_at = db.Column(db.String(20), default=now)

    novel = db.relationship("Novel", backref="chapter_memories")
    # 删除章节时连带删除记忆（否则 flush 会尝试置 NULL 而 chapter_id 非空，触发 IntegrityError）
    # cascade 配置在 backref（Chapter.memory 一对多方向）
    chapter = db.relationship("Chapter", backref=db.backref("memory", cascade="all, delete-orphan"))


class ChapterSummary(db.Model):
    __tablename__ = "chapter_summaries"
    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey("chapters.id"), nullable=False, unique=True)
    summary = db.Column(db.Text, default="")
    causal_chain_json = db.Column(db.Text, default="")  # cause/event/effect/decision
    generated_at = db.Column(db.String(20), default=now)

    # 删除章节时连带删除摘要（chapter_id 非空，防 nullify IntegrityError）
    chapter = db.relationship("Chapter", backref=db.backref("summary", cascade="all, delete-orphan"))
