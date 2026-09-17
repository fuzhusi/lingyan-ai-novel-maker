"""章节大纲固定格式（7 字段）——CLI 手写入口与 AI 生成提示词的共享契约。

AI 生成大纲的 system prompt（prompt_builder/writer.py）与前端一键模板
（static/js/outline-template.js）遵循同一套字段；本模块是 Python 侧的
单一真源，供 CLI 打印模板与软校验手写大纲。三处字段名必须保持一致，
test_cli_outline_template.py 锁定。
"""

OUTLINE_FIELDS = (
    "【本章定位】", "【核心事件】", "【出场人物】", "【场景节拍】",
    "【情感基调】", "【伏笔操作】", "【结尾钩子】",
)

OUTLINE_TEMPLATE = """【本章定位】推进：
【核心事件】1.
【出场人物】（人名须与人物卡完全一致；仅提及的标（背景提及））
【场景节拍】1.
【情感基调】→
【伏笔操作】埋设：
【结尾钩子】"""


def check_outline_format(outline):
    """检查大纲是否含全部 7 字段。空大纲视为合规（不检查）。

    Returns: (ok: bool, missing: list[str])
    """
    text = outline or ""
    if not text.strip():
        return True, []
    missing = [f for f in OUTLINE_FIELDS if f not in text]
    return not missing, missing
