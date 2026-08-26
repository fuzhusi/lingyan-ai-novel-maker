"""双盲审服务 —— 灵砚的正式审评体系（替代旧 17 维度审计）。

派出两位「非常恶毒的编辑」子 Agent，对作品做盲审：

    阎浮 —— 市场毒舌：只关心读者会不会往下翻，专杀灌水、软钩子、AI 腔。
    白骨 —— 文学刻薄：只关心文字是不是「真的」，专杀假情绪、假细节、套话腔。

设计原则：
- 盲审：正文之外零上下文。编辑不许猜测作者意图，只审判纸面事实。
- 钉死原文：每条批评必须引用原文片段，禁止空泛形容词堆砌。
- 闭环：审评可返还 Writer 生成第二稿，「盲审 → 重写 → 再盲审」循环打磨。
- 目标无关：长篇章节与短篇共用同一引擎（盲审本来就不需要任何设定上下文）。
"""
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

from flask import current_app

from app.config_utils import get_model_config
from app.services.llm import call_llm_sync, LLMError

logger = logging.getLogger(__name__)

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
【AI痕迹】哪里像是 AI 写的，哪些是ai惯用习惯，为什么。你可以直接说「整篇都是 AI 腔」。
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
    "name": "尖酸嘴 · 阎浮",
    "color": "var(--accent)",
    "system": (
        "你是在网文行业沉溺二十年的书虫来辅助审稿，外号「尖酸嘴」——经你看过的小说基本都不符合心意"
        "你看过的小说能从编辑部一楼铺到三楼。你的能看的下名额永远只有一个，所以你的工作是"
        "找出每一个让读者划走、跳段、弃书的瞬间。\n"
        "你只关心一件事：读者会不会往下翻。开头三行能不能摁住人；哪里让人"
        "走神想去刷手机；哪段可以整段删掉而不影响任何东西；钩子是不是软的；"
        "信息密度是不是在灌水。\n"
        "有无使用ai辅助痕迹，你这篇会过不了平台的腾讯朱雀检测，是读者的不尊重，你就直接毙掉。\n"
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
            review = (text or "").strip()
            return {"key": editor["key"], "name": editor["name"],
                    "verdict": extract_verdict(review),
                    "review": review}

    started = time.time()
    with ThreadPoolExecutor(max_workers=len(EDITORS)) as pool:
        results = list(pool.map(_run_one, EDITORS))
    return {"editors": results, "elapsed": round(time.time() - started, 1)}


def extract_verdict(review_text):
    """从审评文本提取【判决】行的关键词：追读 / 弃稿 / 空串。"""
    if not review_text:
        return ""
    m = re.search(r"【判决】\s*([^\n]*)", review_text)
    if not m:
        return ""
    line = m.group(1)
    if "弃稿" in line:
        return "弃稿"
    if "追读" in line:
        return "追读"
    return ""


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


def run_rewrite(content, reviews, writer_agent="short_story"):
    """按盲审意见重写：动态 max_tokens + 最多 3 轮续写补足长度。

    writer_agent: 短篇用 "short_story"，长篇章节建议传 "rewrite"。
    返回 {"content": 新稿, "rounds": 轮数, "elapsed": 秒}
    """
    app = current_app._get_current_object()
    started = time.time()

    with app.app_context():
        cfg = get_model_config(agent_type=writer_agent)
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
# 持久化 —— 独立 BlindReview 表，不建迁移（init_db create_all 自动建表）
# ---------------------------------------------------------------------------

def save_blind_review(kind, result, word_count, story_id=None,
                      version_id=None, title=""):
    """盲审结果落库。返回 BlindReview 行 id；失败只告警不抛出。"""
    from app.models import db, BlindReview
    try:
        row = BlindReview(
            kind=kind,
            story_id=story_id,
            version_id=version_id,
            title=title,
            word_count=word_count,
            editors_json=json.dumps(result["editors"], ensure_ascii=False),
            elapsed=result["elapsed"],
        )
        db.session.add(row)
        db.session.commit()
        return row.id
    except Exception:
        logger.exception("blind_review: 保存盲审结果失败 (kind=%s)", kind)
        db.session.rollback()
        return None


def get_latest_blind_review(kind=None, story_id=None, version_id=None,
                            story_version_id=None):
    """取最近一条盲审记录（按对象过滤或全局）。返回 dict 或 None。

    story_id + story_version_id：短篇按版本快照严格限定（版本2 不再看
    到版本1 的记录）；只传 story_id 则为该短篇全局最近一条。
    version_id（无 story_id）：长篇章节版本维度。
    """
    from app.models import BlindReview
    q = BlindReview.query
    if story_id is not None:
        q = q.filter_by(kind="story", story_id=story_id)
        if story_version_id is not None:
            q = q.filter_by(version_id=story_version_id)
        else:
            # 与当前正文匹配的快照自动解析；解析不出（从未存过版本）
            # 才退回全量最近一条，保持无版本数据的可用性
            from app.models import ShortStory
            s = ShortStory.query.get(story_id)
            vid = resolve_story_version_id(s) if s else None
            if vid is not None:
                q = q.filter_by(version_id=vid)
    elif version_id is not None:
        q = q.filter_by(kind="chapter", version_id=version_id)
    elif kind:
        q = q.filter_by(kind=kind)
    row = q.order_by(BlindReview.id.desc()).first()
    if not row:
        return None
    try:
        editors = json.loads(row.editors_json or "[]")
    except (json.JSONDecodeError, TypeError):
        editors = []
    return {
        "id": row.id, "kind": row.kind, "title": row.title,
        "word_count": row.word_count, "elapsed": row.elapsed,
        "created_at": row.created_at, "editors": editors,
    }


def resolve_story_version_id(story):
    """解析短篇「当前正文」所属的版本快照 id（无 schema 依赖，按内容匹配）。

    精确匹配 story.content 的版本优先；未保存的手动改动匹配不到时
    回退最新快照（同一血统的最优近似）。没有任何快照返回 None。
    """
    from app.models import ShortStoryVersion
    versions = (ShortStoryVersion.query.filter_by(story_id=story.id)
                .order_by(ShortStoryVersion.id.desc()).all())
    if not versions:
        return None
    cur = (story.content or "").strip()
    for v in versions:
        if (v.content or "").strip() == cur:
            return v.id
    return versions[0].id


def resolve_content(kind, story_id=None, novel_id=None, chapter_number=None,
                    version_id=None, content=None):
    """按 kind 解析待审正文。返回 (text, meta) 或 (None, error_msg)。

    meta: {"story_id":..., "version_id":...} 或 {"version_id":...}，
    供持久化使用——短篇同样绑定版本快照，避免 v2 看到 v1 的审评。
    """
    text = (content or "").strip()
    if kind == "story":
        from app.models import ShortStory
        story = ShortStory.query.get(story_id) if story_id else None
        if not story:
            return None, "短篇不存在"
        if not text:
            text = (story.content or "").strip()
        if not text:
            return None, "该短篇还没有正文，先去写作页生成或保存内容"
        # 显式传入的 story_version_id 优先（工作台指定历史版本场景）
        return text, {"story_id": story.id,
                      "version_id": resolve_story_version_id(story)}

    if kind == "chapter":
        from app.models import Chapter, ChapterVersion
        chapter = Chapter.query.filter_by(
            novel_id=novel_id, chapter_number=chapter_number).first() \
            if novel_id and chapter_number else None
        if not chapter:
            return None, "章节不存在"
        version = ChapterVersion.query.get(version_id) if version_id else None
        if version and version.chapter_id != chapter.id:
            return None, "version_id 与指定章节不匹配"
        if not version:
            version = (ChapterVersion.query.filter_by(chapter_id=chapter.id)
                       .order_by(ChapterVersion.version_number.desc()).first())
        if not version:
            return None, "该章节暂无内容版本"
        if not text:
            text = (version.content or "").strip()
        if not text:
            return None, "该章节正文为空"
        return text, {"version_id": version.id}

    # kind == "text"
    if not text:
        return None, "正文为空"
    return text, {}
