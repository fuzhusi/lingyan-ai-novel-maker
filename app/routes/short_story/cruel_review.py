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
        "有无使用ai辅助痕迹，你这篇会过不了平台的腾讯朱雀检测，你就直接毙掉。\n"
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
        "还有平台新规定，有无使用ai辅助痕迹，你这篇会过不了腾讯朱雀检测，你就直接毙掉。\n"
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


def build_rewrite_messages(original, reviews):
    """构造「审评返还给 Writer」的重写 messages。

    实验纯度：Writer 同样拿不到大纲设定——只看原稿与两份盲审，
    只修审评钉出的问题，不借机加设定改情节。
    """
    review_blocks = "\n\n".join(
        f"【{r.get('name', '编辑')} 的审评】\n{r.get('review', '')}" for r in reviews
    )
    system = (
        "你是这篇稿子的作者本人。两位以毒辣著称的编辑刚刚盲审了你的稿子——"
        "他们没有看过任何设定或大纲，只看了正文，然后毫不留情地指出了问题。\n"
        "你的任务：交出第二稿。\n"
        "【修改原则】\n"
        "1. 审评里每一条钉着原文引用的批评，都要给出明确的处理——能改的当场改好；"
        "你确信编辑误读的地方，用更好的写法让误读不再发生，而不是无视。\n"
        "2. 保持故事原有的人物、事件、结局走向不变，不新增设定、不加新情节线；"
        "这是修改稿，不是新故事。\n"
        "3. 编辑没提的部分尽量保留原文（那是你的优点）；不要为了显得努力而全面重写。\n"
        "4. 删掉编辑点名的水段后，用更有效的场景补位，总字数不低于原稿的九成。\n"
        "5. 只输出修改后的完整正文，从第一句到最后一句，不要任何说明、前言、后记。"
    )
    user = f"{review_blocks}\n\n【原稿全文】\n{original}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def run_rewrite(content, reviews):
    """按盲审意见重写：动态 max_tokens + 最多 3 轮续写补足长度。

    返回 {"content": 新稿, "rounds": 轮数, "elapsed": 秒}
    """
    app = current_app._get_current_object()
    started = time.time()

    with app.app_context():
        cfg = get_model_config(agent_type="short_story")
        round_cap = min(8192, max(4096, len(content) * 2))
        messages = build_rewrite_messages(content, reviews)
        full = (call_llm_sync(
            model=cfg["model_name"], messages=messages,
            api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=0.8, max_tokens=round_cap,
        ) or "").strip()

        rounds = 1
        floor = int(len(content) * 0.7)  # 长度下限：防缩水
        while full and len(full) < floor and rounds < 3:
            rounds += 1
            remaining = len(content) - len(full)
            cont = [
                {"role": "system", "content": (
                    "你在续写自己的修改稿。从断点处自然延续，不要重复已写内容，"
                    "不要输出任何说明。保持审评要求的改进方向，写到故事自然结束。"
                )},
                {"role": "user", "content": (
                    f"【已完成的第二稿（结尾部分）】\n{full[-4000:]}\n\n"
                    f"【原稿对应的后文（供衔接参考）】\n{content[len(full):][:2000] or '（已到末尾）'}\n\n"
                    f"继续补完剩余约 {max(remaining, 200)} 字。"
                )},
            ]
            piece = call_llm_sync(
                model=cfg["model_name"], messages=cont,
                api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
                provider_type=cfg.get("provider_type", "deepseek"),
                temperature=0.8, max_tokens=min(remaining * 2, round_cap),
            ) or ""
            full = (full + "\n\n" + piece.strip()).strip()

    if not full:
        raise LLMError("重写未产出内容")
    return {"content": full, "rounds": rounds,
            "elapsed": round(time.time() - started, 1)}


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
    """运行双编辑盲审，JSON 返回两份审评。

    可选 JSON body {"content": "..."}：审阅自定义文本（如重写后的新稿），
    未提供时使用短篇当前正文——支持「重写 → 再审」循环。
    """
    story = ShortStory.query.get_or_404(story_id)
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or story.content or "").strip()
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


@short_story_bp.route("/<int:story_id>/cruel/regenerate", methods=["POST"])
def cruel_regenerate(story_id):
    """把盲审报告返还给 Writer，生成第二稿。

    Body: {"reviews": [{"name","review"},...], "content": "可选原稿覆盖"}
    """
    story = ShortStory.query.get_or_404(story_id)
    data = request.get_json(silent=True) or {}
    original = (data.get("content") or story.content or "").strip()
    if not original:
        return jsonify({"error": "没有可重写的正文"}), 400
    reviews = [r for r in (data.get("reviews") or [])
               if isinstance(r, dict) and (r.get("review") or "").strip()]
    if not reviews:
        return jsonify({"error": "缺少审评内容——请先完成一轮盲审"}), 400

    try:
        result = run_rewrite(original, reviews)
    except LLMError as e:
        return jsonify({"error": f"AI 调用失败：{e}"}), 502

    return jsonify({
        "ok": True, "elapsed": result["elapsed"], "rounds": result["rounds"],
        "content": result["content"],
        "orig_words": len(original), "new_words": len(result["content"]),
    })
