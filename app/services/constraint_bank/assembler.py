"""约束词库装配器：从词库数据文件按预算装配约束文本。

设计要点（docs/约束promote engineer.md §五、constraint_bank/README.md）：
- 词库完整性 ≠ 注入量：按 agent/体裁挑选模块，总字符数受预算硬上限保护——
  解决「词库越大 → attention 越稀释」的矛盾；
- 保护序：超预算时先丢 P2（词表过渡清单）再丢 P1（场景模块）；
  P0（核心层与正向要求类）永不裁剪，防止滑向「全是禁止、没有正向注入」；
- 装配失败永不阻断生成：本模块只返回空串，由调用方走 fallback
  （与 get_skill_prompt 的容错哲学一致）。
"""
import logging
import os
import re

logger = logging.getLogger(__name__)

BANK_DIR = os.path.dirname(os.path.abspath(__file__))
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)
_MODULE_FILE_RE = re.compile(r"^L\d_.+\.md$")

# 总预算（字符）。决议记录：先按 1800 试运行，Phase D 用 A/B 人味分数据校准。
CONSTRAINT_BUDGET_CHARS = 1800

_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}

_cache = None

# 最近装配快照，按 agent_type 分键（critic/rewrite/editor 各记各的，
# 互不覆盖；空结果也记录并带 reason，保证回显语义真实）
_LAST_ASSEMBLY = {}


def _parse_front_matter(raw):
    """解析词库模块的简易 front matter（扁平 key: value，支持缩进续行与 [] 列表）。

    不引入 pyyaml 依赖——字段格式由本仓库自控，手工解析足够且不会因
    YAML 特殊字符（中文引号/书名号）出幺蛾子。
    """
    meta = {}
    last_key = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1] in (" ", "\t") and last_key:
            meta[last_key] = meta[last_key] + " " + stripped
            continue
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        last_key = key.strip()
        meta[last_key] = value.strip()

    agents_raw = meta.get("agents", "")
    inner = str(agents_raw).strip().strip("[]")
    meta["agents"] = [a.strip() for a in inner.split(",") if a.strip()] \
        if inner else []
    try:
        meta["budget_chars"] = int(meta.get("budget_chars", 320))
    except ValueError:
        meta["budget_chars"] = 320
    meta["enabled"] = str(meta.get("enabled", "true")).strip().lower() != "false"
    meta["priority"] = str(meta.get("priority", "P1")).strip().upper()
    return meta


def load_bank(force_refresh=False):
    """加载词库全部模块（带文件指纹缓存：任何模块增删改自动重载）。

    返回 list[dict]，每个元素含 front matter 元数据 + body/body_chars/file。
    目录缺失时返回空列表（调用方据此走 fallback），不抛异常；
    单个模块解析失败只跳过该模块并告警，不影响其余。
    """
    global _cache
    # 指纹探测：每次调用的开销是十来次 stat，远小于一次 LLM 生成，
    # 换取「改词库文件即时生效」——A/B 调参期频繁编辑模块是常态
    try:
        names = sorted(n for n in os.listdir(BANK_DIR)
                       if _MODULE_FILE_RE.match(n))
        fingerprint = tuple(
            (n,
             os.path.getmtime(os.path.join(BANK_DIR, n)),
             os.path.getsize(os.path.join(BANK_DIR, n)))
            for n in names)
    except OSError:
        logger.warning("constraint bank 目录不可读，词库停用", exc_info=True)
        return []

    if _cache is not None and not force_refresh and _cache[0] == fingerprint:
        return _cache[1]

    modules = []
    for name in names:
        path = os.path.join(BANK_DIR, name)
        try:
            # utf-8-sig 兼容 Windows 编辑器写入的 UTF-8 BOM
            with open(path, encoding="utf-8-sig") as fh:
                text = fh.read()
        except Exception:
            # 解码失败等单文件问题只跳过该文件，绝不外泄中断整体装配
            logger.warning("constraint bank: %s 读取/解码失败，跳过", name,
                           exc_info=True)
            continue
        m = _FRONT_MATTER_RE.match(text)
        if not m:
            logger.warning("constraint bank: %s 缺少 front matter，跳过", name)
            continue
        meta = _parse_front_matter(m.group(1))
        body = m.group(2).strip()
        if not body or not meta.get("id"):
            logger.warning("constraint bank: %s 元数据或正文为空，跳过", name)
            continue
        meta["body"] = body
        meta["body_chars"] = len(body)
        meta["file"] = name
        modules.append(meta)

    _cache = (fingerprint, modules)
    return modules


def is_constraint_bank_enabled():
    """全局开关：Setting 键 ``constraint_bank_enabled``（缺省启用）。

    无应用上下文（裸脚本等）时按启用处理——词库装配不因检查不了开关而瘫痪；
    关闭的唯一入口是显式写入该 Setting（Web 设置页 / CLI ``constraint toggle``）。
    """
    try:
        from app.models import Setting
        row = Setting.query.get("constraint_bank_enabled")
        if row is None:
            return True
        return str(row.value).strip().lower() not in ("0", "false", "off")
    except Exception:
        return True


def get_last_assembly():
    """最近装配快照，{agent_type: 条目} 结构（无记录返回空 dict）。

    条目字段：included/dropped/total_chars/budget/genre；
    词库停用或无候选时 included 为空且带 reason 字段——回显不撒谎。
    """
    return {k: dict(v) for k, v in _LAST_ASSEMBLY.items()}


def get_constraints_text(agent_type="writer", genre=None):
    """容错便捷封装：返回装配文本；停用/异常/无模块时返回 None。

    供路由层一行式接入：``xxx + (get_constraints_text("short_story",
    genre=story.genre) or DEFAULT_WRITER_CONSTRAINTS) + yyy``
    """
    try:
        return assemble_constraints(agent_type=agent_type,
                                    genre=genre)["text"] or None
    except Exception:
        logger.warning("constraint bank unavailable for %s", agent_type,
                       exc_info=True)
        return None


def _record_assembly(agent_type, genre, result, reason=None):
    """记录某 agent 的最近装配结果（分键存储，互不覆盖）。"""
    entry = {
        "included": list(result["included"]),
        "dropped": list(result["dropped"]),
        "total_chars": result["total_chars"],
        "budget": result["budget"],
        "genre": genre,
    }
    if reason:
        entry["reason"] = reason
    _LAST_ASSEMBLY[agent_type] = entry


def assemble_constraints(agent_type="writer", genre=None,
                         budget=CONSTRAINT_BUDGET_CHARS):
    """按 Agent 类型与体裁从词库装配约束文本。

    选择规则：
      0. 全局开关关闭时返回空串，调用方自然走兜底；
      1. enabled 且 agents 含 agent_type 且体裁匹配（模块 genre=any 视为全匹配）；
      2. P0 模块无条件入选（即使超预算——正向要求是底线）；
      3. 其余按 P1→P2 依次装入，装不下即弃（记录进 dropped）。
    返回 dict：
      text        装配结果，可直接拼入 system prompt；无可用模块时为 ""
      included    [{"id","chars"}]  实际装配的模块
      dropped     [id]              超预算被裁的模块
      total_chars / budget
    """
    result = {"text": "", "included": [], "dropped": [],
              "total_chars": 0, "budget": budget}

    genre = (genre or "").strip() or None  # 归一化：空白串视同未指定
    if not is_constraint_bank_enabled():
        logger.debug("constraint bank disabled by setting, caller will fallback")
        _record_assembly(agent_type, genre, result, reason="disabled")
        return result

    candidates = [
        m for m in load_bank()
        if m["enabled"]
        and agent_type in m["agents"]
        and (not genre or m.get("genre", "any") in ("any", "", None, genre))
    ]
    if not candidates:
        _record_assembly(agent_type, genre, result, reason="no_modules")
        return result

    candidates.sort(key=lambda m: (_PRIORITY_RANK.get(m["priority"], 9), m["file"]))
    chosen, total = [], 0
    for mod in candidates:
        if mod["priority"] == "P0":
            chosen.append(mod)
            total += mod["body_chars"]
            continue
        if total + mod["body_chars"] <= budget:
            chosen.append(mod)
            total += mod["body_chars"]
        else:
            result["dropped"].append(mod["id"])

    if total > budget:
        logger.warning("constraint bank: P0 模块已超预算 (%d > %d)，照常注入",
                       total, budget)

    result["text"] = "\n\n".join(m["body"] for m in chosen)
    result["included"] = [{"id": m["id"], "chars": m["body_chars"]} for m in chosen]
    result["total_chars"] = total

    global _LAST_ASSEMBLY  # noqa: F841 —— 经由 _record_assembly 分键写入
    _record_assembly(agent_type, genre, result)
    logger.info("constraint assembled: agent=%s modules=%s chars=%d/%d dropped=%s",
                agent_type, [i["id"] for i in result["included"]],
                total, budget, result["dropped"])
    return result
