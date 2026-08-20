"""短篇故事结构模板 — 为不同类型的短篇提供结构化写作指导。

Inspired by creative-writing-skill's 10 principles and story-architect's lifecycle.

4 种结构模板：
- three_act: 三段式 — 铺垫→冲突→解决（通用短篇）
- twist: 反转式 — 表象→伏笔→反转→真相（悬疑/推理）
- emotional_arc: 情感弧 — 日常→触动→改变→余韵（治愈/文艺）
- escalating: 冲突递进 — 小冲突→升级→高潮→抉择（动作/冒险）
"""


# 结构模板定义
STRUCTURE_TEMPLATES = {
    "three_act": {
        "name": "三段式",
        "description": "经典三幕结构，铺垫→冲突→解决，适用于大多数短篇",
        "icon": "📐",
        "genres": ["通用", "现实主义", "科幻", "奇幻"],
        "structure": [
            {"phase": "铺垫", "ratio": "25%", "desc": "建立角色、场景、日常世界，引出核心矛盾"},
            {"phase": "冲突", "ratio": "50%", "desc": "矛盾激化，角色面对挑战，情节推进"},
            {"phase": "解决", "ratio": "25%", "desc": "冲突达到顶点后解决，留下余韵或启示"},
        ],
        "prompt": (
            "【结构指导 — 三段式】\n"
            "请按以下结构组织故事：\n"
            "1. 铺垫（约25%篇幅）：建立角色和场景，展示日常世界，引出核心矛盾或悬念\n"
            "2. 冲突（约50%篇幅）：矛盾激化，角色面对挑战和阻碍，情节不断推进\n"
            "3. 解决（约25%篇幅）：冲突达到顶点，角色做出关键选择，故事收束并留下余味\n\n"
            "注意：每个阶段之间要有清晰的转折点，节奏张弛有度。"
        ),
    },
    "twist": {
        "name": "反转式",
        "description": "表象→伏笔→反转→真相，适合悬疑、推理、惊悚类故事",
        "icon": "🔄",
        "genres": ["悬疑", "推理", "惊悚", "恐怖"],
        "structure": [
            {"phase": "表象", "ratio": "30%", "desc": "呈现表面事实，建立读者的初始认知"},
            {"phase": "伏笔", "ratio": "30%", "desc": "埋下微妙线索，暗示真相并非如此"},
            {"phase": "反转", "ratio": "25%", "desc": "关键真相揭露，颠覆读者认知"},
            {"phase": "真相", "ratio": "15%", "desc": "重新解读前文线索，完整揭示真相"},
        ],
        "prompt": (
            "【结构指导 — 反转式】\n"
            "请按以下结构组织故事：\n"
            "1. 表象（约30%篇幅）：呈现表面事实，让读者建立初始认知和预期\n"
            "2. 伏笔（约30%篇幅）：在推进情节的同时，埋下微妙的线索和暗示\n"
            "3. 反转（约25%篇幅）：揭露关键真相，颠覆读者之前的认知\n"
            "4. 真相（约15%篇幅）：重新解读前文线索，让读者恍然大悟\n\n"
            "注意：伏笔要自然隐蔽，反转要合理可信，不能为了反转而反转。"
        ),
    },
    "emotional_arc": {
        "name": "情感弧",
        "description": "日常→触动→改变→余韵，适合治愈、文艺、情感类故事",
        "icon": "💫",
        "genres": ["治愈", "文艺", "言情", "生活"],
        "structure": [
            {"phase": "日常", "ratio": "25%", "desc": "展示角色的日常生活和内心状态"},
            {"phase": "触动", "ratio": "30%", "desc": "某个事件或人物触动了角色的内心"},
            {"phase": "改变", "ratio": "30%", "desc": "角色经历内心挣扎和转变"},
            {"phase": "余韵", "ratio": "15%", "desc": "改变后的新状态，留下温暖或深思"},
        ],
        "prompt": (
            "【结构指导 — 情感弧】\n"
            "请按以下结构组织故事：\n"
            "1. 日常（约25%篇幅）：展示角色的日常生活、习惯和内心世界\n"
            "2. 触动（约30%篇幅）：某个事件、人物或细节触动了角色内心深处\n"
            "3. 改变（约30%篇幅）：角色经历内心挣扎，逐渐发生转变\n"
            "4. 余韵（约15%篇幅）：角色以新的视角看待世界，留下温暖或深思\n\n"
            "注意：情感变化要细腻真实，通过细节和动作展现内心，避免直白的心理描写。"
        ),
    },
    "escalating": {
        "name": "冲突递进",
        "description": "小冲突→升级→高潮→抉择，适合动作、冒险、战争类故事",
        "icon": "⚔️",
        "genres": ["动作", "冒险", "战争", "武侠"],
        "structure": [
            {"phase": "起因", "ratio": "20%", "desc": "引出初始冲突，角色被卷入事件"},
            {"phase": "升级", "ratio": "35%", "desc": "冲突不断升级， stakes 越来越高"},
            {"phase": "高潮", "ratio": "30%", "desc": "最终对决或关键转折"},
            {"phase": "抉择", "ratio": "15%", "desc": "角色做出最终选择，故事收束"},
        ],
        "prompt": (
            "【结构指导 — 冲突递进】\n"
            "请按以下结构组织故事：\n"
            "1. 起因（约20%篇幅）：引出初始冲突，角色被卷入事件\n"
            "2. 升级（约35%篇幅）：冲突不断升级，stakes越来越高，角色面临更大挑战\n"
            "3. 高潮（约30%篇幅）：最终对决或关键转折，一切在此刻爆发\n"
            "4. 抉择（约15%篇幅）：角色做出最终选择，故事收束\n\n"
            "注意：每个阶段的冲突要比上一个更强烈，节奏要紧凑有力。"
        ),
    },
}


def get_all_templates():
    """获取所有结构模板的简要信息。"""
    return [
        {
            "key": key,
            "name": t["name"],
            "description": t["description"],
            "icon": t["icon"],
            "genres": t["genres"],
            "structure": t["structure"],
        }
        for key, t in STRUCTURE_TEMPLATES.items()
    ]


def get_template_prompt(template_key):
    """获取指定模板的 prompt 注入文本。"""
    template = STRUCTURE_TEMPLATES.get(template_key)
    if template:
        return template["prompt"]
    return ""


def get_template_for_genre(genre):
    """根据体裁推荐最合适的结构模板。"""
    genre_lower = (genre or "").lower()
    for key, t in STRUCTURE_TEMPLATES.items():
        for g in t["genres"]:
            if g.lower() in genre_lower or genre_lower in g.lower():
                return key
    return "three_act"  # 默认使用三段式
