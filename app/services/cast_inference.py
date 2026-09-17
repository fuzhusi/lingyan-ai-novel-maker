"""出场角色推断——章节大纲文本 ↔ 人物卡名字匹配。

大纲是出场名单的天然来源：写作页据此前亮勾选（用户可手动覆盖），
配合 cast_constraint 硬约束形成闭环——大纲点到谁，就只放行谁。

设计取舍：确定性字符串匹配（免费/零延迟/可解释），不做 LLM 推断——
每次存大纲多一次模型调用不划算，且人名是精确实体，模糊匹配反而引入误报。
别名支持留作扩展（Character 表暂无别名字段）。

固定格式契约：大纲【出场人物】行里带（背景提及）标注的名字属于
"仅提及不登场"，不得点亮勾选——否则 cast_constraint 白名单会反向
给背景角色发登场许可，与大纲提示词的标注语义正面冲突。
"""
import re

from app.models import Character

# 匹配「张三（背景提及）」/「张三(背景提及)」两种写法
_BG_MENTION_RE = re.compile(r"([^\s，、,；;（）()【】]+)\s*[（(]\s*背景提及\s*[)）]")


def _background_mention_names(text):
    """大纲中被标注为（背景提及）的名字集合——仅提及、不登场。"""
    return {m.group(1) for m in _BG_MENTION_RE.finditer(text)}


def infer_cast(novel_id, text):
    """按大纲文本匹配出场角色，按命中次数降序。

    全名包含命中即算（中文姓名 2-4 字，误报率低）；名字为空的角色跳过；
    带（背景提及）标注的名字视为未出场（用户仍可手动勾选）。
    Returns: [{"id": int, "name": str, "hits": int}]
    """
    if not (text or "").strip():
        return []
    chars = Character.query.filter_by(novel_id=novel_id).all()
    bg_names = _background_mention_names(text)
    matched = []
    for c in chars:
        name = (c.name or "").strip()
        if not name or name in bg_names:
            continue
        hits = text.count(name)
        if hits > 0:
            matched.append({"id": c.id, "name": name, "hits": hits})
    matched.sort(key=lambda m: (-m["hits"], m["name"]))
    return matched
