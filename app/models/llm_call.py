"""LLM 调用计量(P1-4):每次调用一行,支撑成本核算与失败率聚合。

粗估口径:中文字符 ≈ 0.5-0.7 token,展示层可用 chars/2 做"约多少 token"参考;
精确 token 需厂商返回 usage,后续在 langchain 响应上补采。
"""
from app.models.base import db, now


class LLMCall(db.Model):
    __tablename__ = "llm_calls"
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(10), default="sync")   # sync / stream
    model = db.Column(db.String(200), default="")
    ok = db.Column(db.Boolean, default=True)
    duration_ms = db.Column(db.Integer, default=0)
    prompt_chars = db.Column(db.Integer, default=0)
    output_chars = db.Column(db.Integer, default=0)
    error = db.Column(db.Text, default="")
    created_at = db.Column(db.String(20), default=now, index=True)
