"""知识库模型：角色、世界观、大纲、伏笔、角色关系。"""
from app.models.base import db, now


class Character(db.Model):
    __tablename__ = "characters"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey("novels.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    personality = db.Column(db.Text, default="")
    speaking_style = db.Column(db.Text, default="")
    appearance = db.Column(db.Text, default="")
    background = db.Column(db.Text, default="")
    motivation = db.Column(db.Text, default="")
    arc_direction = db.Column(db.Text, default="")
    status_json = db.Column(db.Text, default="{}")
    created_at = db.Column(db.String(20), default=now)
    updated_at = db.Column(db.String(20), default=now, onupdate=now)

    novel = db.relationship("Novel", backref="characters")


class WorldSetting(db.Model):
    __tablename__ = "world_settings"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey("novels.id"), nullable=False)
    category = db.Column(db.String(100), default="")
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, default="")
    created_at = db.Column(db.String(20), default=now)
    updated_at = db.Column(db.String(20), default=now, onupdate=now)

    novel = db.relationship("Novel", backref="world_settings")


class OutlineNode(db.Model):
    __tablename__ = "outline_nodes"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey("novels.id"), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("outline_nodes.id"), nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    node_type = db.Column(db.String(20), default="chapter")  # volume, chapter, scene
    title = db.Column(db.String(200), default="")
    summary = db.Column(db.Text, default="")
    created_at = db.Column(db.String(20), default=now)

    novel = db.relationship("Novel", backref="outline_nodes")
    children = db.relationship("OutlineNode", backref=db.backref("parent", remote_side=[id]),
                               order_by="OutlineNode.sort_order")


class Foreshadowing(db.Model):
    __tablename__ = "foreshadowing"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey("novels.id"), nullable=False)
    title = db.Column(db.String(200), default="")
    description = db.Column(db.Text, default="")
    planted_chapter = db.Column(db.Integer, nullable=True)
    resolve_chapter = db.Column(db.Integer, nullable=True)
    # State machine: planned → buried → advancing → reclaimable → resolved
    # Any state → abandoned
    status = db.Column(db.String(20), default="open")
    importance = db.Column(db.Integer, default=5)
    last_mentioned_chapter = db.Column(db.Integer, nullable=True)
    timeout_threshold = db.Column(db.Integer, default=15)
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.String(20), default=now)

    novel = db.relationship("Novel", backref="foreshadowing_items")


class CharacterRelation(db.Model):
    """Multi-dimensional character relationship with dynamic evolution."""
    __tablename__ = "character_relations"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey("novels.id"), nullable=False)
    character_a_id = db.Column(db.Integer, db.ForeignKey("characters.id"), nullable=False)
    character_b_id = db.Column(db.Integer, db.ForeignKey("characters.id"), nullable=False)
    relation_type = db.Column(db.String(50), default="ordinary")
    description = db.Column(db.Text, default="")
    # Multi-dimensional scores (0-100)
    trust = db.Column(db.Integer, default=50)
    affection = db.Column(db.Integer, default=50)
    respect = db.Column(db.Integer, default=50)
    fear = db.Column(db.Integer, default=0)
    dependency = db.Column(db.Integer, default=50)
    status = db.Column(db.String(20), default="active")
    start_chapter = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.String(20), default=now)
    updated_at = db.Column(db.String(20), default=now, onupdate=now)

    novel = db.relationship("Novel", backref="character_relations")
    character_a = db.relationship("Character", foreign_keys=[character_a_id], backref="relations_as_a")
    character_b = db.relationship("Character", foreign_keys=[character_b_id], backref="relations_as_b")

    __table_args__ = (
        db.UniqueConstraint("character_a_id", "character_b_id", name="uq_char_relation"),
    )

    @property
    def overall_score(self):
        """Weighted relationship score."""
        return (self.trust * 0.3 + self.affection * 0.25 +
                self.respect * 0.2 + (100 - self.fear) * 0.15 +
                self.dependency * 0.1)

    @property
    def auto_relation_type(self):
        """Auto-detect relation type from scores."""
        if self.affection > 80 and self.trust > 70:
            return "恋人/挚友"
        if self.trust > 70 and self.respect > 60:
            return "好友"
        if self.fear > 70 and self.respect < 30:
            return "畏惧/仇恨"
        if self.dependency > 70 and self.trust > 60:
            return "依赖/师徒"
        if self.trust < 30 and self.affection < 30:
            return "敌对"
        return "普通"
