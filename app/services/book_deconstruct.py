"""拆书复刻服务 —— 对标书整本拆解 → 待确认条目 → 采纳入库 → 复刻生成。

三层漏斗管线（不同维度匹配不同精度的输入，全程覆盖不截断）：
    L0 开篇精读：前 2 章原文不压缩直进 LLM → 开篇节奏 / 金手指初始态 / 文风（节奏与文风
       只存在于原文句子里，摘要还原不了，必须给真原文）
    L1 章级摘要：全部章节逐章压 400-600 字，逐章落库可断点续跑（上限 600 章，截断显式警告）
    L2 卷级归并：每 50 章摘要归并成一条卷级摘要（1000-1500 字），保证全量信息进入 L3
    L3 全局拆解：全部卷级摘要 + L0 结论 → 整体架构 / 全书人物 / 世界观体系 / 金手指成长线

短书（≤2 万字）走快路：原文单次调用直接拆六维。
拆解产物落 DeconstructItem 待确认队列：人工逐条编辑修改后「采纳」，复刻生成时统一落库。
拆解模型复用现有 audit agent，零配置改动。
"""
import json
import logging
import math
import queue
import re
import threading
from concurrent import futures as concurrent_futures

from app.models import (
    db, PlagiarizeTask, DeconstructItem, Novel, Chapter, ChapterVersion,
    Character, WorldSetting, OutlineNode, ShortStory, Foreshadowing,
)


logger = logging.getLogger(__name__)
from app.services.llm import call_llm_sync, stream_llm_tokens, LLMError
from app.config_utils import get_model_config

# 超长阈值：超过走三层漏斗，以内走快路（原文单次拆解）
SUMMARY_THRESHOLD = 20000
# 章级摘要的章节数上限（防止失控；超过显式警告，绝不静默）
MAX_SUMMARIZE_CHAPTERS = 600
# 卷级归并：每次归并的章数
VOLUME_GROUP_SIZE = 50
# 摘要合批：一次 LLM 调用压几章（NovelForge 用并发不合批，我们两者叠加）
SUMMARY_BATCH_SIZE = 4
# 摘要/归并的线程池并发数（保守值；NovelForge 默认 30，8-10 对主流厂商 RPM 都安全）
SUMMARY_CONCURRENCY = 8
# L0 开篇精读的原文上限与章数
OPENING_CHAPTERS = 2
OPENING_RAW_LIMIT = 20000
# 单章摘要输出字数
SUMMARY_TARGET_WORDS = "400-600"

# 章节切分（网文常见「第X章/回/节/卷」）
_CHAPTER_RE = re.compile(r"^\s*(?:第\s*[0-9零一二三四五六七八九十百千万]+\s*[章节回卷](?:\s|$)|[Cc]hapter\s*\d+\s*[:：.]?)", re.M)

# 拆解产物中人物/世界/大纲/伏笔的合法结构化键（供路由组装采纳表单用）
CHARACTER_KEYS = ("name", "role", "personality", "speaking_style", "appearance",
                  "background", "motivation", "arc_direction", "relationships", "migratable_methods",
                  "first_event", "exit_event", "exit_mode")
WORLD_KEYS = ("category", "title", "content")
OUTLINE_KEYS = ("phase", "title", "summary")
FORESHADOW_KEYS = ("title", "description", "planted_event", "resolve_event", "importance")


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------

SUMMARIZE_BATCH_PROMPT = """你是一位网文内容压缩器。以下是一部小说的连续若干章正文，请**逐章**压缩成摘要，输出 JSON 数组（只输出 JSON，不要解释）：

[{"chapter_no": 1, "summary": "…"}, {"chapter_no": 2, "summary": "…"}]

要求：
1. 每章一条，chapter_no 用输入中【第N章】标注的章号，顺序与输入一致，不要漏章、不要合并
2. 每条摘要 {target} 字，覆盖：本章推进了哪些事件、出现了哪些人物/设定/伏笔、章节结尾的钩子
3. 只提炼事实与结构，不输出评论"""

CONSOLIDATE_PROMPT = """你是一位网文结构压缩器。以下是一部小说连续若干章的逐章摘要，请归并成一条「卷级摘要」。

要求：
1. 输出 1000-1500 字（中文字符）
2. 覆盖：本阶段主线推进、关键事件链（按顺序）、出场人物及其关系变化、金手指/力量成长、结尾钩子
3. 只提炼事实与结构，不评论
4. 直接输出摘要正文，不要输出 JSON、标题或解释"""

DECONSTRUCT_PROMPT = """你是一位网文工业化拆解师。请把一部对标书拆解成六维创作蓝图，输出严格 JSON。

拆解原则：
1. 这是「技法拆解」——只提炼可复用的结构/节奏/设定机制/文风技法，不复制原文语句
2. 每个维度末尾必须给出「可迁移方法」(migratable_methods)，说明复刻到新书时怎么用
3. 信息不足的字段写"待补证据"，不要编造
4. 只输出 JSON，不要输出任何解释或 Markdown 代码块

输出 JSON 结构：
{
  "opening_rhythm": {
    "hook": {"type": "悬念/冲突/设定新奇/…", "description": "开篇钩子怎么设的", "reader_expectation": "读者被吊起什么期待"},
    "first_200_words": "开篇前200字做了什么（场景/事件/人物出场）",
    "first_500_words": "前500字节奏：冲突如何升级",
    "first_1000_words": "前1000字：第一个爽点/转折",
    "rhythm_steps": [{"step": "开局事件/升级事件/结果事件/转折事件/…", "description": "这一步做了什么"}],
    "pacing_features": ["节奏特征，如：三章内必须见金手指"],
    "migratable_methods": ["可迁移的节奏手法，如：开篇第1章末必须丢钩子"]
  },
  "golden_finger": {
    "name": "金手指名称",
    "type": "系统/穿越福利/血脉/法宝/知识/…",
    "rules": ["金手指的规则/限制"],
    "growth_design": "金手指如何随剧情成长",
    "satisfaction_points": [{"type": "打脸爽/扮猪吃虎/你没有我有/全场瞩目/惊天实力/…", "description": "怎么制造爽点"}],
    "migratable_methods": ["可迁移设定，如：金手指必须带成长线+代价"]
  },
  "structure": {
    "main_conflict": "全书核心矛盾",
    "theme": "主题内核",
    "stages": [{"stage_name": "阶段名", "chapter_start": 1, "chapter_end": 10,
                "stage_outline": "阶段起因/目标/冲突与阻力/关键事件链(≥3条)/关系变化/结尾钩子",
                "key_events": ["关键事件"]}],
    "turning_points": [{"moment": "转折时刻", "impact": "影响"}],
    "migratable_methods": ["可迁移的结构手法，如：每20章一个阶段钩子"]
  },
  "characters": [
    {"name": "角色名", "role": "主角/配角/反派/…", "personality": "性格", "speaking_style": "说话风格",
     "appearance": "外貌", "background": "背景", "motivation": "动机", "arc_direction": "弧光方向",
     "relationships": "关系", "migratable_methods": "这个角色怎么塑造的可迁移点",
     "first_event": "首现事件名(必须取自 key_events 中的事件名)",
     "exit_event": "退场事件名(死亡/离开/弧光完成的收束点；未退场写空)",
     "exit_mode": "死亡/离开/弧光完成/未知"}
  ],
  "world": [
    {"category": "规则/力量体系/势力/地图/时间线/经济/…", "title": "设定名", "content": "设定内容与作用"}
  ],
  "foreshadows": [
    {"title": "伏笔名", "description": "埋了什么、如何铺垫、收的时候揭晓什么",
     "planted_event": "埋设事件名(必须取自 key_events)",
     "resolve_event": "回收事件名(必须取自 key_events；尚无回收计划则写空)",
     "importance": 8}
  ],
  "style": {
    "rhythm": "文风节奏特征（段落长短/句子密度）",
    "sentence_features": "句式特征",
    "dialogue_features": "对话特征",
    "tone": "整体基调",
    "techniques": ["特色技法"],
    "migratable_methods": ["可迁移的文风手法，只学技法不抄内容"]
  }
}

锚定纪律：
- first_event / exit_event / planted_event / resolve_event 必须使用 key_events 中出现过的关键事件名原文，不得自创——它们是新书的章节锚点
- foreshadows 提取 5-20 条，按重要度排序；只收有明确"埋-收"对应关系的，单方面悬念不算
"""

OPENING_DECONSTRUCT_PROMPT = """你是一位网文工业化拆解师。以下是某部小说的**开篇原文**（前几章，未压缩）。
开篇节奏和文风只存在于原文的句子里，请基于原文逐句细读，拆解输出 JSON（只输出 JSON，不要解释）：

{
  "opening_rhythm": {
    "hook": {"type": "悬念/冲突/设定新奇/…", "description": "开篇钩子怎么设的", "reader_expectation": "读者被吊起什么期待"},
    "first_200_words": "开篇前200字做了什么（场景/事件/人物出场）",
    "first_500_words": "前500字节奏：冲突如何升级",
    "first_1000_words": "前1000字：第一个爽点/转折",
    "rhythm_steps": [{"step": "开局事件/升级事件/结果事件/转折事件/…", "description": "这一步做了什么"}],
    "pacing_features": ["节奏特征，如：三章内必须见金手指"],
    "migratable_methods": ["可迁移的节奏手法"]
  },
  "golden_finger": {
    "name": "金手指名称", "type": "系统/穿越福利/血脉/法宝/知识/…",
    "rules": ["金手指的规则/限制"], "growth_design": "开篇展现的初始形态与成长空间",
    "satisfaction_points": [{"type": "打脸爽/扮猪吃虎/…", "description": "怎么制造爽点"}],
    "migratable_methods": ["可迁移设定"]
  },
  "style": {
    "rhythm": "文风节奏特征（段落长短/句子密度）",
    "sentence_features": "句式特征", "dialogue_features": "对话特征", "tone": "整体基调",
    "techniques": ["特色技法"], "migratable_methods": ["可迁移的文风手法，只学技法不抄内容"]
  },
  "characters": [
    {"name": "角色名", "role": "主角/配角/…", "personality": "性格", "speaking_style": "说话风格",
     "appearance": "外貌", "background": "背景", "motivation": "动机", "arc_direction": "弧光方向",
     "relationships": "关系", "migratable_methods": "可迁移塑造点"}
  ],
  "world": [
    {"category": "规则/力量体系/势力/…", "title": "设定名", "content": "设定内容与作用"}
  ]
}

原则：只提炼可复用的技法/机制/设定，不复制原文语句；信息不足写"待补证据"，不要编造。"""

GLOBAL_DECONSTRUCT_PROMPT = """你是一位网文工业化拆解师。你将看到一部小说的**开篇精读结论**（基于原文，可信）
和**全书卷级摘要**（由全部章节逐章摘要归并而来，覆盖全书但已压缩）。
请基于这两部分输出**全书级**结构拆解 JSON（只输出 JSON，不要解释）：

{
  "structure": {
    "main_conflict": "全书核心矛盾",
    "theme": "主题内核",
    "stages": [{"stage_name": "阶段/卷名", "chapter_start": 1, "chapter_end": 50,
                "stage_outline": "阶段起因/目标/冲突与阻力/关键事件链(≥3条)/关系变化/结尾钩子",
                "key_events": ["关键事件"]}],
    "turning_points": [{"moment": "转折时刻", "impact": "影响"}],
    "migratable_methods": ["可迁移的结构手法"]
  },
  "characters": [
    {"name": "角色名", "role": "主角/配角/反派/…", "personality": "性格", "speaking_style": "说话风格",
     "appearance": "外貌", "background": "背景", "motivation": "动机", "arc_direction": "弧光方向",
     "relationships": "关系", "migratable_methods": "可迁移塑造点"}
  ],
  "world": [
    {"category": "规则/力量体系/势力/地图/时间线/…", "title": "设定名", "content": "设定内容与作用"}
  ],
  "golden_finger_growth": "金手指/核心优势的**全书**成长线设计（各阶段形态与代价）"
}

原则：
1. structure.stages 必须覆盖全部卷级摘要标注的章节范围，不能只覆盖开头
2. 只提炼可迁移的技法/机制/设定，不复制原文语句
3. 信息不足写"待补证据"，不要编造"""


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _extract_json(text):
    """从 LLM 输出中稳健提取 JSON dict。失败返回 None。"""
    if not text:
        return None
    text = text.strip()
    # 1) 直接解析
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        pass
    # 2) 剥掉 Markdown 代码围栏
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        try:
            data = json.loads(fenced.group(1))
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, TypeError):
            pass
    # 3) 取首个 { 到末个 } 的片段
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def _s(v):
    """LLM JSON 字段防御性转字符串（拆解输出类型不可信）。"""
    if v is None:
        return ""
    return v if isinstance(v, str) else str(v)


def _dict(v):
    """LLM JSON 容器字段防御性取 dict（非 dict 一律按空处理）。"""
    return v if isinstance(v, dict) else {}


def _list(v):
    """LLM JSON 列表字段防御性取 list（字符串包装成单元素，避免逐字迭代）。"""
    if isinstance(v, list):
        return v
    return [v] if v else []


def _extract_json_array(text):
    """从 LLM 输出中稳健提取 JSON 数组。失败返回 None。"""
    if not text:
        return None
    text = text.strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else None
    except (json.JSONDecodeError, TypeError):
        pass
    fenced = re.search(r"```(?:json)?\s*(\[.*\])\s*```", text, re.S)
    if fenced:
        try:
            data = json.loads(fenced.group(1))
            return data if isinstance(data, list) else None
        except (json.JSONDecodeError, TypeError):
            pass
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            return data if isinstance(data, list) else None
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def _split_chapters(text):
    """按章节标题切分源文本，返回 [(标题, 正文)]；识别不到章节则按定长分块。"""
    text = (text or "").strip()
    if not text:
        return []
    matches = list(_CHAPTER_RE.finditer(text))
    if len(matches) >= 2:
        chunks = []
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            title = m.group(0).strip()
            body = text[start:end].strip()
            # 过滤「第X卷」这类只有标题行没有正文的空块
            if len(body) > 30:
                chunks.append((title, body))
        if chunks:
            return chunks
        # 全是标题行（如目录）→ 回退定长分块
    # 无章节标记：按 6000 字定长分块
    size = 6000
    return [(f"片段{i + 1}", text[i:i + size]) for i in range(0, len(text), size) if text[i:i + size].strip()]


def _load_task(task_id):
    task = db.session.get(PlagiarizeTask, task_id)
    if not task:
        raise LLMError(f"拆书任务 {task_id} 不存在")
    return task


def _set_status(task_id, status, error=""):
    """流式生成器内跨请求上下文安全落状态。"""
    task = _load_task(task_id)
    task.status = status
    task.error_message = error or task.error_message
    db.session.commit()


# ---------------------------------------------------------------------------
# L1：章级摘要（逐章落库、断点续跑）
# L2：卷级归并（保证全量信息进入全局拆解）
# ---------------------------------------------------------------------------

def _parse_json_list(raw):
    """从 Text 列安全解析 JSON 数组，非数组一律按空处理。"""
    try:
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def summarize_chapters(task_id):
    """L1 章级摘要：合批（一次压 SUMMARY_BATCH_SIZE 章）+ 线程池并发。

    参照 NovelForge（并发扇出 + 单章失败隔离 + checkpoint）与 LangChain
    map-reduce 实测结论（map 阶段是瓶颈，并发化 + 小模型赢得一切）：
    - 工作线程只做 LLM 网络调用（无 DB 访问，无跨线程 session 问题）
    - 每批完成即落库（checkpoint，断点续跑只补缺失章）
    - 单章失败兜底为截断正文，不炸批
    - 模型走 summary agent（fast 挡），拆解仍用 audit（deep 挡）
    """
    task = _load_task(task_id)
    if not task.source_text:
        raise LLMError("对标书文本为空")
    task.status = "summarizing"
    db.session.commit()

    chapters_all = _split_chapters(task.source_text)
    chapters = chapters_all[:MAX_SUMMARIZE_CHAPTERS]
    truncated = len(chapters_all) > MAX_SUMMARIZE_CHAPTERS
    if not chapters:
        raise LLMError("无法从对标书文本中切分出章节")

    if truncated:
        yield (f"⚠ 对标书超过 {MAX_SUMMARIZE_CHAPTERS} 章，仅摘要前 {MAX_SUMMARIZE_CHAPTERS} 章，"
               f"整体架构拆解基于这部分内容\n")
    # index 必须是 int：脏数据（str 型 index）混入会让 sorted() 混排 str/int 直接 TypeError
    summaries = {s["index"]: s for s in _parse_json_list(task.chapters_summary_json)
                 if isinstance(s, dict) and s.get("summary") and isinstance(s.get("index"), int)}
    # 兜底截断的章不算完成——续跑时重做(P0-2:不让降级文本永久污染拆解)
    remaining = [(i, title, body) for i, (title, body) in enumerate(chapters, start=1)
                 if not (i in summaries and not summaries[i].get("fallback"))]
    if not remaining:
        yield f"[摘要] 全部 {len(summaries)} 章已有摘要，跳过\n"
        return
    n_batches = math.ceil(len(remaining) / SUMMARY_BATCH_SIZE)
    yield (f"[摘要] 待摘要 {len(remaining)}/{len(chapters)} 章：每次压 {SUMMARY_BATCH_SIZE} 章"
           f" × 并发 {SUMMARY_CONCURRENCY}，约 {n_batches} 次调用\n")

    cfg = get_model_config(agent_type="summary")
    batches = [remaining[i:i + SUMMARY_BATCH_SIZE]
               for i in range(0, len(remaining), SUMMARY_BATCH_SIZE)]
    done = len(summaries)

    def _summarize_batch(batch):
        """纯 LLM 调用（无 DB）：返回 [(index, title, summary), ...]。"""
        numbered = "\n\n".join(f"【第{i}章 {title}】\n{body}" for i, title, body in batch)
        try:
            out = call_llm_sync(
                model=cfg["model_name"],
                messages=[
                    # 提示词含 JSON 花括号字面量，不能用 .format（会被当格式化字段）
                    {"role": "system",
                     "content": SUMMARIZE_BATCH_PROMPT.replace("{target}", SUMMARY_TARGET_WORDS)},
                    {"role": "user", "content": numbered},
                ],
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
                provider_type=cfg.get("provider_type", "deepseek"),
                temperature=cfg["temperature"],
                max_tokens=4096,
            )
        except LLMError:
            out = None
        entries = _extract_json_array(out or "")
        by_no = {}
        if entries:
            indices = [i for i, _, _ in batch]
            for pos, e in enumerate(entries):
                if not isinstance(e, dict):
                    continue
                no = e.get("chapter_no")
                # chapter_no 可信则用之；模型串号/缺失时按批内位置回退
                idx = no if isinstance(no, int) and no in indices else (
                    indices[pos] if pos < len(indices) else None)
                if idx is None:
                    continue
                text = _s(e.get("summary")).strip()
                if text:
                    by_no[idx] = text
        results = []
        for i, title, body in batch:
            text = by_no.get(i)
            if text:
                results.append((i, title, text, False))
            else:
                results.append((i, title, body[:600], True))  # 兜底截断:标记待续跑重做
        return results

    # 分波提交：每波至多 SUMMARY_CONCURRENCY 批。断连时最多等当前波跑完，
    # 不会挂住等全部批次（几百章的书 = 150 批，一次性提交会让 close 等到天荒地老）
    with concurrent_futures.ThreadPoolExecutor(max_workers=SUMMARY_CONCURRENCY) as pool:
        for wave_start in range(0, len(batches), SUMMARY_CONCURRENCY):
            wave = batches[wave_start:wave_start + SUMMARY_CONCURRENCY]
            for fut in concurrent_futures.as_completed(
                    [pool.submit(_summarize_batch, b) for b in wave]):
                for i, title, text, is_fallback in fut.result():
                    entry = {"index": i, "title": title, "summary": text}
                    if is_fallback:
                        entry["fallback"] = True
                    summaries[i] = entry
                    done += 1
                # 每批落库：断连只损失进行中的批次
                task.chapters_summary_json = json.dumps(
                    [summaries[k] for k in sorted(summaries)], ensure_ascii=False)
                task.status = "deconstructing"
                db.session.commit()
                yield f"[摘要 {done}/{len(chapters)}] 批次完成\n"

    yield f"✓ 章级摘要完成，共 {len(summaries)} 章\n"


def consolidate_volumes(task_id):
    """L2 卷级归并：每 VOLUME_GROUP_SIZE 章摘要归并成一条卷级摘要，线程池并发。

    归并后全量信息进入 L3 全局拆解——不存在静默截断。模型走 summary agent（fast 挡）。
    """
    task = _load_task(task_id)
    summaries = [s for s in _parse_json_list(task.chapters_summary_json)
                 if isinstance(s, dict) and s.get("summary")]
    if not summaries:
        raise LLMError("没有章级摘要可归并（摘要阶段未完成）")
    task.status = "summarizing"
    db.session.commit()

    groups = [summaries[i:i + VOLUME_GROUP_SIZE]
              for i in range(0, len(summaries), VOLUME_GROUP_SIZE)]
    volumes = {v["index"]: v for v in _parse_json_list(task.volumes_summary_json)
               if isinstance(v, dict) and v.get("summary") and isinstance(v.get("index"), int)}
    todo = [(gi, g) for gi, g in enumerate(groups, start=1)
            if not (gi in volumes and not volumes[gi].get("fallback"))]
    if not todo:
        yield f"[归并] 全部 {len(volumes)} 卷已有归并摘要，跳过\n"
        return
    yield f"[归并] 待归并 {len(todo)}/{len(groups)} 卷 × 并发 {SUMMARY_CONCURRENCY}\n"

    cfg = get_model_config(agent_type="summary")

    def _consolidate_group(gi, group):
        """纯 LLM 调用（无 DB）：返回 (gi, start, end, text)。"""
        body = "\n\n".join(f"{s.get('title', '')}\n{s.get('summary', '')}" for s in group)
        try:
            out = call_llm_sync(
                model=cfg["model_name"],
                messages=[
                    {"role": "system", "content": CONSOLIDATE_PROMPT},
                    {"role": "user", "content": f"【第 {group[0].get('index', '?')}-{group[-1].get('index', '?')} 章】\n{body}"},
                ],
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
                provider_type=cfg.get("provider_type", "deepseek"),
                temperature=cfg["temperature"],
                max_tokens=2048,
            )
        except LLMError:
            out = None
        ok_text = bool((out or "").strip())
        text = (out or "").strip() or body[:2000]
        return gi, group[0].get("index"), group[-1].get("index"), text, (not ok_text)

    # 分波提交（同 summarize_chapters：断连只等当前波）
    with concurrent_futures.ThreadPoolExecutor(
            max_workers=min(SUMMARY_CONCURRENCY, len(todo))) as pool:
        for wave_start in range(0, len(todo), SUMMARY_CONCURRENCY):
            wave = todo[wave_start:wave_start + SUMMARY_CONCURRENCY]
            for fut in concurrent_futures.as_completed(
                    [pool.submit(_consolidate_group, gi, g) for gi, g in wave]):
                gi, start, end, text, is_fallback = fut.result()
                entry = {"index": gi, "start": start, "end": end, "summary": text}
                if is_fallback:
                    entry["fallback"] = True
                volumes[gi] = entry
                task.volumes_summary_json = json.dumps(
                    [volumes[k] for k in sorted(volumes)], ensure_ascii=False)
                task.status = "deconstructing"
                db.session.commit()
                yield f"[归并 {len(volumes)}/{len(groups)}] 第 {start}-{end} 章 → {len(text)} 字\n"

    yield f"✓ 卷级归并完成，共 {len(volumes)} 卷\n"


# ---------------------------------------------------------------------------
# 二级：六维拆解
# ---------------------------------------------------------------------------

def deconstruct_source(task_id):
    """完整拆书管线：超长先摘要压缩 → 基于摘要流式拆六维 JSON → 落报告+待确认条目。

    yield 流式文本：摘要进度标记 → 拆解 token 流 → 完成统计。
    任何未捕获异常/客户端断开都会把任务置为 failed，避免永久卡在「拆解中」。
    """
    try:
        yield from _deconstruct_pipeline(task_id)
    except GeneratorExit:
        # 客户端中途断开（关页面/刷新）——不能 yield，只回写状态
        _set_status(task_id, "failed", "连接中断，拆解未完成，可重新拆书")
        raise
    except LLMError as e:
        _set_status(task_id, "failed", str(e))
        yield f"\n[拆解失败: {e}]\n"
    except Exception as e:
        _set_status(task_id, "failed", str(e))
        yield f"\n[拆解失败: {e}]\n"
    # 业务失败(管线内部已 yield 失败标记并置 failed)时让长任务也置失败,
    # 而不是"跑完了但失败"的矛盾状态(P0-3 执行器契约)
    if _load_task(task_id).status == "failed":
        raise LLMError(_load_task(task_id).error_message or "拆解失败")


def _opening_text(source_text):
    """L0 开篇精读输入：前 OPENING_CHAPTERS 章原文（不压缩），无章节标记时取头部。"""
    chapters = _split_chapters(source_text)
    if len(chapters) >= 2:
        return "\n\n".join(body for _, body in chapters[:OPENING_CHAPTERS])[:OPENING_RAW_LIMIT]
    return (source_text or "")[:OPENING_RAW_LIMIT]


def _stream_elements(system, user_content, label, heartbeat_secs=15):
    """流式跑一次拆解调用并解析 JSON。

    心跳：deep 挡推理类模型在思考阶段不吐 token（reasoning_content 不进流），
    用后台线程 + 队列做 15 秒心跳，避免长静默被当成卡死。
    取消：消费者断开（GeneratorExit）时置 closed 事件，生产者停止入队，
    不再为已离开的用户白烧剩余 token。
    yield token 流与心跳；通过 StopIteration.value 返回 (elements, error)。
    """
    cfg = get_model_config(agent_type="audit")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]
    q = queue.Queue()
    closed = threading.Event()

    def _produce():
        try:
            for text in stream_llm_tokens(
                model=cfg["model_name"],
                messages=messages,
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
                provider_type=cfg.get("provider_type", "deepseek"),
                temperature=cfg["temperature"],
                max_tokens=8192,
            ):
                if closed.is_set():
                    return
                if text:
                    q.put(("token", text))
            q.put(("done", None))
        except Exception as e:
            if not closed.is_set():
                q.put(("error", str(e)))

    threading.Thread(target=_produce, daemon=True, name=f"deconstruct-{label}").start()
    collected = []
    try:
        while True:
            try:
                kind, payload = q.get(timeout=heartbeat_secs)
            except queue.Empty:
                yield f"…[{label}仍在生成，deep 挡模型输出中，请耐心等待]\n"
                continue
            if kind == "token":
                collected.append(payload)
                yield payload
            elif kind == "done":
                break
            else:
                yield f"\n[{label}失败: {payload}]\n"
                return None, payload
    finally:
        closed.set()
    yield "\n"
    elements = _extract_json("".join(collected))
    if not elements:
        yield f"\n[{label}失败: 输出无法解析为 JSON]\n"
        return None, "输出无法解析为 JSON，请重试"
    return elements, None


def _merge_elements(opening, glob):
    """合并 L0 开篇精读与 L3 全局拆解。

    权威归属：opening_rhythm / golden_finger / style 归 L0（基于原文，证据可信）；
    structure 归 L3（全书视角）；characters / world 两边合并（开篇优先，按名字/标题去重）；
    金手指全书成长线以 L3 的 golden_finger_growth 覆盖。
    """
    opening = opening if isinstance(opening, dict) else {}
    glob = glob if isinstance(glob, dict) else {}
    if not opening and not glob:
        return {}
    elements = {}
    if glob.get("structure"):
        elements["structure"] = glob["structure"]
    for k in ("opening_rhythm", "style"):
        if opening.get(k):
            elements[k] = opening[k]

    # 金手指：L0 为基础，成长线用 L3 的全书视角
    gf = dict(opening.get("golden_finger")) if isinstance(opening.get("golden_finger"), dict) else {}
    if not gf and isinstance(glob.get("golden_finger"), dict):
        gf = dict(glob["golden_finger"])
    growth = _s(glob.get("golden_finger_growth")).strip()
    if growth:
        gf["growth_design"] = growth
    if gf:
        elements["golden_finger"] = gf

    def _merge_lists(a, b, key):
        def norm(x):
            return _s(x.get(key)).strip() if isinstance(x, dict) else ""
        merged = [x for x in (a or []) if isinstance(x, dict) and norm(x)]
        seen = {norm(x) for x in merged}
        for x in (b or []):
            if isinstance(x, dict) and norm(x) and norm(x) not in seen:
                merged.append(x)
                seen.add(norm(x))
        return merged

    chars = _merge_lists(opening.get("characters"), glob.get("characters"), "name")
    if chars:
        elements["characters"] = chars
    worlds = _merge_lists(opening.get("world"), glob.get("world"), "title")
    if worlds:
        elements["world"] = worlds
    return elements


def _deconstruct_pipeline(task_id):
    task = _load_task(task_id)
    if not task.source_text:
        raise LLMError("对标书文本为空")

    task.status = "deconstructing"
    task.error_message = ""
    db.session.commit()

    if len(task.source_text) <= SUMMARY_THRESHOLD:
        # 快路：短书原文单次六维拆解（节奏/文风证据天然齐全）
        yield "[快路] 文本适中，原文单次六维拆解\n"
        elements, err = yield from _stream_elements(
            DECONSTRUCT_PROMPT,
            f"【对标书】（以下为原文）\n{task.source_text[:SUMMARY_THRESHOLD]}",
            "拆解")
        if err:
            _set_status(task_id, "failed", err)
            return
    else:
        # 长书：四层漏斗（L1 章摘要 → L2 卷归并 → L0 开篇精读 → L3 全局拆解）
        yield "[阶段 1/4] 章级摘要（逐章压缩，逐章落库可断点续跑）\n"
        try:
            for chunk in summarize_chapters(task_id):
                yield chunk
        except LLMError as e:
            _set_status(task_id, "failed", str(e))
            yield f"\n[拆解失败: {e}]\n"
            return

        yield "[阶段 2/4] 卷级归并（保证全量信息进入全局拆解）\n"
        try:
            for chunk in consolidate_volumes(task_id):
                yield chunk
        except LLMError as e:
            _set_status(task_id, "failed", str(e))
            yield f"\n[拆解失败: {e}]\n"
            return

        # L0：开篇精读（原文）——节奏/文风/金手指初始态的证据只在这里
        task = _load_task(task_id)
        yield "[阶段 3/4] 开篇精读（原文细拆节奏/文风/金手指）\n"
        opening, err = yield from _stream_elements(
            OPENING_DECONSTRUCT_PROMPT,
            f"【开篇原文】\n{_opening_text(task.source_text)}",
            "开篇精读")
        if err:
            opening = {}
            yield "⚠ 开篇精读失败，将仅基于全书摘要拆解（节奏/文风精度受限）\n"

        # L3：全局拆解（全部卷级摘要 + 开篇结论校准）
        task = _load_task(task_id)
        volumes = [v for v in _parse_json_list(task.volumes_summary_json)
                   if isinstance(v, dict) and v.get("summary")]
        if not volumes:
            _set_status(task_id, "failed", "卷级归并未完成，无法全局拆解")
            yield "\n[拆解失败: 卷级归并未完成]\n"
            return
        yield ("[阶段 4/4] 全局拆解（全书架构/人物/世界观）——这是整条管线最慢的一步："
               "deep 挡模型要生成覆盖全书的架构 JSON，通常 1-3 分钟，"
               "若模型带深度思考则开头静默更久（有心跳提示，不是卡死）\n")
        volumes_text = "\n\n".join(
            f"【第 {v.get('start', '?')}-{v.get('end', '?')} 章 · 卷{v.get('index', '?')}】\n{v.get('summary', '')}"
            for v in volumes)
        opening_hint = json.dumps(opening, ensure_ascii=False)[:6000] if opening else "（开篇精读失败，无）"
        glob, err = yield from _stream_elements(
            GLOBAL_DECONSTRUCT_PROMPT,
            f"【开篇精读结论】\n{opening_hint}\n\n【全书卷级摘要（共 {len(volumes)} 卷）】\n{volumes_text}",
            "全局拆解")
        if err:
            _set_status(task_id, "failed", err)
            return
        elements = _merge_elements(opening, glob)
        if not elements:
            _set_status(task_id, "failed", "拆解结果为空")
            yield "\n[拆解失败: 拆解结果为空]\n"
            return

    # 落库：elements + 报告 + 待确认条目在单事务内完成，
    # 任何一步失败整体回滚并置 failed，不会出现「状态 done 但队列为空」
    try:
        task = _load_task(task_id)
        task.elements_json = json.dumps(elements, ensure_ascii=False)
        task.report_text = compose_report(elements)
        task.status = "done"
        DeconstructItem.query.filter_by(task_id=task_id).delete()
        counts = _build_items(task, elements)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        _set_status(task_id, "failed", f"拆解结果落库失败: {e}")
        yield "\n[拆解失败: 结果落库失败，请重试]\n"
        return

    yield (f"\n✓ 拆解完成：{counts['characters']} 个人物 / {counts['world']} 条世界观"
           f" / {counts['outline']} 个大纲节点 / {counts['foreshadow']} 条伏笔 进入待确认队列\n")

    # 拆书→资源库联动:自动入资源库(原文+分段+向量),供语义检索
    try:
        from app.services.resource_service import add_resource
        from app.models import ResourceBook
        existing = ResourceBook.query.filter_by(
            title=task.title, source_type="paste").first()
        if not existing:
            book = add_resource(task.title or "对标书", task.source_text,
                                source_type="paste")
            yield f"📚 已入资源库「{book.title}」（{book.chapter_count} 段向量）\n"
    except Exception as e:
        logger.warning("资源库入库失败(不影响拆解结果): %s", e)


def _build_items(task, elements):
    """把拆解 JSON 落成 DeconstructItem 待确认条目。返回各维度计数。"""
    counts = {"characters": 0, "world": 0, "outline": 0, "foreshadow": 0}

    for c in _list(elements.get("characters")):
        if not isinstance(c, dict) or not _s(c.get("name")).strip():
            continue
        item = DeconstructItem(
            task_id=task.id, kind="character",
            title=_s(c.get("name")).strip(),
            content_json=json.dumps({k: _s(c.get(k, "")) for k in CHARACTER_KEYS}, ensure_ascii=False),
        )
        db.session.add(item)
        counts["characters"] += 1

    for w in _list(elements.get("world")):
        if not isinstance(w, dict) or not _s(w.get("title")).strip():
            continue
        item = DeconstructItem(
            task_id=task.id, kind="world",
            title=_s(w.get("title")).strip(),
            content_json=json.dumps({k: _s(w.get(k, "")) for k in WORLD_KEYS}, ensure_ascii=False),
        )
        db.session.add(item)
        counts["world"] += 1

    structure = _dict(elements.get("structure"))
    for st in _list(structure.get("stages")):
        if not isinstance(st, dict) or not _s(st.get("stage_name")).strip():
            continue
        events = _list(st.get("key_events"))
        if events:
            outline_body = _s(st.get("stage_outline", ""))
            for ev in events:
                ev_text = _s(ev).strip()
                if not ev_text:
                    continue
                summary = f"{outline_body}\n- 关键事件：{ev_text}".strip() if outline_body else f"- 关键事件：{ev_text}"
                item = DeconstructItem(
                    task_id=task.id, kind="outline",
                    title=ev_text[:60],
                    content_json=json.dumps(
                        {"phase": _s(st.get("stage_name", "")), "title": ev_text[:60], "summary": summary},
                        ensure_ascii=False),
                )
                db.session.add(item)
                counts["outline"] += 1
        else:
            item = DeconstructItem(
                task_id=task.id, kind="outline",
                title=_s(st.get("stage_name")).strip(),
                content_json=json.dumps(
                    {"phase": "", "title": _s(st.get("stage_name", "")), "summary": _s(st.get("stage_outline", ""))},
                    ensure_ascii=False),
            )
            db.session.add(item)
            counts["outline"] += 1

    # 伏笔候选（埋/收锚定在关键事件上，落库时换算成章节号）
    for f in _list(elements.get("foreshadows")):
        if not isinstance(f, dict) or not _s(f.get("title")).strip():
            continue
        item = DeconstructItem(
            task_id=task.id, kind="foreshadow",
            title=_s(f.get("title")).strip()[:80],
            content_json=json.dumps({
                k: (_s(f.get(k, "")) if k != "importance" else f.get("importance", 5))
                for k in FORESHADOW_KEYS
            }, ensure_ascii=False),
        )
        db.session.add(item)
        counts["foreshadow"] += 1

    return counts


# ---------------------------------------------------------------------------
# 报告合成
# ---------------------------------------------------------------------------

def compose_report(elements):
    """六维拆解 JSON → 可读 Markdown 报告（用户可在此基础上编辑）。"""
    if not isinstance(elements, dict) or not elements:
        return ""
    parts = ["# 拆书报告", "",
             "> 来源：AI 从外部文本自动拆解，仅供创作参考；复刻产物的专名与情节必须经改写更换，"
             "平台有 AI 检测与抄袭鉴定，请负责任发布。", ""]

    # 开篇节奏
    orh = _dict(elements.get("opening_rhythm"))
    parts += ["## 一、开篇节奏", ""]
    hook = _dict(orh.get("hook"))
    if hook.get("description"):
        parts += [f"- **开篇钩子**（{hook.get('type', '未知类型')}）：{hook['description']}"]
        if hook.get("reader_expectation"):
            parts += [f"  - 读者期待：{hook['reader_expectation']}"]
    for key, label in [("first_200_words", "前 200 字"), ("first_500_words", "前 500 字"), ("first_1000_words", "前 1000 字")]:
        if orh.get(key):
            parts += [f"- **{label}**：{orh[key]}"]
    steps = _list(orh.get("rhythm_steps"))
    if steps:
        parts += ["- **节奏链**："]
        for s in steps:
            if isinstance(s, dict):
                parts += [f"  - {s.get('step', '')}：{s.get('description', '')}"]
            else:
                parts += [f"  - {s}"]
    for m in _list(orh.get("migratable_methods")):
        parts += [f"- 迁移方法：{m}"]
    parts += [""]

    # 金手指
    gf = _dict(elements.get("golden_finger"))
    if gf.get("name"):
        parts += ["## 二、金手指", ""]
        parts += [f"- **名称**：{gf.get('name')}（{gf.get('type', '未知类型')}）"]
        for r in _list(gf.get("rules")):
            parts += [f"- 规则：{r}"]
        if gf.get("growth_design"):
            parts += [f"- 成长线：{gf['growth_design']}"]
        for sp in _list(gf.get("satisfaction_points")):
            if isinstance(sp, dict):
                parts += [f"- 爽点（{sp.get('type', '')}）：{sp.get('description', '')}"]
            else:
                parts += [f"- 爽点：{sp}"]
        for m in _list(gf.get("migratable_methods")):
            parts += [f"- 迁移方法：{m}"]
        parts += [""]

    # 整体架构
    st = _dict(elements.get("structure"))
    parts += ["## 三、整体架构", ""]
    if st.get("main_conflict"):
        parts += [f"- **核心冲突**：{st['main_conflict']}"]
    if st.get("theme"):
        parts += [f"- **主题**：{st['theme']}"]
    for stage in _list(st.get("stages")):
        if not isinstance(stage, dict):
            continue
        parts += [f"### {stage.get('stage_name', '')}（第 {stage.get('chapter_start', '?')}-{stage.get('chapter_end', '?')} 章）", ""]
        if stage.get("stage_outline"):
            parts += [stage["stage_outline"], ""]
    for tp in _list(st.get("turning_points")):
        if isinstance(tp, dict):
            parts += [f"- 转折：{tp.get('moment', '')} → {tp.get('impact', '')}"]
        else:
            parts += [f"- 转折：{tp}"]
    for m in _list(st.get("migratable_methods")):
        parts += [f"- 迁移方法：{m}"]
    parts += [""]

    # 人物
    chars = [c for c in _list(elements.get("characters")) if isinstance(c, dict)]
    if chars:
        parts += ["## 四、人物", ""]
        for c in chars:
            name = c.get("name") or "未命名"
            parts += [f"### {name}（{c.get('role', '')}）", ""]
            for key, label in [("personality", "性格"), ("speaking_style", "说话风格"), ("appearance", "外貌"),
                               ("background", "背景"), ("motivation", "动机"), ("arc_direction", "弧光")]:
                if c.get(key):
                    parts += [f"- {label}：{c[key]}"]
            if c.get("relationships"):
                parts += [f"- 关系：{c['relationships']}"]
            anchors = []
            if c.get("first_event"):
                anchors.append(f"首现于「{c['first_event']}」")
            if c.get("exit_event"):
                anchors.append(f"退场于「{c['exit_event']}」({_s(c.get('exit_mode')) or '未知方式'})")
            if anchors:
                parts += [f"- 时间线：{'，'.join(anchors)}"]
            if c.get("migratable_methods"):
                parts += [f"- 塑造方法：{c['migratable_methods']}"]
            parts += [""]

    # 世界观
    world = [w for w in _list(elements.get("world")) if isinstance(w, dict)]
    if world:
        parts += ["## 五、世界观", ""]
        for w in world:
            parts += [f"- **[{w.get('category', '设定')}] {w.get('title', '')}**：{w.get('content', '')}"]
        parts += [""]

    # 伏笔规划
    foreshadows = [f for f in _list(elements.get("foreshadows")) if isinstance(f, dict)]
    if foreshadows:
        parts += ["## 六、伏笔规划（埋/收锚定在关键事件上）", ""]
        for f in foreshadows:
            title = _s(f.get("title"))
            planted = _s(f.get("planted_event"))
            resolve = _s(f.get("resolve_event"))
            line = f"- **{title}**：埋于「{planted or '?'}」"
            line += f"，收于「{resolve}」" if resolve else "，回收计划未定"
            if f.get("importance"):
                line += f"（重要度 {f.get('importance')}）"
            parts += [line]
            if f.get("description"):
                parts += [f"  - {f['description']}"]
        parts += [""]

    # 文风
    style = _dict(elements.get("style"))
    if style:
        parts += ["## 七、文风", ""]
        for key, label in [("rhythm", "节奏"), ("sentence_features", "句式"), ("dialogue_features", "对话"),
                           ("tone", "基调")]:
            if style.get(key):
                parts += [f"- **{label}**：{style[key]}"]
        for t in _list(style.get("techniques")):
            parts += [f"- 技法：{t}"]
        for m in _list(style.get("migratable_methods")):
            parts += [f"- 迁移方法：{m}"]
        parts += [""]

    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# 条目采纳（确认 + 保存修改稿；知识库写入延迟到复刻生成时统一落库）
# ---------------------------------------------------------------------------

def _item_data(item):
    """条目最终内容：用户修改稿优先，否则拆解原稿。"""
    if item.modified_content and item.modified_content.strip():
        try:
            data = json.loads(item.modified_content)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError):
            pass
    return item.content


def adopt_item(item_id, modified=None):
    """确认一条待确认条目：保存用户修改稿并标记「已采纳」。

    知识库写入不在此时发生——复刻生成时（apply_blueprint_long/short）由
    materialize 统一把已采纳条目落进目标书知识库并回填 target_id。
    返回 (ok, message, target_id)。
    """
    item = db.session.get(DeconstructItem, item_id)
    if not item:
        return False, f"条目 {item_id} 不存在", None
    if modified is not None and not isinstance(modified, dict):
        return False, "修改内容必须是 JSON 对象（字段→值的字典）", None
    if item.status == "adopted" and item.target_id:
        return False, f"「{item.title}」已写入知识库，如需修改请到目标书的知识库页面改", item.target_id
    if modified:
        # 合并语义：UI 表单只提交可见字段；时间轴锚点等不可见键（first_event 等）
        # 从现稿保留，不被表单提交冲掉
        merged = dict(_item_data(item))
        merged.update(modified)
        item.modified_content = json.dumps(merged, ensure_ascii=False)
    item.status = "adopted"
    db.session.commit()
    return True, f"已采纳「{item.title}」（复刻生成时入库）", None


def adopt_all_items(task_id):
    """把任务下所有待确认条目按拆解原稿标记采纳。返回 (ok, message)。"""
    pending = DeconstructItem.query.filter_by(task_id=task_id, status="pending").all()
    if not pending:
        return True, "没有待采纳的条目"
    for item in pending:
        item.status = "adopted"
        item.target_id = None
    db.session.commit()
    return True, f"已采纳 {len(pending)} 条（复刻生成时入库）"


def _materialize_items(task, novel_id):
    """把已采纳条目写入目标书知识库（角色/世界观/大纲树），回填 target_id。返回计数。"""
    counts = {"characters": 0, "world": 0, "outline": 0}
    adopted = DeconstructItem.query.filter_by(task_id=task.id, status="adopted") \
        .order_by(DeconstructItem.id).all()
    for item in adopted:
        if item.target_id:
            # 已落库过，跳过（幂等，不计入新增）
            continue
        data = _item_data(item)
        if item.kind == "character":
            # 生命周期计划（时间轴锚点为关键事件名；事件→章节的换算在写作页联动时做）
            plan = {}
            for k in ("first_event", "exit_event", "exit_mode"):
                v = _s(data.get(k, "")).strip()
                if v:
                    plan[k] = v
            char = Character(
                novel_id=novel_id,
                name=_s(data.get("name")).strip() or item.title or "角色",
                personality=_s(data.get("personality", "")),
                speaking_style=_s(data.get("speaking_style", "")),
                appearance=_s(data.get("appearance", "")),
                background=_s(data.get("background", "")),
                motivation=_s(data.get("motivation", "")),
                arc_direction=_s(data.get("arc_direction", "")),
                status_json=json.dumps({"plan": plan}, ensure_ascii=False) if plan else "{}",
            )
            db.session.add(char)
            db.session.flush()
            item.target_id = char.id
            counts["characters"] += 1

        elif item.kind == "world":
            ws = WorldSetting(
                novel_id=novel_id,
                category=_s(data.get("category")).strip() or "规则",
                title=_s(data.get("title")).strip() or item.title or "设定",
                content=_s(data.get("content", "")),
            )
            db.session.add(ws)
            db.session.flush()
            item.target_id = ws.id
            counts["world"] += 1

        elif item.kind == "outline":
            # 卷（阶段）→ 章，两级树；卷名做归一匹配（LLM 对同一卷名的写法可能抖动）
            phase = _s(data.get("phase")).strip()
            parent = None
            if phase:
                norm = re.sub(r"[\s:：·、，,]+", "", phase)
                for vol in OutlineNode.query.filter_by(novel_id=novel_id, node_type="volume").all():
                    if re.sub(r"[\s:：·、，,]+", "", vol.title or "") == norm:
                        parent = vol
                        break
                if not parent:
                    parent = OutlineNode(novel_id=novel_id, node_type="volume",
                                         title=phase, sort_order=_next_outline_order(novel_id, None))
                    db.session.add(parent)
                    db.session.flush()
            node = OutlineNode(
                novel_id=novel_id, parent_id=parent.id if parent else None,
                sort_order=_next_outline_order(novel_id, parent.id if parent else None),
                node_type="chapter",
                title=_s(data.get("title")).strip() or item.title or "章节",
                summary=_s(data.get("summary", "")),
            )
            db.session.add(node)
            db.session.flush()
            item.target_id = node.id
            counts["outline"] += 1
    return counts


def _event_chapter_map(novel_id):
    """事件名 → 章节号映射（来自已采纳大纲条目建出的章）。

    拆解锚点是关键事件名，新书的章也是关键事件建的——事件名即换算表。
    """
    mapping = {}
    for ch in Chapter.query.filter_by(novel_id=novel_id).all():
        if not ch.outline_node_id:
            continue
        node = db.session.get(OutlineNode, ch.outline_node_id)
        if node and node.title and node.title.strip():
            mapping.setdefault(node.title.strip(), ch.chapter_number)
    return mapping


def _materialize_foreshadows(task, novel, event_map):
    """把已采纳伏笔条目写入 Foreshadowing（双锚点 + 证据，jarvis-write 语义）。

    返回 (count, warnings)：锚点事件未建章时降级为 null 并记警告（StoryForge 纪律：
    不确定章号就传 null，不瞎猜）。
    """
    adopted = DeconstructItem.query.filter_by(task_id=task.id, kind="foreshadow", status="adopted") \
        .order_by(DeconstructItem.id).all()
    warnings = []
    count = 0
    for item in adopted:
        if item.target_id:
            continue  # 已落库，幂等
        data = _item_data(item)
        planted_event = _s(data.get("planted_event", "")).strip()
        resolve_event = _s(data.get("resolve_event", "")).strip()
        planted = event_map.get(planted_event) if planted_event else None
        expected = event_map.get(resolve_event) if resolve_event else None
        if planted_event and planted is None:
            warnings.append(f"伏笔「{item.title}」的埋设事件「{planted_event}」没有对应章节（该大纲条目未采纳）")
        try:
            importance = max(1, min(10, int(data.get("importance") or 5)))
        except (TypeError, ValueError):
            importance = 5
        fs = Foreshadowing(
            novel_id=novel.id,
            title=_s(data.get("title")).strip() or item.title or "伏笔",
            description=_s(data.get("description", "")),
            planted_chapter=planted,
            resolve_chapter=None,  # 回收章由生成过程的真实正文确认（抽取队列），计划值放 expected
            expected_resolve_chapter=expected,
            earliest_resolve_chapter=(planted + 1) if planted else None,
            status="planned",
            importance=importance,
            source_event=";".join(x for x in [planted_event, resolve_event] if x),
            timeout_threshold=30 if importance >= 8 else 20 if importance >= 5 else 15,
        )
        db.session.add(fs)
        db.session.flush()
        item.target_id = fs.id
        count += 1
    return count, warnings


def unwritten_chapters(novel_id, limit=None):
    """目标书中还没有任何正文版本的章节（按章号序）。

    limit 归一：None 视为不限；给定时至少 1（0/负数是调用方 bug，兜底为 1
    而不是 falsy 退化成「无上限全本生成」）。
    """
    if limit is not None:
        limit = max(int(limit), 1)
    result = []
    for ch in Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.chapter_number).all():
        if not ChapterVersion.query.filter_by(chapter_id=ch.id).first():
            result.append(ch)
            if limit and len(result) >= limit:
                break
    return result


def materialized_items_count(task_id):
    """已落库且知识库实体仍然存在的条目数。

    实体被用户从知识库删除后不再计数——重拆守卫不能拿「假逃生通道」
    （提示用户去删，删了却依然 409）把任务永久锁死。
    """
    count = 0
    adopted = DeconstructItem.query.filter_by(task_id=task_id, status="adopted").all()
    for item in adopted:
        if not item.target_id:
            continue
        if item.kind == "character":
            alive = db.session.get(Character, item.target_id)
        elif item.kind == "world":
            alive = db.session.get(WorldSetting, item.target_id)
        elif item.kind == "outline":
            alive = db.session.get(OutlineNode, item.target_id)
        else:
            alive = None
        if alive:
            count += 1
    return count


def _next_outline_order(novel_id, parent_id):
    """同一父节点下的大纲排序号。"""
    max_order = db.session.query(db.func.max(OutlineNode.sort_order)).filter_by(
        novel_id=novel_id,
        parent_id=parent_id if parent_id is not None else None,
    ).scalar()
    return (max_order or 0) + 1


def _materialize_chapters(task, novel):
    """为已采纳 outline 条目补建 Chapter 行（幂等：跳过已链接章节）。"""
    adopted = DeconstructItem.query.filter_by(task_id=task.id, kind="outline", status="adopted") \
        .order_by(DeconstructItem.id).all()
    existing_max = db.session.query(db.func.max(Chapter.chapter_number)).filter_by(
        novel_id=novel.id).scalar() or 0
    created = []
    for item in adopted:
        node = db.session.get(OutlineNode, item.target_id) if item.target_id else None
        if not node:
            continue
        linked = Chapter.query.filter_by(outline_node_id=node.id).first()
        if linked:
            continue
        existing_max += 1
        ch = Chapter(
            novel_id=novel.id,
            chapter_number=existing_max,
            title=node.title or f"第{existing_max}章",
            outline=node.summary or "",
            outline_node_id=node.id,
        )
        db.session.add(ch)
        db.session.flush()
        created.append(ch)
    return created


# ---------------------------------------------------------------------------
# AI 差异化改写（保功能、换皮肉；改写稿进 modified_content 由人工审阅签字）
# ---------------------------------------------------------------------------

_REWORK_KEYS = {"character": CHARACTER_KEYS, "world": WORLD_KEYS,
                "outline": OUTLINE_KEYS, "foreshadow": FORESHADOW_KEYS}

_REWORK_KEEP_HINTS = {
    "character": "角色定位(主角/反派等)、性格骨架、弧光方向、与他人关系的类型、首现/退场事件锚点",
    "world": "该设定在故事中的规则结构与功能",
    "outline": "所属阶段、本章节的节奏功能(钩子位置/冲突升级方式)",
    "foreshadow": "埋设与回收的事件锚点(planted_event/resolve_event 原样保留)、重要度",
}

REWORK_SYSTEM = """你是一位网文差异化改写师。把拆解自对标书的设定条目改写为**新书的原创内容**。

【改写边界】
- 必须保留(结构功能):{keep}
- 必须更换:人名/地名/势力名等一切专名、情节的表面动作与场景、具体设定细节——不得残留原书任何专名
- 未提及的细节可自由重组,但不得与保留项矛盾

【防偷懒红线】仅替换人名不算改写:每个情节单元的动作、因果、场景必须与原书明显拉开,复述原书情节即视为失败。字不抄、话不抄,只抄结构与因果。

【本书差异方向(微创新指令)】{modifications}

【输出】只输出 JSON 对象,字段名与输入完全一致;「必须保留」的字段保留原值,其余全部重写。"""

NAME_MAP_PROMPT = """你是网文改名师。下面是从对标书拆出的人物名与设定名清单。请为每个名字设计一个全新的中文名/名号(风格与题材相符,绝不与原名相同或谐音),保证全员改名后人物关系与称呼仍然成立。
并给出本书与原书的差异轴组合:主角类型 × 冲突来源 × 情绪基调,必须给出与原书不同的组合(如原书是"天才少年×夺宝×热血",改为"小人物×生计×冷")。

只输出 JSON:
{{"mapping": {{"旧名": "新名"}}, "axes": "差异轴一句话"}}"""


def _rework_llm(kind, data, modifications, name_mapping=None):
    """纯 LLM 改写（无 DB 访问，可入线程池）。返回 (sanitized, warnings, error)。"""
    keys = _REWORK_KEYS.get(kind) or ()
    system = (REWORK_SYSTEM
              .replace("{keep}", _REWORK_KEEP_HINTS.get(kind, ""))
              .replace("{modifications}", modifications or "(未设置——在满足边界的前提下自由发散)"))
    user_parts = [f"【条目类型】{kind}", f"【原条目】{json.dumps(data, ensure_ascii=False)}"]
    if name_mapping:
        # 只传与本条目相关的映射,减少无关干扰
        text = json.dumps(data, ensure_ascii=False)
        relevant = {o: n for o, n in name_mapping.items() if o and o in text}
        if relevant:
            user_parts.append(f"【全书改名映射表(涉及这些名字时必须采用新名)】{json.dumps(relevant, ensure_ascii=False)}")
    cfg = get_model_config(agent_type="writer")
    try:
        out = call_llm_sync(
            model=cfg["model_name"],
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": "\n".join(user_parts)},
            ],
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=cfg["temperature"],
            max_tokens=2048,
        )
    except LLMError as e:
        return None, None, str(e)
    reworked = _extract_json(out or "")
    if not reworked:
        return None, None, "改写输出无法解析为 JSON，请重试"
    sanitized = {k: _s(reworked.get(k, data.get(k, ""))) for k in keys}
    warnings = _rework_warnings(kind, data, sanitized)
    return sanitized, warnings, None


def _rework_warnings(kind, original, reworked):
    """确定性校验（advisory 只提示不拦截）：同名未换 / 结构锚点被误改。"""
    warnings = []
    if kind in ("character", "world"):
        name_key = "name" if kind == "character" else "title"
        if _s(reworked.get(name_key)).strip() == _s(original.get(name_key)).strip():
            warnings.append("名称未改")
    if kind == "outline" and _s(reworked.get("phase")).strip() != _s(original.get("phase")).strip():
        warnings.append("阶段锚点被改动")
    if kind == "foreshadow":
        for k in ("planted_event", "resolve_event"):
            if _s(reworked.get(k)).strip() != _s(original.get(k)).strip():
                warnings.append("事件锚点被改动")
                break
    return warnings


def rework_item(item_id, name_mapping=None):
    """AI 改写单条待确认条目：改写稿写入 modified_content（人工可继续编辑/还原）。

    返回 (ok, message, warnings)。
    """
    item = db.session.get(DeconstructItem, item_id)
    if not item:
        return False, f"条目 {item_id} 不存在", []
    if item.status == "adopted" and item.target_id:
        return False, f"「{item.title}」已写入知识库，不可改写", []
    if item.kind not in _REWORK_KEYS:
        return False, f"未知条目类型: {item.kind}", []
    modifications = _s(item.task.modifications_text).strip()
    sanitized, warnings, err = _rework_llm(item.kind, _item_data(item), modifications, name_mapping)
    if err:
        return False, f"改写失败: {err}", []
    item.modified_content = json.dumps(sanitized, ensure_ascii=False)
    db.session.commit()
    msg = f"已改写「{item.title}」"
    if warnings:
        msg += "（⚠ " + "、".join(warnings) + "，请人工复核）"
    return True, msg, warnings


def rework_all_items(task_id):
    """批量成套改写：先生成新旧名映射表与差异轴，再分波并发逐条改写。

    yield 进度流；全部改写稿只进 modified_content，等人工逐条审阅采纳。
    """
    task = _load_task(task_id)
    items = DeconstructItem.query.filter_by(task_id=task_id) \
        .filter(DeconstructItem.status.in_(("pending", "adopted")),
                DeconstructItem.target_id.is_(None)) \
        .order_by(DeconstructItem.id).all()
    if not items:
        yield "没有可改写的条目（已入库的条目不可改写）\n"
        return
    modifications = _s(task.modifications_text).strip()

    # 1) 成套改名映射表 + 差异轴（成套一致性：全员改名关系不断）
    name_mapping, axes = {}, ""
    names = []
    for it in items:
        d = _item_data(it)
        name = _s(d.get("name") if it.kind == "character" else d.get("title", "")).strip()
        if name:
            names.append(name)
    if names:
        yield f"[改写] 共 {len(items)} 条；先生成新旧名映射表（{len(names)} 个专名）…\n"
        cfg = get_model_config(agent_type="writer")
        try:
            out = call_llm_sync(
                model=cfg["model_name"],
                messages=[
                    {"role": "system", "content": NAME_MAP_PROMPT},
                    {"role": "user", "content": f"【微创新方向】{modifications or '(未设置)'}\n【名字清单】{json.dumps(names, ensure_ascii=False)}"},
                ],
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
                provider_type=cfg.get("provider_type", "deepseek"),
                temperature=cfg["temperature"],
                max_tokens=2048,
            )
            parsed = _extract_json(out or "") or {}
            if isinstance(parsed.get("mapping"), dict):
                name_mapping = {k: v for k, v in parsed["mapping"].items() if _s(k) and _s(v)}
            axes = _s(parsed.get("axes"))
        except LLMError:
            yield "⚠ 映射表生成失败，转为逐条独立改写（名称一致性请人工核对）\n"
    if axes:
        task.axes_text = axes  # 持久化差异轴：复刻生成时注入写作包(生成期差异化)
        db.session.commit()
        yield f"[差异轴] {axes}\n"

    # 2) 顺序逐条改写（条目量通常 10-40、单条 2-4 秒；LLM 改写质量依赖
    #    映射表与上下文一致性，并发收益小于串行的稳定度）
    work = [(it.id, it.kind, _item_data(it)) for it in items]
    done = 0
    warn_total = 0
    for item_id, kind, data in work:
        sanitized, warnings, err = _rework_llm(kind, data, modifications, name_mapping or None)
        item = db.session.get(DeconstructItem, item_id)
        done += 1
        if err:
            yield f"[改写 {done}/{len(work)}] ✗ {err}\n"
            continue
        item.modified_content = json.dumps(sanitized, ensure_ascii=False)
        db.session.commit()
        warn_total += len(warnings)
        mark = "⚠" if warnings else "✓"
        extra = f"（{'、'.join(warnings)}）" if warnings else ""
        yield f"[改写 {done}/{len(work)}] {mark} {item.title}{extra}\n"
    yield f"✓ 批量改写完成：{len(work)} 条（{warn_total} 条带警告），改写稿已就位，请逐条审阅后采纳\n"


# ---------------------------------------------------------------------------
# 复刻生成
# ---------------------------------------------------------------------------

def _load_elements(task):
    """任务拆解产物 dict（解析失败/非 dict 返回空 dict）。"""
    try:
        data = json.loads(task.elements_json or "{}")
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def apply_blueprint_long(task_id, title="", genre="", novel_id=None, fallback_chapters=0):
    """拆书蓝图 → 长篇落地：建/选 Novel + 已采纳条目入知识库 + 大纲树 + 章节。

    fallback_chapters: 未采纳任何大纲条目时按此数量建空大纲章节兜底
    （章节流水线会自动补大纲）。0 表示不兜底。
    返回 (novel, created_chapters, message)；novel 为 None 表示目标书不存在。
    整个落地在单事务内完成：中途失败由调用方 rollback，不会留下半成品目标书。
    """
    task = _load_task(task_id)
    elements = _load_elements(task)

    st = _dict(elements.get("structure"))
    orh = _dict(elements.get("opening_rhythm"))
    gf = _dict(elements.get("golden_finger"))
    style = _dict(elements.get("style"))

    # 1) 目标书（flush 取 id，不提前 commit）
    #    未显式指定且任务已绑定目标书时复用——重复点击=补充落地，不产生重复空书
    if novel_id is None and task.target_novel_id:
        bound = db.session.get(Novel, task.target_novel_id)
        if bound:
            novel_id = bound.id
    intent = _compose_author_intent(st, gf, orh, style, task.modifications_text)
    if novel_id:
        novel = db.session.get(Novel, novel_id)
        if not novel:
            return None, [], f"目标小说 {novel_id} 不存在"
        if not novel.author_intent:
            novel.author_intent = intent
        if not novel.current_focus:
            novel.current_focus = _compose_current_focus(st)
        message = f"已追加到已有小说 [{novel.id}] {novel.title}"
    else:
        synopsis = "；".join(x for x in [st.get("main_conflict", ""), st.get("theme", "")] if x)
        world_intro = _compose_world_intro(elements)
        novel = Novel(
            title=title or task.title or "复刻新书",
            genre=genre or "",
            synopsis=synopsis,
            world_intro=world_intro,
            author_intent=intent,
            current_focus=_compose_current_focus(st),
        )
        db.session.add(novel)
        db.session.flush()
        message = f"已创建小说 [{novel.id}] {novel.title}"
    task.target_novel_id = novel.id

    # 2) 已采纳条目统一落库（角色/世界观/大纲树，回填 target_id，幂等；只计新增）
    counts = _materialize_items(task, novel.id)

    # 3) 为已采纳大纲条目补建章节
    created_chapters = _materialize_chapters(task, novel)

    # 4) 未采纳任何大纲条目时，按请求章节数建空大纲章节兜底（流水线自动补大纲）
    if not created_chapters and fallback_chapters > 0:
        has_adopted_outline = DeconstructItem.query.filter_by(
            task_id=task.id, kind="outline", status="adopted").count() > 0
        if not has_adopted_outline:
            base = db.session.query(db.func.max(Chapter.chapter_number)).filter_by(
                novel_id=novel.id).scalar() or 0
            for i in range(1, fallback_chapters + 1):
                ch = Chapter(novel_id=novel.id, chapter_number=base + i, title=f"第{base + i}章")
                db.session.add(ch)
                created_chapters.append(ch)

    # 4.5) 伏笔计划值落库（事件锚 → 章节号，确定性查表换算）
    event_map = _event_chapter_map(novel.id)
    fs_count, fs_warnings = _materialize_foreshadows(task, novel, event_map)
    counts["foreshadow"] = fs_count
    from app.services.narrative_plan import resolve_plan_chapters
    resolve_plan_chapters(novel.id, event_map)
    from app.services.semantic_service import embed_novel_entities
    embed_novel_entities(novel.id)

    # 4.6) 蓝图采纳条目→嵌入资源库(语义检索供后续章节生成引用)
    try:
        from app.services.resource_service import add_resource
        from app.models.resource import ResourceBook
        bp_title = f"{task.title}·蓝图" if task.title else "拆书蓝图"
        existing_bp = ResourceBook.query.filter_by(title=bp_title, source_type="blueprint").first()
        if not existing_bp and counts.get("characters", 0) + counts.get("world", 0) > 0:
            blueprint_text = "\n\n".join(
                f"{d.get('name') or d.get('title', '')}：{_s(d.get('personality') or d.get('content') or d.get('summary') or '')}"
                for d in (_item_data(i) for i in
                          DeconstructItem.query.filter_by(task_id=task.id, status="adopted").all())
            )
            if blueprint_text.strip():
                add_resource(bp_title, blueprint_text, source_type="blueprint")
    except Exception:
        pass  # 蓝图入库失败不影响落地
    message = (f"{message}（新增：人物 {counts['characters']} / 世界观 {counts['world']}"
               f" / 大纲 {counts['outline']} / 伏笔 {counts['foreshadow']}）")
    if fs_warnings:
        message += "；⚠ " + "；".join(fs_warnings[:3]) + ("…" if len(fs_warnings) > 3 else "")

    # 5) 蓝图注入创作罗盘/世界观简述（新书已注入；已有书仅在空时补）
    if not novel.synopsis:
        novel.synopsis = "；".join(x for x in [st.get("main_conflict", ""), st.get("theme", "")] if x)
    if not novel.world_intro:
        novel.world_intro = _compose_world_intro(elements)

    db.session.commit()
    return novel, created_chapters, message


_INJECTION_RE = re.compile(
    r"(忽略|无视)(之前|上面|以上|先前|此前)|ignore (all )?(previous|above|prior)"
    r"|system prompt|你现在是|请扮演|act as (a|an) ", re.I)


def _sanitize_injection(text):
    """软防御(P1-1):对标书是任意外部文本,剥离疑似指令式语句,
    防止 prompt injection 经拆解产物驻留进创作罗盘(永不压缩通道)。"""
    lines = [ln for ln in _s(text).splitlines() if not _INJECTION_RE.search(ln)]
    cleaned = chr(10).join(lines).strip()
    return cleaned or _s(text).strip()


def _budget_join(parts, limit=480):
    """把候选行按序拼进字数预算（创作罗盘 author_intent 约 500 字上限）。"""
    out, total = [], 0
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if total + len(p) > limit:
            break
        out.append(p)
        total += len(p)
    return "\n".join(out)


def _compose_author_intent(st, gf, orh, style=None, modifications=""):
    """全书承诺（创作罗盘 author_intent）。

    这是节奏/文风/金手指进入每章生成链的通道（罗盘注入且上下文压缩永不裁）：
    开篇钩子、节奏特征与迁移手法、文风基调与手法、金手指成长线、微创新方向。
    """
    st, gf, orh, style = _dict(st), _dict(gf), _dict(orh), _dict(style)
    parts = []
    if gf.get("name"):
        parts.append(f"金手指：{gf['name']}（{gf.get('type', '')}），{_s(gf.get('growth_design', ''))[:80]}")
    if st.get("main_conflict"):
        parts.append(f"核心冲突：{st['main_conflict']}")
    if st.get("theme"):
        parts.append(f"主题：{st['theme']}")
    hook = orh.get("hook")
    if isinstance(hook, dict) and hook.get("description"):
        parts.append(f"开篇钩子（复刻）：{_s(hook['description'])[:80]}")
    for f in _list(orh.get("pacing_features"))[:2]:
        parts.append(f"节奏特征（复刻）：{_s(f)[:60]}")
    for m in _list(orh.get("migratable_methods"))[:2]:
        parts.append(f"节奏手法（复刻）：{_s(m)[:60]}")
    if style.get("tone"):
        parts.append(f"文风（复刻）：{_s(style['tone'])[:60]}")
    for m in _list(style.get("migratable_methods"))[:2]:
        parts.append(f"文风手法（复刻）：{_s(m)[:60]}")
    for m in _list(gf.get("migratable_methods"))[:1]:
        parts.append(f"金手指手法（复刻）：{_s(m)[:60]}")
    mods = _s(modifications).strip()
    if mods:
        parts.append(f"微创新方向（必须执行）：{mods[:150]}")
    return _sanitize_injection(_budget_join(parts)) or "对标书复刻（待补充全书承诺）"


def _compose_current_focus(st):
    stages = _list(_dict(st).get("stages"))
    if stages and isinstance(stages[0], dict):
        return f"开篇阶段：{stages[0].get('stage_name', '')}"
    return ""


def _compose_world_intro(elements):
    world = [w for w in _list(elements.get("world")) if isinstance(w, dict)]
    lines = []
    for w in world:
        if w.get("title"):
            lines.append(f"[{w.get('category', '设定')}] {w['title']}：{w.get('content', '')}")
    return "\n".join(lines)


def apply_blueprint_short(task_id, title="", genre="", word_target=3000):
    """拆书蓝图 → 短篇落地：建 ShortStory，已采纳条目进策划字段 + 大纲节点。

    返回 (story, message)。
    """
    task = _load_task(task_id)
    elements = _load_elements(task)

    st = _dict(elements.get("structure"))
    style = _dict(elements.get("style"))

    adopted_char = DeconstructItem.query.filter_by(task_id=task.id, kind="character", status="adopted") \
        .order_by(DeconstructItem.id).all()
    adopted_world = DeconstructItem.query.filter_by(task_id=task.id, kind="world", status="adopted") \
        .order_by(DeconstructItem.id).all()
    adopted_outline = DeconstructItem.query.filter_by(task_id=task.id, kind="outline", status="adopted") \
        .order_by(DeconstructItem.id).all()

    plan_chars = _render_characters(adopted_char)
    plan_setting = _render_world(adopted_world)
    plan_theme = _s(st.get("theme", ""))

    nodes = []
    for i, item in enumerate(adopted_outline, start=1):
        data = _item_data(item)
        nodes.append({
            "id": f"n{i}", "act": _s(data.get("phase", "正题")) or "正题",
            "title": _s(data.get("title")) or item.title,
            "summary": _s(data.get("summary", "")),
            "word_count": int((word_target or 3000) / max(len(adopted_outline), 1)),
            "status": "pending", "content": "",
        })

    story = ShortStory(
        title=title or task.title or "复刻短篇",
        mode="setting",
        genre=genre or "",
        theme=plan_theme,
        plan_characters=plan_chars,
        plan_setting=plan_setting,
        tone=_s(style.get("tone", "")),
        word_target=word_target or 3000,
        extra_instructions=_s(task.modifications_text),
        outline_nodes=json.dumps(nodes, ensure_ascii=False),
        status="draft",
    )
    db.session.add(story)
    db.session.flush()
    task.target_short_story_id = story.id
    db.session.commit()
    return story, f"已创建短篇 [{story.id}] {story.title}（角色/世界观/大纲节点已写入策划）"


def _render_characters(items):
    lines = []
    for item in items:
        d = _item_data(item)
        lines.append(f"### {d.get('name') or item.title}（{d.get('role', '')}）")
        for key, label in [("personality", "性格"), ("speaking_style", "说话风格"), ("appearance", "外貌"),
                           ("background", "背景"), ("motivation", "动机"), ("arc_direction", "弧光")]:
            if d.get(key):
                lines.append(f"- {label}：{d[key]}")
        if d.get("relationships"):
            lines.append(f"- 关系：{d['relationships']}")
    return "\n".join(lines)


def _render_world(items):
    lines = []
    for item in items:
        d = _item_data(item)
        lines.append(f"**[{d.get('category', '设定')}] {d.get('title') or item.title}**")
        if d.get("content"):
            lines.append(d["content"])
        lines.append("")
    return "\n".join(lines).strip()
