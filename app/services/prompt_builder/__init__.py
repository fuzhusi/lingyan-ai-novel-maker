"""提示词构建包 — 按 Agent 类型拆分的提示词构建器。

统一导出所有构建函数，保持向后兼容。
"""
from app.services.prompt_builder.context import (
    _section, _load_system_prompt, _load_constraints,
    DEFAULT_WRITER_CONSTRAINTS, assemble_chapter_context,
)
from app.services.prompt_builder.writer import (
    build_writer_prompt, build_outline_prompt,
)
from app.services.prompt_builder.review import (
    build_critic_prompt, build_summary_prompt, build_rewrite_prompt,
)
from app.services.prompt_builder.keepers import (
    build_character_keeper_prompt, build_lore_keeper_prompt,
    build_foreshadow_keeper_prompt, build_editor_prompt,
)

__all__ = [
    "DEFAULT_WRITER_CONSTRAINTS",
    "assemble_chapter_context",
    "build_writer_prompt",
    "build_outline_prompt",
    "build_critic_prompt",
    "build_summary_prompt",
    "build_rewrite_prompt",
    "build_character_keeper_prompt",
    "build_lore_keeper_prompt",
    "build_foreshadow_keeper_prompt",
    "build_editor_prompt",
]
