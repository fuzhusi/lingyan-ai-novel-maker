"""Skill System — modular, pluggable writing techniques.

Inspired by InkOS's skill system and show-me-the-story's writing techniques.

Skills are reusable prompt fragments that can be:
- Built-in (chapter hooks, pacing, rhythm control)
- User-created (custom writing techniques)
- Applied per-chapter or globally

Each skill contains:
- Name and description
- A prompt fragment to inject into the writer system prompt
- Optional constraints (similar to writing constraints)
"""
import json
from flask import Blueprint, render_template, request, jsonify
from app.models import db, Setting

skill_bp = Blueprint("skills", __name__, url_prefix="/api")

# Built-in skills
BUILTIN_SKILLS = {
    "chapter_hook": {
        "name": "章节钩子",
        "description": "在章节开头制造悬念，吸引读者继续阅读",
        "prompt": """章节开头技巧：
- 以一个悬念问题开头（"他没想到，这竟然是最后一次见面"）
- 以一个动作场景开头（直接进入冲突）
- 以一个感官细节开头（"空气中弥漫着焦糊的味道"）
- 避免以"阳光透过窗户"等陈词滥调开头""",
        "constraints": "",
    },
    "pacing_control": {
        "name": "节奏控制",
        "description": "控制叙事节奏，张弛有度",
        "prompt": """节奏控制技巧：
- 高潮场景：短句为主，每句不超过15字，段落不超过3句
- 过渡场景：可以适当放长，加入环境描写
- 对话场景：对话和动作交替，不要连续超过5句对话
- 每1000字至少有一次节奏变化（快→慢 或 慢→快）""",
        "constraints": "",
    },
    "show_dont_tell": {
        "name": "展示而非讲述",
        "description": "用动作和细节代替直接描述",
        "prompt": """展示而非讲述技巧：
- 不要写"他很紧张"，写"他的手指在桌面上敲了三下"
- 不要写"她很伤心"，写"她把杯子放下时，水洒了一桌"
- 不要写"气氛很尴尬"，写"谁也没说话，只有钟在滴答响"
- 不要写"他很厉害"，写具体的行为让读者自己判断""",
        "constraints": "禁止使用'他很X'、'她很Y'等直接心理描述",
    },
    "dialogue_realism": {
        "name": "对话写实",
        "description": "让对话更自然、更像真人说话",
        "prompt": """对话写实技巧：
- 对话不要加"他沉声道""她轻笑道"等修饰语
- 用动作代替修饰语（"他放下杯子"比"他沉声道"更好）
- 对话要有潜台词，不要让人物直接说出自己的感受
- 每个人物的说话方式应该不同（参考角色设定中的说话风格）
- 避免连续超过3句纯对话，中间插入动作或环境""",
        "constraints": "禁止使用'X声道'、'X笑道'、'X怒道'等对话修饰语",
    },
    "sensory_detail": {
        "name": "感官细节",
        "description": "加入具体的感官描写，增强画面感",
        "prompt": """感官细节技巧：
- 每500字至少一个具体的感官细节
- 优先使用不常见的感官（触觉、嗅觉、味觉）而不是视觉
- 视觉：避免"阳光""月光"等陈词滥调
- 听觉：具体的声音（"远处传来狗叫"而非"听到声音"）
- 触觉：温度、质感（"指尖碰到冰凉的铁栏杆"）
- 嗅觉：具体的气味（"空气里有股炸葱花的味道"而非"闻到香味"）""",
        "constraints": "",
    },
    "foreshadow_weaving": {
        "name": "伏笔编织",
        "description": "自然地在文中埋设伏笔",
        "prompt": """伏笔编织技巧：
- 伏笔要埋在看似无关紧要的细节中
- 用"三次暗示"法则：同一个伏笔至少暗示3次才回收
- 第一次：读者不会注意
- 第二次：读者会觉得"好像在哪里见过"
- 第三次：回收，读者恍然大悟
- 伏笔不要埋得太明显（"他总觉得那把钥匙不一般"太直白）""",
        "constraints": "",
    },
    "emotion_layering": {
        "name": "情感层次",
        "description": "让人物情感更丰富、更有层次",
        "prompt": """情感层次技巧：
- 人物的情感应该是混合的，不是单一的（"愤怒中带着一丝恐惧"）
- 用环境烘托情感（"雨下得更大了"暗示悲伤）
- 用矛盾行为展示内心冲突（"他笑着说，但手在发抖"）
- 避免情感的直接表达（"他很伤心"→"他把烟掐灭，又点了一根"）""",
        "constraints": "",
    },
    # --- 去 AI 味结构级技巧 ---
    "rhythm_breaking": {
        "name": "句式节奏打散",
        "description": "打破 AI 匀称的句式结构，制造自然的阅读节奏",
        "prompt": """句式节奏打散技巧（去AI味核心）：
- 长短句交替：连续2-3个短句后接一个长句，或反过来，不要每句都差不多长
- 碎片句：偶尔用不完整的句子（"嗯。""算了。""不对。"）打破工整感
- 避免三连排比：AI 最爱写"有的…有的…有的…"，如果写了排比，打散它
- 段落长度不均：有的段落2行，有的段落8行，不要每段都4-5行
- 避免每段开头都是"他/她"或人名，偶尔用代词、用动作、用对话开头
- 对话和叙述的比例不固定：有的地方连续对话，有的地方大段叙述""",
        "constraints": "",
    },
    "sensory_concrete": {
        "name": "感官具象化",
        "description": "用具体的感官细节替代抽象描述，消除 AI 的空洞感",
        "prompt": """感官具象化技巧（去AI味核心）：
- 用动词替代形容词："他疲惫地走着"→"他拖着步子，鞋底蹭着地面"
- 用具体替代抽象："周围很安静"→"能听见墙上时钟的秒针在走"
- 用实物替代概念："桌上很乱"→"桌上摊着三本没合上的书，烟灰缸满了"
- 用身体反应替代心理描写："他很紧张"→"他攥着手机，指节发白"
- 用环境细节替代情感标签："她很难过"→"她盯着碗里的饭，筷子戳了半天没夹起来"
- 一个场景至少有一个"无用"的感官细节（远处的狗叫、空气里的油烟味、脚底硌到的石子）""",
        "constraints": "",
    },
    "imperfection": {
        "name": "留白与不完美",
        "description": "适当留白、跳跃、不解释，模仿真实写作的不完美",
        "prompt": """留白与不完美技巧（去AI味核心）：
- 不必每件事都解释因果：有时候事情就是发生了，不需要"因为…所以…"
- 不必每段都有总结句：AI 爱在段末加一句总结/升华，删掉它
- 避免结尾升华：不要在章节结尾写人生道理、哲学感悟、"他终于明白了…"
- 思维跳跃：人物的思路可以突然拐弯（"他想起来了——不对，现在不是想这个的时候"）
- 省略：有时候"他没说话"比"他沉默了一会儿，然后缓缓开口"更好
- 留白：不把所有情感都说透，让读者自己感受（"她转过身走了。"不加任何修饰）""",
        "constraints": "",
    },
    "dialogue_humanize": {
        "name": "对话人味化",
        "description": "让对话更像真人说话，去除 AI 的书面腔",
        "prompt": """对话人味化技巧（去AI味核心）：
- 加入语气词："嗯""啊""哦""呃""那个…"（不是每句都加，偶尔用）
- 不完整句："算了不——""你别说，还真——"真人说话经常说一半
- 打断和重叠："不是，你听我说——""我听你说了，但——"
- 口癖：给人物设定1-2个口头禅（"说真的""反正""你知道吗"）
- 答非所问：真人对话经常不直接回答问题（"你去不去？""外面下雨了吗？"）
- 废话和寒暄：不要每句对话都推动剧情，偶尔加点"今天真热""吃了吗"
- 避免每句对话都带动作描写：有时直接写对话，不需要每句都加「他说」「她叹了口气说」""",
        "constraints": "",
    },
    "deai_structure": {
        "name": "结构去模板化",
        "description": "打破 AI 的总分总/三段式/逐条罗列结构",
        "prompt": """结构去模板化技巧（去AI味核心）：
- 避免"首先…其次…再次…最后…"结构，这是 AI 最明显的标志
- 避免总分总：不要开头概述、中间展开、结尾总结
- 不要每段都只讲一个点然后总结，让段落之间有交叉和流动
- 加入闲笔：写一段看似和主线无关的内容（路边的猫、收音机里的歌、窗台上的灰）
- 时间线不要完全线性：偶尔插叙、倒叙、或者"那天的事他后来才想起来"
- 场景切换不要用过渡句："与此同时""另一边"→直接切，读者能跟上
- 打破信息密度均匀：有的地方密集推进，有的地方放慢写一个细节""",
        "constraints": "",
    },
}


def get_active_skills():
    """Get list of active skill names."""
    setting = Setting.query.get("active_skills")
    if setting and setting.value:
        try:
            return json.loads(setting.value)
        except json.JSONDecodeError:
            pass
    # 默认激活核心去AI化技能
    return ["rhythm_breaking", "sensory_concrete", "imperfection", "dialogue_humanize", "deai_structure"]


def set_active_skills(skill_names):
    """Set active skills."""
    setting = Setting.query.get("active_skills")
    if setting:
        setting.value = json.dumps(skill_names, ensure_ascii=False)
    else:
        setting = Setting(key="active_skills", value=json.dumps(skill_names, ensure_ascii=False))
        db.session.add(setting)
    db.session.commit()


def get_custom_skills():
    """Get user-created custom skills."""
    setting = Setting.query.get("custom_skills")
    if setting and setting.value:
        try:
            return json.loads(setting.value)
        except json.JSONDecodeError:
            pass
    return {}


def save_custom_skill(name, skill_data):
    """Save a custom skill."""
    skills = get_custom_skills()
    skills[name] = skill_data
    setting = Setting.query.get("custom_skills")
    if setting:
        setting.value = json.dumps(skills, ensure_ascii=False)
    else:
        setting = Setting(key="custom_skills", value=json.dumps(skills, ensure_ascii=False))
        db.session.add(setting)
    db.session.commit()


def delete_custom_skill(name):
    """Delete a custom skill."""
    skills = get_custom_skills()
    if name in skills:
        del skills[name]
        setting = Setting.query.get("custom_skills")
        if setting:
            setting.value = json.dumps(skills, ensure_ascii=False)
            db.session.commit()


def get_all_skills():
    """Get all available skills (built-in + custom)."""
    all_skills = {}
    for key, skill in BUILTIN_SKILLS.items():
        all_skills[key] = {**skill, "builtin": True}
    for key, skill in get_custom_skills().items():
        all_skills[key] = {**skill, "builtin": False}
    return all_skills


def build_skill_prompt():
    """Build the combined skill prompt from active skills."""
    active = get_active_skills()
    all_skills = get_all_skills()

    parts = []
    for skill_name in active:
        skill = all_skills.get(skill_name)
        if skill and skill.get("prompt"):
            parts.append(f"【{skill['name']}技巧】\n{skill['prompt']}")
            if skill.get("constraints"):
                parts.append(f"约束：{skill['constraints']}")

    if not parts:
        return ""

    return "【写作技巧 — 请在写作中运用以下技巧】\n\n" + "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@skill_bp.route("/skills/page")
def skills_page():
    """技能管理页面。"""
    all_skills = get_all_skills()
    active = get_active_skills()
    builtin_skills = []
    custom_skills = []
    for key, skill in all_skills.items():
        item = {
            "key": key,
            "name": skill.get("name", key),
            "description": skill.get("description", ""),
            "prompt": skill.get("prompt", ""),
            "constraints": skill.get("constraints", ""),
            "builtin": skill.get("builtin", True),
            "active": key in active,
        }
        if skill.get("builtin", True):
            builtin_skills.append(item)
        else:
            custom_skills.append(item)
    return render_template("skills.html",
                           builtin_skills=builtin_skills,
                           custom_skills=custom_skills,
                           active_count=len(active))


@skill_bp.route("/skills")
def list_skills():
    """List all available skills."""
    all_skills = get_all_skills()
    active = get_active_skills()
    result = []
    for key, skill in all_skills.items():
        result.append({
            "key": key,
            "name": skill.get("name", key),
            "description": skill.get("description", ""),
            "builtin": skill.get("builtin", True),
            "active": key in active,
        })
    return jsonify(result)


@skill_bp.route("/skills/active", methods=["POST"])
def update_active():
    """Update active skills."""
    data = request.get_json(silent=True) or {}
    skill_names = data.get("skills", [])
    set_active_skills(skill_names)
    return jsonify({"ok": True, "active": skill_names})


@skill_bp.route("/skills/custom", methods=["POST"])
def create_custom():
    """Create a custom skill."""
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400

    skill_data = {
        "name": name,
        "description": data.get("description", ""),
        "prompt": data.get("prompt", ""),
        "constraints": data.get("constraints", ""),
    }
    save_custom_skill(name, skill_data)
    return jsonify({"ok": True})


@skill_bp.route("/skills/custom/<name>", methods=["DELETE"])
def delete_custom(name):
    """Delete a custom skill."""
    delete_custom_skill(name)
    return jsonify({"ok": True})
