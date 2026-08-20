"""核心小说结构模型：小说、章节、版本、评审、模板、设置。"""
from app.models.base import db, now


class Novel(db.Model):
    __tablename__ = "novels"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    genre = db.Column(db.String(100), default="")
    synopsis = db.Column(db.Text, default="")
    world_intro = db.Column(db.Text, default="")
    model_override = db.Column(db.Text, default="{}")
    created_at = db.Column(db.String(20), default=now)

    chapters = db.relationship("Chapter", back_populates="novel", order_by="Chapter.chapter_number")


class Chapter(db.Model):
    __tablename__ = "chapters"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey("novels.id"), nullable=False)
    chapter_number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200), default="")
    outline = db.Column(db.Text, default="")
    user_directive = db.Column(db.Text, default="")
    outline_node_id = db.Column(db.Integer, db.ForeignKey("outline_nodes.id"), nullable=True)
    created_at = db.Column(db.String(20), default=now)

    novel = db.relationship("Novel", back_populates="chapters")
    versions = db.relationship("ChapterVersion", back_populates="chapter", order_by="ChapterVersion.version_number")
    outline_node = db.relationship("OutlineNode", backref="linked_chapter", uselist=False)

    __table_args__ = (db.UniqueConstraint("novel_id", "chapter_number", name="uq_chapter_number"),)


class ChapterVersion(db.Model):
    __tablename__ = "chapter_versions"
    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey("chapters.id"), nullable=False)
    version_number = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, default="")
    source = db.Column(db.String(10), default="ai")  # "ai" or "human"
    prompt_used = db.Column(db.Text, default="")
    model_params_json = db.Column(db.Text, default="{}")
    approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.String(20), default=now)

    chapter = db.relationship("Chapter", back_populates="versions")
    reviews = db.relationship("CriticReview", back_populates="version", lazy="dynamic")

    __table_args__ = (db.UniqueConstraint("chapter_id", "version_number", name="uq_version_number"),)


class CriticReview(db.Model):
    __tablename__ = "critic_reviews"
    id = db.Column(db.Integer, primary_key=True)
    version_id = db.Column(db.Integer, db.ForeignKey("chapter_versions.id"), nullable=False)
    overall_score = db.Column(db.Float, nullable=True)
    dimension_scores_json = db.Column(db.Text, default="[]")
    annotations_json = db.Column(db.Text, default="[]")
    overall_comment = db.Column(db.Text, default="")
    full_response = db.Column(db.Text, default="")
    user_feedback = db.Column(db.Text, default="")
    created_at = db.Column(db.String(20), default=now)

    version = db.relationship("ChapterVersion", back_populates="reviews")


class PromptTemplate(db.Model):
    __tablename__ = "prompt_templates"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    template_type = db.Column(db.String(20), default="writer")
    template_content = db.Column(db.Text, default="")
    constraints = db.Column(db.Text, default="")
    variable_help = db.Column(db.Text, default="")
    created_at = db.Column(db.String(20), default=now)
    updated_at = db.Column(db.String(20), default=now, onupdate=now)


class Setting(db.Model):
    __tablename__ = "settings"
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, default="")
