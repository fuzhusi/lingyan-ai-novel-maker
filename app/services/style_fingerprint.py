"""Style Fingerprint — extracts and applies writing style from reference text.

Inspired by knowrite's Author Fingerprint and AI-Novel-Writing-Assistant's
Writing Method Engine.

Workflow:
1. User provides a reference text (their favorite author, their own writing, etc.)
2. AI analyzes the text and extracts style features
3. Features are stored as a reusable style profile
4. Style profile is injected into writer prompts
"""
import json
from flask import Blueprint, request, jsonify
from app.models import db, Setting
from app.services.llm import call_llm_sync, stream_llm_tokens, LLMError

style_bp = Blueprint("style", __name__, url_prefix="/api")

STYLE_ANALYSIS_PROMPT = """你是一位文学风格分析专家。分析以下文本的写作风格，提取可量化的特征。

请输出JSON格式：
{
  "sentence_length": "短句为主/中等/长句为主/混合",
  "avg_sentence_len": 15,
  "vocabulary_level": "口语/通俗/文学/古典",
  "narrative_pov": "第一人称/第三人称有限/第三人称全知",
  "tense": "过去时/现在时",
  "dialogue_style": "简洁/详细/含动作描写/纯对话",
  "description_density": "稀疏/适中/密集",
  "rhythm": "快节奏/中等/慢节奏",
  "tone": ["冷峻", "克制", "..."],
  "forbidden_words": ["词1", "词2"],
  "preferred_patterns": ["常用句式1", "常用句式2"],
  "literary_devices": ["比喻", "象征", "..."],
  "paragraph_length": "短段(1-3句)/中段(4-6句)/长段(7+句)/混合",
  "emotional_expression": "直接表达/间接暗示/通过动作展示/通过环境烘托",
  "example_sentences": ["风格代表句1", "风格代表句2", "风格代表句3"]
}

只输出JSON，不要输出其他内容。"""


def analyze_style(text, cfg=None):
    """Analyze a reference text and extract style features."""
    if cfg is None:
        from app.config_utils import get_model_config
        cfg = get_model_config(agent_type="style")

    messages = [
        {"role": "system", "content": STYLE_ANALYSIS_PROMPT},
        {"role": "user", "content": f"【参考文本】\n{text[:3000]}"},
    ]

    try:
        text = call_llm_sync(
            model=cfg["model_name"],
            messages=messages,
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
        )
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            json_lines = [l for l in lines[1:] if not l.startswith("```")]
            text = "\n".join(json_lines)
        return json.loads(text)
    except LLMError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


def save_style(style_data, name="default"):
    """Save a style fingerprint to the database."""
    key = f"style_fingerprint_{name}"
    value = json.dumps(style_data, ensure_ascii=False)
    setting = Setting.query.get(key)
    if setting:
        setting.value = value
    else:
        setting = Setting(key=key, value=value)
        db.session.add(setting)
    db.session.commit()


def load_style(name="default"):
    """Load a style fingerprint from the database."""
    key = f"style_fingerprint_{name}"
    setting = Setting.query.get(key)
    if setting and setting.value:
        try:
            return json.loads(setting.value)
        except json.JSONDecodeError:
            pass
    return None


def format_style_for_prompt(style_data):
    """Format style fingerprint into a prompt injection string."""
    if not style_data or style_data.get("error"):
        return ""

    parts = []

    if style_data.get("sentence_length"):
        parts.append(f"句式：{style_data['sentence_length']}（平均{style_data.get('avg_sentence_len', '?')}字）")
    if style_data.get("vocabulary_level"):
        parts.append(f"用词：{style_data['vocabulary_level']}")
    if style_data.get("narrative_pov"):
        parts.append(f"视角：{style_data['narrative_pov']}")
    if style_data.get("dialogue_style"):
        parts.append(f"对话：{style_data['dialogue_style']}")
    if style_data.get("description_density"):
        parts.append(f"描写密度：{style_data['description_density']}")
    if style_data.get("rhythm"):
        parts.append(f"节奏：{style_data['rhythm']}")
    if style_data.get("tone"):
        tone = style_data["tone"]
        if isinstance(tone, list):
            parts.append(f"基调：{'、'.join(tone)}")
    if style_data.get("paragraph_length"):
        parts.append(f"段落：{style_data['paragraph_length']}")
    if style_data.get("emotional_expression"):
        parts.append(f"情感表达：{style_data['emotional_expression']}")

    if style_data.get("forbidden_words"):
        words = style_data["forbidden_words"]
        if isinstance(words, list) and words:
            parts.append(f"禁止用词：{'、'.join(words[:10])}")

    if style_data.get("preferred_patterns"):
        patterns = style_data["preferred_patterns"]
        if isinstance(patterns, list) and patterns:
            parts.append(f"常用句式：{'、'.join(patterns[:5])}")

    if style_data.get("literary_devices"):
        devices = style_data["literary_devices"]
        if isinstance(devices, list) and devices:
            parts.append(f"修辞手法：{'、'.join(devices[:5])}")

    if style_data.get("example_sentences"):
        examples = style_data["example_sentences"]
        if isinstance(examples, list) and examples:
            parts.append("风格示例：")
            for ex in examples[:3]:
                parts.append(f"  「{ex}」")

    if not parts:
        return ""

    return "【写作风格要求】\n" + "\n".join(parts)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@style_bp.route("/style/analyze", methods=["POST"])
def api_analyze_style():
    """Analyze reference text and extract style features."""
    text = request.form.get("text", "")
    if not text:
        return jsonify({"error": "text required"}), 400

    result = analyze_style(text)
    return jsonify(result)


@style_bp.route("/style/save", methods=["POST"])
def api_save_style():
    """Save a style fingerprint."""
    data = request.get_json(silent=True) or {}
    name = data.get("name", "default")
    style_data = data.get("style", {})
    save_style(style_data, name)
    return jsonify({"ok": True})


@style_bp.route("/style/load")
def api_load_style():
    """Load the current style fingerprint."""
    name = request.args.get("name", "default")
    style = load_style(name)
    if style:
        return jsonify(style)
    return jsonify(None)


@style_bp.route("/style/list")
def api_list_styles():
    """List all saved style fingerprints."""
    styles = Setting.query.filter(Setting.key.like("style_fingerprint_%")).all()
    return jsonify([{
        "name": s.key.replace("style_fingerprint_", ""),
        "preview": (s.value or "")[:100],
    } for s in styles])


# ---------------------------------------------------------------------------
# 文风锚例（anchor）—— 原文直插 prompt，保留 token 级节奏质感
# ---------------------------------------------------------------------------

_ANCHOR_INSTRUCTION = (
    "模仿以下片段的叙事质感、句式节奏、用词习惯来写作。"
    "只学习文风，严禁复述或抄袭片段中的具体情节、人物、名词。"
    "不要在正文中提及这个片段，把它当作你自己的写作风格即可。"
)

_ANCHOR_MAX_CHARS = 2000  # 约 1000-1500 中文字 + 指令，防 prompt 膨胀


def save_anchor(text):
    """保存文风锚例原文到数据库。"""
    setting = Setting.query.get("style_anchor_text")
    if setting:
        setting.value = text
    else:
        setting = Setting(key="style_anchor_text", value=text)
        db.session.add(setting)
    db.session.commit()


def load_anchor():
    """加载文风锚例原文，不存在时返回空串。"""
    setting = Setting.query.get("style_anchor_text")
    if setting and setting.value:
        return setting.value.strip()
    return ""


def anchor_enabled():
    """锚例是否启用。"""
    setting = Setting.query.get("style_anchor_enabled")
    return setting is not None and str(setting.value).strip() == "1"


def set_anchor_enabled(flag):
    """设置锚例开关。"""
    setting = Setting.query.get("style_anchor_enabled")
    if setting:
        setting.value = "1" if flag else "0"
    else:
        setting = Setting(key="style_anchor_enabled", value="1" if flag else "0")
        db.session.add(setting)
    db.session.commit()


def format_anchor_for_prompt():
    """返回可直接注入 prompt 的文风锚例块（含指令+原文），无内容时返回空串。"""
    if not anchor_enabled():
        return ""
    text = load_anchor()
    if not text or len(text) < 50:
        return ""
    # 截断防 prompt 膨胀；按段落边界截断，不要切到半句话
    if len(text) > _ANCHOR_MAX_CHARS:
        cut = text[:_ANCHOR_MAX_CHARS]
        last_para = cut.rfind("\n\n")
        if last_para > _ANCHOR_MAX_CHARS // 2:
            cut = cut[:last_para]
        text = cut + "\n……（节选）"
    return f"【文风锚例 — 模仿此风格续写，勿抄情节】\n{_ANCHOR_INSTRUCTION}\n\n{text}"


@style_bp.route("/style-anchor", methods=["GET"])
def api_get_anchor():
    """获取当前文风锚例内容与启用状态。"""
    return jsonify({
        "text": load_anchor(),
        "enabled": anchor_enabled(),
    })


@style_bp.route("/style-anchor", methods=["POST"])
def api_save_anchor():
    """保存文风锚例文本（纯文本，JSON body）。"""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    save_anchor(text)
    return jsonify({"ok": True, "len": len(text)})


@style_bp.route("/style-anchor/toggle", methods=["POST"])
def api_toggle_anchor():
    """开关文风锚例（JSON body: {"enabled": true/false}）。"""
    data = request.get_json(silent=True) or {}
    flag = bool(data.get("enabled"))
    set_anchor_enabled(flag)
    return jsonify({"ok": True, "enabled": flag})
