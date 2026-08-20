"""大纲模板服务 — 提供标准的小说大纲结构 (P2-1)。"""

from flask import Blueprint, jsonify

templates_bp = Blueprint("outline_tmpl", __name__, url_prefix="/api/outline-templates")


# 三种标准大纲结构
OUTLINE_TEMPLATES = {
    "beat": {
        "name": "节拍式大纲",
        "description": "经典 15 节拍结构，适合大多数商业小说",
        "structure": [
            {"type": "volume", "title": "第一卷", "summary": "开端"},
            {"type": "chapter", "title": "第一章：开场", "summary": "介绍主角及其日常世界"},
            {"type": "chapter", "title": "第二章：触发事件", "summary": "打破主角生活的事件"},
            {"type": "chapter", "title": "第三章：拒绝召唤", "summary": "主角最初拒绝冒险"},
            {"type": "chapter", "title": "第四章：遇见导师", "summary": "导师出现并给予指导"},
            {"type": "chapter", "title": "第五章：跨越门槛", "summary": "主角踏上冒险之旅"},
            {"type": "chapter", "title": "第六章：考验伙伴盟友敌人", "summary": "主角遇到伙伴和敌人"},
            {"type": "chapter", "title": "第七章：接近洞穴", "summary": "主角接近核心冲突"},
            {"type": "chapter", "title": "第八章：严峻考验", "summary": "主角面对重大挑战"},
            {"type": "chapter", "title": "第九章：获得宝物", "summary": "主角获得关键物品或认知"},
            {"type": "chapter", "title": "第十章：归途", "summary": "主角踏上归途"},
            {"type": "chapter", "title": "第十一章：复活", "summary": "主角经历重生或觉醒"},
            {"type": "chapter", "title": "第十二章：归来", "summary": "主角带着改变归来"},
            {"type": "chapter", "title": "第十三章：高潮对决", "summary": "最终对决"},
            {"type": "chapter", "title": "第十四章：尾声", "summary": "新平衡建立"},
        ],
    },
    "three_act": {
        "name": "三幕式大纲",
        "description": "经典三幕剧结构，适合戏剧性强的小说",
        "structure": [
            {"type": "volume", "title": "第一幕：开端", "summary": "建立人物和世界"},
            {"type": "chapter", "title": "第一章：钩子", "summary": "吸引读者的事件"},
            {"type": "chapter", "title": "第二章：背景设定", "summary": "介绍主角及其环境"},
            {"type": "chapter", "title": "第三章：触发事件", "summary": "改变主角生活的事件"},
            {"type": "volume", "title": "第二幕：对抗", "summary": "主角面对挑战"},
            {"type": "chapter", "title": "第四章：上升行动", "summary": "主角采取行动"},
            {"type": "chapter", "title": "第五章：中点", "summary": "故事核心转折点"},
            {"type": "chapter", "title": "第六章：低谷", "summary": "主角面临最低点"},
            {"type": "chapter", "title": "第七章：觉醒", "summary": "主角获得关键认知"},
            {"type": "volume", "title": "第三幕：解决", "summary": "冲突解决"},
            {"type": "chapter", "title": "第八章：高潮", "summary": "最终对决"},
            {"type": "chapter", "title": "第九章：收尾", "summary": "冲突解决"},
        ],
    },
    "heros_journey": {
        "name": "英雄之旅",
        "description": "约瑟夫·坎贝尔 12 阶段英雄之旅",
        "structure": [
            {"type": "chapter", "title": "第一章：平凡世界", "summary": "介绍英雄的日常"},
            {"type": "chapter", "title": "第二章：冒险召唤", "summary": "英雄面临挑战"},
            {"type": "chapter", "title": "第三章：拒绝召唤", "summary": "英雄的恐惧与犹豫"},
            {"type": "chapter", "title": "第四章：遇见导师", "summary": "导师传授智慧"},
            {"type": "chapter", "title": "第五章：跨越门槛", "summary": "英雄踏入未知世界"},
            {"type": "chapter", "title": "第六章：考验盟友敌人", "summary": "结交盟友，面对敌人"},
            {"type": "chapter", "title": "第七章：接近最深处", "summary": "接近核心冲突"},
            {"type": "chapter", "title": "第八章：严峻考验", "summary": "面对最大恐惧"},
            {"type": "chapter", "title": "第九章：获得宝物", "summary": "英雄获得回报"},
            {"type": "chapter", "title": "第十章：归途", "summary": "踏上回家之路"},
            {"type": "chapter", "title": "第十一章：复活", "summary": "最终觉醒"},
            {"type": "chapter", "title": "第十二章：带着宝物归来", "summary": "英雄归来，分享智慧"},
        ],
    },
    "four_act": {
        "name": "四幕式大纲",
        "description": "电影剧本常用的四幕结构",
        "structure": [
            {"type": "volume", "title": "第一幕：开端", "summary": "建立世界和人物"},
            {"type": "chapter", "title": "第一章：日常与钩子", "summary": "介绍主角日常"},
            {"type": "chapter", "title": "第二章：触发事件", "summary": "打破平衡的事件"},
            {"type": "volume", "title": "第二幕：对抗", "summary": "冲突升级"},
            {"type": "chapter", "title": "第三章：陷入困境", "summary": "主角面对挑战"},
            {"type": "chapter", "title": "第四章：羁绊加深", "summary": "建立情感连接"},
            {"type": "chapter", "title": "第五章：中点转折", "summary": "故事核心变化"},
            {"type": "volume", "title": "第三幕：危机", "summary": "危机加深"},
            {"type": "chapter", "title": "第六章：失去一切", "summary": "主角陷入低谷"},
            {"type": "chapter", "title": "第七章：终极对决", "summary": "面对最终敌人"},
            {"type": "volume", "title": "第四幕：结局", "summary": "冲突解决"},
            {"type": "chapter", "title": "第八章：高潮解决", "summary": "最终冲突解决"},
            {"type": "chapter", "title": "第九章：新平衡", "summary": "新秩序建立"},
        ],
    },
}


@templates_bp.route("/list")
def list_templates():
    """获取所有大纲模板（JSON）。"""
    result = {}
    for key, tmpl in OUTLINE_TEMPLATES.items():
        result[key] = {
            "name": tmpl["name"],
            "description": tmpl["description"],
            "node_count": len(tmpl["structure"]),
            "structure": tmpl["structure"],
        }
    return jsonify(result)


@templates_bp.route("/<key>")
def get_template(key):
    """获取单个大纲模板。"""
    tmpl = OUTLINE_TEMPLATES.get(key)
    if not tmpl:
        return jsonify({"error": "模板不存在"}), 404
    return jsonify({"key": key, **tmpl})


def apply_template(novel_id, template_key, db, OutlineNode):
    """应用大纲模板到指定小说，创建对应的 OutlineNode 节点。"""
    tmpl = OUTLINE_TEMPLATES.get(template_key)
    if not tmpl:
        return None

    # 删除现有大纲
    OutlineNode.query.filter_by(novel_id=novel_id).delete()

    # 创建新大纲
    nodes = []
    for i, item in enumerate(tmpl["structure"], 1):
        node = OutlineNode(
            novel_id=novel_id,
            title=item["title"],
            summary=item["summary"],
            node_type=item["type"],
            sort_order=i,
        )
        db.session.add(node)
        nodes.append(node)
    db.session.flush()

    # 构建父子关系（卷 → 章）
    last_volume = None
    for node in nodes:
        if node.node_type == "volume":
            last_volume = node
            node.parent_id = None
        else:
            if last_volume:
                node.parent_id = last_volume.id
            else:
                node.parent_id = None

    db.session.commit()
    return nodes