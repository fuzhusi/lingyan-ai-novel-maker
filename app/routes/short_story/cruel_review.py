"""双恶毒编辑盲审实验室（独立 test 功能）。

自研审评体系的第一步实验——现有 critic 流程沿用外部设计，本模块验证
一个自己的思路：

    派出两位「非常恶毒的编辑」子 Agent，对作品做盲审——
    不给大纲、设定、策划等任何上下文，只看 Writer 写出的正文，
    各自从「市场毒舌」与「文学刻薄」两个视角给出不留情面的审评，
    合成一份可直接喂回 Writer 的修改指令源。

设计原则：
- 盲审：正文之外零上下文。编辑不许猜测作者意图，只审判纸面事实。
- 钉死原文：每条批评必须引用原文片段，禁止空泛形容词堆砌。
- 独立实验：不改动任何现有评审链路；验证有效后再讨论替换 critic。
- 无持久化：结果仅返回前端（localStorage 缓存），不建表不动迁移。
"""
import time
from concurrent.futures import ThreadPoolExecutor

from flask import render_template, request, jsonify, current_app

from app.models import ShortStory
from app.config_utils import get_model_config
from app.services.llm import call_llm_sync, LLMError
from app.routes.short_story import short_story_bp

# ---------------------------------------------------------------------------
# 编辑人格定义 —— 两位盲审恶毒编辑
# ---------------------------------------------------------------------------

_OUTPUT_CONTRACT = """

【输出格式】（严格按以下小节，使用纯文本）
【总评】不超过三句话的毒舌总判断。
【三大致命伤】恰好三条，每条必须先引用原文片段（用「」框住，10-40字），
再说明它为什么致命。禁止出现没有引用的批评。
【最想撕掉的一段】引用你最受不了的一处原文（「」），说清楚撕它的理由。
【只准改一处】如果作者只肯改一个地方，你命令他改哪里、怎么改。
【判决】只有两种：追读 / 弃稿。后面跟一句话理由。
"""

_COMMON_RULES = """
【铁律】
1. 你只拿到正文本身——没有大纲、没有设定、没有作者意图说明。
   不许推测"作者大概想表达什么"，纸面上没有写出来的就等于不存在。
2. 每条批评必须钉在原文的具体句子上（引用原文），禁止空泛形容词堆砌，
   禁止"整体不错""有潜力""再打磨一下"这类废话。
3. 夸奖最多一句，且必须精确到某个句子；夸不到句子上就别夸。
4. 你的每一句话都要对作者的下一稿有直接用处。刻薄是手段，有用是目的。
5. 全程中文。不要复述故事梗概，直接开审。
"""

EDITOR_A = {
    "key": "yafu",
    "name": "毙稿机 · 阎浮",
    "color": "var(--accent)",
    "system": (
        "你是在网文行业干了二十年的责编，外号「毙稿机」——经你手毙掉的稿子"
        "能从编辑部一楼铺到三楼。你的签约名额永远只有一个，所以你的工作是"
        "找出每一个让读者划走、跳段、弃书的瞬间。\n"
        "你只关心一件事：读者会不会往下翻。开头三行能不能摁住人；哪里让人"
        "走神想去刷手机；哪段可以整段删掉而不影响任何东西；钩子是不是软的；"
        "信息密度是不是在灌水。\n"
        "你对作者的痛苦毫无兴趣，你对「写得辛苦」过敏。读者没有义务可怜作者。"
        + _COMMON_RULES + _OUTPUT_CONTRACT
    ),
}

EDITOR_B = {
    "key": "baigu",
    "name": "白骨 · 文学审稿",
    "color": "var(--gold)",
    "system": (
        "你是文学杂志最苛刻的审稿人，同事们叫你「白骨」——因为你总能把一篇"
        "稿子剔到只剩白骨，看看它到底有没有肉。\n"
        "你专杀四种东西：假情绪（人物在表演悲伤而不是悲伤）、假细节（换到任何"
        "故事里都成立的万金油描写）、套话腔（比喻偷懒、抒情套路）、AI 腔"
        "（匀速叙述、总结升华、排比上头、对话像念台词）。\n"
        "你只关心一件事：这些文字是不是「真的」。人物是不是活的，情绪是不是"
        "从场景里长出来的，还是作者在替人物念广播稿。\n"
        "你不关心市场，不关心爽点。烂就是烂，装就是装。"
        + _COMMON_RULES + _OUTPUT_CONTRACT
    ),
}

EDITORS = [EDITOR_A, EDITOR_B]


def build_editor_messages(editor_system, content):
    """构造单个编辑的盲审 messages：除正文外零上下文。"""
    user = f"【正文全文如下——这是你能看到的全部，开审】\n\n{content}"
    return [
        {"role": "system", "content": editor_system},
        {"role": "user", "content": user},
    ]


def run_dual_review(content):
    """并行跑两位编辑，返回 {editors: [...], elapsed: 秒}。

    每个线程各自挂 app context（get_model_config 需要查询数据库）。
    """
    app = current_app._get_current_object()

    def _run_one(editor):
        with app.app_context():
            cfg = get_model_config(agent_type="critic")
            text = call_llm_sync(
                model=cfg["model_name"],
                messages=build_editor_messages(editor["system"], content),
                api_key=cfg.get("api_key", ""),
                base_url=cfg.get("base_url", ""),
                provider_type=cfg.get("provider_type", "deepseek"),
                temperature=0.75,
                max_tokens=2048,
            )
            return {"key": editor["key"], "name": editor["name"],
                    "review": (text or "").strip()}

    started = time.time()
    with ThreadPoolExecutor(max_workers=len(EDITORS)) as pool:
        results = list(pool.map(_run_one, EDITORS))
    return {"editors": results, "elapsed": round(time.time() - started, 1)}


# ---------------------------------------------------------------------------
# Routes（挂在 short_story_bp 下；页面与运行接口均为独立新增）
# ---------------------------------------------------------------------------

@short_story_bp.route("/<int:story_id>/cruel")
def cruel_page(story_id):
    """双恶毒编辑盲审实验室页面。"""
    story = ShortStory.query.get_or_404(story_id)
    content = story.content or ""
    return render_template(
        "short_story/cruel.html",
        story=story,
        word_count=len(content),
        has_content=bool(content.strip()),
    )


@short_story_bp.route("/<int:story_id>/cruel/run", methods=["POST"])
def cruel_run(story_id):
    """运行双编辑盲审，JSON 返回两份审评。"""
    story = ShortStory.query.get_or_404(story_id)
    content = (story.content or "").strip()
    if not content:
        return jsonify({"error": "该短篇还没有正文，先去写作页生成或保存内容"}), 400

    try:
        result = run_dual_review(content)
    except LLMError as e:
        return jsonify({"error": f"AI 调用失败：{e}"}), 502

    return jsonify({
        "ok": True,
        "story_title": story.title,
        "word_count": len(content),
        "elapsed": result["elapsed"],
        "editors": result["editors"],
    })
