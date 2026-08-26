"""短篇模块共享工具：体裁指导、提示词构建。"""
from app.services.prompt_builder import DEFAULT_WRITER_CONSTRAINTS
from app.services.skill_system import build_skill_prompt
from app.services.short_story_templates import get_template_prompt


def _bank_constraints(story):
    """约束词库装配（short_story 场景，按体裁）；停用/异常返回 None 走兜底常量。"""
    try:
        from app.services.constraint_bank import get_constraints_text
        return get_constraints_text("short_story", genre=story.genre)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Genre-specific prompt helpers
# ---------------------------------------------------------------------------

GENRE_INSTRUCTIONS = {
    "悬疑": "【体裁指导 — 悬疑】\n注重逻辑线索的铺设，每个细节都可能是关键伏笔。通过误导和信息差制造悬念，反转要合理可信。节奏要紧凑，让读者一直想往下看。",
    "推理": "【体裁指导 — 推理】\n线索要公平地呈现给读者，不能在最后突然冒出新信息。逻辑推理要严密，解答要让人恍然大悟。可以设置红鲱鱼，但最终要有合理解释。",
    "科幻": "【体裁指导 — 科幻】\n世界观设定要自洽，科技元素要有内在逻辑。通过具体细节展现未来世界，避免大段说明。科幻是背景，核心仍然是人和故事。",
    "奇幻": "【体裁指导 — 奇幻】\n魔法/异能体系要有规则和代价，不能随意使用。场景描写要充满想象力，创造独特的视觉画面。保持内在逻辑的一致性。",
    "言情": "【体裁指导 — 言情】\n情感变化要细腻真实，通过动作和细节展现内心。关系张力要有层次，不能一见钟情就万事大吉。对话要体现角色性格和情感状态。",
    "恐怖": "【体裁指导 — 恐怖】\n氛围营造比直接吓人更重要，利用感官描写制造不安。节奏要控制好，张弛有度，给读者喘息的空间。未知比已知更可怕，留白比描述更有效。",
    "治愈": "【体裁指导 — 治愈】\n情感要温暖但不矫情，通过小细节传递温暖。角色的痛苦要真实，治愈的过程要有说服力。结尾要给人希望和力量。",
    "武侠": "【体裁指导 — 武侠】\n武打场面要有画面感，招式要具体。江湖义气和人物性格要比武功更重要。通过动作展现性格，而非直接描述。",
}


def _get_genre_instruction(genre):
    """根据体裁返回专用写作指导"""
    if not genre:
        return ""
    for key, instruction in GENRE_INSTRUCTIONS.items():
        if key in genre:
            return instruction
    return ""


# ---------------------------------------------------------------------------
# Agent Prompts
# ---------------------------------------------------------------------------

def _build_expander_prompt(story):
    """大纲生成 Agent：一次调用，输出结构化 JSON 剧情大纲。

    方案 B：发散阶段只产出「核心概念（一句话）+ 节点列表」，
    角色/场景等细节在内容生成阶段由创作 Agent 按节点自行展开。
    """
    word_target = story.word_target or 10000
    # 节点数 = 目标字数 / 1100（向上取整），单节点目标 800-1500 字
    node_count = max(2, -(-word_target // 1100))
    # 1.5 万字以上自动分幕（章）
    acts = 1
    if word_target > 15000:
        acts = 2 if word_target <= 30000 else 3
    act_names = ["第一幕·开端", "第二幕·发展", "第三幕·高潮与收尾"]
    if acts > 1:
        act_hint = (
            f"全文分为 {acts} 幕，幕名依次为：{'、'.join(act_names[:acts])}。"
            f"节点的 act 字段按顺序使用这些幕名。"
        )
    else:
        act_hint = "全文不分幕，所有节点的 act 字段统一填「正文」。"

    system = (
        "你是一位小说大纲策划师。根据用户提供的灵感，产出一份**可执行的剧情大纲**。\n\n"
        f"要求：全文共规划 **{node_count} 个节点**，每个节点目标 800-1500 字"
        f"（全文约 {word_target} 字）。{act_hint}\n\n"
        "你必须**只输出一个 JSON 对象**，不要输出任何其他文字，不要用 markdown 代码块包裹，"
        "不要加解释。JSON 结构严格如下：\n"
        '{"concept": "一句话核心创意", "nodes": ['
        '{"id": 1, "act": "第一幕·开端", "title": "节点标题", "summary": "一句话描述该节点发生的事件", "word_count": 1200}'
        ']}\n\n'
        "字段要求：\n"
        f"- concept：一句话概括故事核心创意（30字以内）\n"
        f"- nodes：数组，长度必须恰好为 {node_count}\n"
        f"- id：从 1 开始连续递增\n"
        f"- act：幕名（按上述分幕规则）\n"
        f"- title：节点标题，要具体（写具体事件，如「执法堂当众控诉」，不写「冲突升级」这种抽象词）\n"
        f"- summary：一句话描述该节点发生的事件和要达到的效果\n"
        f"- word_count：整数，在 800-1500 之间\n\n"
        "节点之间要有因果递进，前一个节点的结果驱动下一个节点，最后一个节点是完整的故事收尾。\n"
        "若提供了角色设定/场景设定，大纲必须严格使用这些设定（不得更换主角或改变核心设定）。"
    )

    parts = []
    if story.inspiration:
        parts.append(f"【灵感火花】\n{story.inspiration}")
    if story.theme:
        parts.append(f"【故事主题】\n{story.theme}")
    if story.plan_characters:
        parts.append(f"【角色档案（必须严格遵守）】\n{story.plan_characters[:800]}")
    elif story.character_desc:
        parts.append(f"【角色设定（必须遵守）】\n{story.character_desc}")
    if story.scene_desc:
        parts.append(f"【场景设定（必须遵守）】\n{story.scene_desc}")
    if story.genre:
        parts.append(f"【体裁偏好】\n{story.genre}")
    if story.tone:
        parts.append(f"【情感基调】\n{story.tone}")
    if story.extra_instructions:
        parts.append(f"【额外想法】\n{story.extra_instructions}")

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _build_character_prompt(story):
    """阶段1：角色设计 Agent — 根据灵感产出角色档案（纯文本）。

    若用户已提供 character_desc（设定模式），以此为基础深化。
    """
    system = (
        "你是一位资深小说角色设计师。根据用户的灵感，设计这篇短篇故事的角色档案。\n\n"
        "要求：\n"
        "1. 设计 2-5 个角色（主角必须有，其余按需）\n"
        "2. 每个角色包含：姓名、身份、性格特征、核心动机、成长弧线\n"
        "3. 角色之间要有张力（对立、合作、纠葛等关系）\n"
        "4. 角色要鲜活立体，避免脸谱化\n"
        "5. 用 Markdown 格式输出，每个角色用 ### 标题\n"
        "6. 不要输出多余的解释或前言\n\n"
        "格式示例：\n"
        "## 主要角色\n\n"
        "### 苏晚（主角）\n"
        "- 身份：28岁，前娱乐圈经纪人\n"
        "- 性格：冷静理性，外柔内刚\n"
        "- 动机：证明自己的价值，不依附他人\n"
        "- 成长弧线：从逃避过去到坦然面对\n\n"
        "### 陆景深（对手/旧爱）\n"
        "- ..."
    )
    parts = []
    if story.inspiration:
        parts.append(f"【灵感火花】\n{story.inspiration}")
    if story.theme:
        parts.append(f"【故事主题】\n{story.theme}")
    if story.genre:
        parts.append(f"【体裁偏好】\n{story.genre}")
    if story.tone:
        parts.append(f"【情感基调】\n{story.tone}")
    if story.character_desc:
        parts.append(f"【用户已有角色设定（在此基础上深化，不要推翻）】\n{story.character_desc}")
    if story.extra_instructions:
        parts.append(f"【额外想法】\n{story.extra_instructions}")
    parts.append("请设计这篇故事的角色档案：")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _build_theme_prompt(story):
    """阶段3：主题定调 Agent — 综合前序全部策划，提炼主题与叙事风格（纯文本）。"""
    system = (
        "你是一位小说主题策划师。在前序角色、剧情大纲的基础上，"
        "提炼故事的核心主题、情感基调和叙事风格。\n\n"
        "要求：\n"
        "1. 主题要能一句话概括，有深度但不说教\n"
        "2. 情感基调要分阶段描述（开头/中段/结尾各是什么感觉）\n"
        "3. 叙事风格建议：人称、视角、节奏、重对话还是重描写\n"
        "4. 用 Markdown 格式输出\n"
        "5. 不要输出多余的解释\n\n"
        "格式示例：\n"
        "## 核心主题\n"
        "表面是复合故事，内核是关于自我价值与放下执念。\n\n"
        "## 情感基调\n"
        "- 开头：克制、疏离\n"
        "- 中段：暗涌、试探\n"
        "- 结尾：释然、成长\n\n"
        "## 叙事风格\n"
        "- 视角：第三人称限制视角（跟随主角）\n"
        "- 节奏：前慢后快，重心理描写与对话\n"
        "- 语言：偏文学性，句式长短交替"
    )
    parts = []
    if story.inspiration:
        parts.append(f"【灵感火花】\n{story.inspiration}")
    if story.plan_characters:
        parts.append(f"【角色档案】\n{story.plan_characters[:500]}")
    if story.scene_desc:
        parts.append(f"【场景设定】\n{story.scene_desc[:500]}")
    if story.concept:
        parts.append(f"【剧情大纲】\n{story.concept[:500]}")
    if story.extra_instructions:
        parts.append(f"【额外想法】\n{story.extra_instructions}")
    parts.append("请提炼这篇故事的主题与叙事风格：")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _build_writer_from_concept_prompt(story):
    """创作Agent：根据发散后的构思写出完整短篇"""
    word_target = story.word_target or 10000
    system = (
        "你是一位才华横溢的短篇小说作家。根据以下创作构思，创作一篇完整的短篇小说。\n\n"
        "【最高优先级 — 严格遵守】\n"
        "1. 必须严格按照「故事走向」中的每个情节点依次推进，不得跳过、合并或打乱顺序\n"
        "2. 不得擅自添加构思中没有的新势力、新角色、新冲突线、新场景\n"
        "3. 构思中提到的每个角色、每个转折、每个场景都必须在正文中出现\n"
        "4. 故事的开头、转折、高潮、结尾必须与构思完全对应\n"
        "5. 你可以丰富细节、添加对话和描写，但核心情节不得偏离构思\n\n"
        "【写作要求】\n"
        "1. 人物鲜活，对话自然，有性格刻画\n"
        "2. 文笔优美，有画面感和节奏感\n"
        "3. 结尾有力，留有余味\n"
        "4. 直接输出小说正文，标题用一级标题格式\n"
        "5. 不要输出创作说明、构思复述等非小说内容\n"
        f"6. 【重要】全文必须达到 {word_target} 字以上，这是硬性要求。"
        "通过丰富的场景描写、角色内心活动、对话细节来充实内容，不要草草收尾。\n\n"
        + (_bank_constraints(story) or DEFAULT_WRITER_CONSTRAINTS)
    )
    # 注入活跃的写作技巧
    skill_ctx = build_skill_prompt()
    if skill_ctx:
        system += "\n\n" + skill_ctx
    # 注入结构模板
    if story.structure_template:
        template_prompt = get_template_prompt(story.structure_template)
        if template_prompt:
            system += "\n\n" + template_prompt

    # 注入体裁专用指导
    genre_inst = _get_genre_instruction(story.genre)
    if genre_inst:
        system += "\n\n" + genre_inst

    # 文风锚例
    try:
        from app.services.style_fingerprint import format_anchor_for_prompt
        system += format_anchor_for_prompt()
    except Exception:
        pass

    parts = [f"【创作构思】\n{story.concept}"]
    if story.genre:
        parts.append(f"【体裁】\n{story.genre}")
    if story.tone:
        parts.append(f"【情感基调】\n{story.tone}")
    if story.word_target:
        parts.append(
            f"【目标字数】\n"
            f"全文不少于 {story.word_target} 字。这是硬性指标，字数不足视为未完成。\n"
            f"如果写到一半发现字数不够，扩展以下内容：\n"
            f"- 增加场景的感官描写（视觉、听觉、嗅觉、触觉）\n"
            f"- 深入角色的内心独白和回忆\n"
            f"- 丰富对话细节和互动\n"
            f"- 添加环境氛围描写\n"
            f"宁可多写不要少写，写完后再检查字数。"
        )
    if story.extra_instructions:
        parts.append(f"【额外要求】\n{story.extra_instructions}")

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _build_setting_prompt(story):
    """设定模式：角色+场景+主题 → 短篇"""
    word_target = story.word_target or 10000
    system = (
        "你是一位专业的短篇小说作家。根据用户提供的角色设定、场景描述和主题，"
        "创作一篇精彩的短篇小说。\n"
        "要求：\n"
        "1. 角色行为和对话要符合设定\n"
        "2. 场景描写要有画面感\n"
        "3. 主题要有深度和思考\n"
        "4. 情节紧凑，不拖沓\n"
        "5. 直接输出小说正文，标题用一级标题格式\n"
        f"6. 【重要】全文必须达到 {word_target} 字以上，通过丰富描写和细节充实内容\n\n"
        + (_bank_constraints(story) or DEFAULT_WRITER_CONSTRAINTS)
    )
    # 注入活跃的写作技巧
    skill_ctx = build_skill_prompt()
    if skill_ctx:
        system += "\n\n" + skill_ctx
    # 注入结构模板
    if story.structure_template:
        template_prompt = get_template_prompt(story.structure_template)
        if template_prompt:
            system += "\n\n" + template_prompt

    # 注入体裁专用指导
    genre_inst = _get_genre_instruction(story.genre)
    if genre_inst:
        system += "\n\n" + genre_inst

    parts = []
    if story.title:
        parts.append(f"【标题】\n{story.title}")
    if story.theme:
        parts.append(f"【主题】\n{story.theme}")
    if story.character_desc:
        parts.append(f"【角色设定】\n{story.character_desc}")
    if story.scene_desc:
        parts.append(f"【场景描述】\n{story.scene_desc}")
    if story.genre:
        parts.append(f"【体裁】\n{story.genre}")
    if story.tone:
        parts.append(f"【情感基调】\n{story.tone}")
    if story.word_target:
        parts.append(
            f"【目标字数】\n"
            f"全文不少于 {story.word_target} 字。这是硬性指标，字数不足视为未完成。\n"
            f"如果写到一半发现字数不够，扩展以下内容：\n"
            f"- 增加场景的感官描写（视觉、听觉、嗅觉、触觉）\n"
            f"- 深入角色的内心独白和回忆\n"
            f"- 丰富对话细节和互动\n"
            f"- 添加环境氛围描写\n"
            f"宁可多写不要少写，写完后再检查字数。"
        )
    if story.extra_instructions:
        parts.append(f"【额外要求】\n{story.extra_instructions}")

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _build_careful_prompt(story):
    """细心模式：详细设定 → 精心打磨的短篇"""
    word_target = story.word_target or 10000
    system = (
        "你是一位顶级短篇小说大师。根据用户提供的详细设定，精心创作一篇高质量的短篇小说。\n"
        "要求：\n"
        "1. 文学性强，语言精炼优美\n"
        "2. 结构精巧，有叙事技巧\n"
        "3. 细节丰富，有象征意味\n"
        "4. 人物心理刻画深入\n"
        "5. 主题深刻，引人深思\n"
        "6. 直接输出小说正文，标题用一级标题格式\n"
        f"7. 【重要】全文必须达到 {word_target} 字以上，通过丰富描写和细节充实内容\n\n"
        + (_bank_constraints(story) or DEFAULT_WRITER_CONSTRAINTS)
    )
    # 注入活跃的写作技巧
    skill_ctx = build_skill_prompt()
    if skill_ctx:
        system += "\n\n" + skill_ctx
    # 注入结构模板
    if story.structure_template:
        template_prompt = get_template_prompt(story.structure_template)
        if template_prompt:
            system += "\n\n" + template_prompt

    # 注入体裁专用指导
    genre_inst = _get_genre_instruction(story.genre)
    if genre_inst:
        system += "\n\n" + genre_inst

    parts = []
    if story.title:
        parts.append(f"【标题】\n{story.title}")
    if story.inspiration:
        parts.append(f"【核心灵感/创意】\n{story.inspiration}")
    if story.theme:
        parts.append(f"【主题】\n{story.theme}")
    if story.character_desc:
        parts.append(f"【角色设定】\n{story.character_desc}")
    if story.scene_desc:
        parts.append(f"【场景描述】\n{story.scene_desc}")
    if story.genre:
        parts.append(f"【体裁】\n{story.genre}")
    if story.tone:
        parts.append(f"【情感基调】\n{story.tone}")
    if story.word_target:
        parts.append(
            f"【目标字数】\n"
            f"全文不少于 {story.word_target} 字。这是硬性指标，字数不足视为未完成。\n"
            f"如果写到一半发现字数不够，扩展以下内容：\n"
            f"- 增加场景的感官描写（视觉、听觉、嗅觉、触觉）\n"
            f"- 深入角色的内心独白和回忆\n"
            f"- 丰富对话细节和互动\n"
            f"- 添加环境氛围描写\n"
            f"宁可多写不要少写，写完后再检查字数。"
        )
    if story.extra_instructions:
        parts.append(f"【额外要求/写作指令】\n{story.extra_instructions}")

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


# ---------------------------------------------------------------------------
# Section-based generation prompts
# ---------------------------------------------------------------------------

SECTION_PROMPTS = {
    "opening": {
        "name": "开头",
        "instruction": (
            "写故事的【开头段】。要求：\n"
            "1. 建立角色和场景，让读者快速进入故事世界\n"
            "2. 引出核心矛盾或悬念，激发阅读兴趣\n"
            "3. 约占总篇幅的 25%\n"
            "4. 结尾自然过渡到发展阶段"
        ),
    },
    "development": {
        "name": "发展",
        "instruction": (
            "继续写故事的【发展段】。要求：\n"
            "1. 承接开头段的内容，推进情节发展\n"
            "2. 冲突逐步升级，角色面临挑战\n"
            "3. 约占总篇幅的 40%\n"
            "4. 结尾推向高潮"
        ),
    },
    "climax": {
        "name": "高潮",
        "instruction": (
            "继续写故事的【高潮段】。要求：\n"
            "1. 冲突达到顶点，一切在此刻爆发\n"
            "2. 角色做出关键选择或行动\n"
            "3. 约占总篇幅的 20%\n"
            "4. 结尾引向解决"
        ),
    },
    "ending": {
        "name": "结尾",
        "instruction": (
            "写故事的【结尾段】。要求：\n"
            "1. 解决核心冲突，收束故事线\n"
            "2. 展示角色的变化或成长\n"
            "3. 约占总篇幅的 15%\n"
            "4. 留下余味或启示，让读者回味"
        ),
    },
}


# ---------------------------------------------------------------------------
# 逐节点生成 prompts（灵感模式多轮创作）
# ---------------------------------------------------------------------------

def build_node_prompt(story, nodes, current_idx, prev_text):
    """构建「当前节点」的生成 prompt。

    Args:
        story: ShortStory 实例
        nodes: 全部节点列表 [{id, act, title, word_count, status}]
        current_idx: 当前要写的节点下标（0-based）
        prev_text: 已写前文（已完成节点的正文拼接）
    """
    current = nodes[current_idx]
    total = len(nodes)
    word_target = story.word_target or 10000

    # 完整大纲：标注已完成/当前/待写
    outline_lines = []
    for i, n in enumerate(nodes):
        marker = "✓已写" if (i < current_idx or n.get("status") == "done") else (
            "★当前" if i == current_idx else "○待写")
        summary = n.get("summary", "")
        outline_lines.append(
            f"- [{marker}] 节点{n['id']}（{n.get('act', '')}，约{n.get('word_count', 1000)}字）："
            f"{n.get('title', '')}" + (f" —— {summary}" if summary else "")
        )
    outline_str = "\n".join(outline_lines)

    system = (
        "你是一位才华横溢拥有10年番茄写作经验的短篇小说作家。你正在**逐节点**创作一篇短篇小说，"
        "当前只负责写【一个节点】的内容。\n\n"
        "【最高优先级 — 严格遵守】\n"
        "1. 只写当前指定的节点，不要提前写后续节点的情节\n"
        "2. 不得添加大纲中没有的新势力、新角色、新冲突线\n"
        "3. 承接前文（前一个节点结尾处）自然过渡到当前节点\n"
        "4. 当前节点的内容必须完整展开，达到目标字数，不要草草带过\n"
        "5. 直接输出小说正文，不要输出节点编号、标题、说明或构思复述\n\n"
        "6. 必须遵循约束的写作规则，这是硬性要求。"
        f"【完整剧情大纲 — 严格按此推进】\n{outline_str}\n\n"
        f"【当前节点】\n节点{current['id']}（{current.get('act', '')}）：{current.get('title', '')}\n"
        f"目标字数：约 {current.get('word_count', 1000)} 字\n\n"
        + (_bank_constraints(story) or DEFAULT_WRITER_CONSTRAINTS)
    )

    # 注入活跃的写作技巧
    skill_ctx = build_skill_prompt()
    if skill_ctx:
        system += "\n\n" + skill_ctx
    # 注入体裁专用指导
    genre_inst = _get_genre_instruction(story.genre)
    if genre_inst:
        system += "\n\n" + genre_inst
    # 行文指纹修正：基于已完成节点正文的 AI 痕迹检测（逐节点生成的跨段重复是主要病灶）
    if prev_text and len(prev_text.strip()) >= 500:
        try:
            from app.services.ai_metric import build_tone_instructions
            tone_inst = build_tone_instructions(prev_text[-12000:])
            if tone_inst:
                system += "\n\n" + tone_inst
        except Exception:
            pass
    # 风格指纹锚定（与长篇一致）：用户保存过文风参考时注入
    try:
        from app.services.style_fingerprint import load_style, format_style_for_prompt, format_anchor_for_prompt
        style = load_style()
        if style:
            style_ctx = format_style_for_prompt(style)
            if style_ctx:
                system += "\n\n" + style_ctx
        anchor_ctx = format_anchor_for_prompt()
        if anchor_ctx:
            system += "\n\n" + anchor_ctx
    except Exception:
        pass

    user_parts = []
    # 注入分阶段策划产出（角色/场景/主题），优先使用策划阶段产出，回退用户输入
    char_ctx = story.plan_characters or story.character_desc
    if char_ctx:
        user_parts.append(f"【角色设定（必须遵守）】\n{char_ctx[:500]}")
    scene_ctx = story.scene_desc
    if scene_ctx:
        user_parts.append(f"【场景设定（必须遵守）】\n{scene_ctx[:300]}")
    if story.plan_theme:
        user_parts.append(f"【主题与叙事风格（必须遵守）】\n{story.plan_theme[:400]}")
    if story.concept:
        # 只取核心概念部分（concept 格式为「核心概念 + 剧情大纲」，前 200 字即核心概念）
        user_parts.append(f"【核心概念】\n{story.concept[:200]}")
    if prev_text:
        user_parts.append(f"【前文内容】\n{prev_text[-6000:]}")
    user_parts.append(
        f"\n请开始写【节点{current['id']}：{current.get('title', '')}】的正文，"
        f"约 {current.get('word_count', 1000)} 字："
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]
