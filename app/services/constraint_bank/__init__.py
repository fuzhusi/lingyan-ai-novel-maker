"""约束词库包：L0-L3 数据文件与本装配器同目录。

用法：
    from app.services.constraint_bank import assemble_constraints
    asm = assemble_constraints(agent_type="writer", genre=novel.genre)
    constraints = asm["text"] or DEFAULT_WRITER_CONSTRAINTS
"""
from app.services.constraint_bank.assembler import (  # noqa: F401
    CONSTRAINT_BUDGET_CHARS,
    assemble_constraints,
    get_constraints_text,
    get_last_assembly,
    is_constraint_bank_enabled,
    load_bank,
)

__all__ = ["assemble_constraints", "load_bank", "CONSTRAINT_BUDGET_CHARS",
           "is_constraint_bank_enabled", "get_last_assembly",
           "get_constraints_text"]
