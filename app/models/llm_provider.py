"""LLM 厂商与模型配置。

LLMProvider: API 厂商（DeepSeek / OpenAI / Ollama / 自定义）
LLMModel:    厂商下的具体模型，用户勾选后可供 Agent 使用
"""
from app.models.base import db, now


class LLMProvider(db.Model):
    __tablename__ = "llm_providers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)          # 显示名，如 "DeepSeek"
    provider_type = db.Column(db.String(20), default="custom")  # deepseek / openai / ollama / custom
    base_url = db.Column(db.String(300), nullable=False)
    api_key = db.Column(db.Text, default="")
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.String(20), default=now)
    updated_at = db.Column(db.String(20), default=now, onupdate=now)

    models = db.relationship("LLMModel", backref="provider", cascade="all, delete-orphan", lazy="dynamic")

    def to_dict(self, include_key=False):
        if include_key:
            masked_key = self.api_key
        elif len(self.api_key) > 8:
            masked_key = self.api_key[:8] + "****"
        elif self.api_key:
            masked_key = self.api_key[:3] + "****"
        else:
            masked_key = ""
        return {
            "id": self.id,
            "name": self.name,
            "provider_type": self.provider_type,
            "base_url": self.base_url,
            "api_key": masked_key,
            "enabled": self.enabled,
        }


class LLMModel(db.Model):
    __tablename__ = "llm_models"

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("llm_providers.id"), nullable=False)
    model_id = db.Column(db.String(200), nullable=False)       # 原始 model id，如 "deepseek-v4-pro"
    display_name = db.Column(db.String(200), default="")       # 可选别名
    enabled = db.Column(db.Boolean, default=False)             # 用户是否勾选
    created_at = db.Column(db.String(20), default=now)

    __table_args__ = (
        db.UniqueConstraint("provider_id", "model_id", name="uq_provider_model"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "display_name": self.display_name or self.model_id,
            "enabled": self.enabled,
        }
