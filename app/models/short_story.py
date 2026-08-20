"""短篇小说模型：短篇、版本、评审。"""
from app.models.base import db, now


class ShortStory(db.Model):
    """Short story — lightweight single-piece creation."""
    __tablename__ = "short_stories"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), default="")
    # Mode: inspiration / setting / careful
    mode = db.Column(db.String(20), default="inspiration")
    # User input fields
    inspiration = db.Column(db.Text, default="")
    genre = db.Column(db.String(100), default="")
    theme = db.Column(db.Text, default="")
    character_desc = db.Column(db.Text, default="")
    scene_desc = db.Column(db.Text, default="")
    tone = db.Column(db.String(50), default="")
    word_target = db.Column(db.Integer, default=2000)
    extra_instructions = db.Column(db.Text, default="")
    structure_template = db.Column(db.String(30), default="")
    # Expanded concept (from expander agent, inspiration mode)
    concept = db.Column(db.Text, default="")
    # 剧情大纲节点列表（JSON）: [{id, act, title, summary, word_count, status, content}]
    # content 为该节点的独立正文（去AI处理后）；status: pending / done
    # 由大纲 Agent 产出，驱动逐节点多轮生成与单节点重写
    outline_nodes = db.Column(db.Text, default="[]")
    # 分阶段策划产出（灵感模式 4 阶段流程）
    # 阶段1: 角色档案（纯文本，可编辑）
    plan_characters = db.Column(db.Text, default="")
    # 阶段2: 场景设定（纯文本，可编辑）
    plan_setting = db.Column(db.Text, default="")
    # 阶段4: 主题定调（纯文本，可编辑）
    plan_theme = db.Column(db.Text, default="")
    # Output
    content = db.Column(db.Text, default="")
    # Status: draft / concept_ready / generating / done
    status = db.Column(db.String(20), default="draft")
    created_at = db.Column(db.String(20), default=now)
    updated_at = db.Column(db.String(20), default=now, onupdate=now)

    versions = db.relationship("ShortStoryVersion", back_populates="story",
                               order_by="ShortStoryVersion.version_number",
                               cascade="all, delete-orphan")


class ShortStoryVersion(db.Model):
    """Version history for short stories — like ChapterVersion for long-form."""
    __tablename__ = "short_story_versions"
    id = db.Column(db.Integer, primary_key=True)
    story_id = db.Column(db.Integer, db.ForeignKey("short_stories.id"), nullable=False)
    version_number = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, default="")
    source = db.Column(db.String(10), default="ai")  # ai / human / rewrite
    approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.String(20), default=now)

    story = db.relationship("ShortStory", back_populates="versions")
    reviews = db.relationship("ShortStoryReview", back_populates="version",
                              order_by="ShortStoryReview.id.desc()",
                              cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint("story_id", "version_number", name="uq_ss_version"),)


class ShortStoryReview(db.Model):
    """Review/audit results for short story versions."""
    __tablename__ = "short_story_reviews"
    id = db.Column(db.Integer, primary_key=True)
    version_id = db.Column(db.Integer, db.ForeignKey("short_story_versions.id"), nullable=False)
    overall_score = db.Column(db.Float, nullable=True)
    dimension_scores_json = db.Column(db.Text, default="[]")
    annotations_json = db.Column(db.Text, default="[]")
    overall_comment = db.Column(db.Text, default="")
    full_response = db.Column(db.Text, default="")
    user_feedback = db.Column(db.Text, default="")
    # 17 维度审计结果（JSON），持久化以便页面刷新后恢复
    audit_json = db.Column(db.Text, default="")
    created_at = db.Column(db.String(20), default=now)

    version = db.relationship("ShortStoryVersion", back_populates="reviews")
