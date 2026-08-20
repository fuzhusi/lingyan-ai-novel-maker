# 测试套件

## 概述

本目录包含灵砚 (LingYan) AI 小说创作系统的单元测试和集成测试。

## 测试内容

### 1. Skill System 测试 (`test_skill_system.py`)

**测试时间**: 2025-08-14  
**测试文件**: `tests/test_skill_system.py`  
**测试模块**: `app/services/skill_system.py`

#### 测试范围

| 测试类 | 测试内容 | 测试数量 |
|--------|----------|----------|
| `TestBuiltinSkills` | 内置技能数据完整性验证 | 3 |
| `TestActiveSkills` | 活跃技能的获取和设置 | 3 |
| `TestCustomSkills` | 自定义技能的 CRUD 操作 | 4 |
| `TestSkillPromptBuilding` | 技能提示词构建逻辑 | 4 |
| `TestContextInjectionSafety` | 上下文注入安全性检测 | 3 |
| **总计** | | **17** |

#### 测试结果

**测试时间**: 2025-08-14  
**测试状态**: ✅ 全部通过 (17/17)

```
============================= test session starts ==============================
platform linux -- Python 3.14.4, pytest-9.1.1, pluggy-1.6.0
collecting ... collected 17 items

tests/test_skill_system.py::TestBuiltinSkills::test_all_builtin_skills_have_required_fields PASSED [  5%]
tests/test_skill_system.py::TestBuiltinSkills::test_builtin_skills_count PASSED [ 11%]
tests/test_skill_system.py::TestBuiltinSkills::test_deai_skills_present PASSED [ 17%]
tests/test_skill_system.py::TestActiveSkills::test_default_active_skills PASSED [ 23%]
tests/test_skill_system.py::TestActiveSkills::test_set_active_skills PASSED [ 29%]
tests/test_skill_system.py::TestActiveSkills::test_set_active_skills_empty PASSED [ 35%]
tests/test_skill_system.py::TestCustomSkills::test_save_custom_skill PASSED [ 41%]
tests/test_skill_system.py::TestCustomSkills::test_delete_custom_skill PASSED [ 47%]
tests/test_skill_system.py::TestCustomSkills::test_delete_nonexistent_skill PASSED [ 52%]
tests/test_skill_system.py::TestCustomSkills::test_get_all_skills_includes_custom PASSED [ 58%]
tests/test_skill_system.py::TestSkillPromptBuilding::test_build_prompt_with_no_active_skills PASSED [ 64%]
tests/test_skill_system.py::TestSkillPromptBuilding::test_build_prompt_with_active_skills PASSED [ 70%]
tests/test_skill_system.py::TestSkillPromptBuilding::test_prompt_contains_constraints PASSED [ 76%]
tests/test_skill_system.py::TestSkillPromptBuilding::test_multiple_skills_prompt PASSED [ 82%]
tests/test_skill_system.py::TestContextInjectionSafety::test_custom_skill_prompt_no_injection PASSED [ 88%]
tests/test_skill_system.py::TestContextInjectionSafety::test_skill_prompt_escape_special_chars PASSED [ 94%]
tests/test_skill_system.py::TestContextInjectionSafety::test_builtin_skills_no_injection_risk PASSED [100%]

============================== 17 passed, 41 warnings in 2.56s ==============================
```

#### 测试详情

1. **内置技能完整性**
   - 验证所有 12 个内置技能包含必需字段 (`name`, `description`, `prompt`)
   - 验证核心去 AI 化技能存在 (5 个)

2. **活跃技能管理**
   - 默认激活 5 个去 AI 化核心技能
   - 支持设置和清空活跃技能列表

3. **自定义技能 CRUD**
   - 保存自定义技能
   - 删除自定义技能
   - 删除不存在的技能不报错
   - 自定义技能与内置技能合并

4. **提示词构建**
   - 无活跃技能时返回空字符串
   - 有活跃技能时返回格式化提示词
   - 提示词包含技能约束
   - 多个技能正确合并

5. **上下文注入安全性**
   - 自定义技能提示词不包含恶意注入
   - 技能提示词正确处理特殊字符
   - 内置技能无注入风险

#### 发现的问题

**逻辑漏洞**:
1. **无输入验证**: `save_custom_skill` 不验证 `skill_data` 结构，可保存任意数据
2. **无长度限制**: 技能提示词无长度限制，可能导致上下文溢出
3. **无重复检查**: 可以覆盖已存在的自定义技能（无确认机制）
4. **无权限控制**: 任何用户都可以创建/删除自定义技能

**上下文注入风险**:
1. **用户输入直接注入**: 自定义技能的 `prompt` 字段直接注入到系统提示中，无过滤
2. **特殊字符未转义**: JSON 序列化时使用 `ensure_ascii=False`，特殊字符可能被误解
3. **无沙箱隔离**: 技能提示词与系统提示在同一上下文中，可能被恶意利用

#### 运行测试

```bash
# 运行所有测试
pytest tests/

# 运行 Skill System 测试
pytest tests/test_skill_system.py

# 运行并显示详细输出
pytest tests/test_skill_system.py -v

# 运行并显示覆盖率
pytest tests/test_skill_system.py --cov=app.services.skill_system
```

#### 依赖

- pytest >= 7.0
- pytest-cov (可选，用于覆盖率)

---

## 测试目录结构

```
tests/
├── __init__.py
├── README.md
├── test_skill_system.py      # Skill System 单元测试 (17)
├── test_outline_nodes.py     # 剧情大纲节点解析测试 (8)
└── test_gen_ch1.py           # 第一章生成测试脚本
```

### 3. 剧情大纲节点解析测试 (`test_outline_nodes.py`)

**测试时间**: 2025-08-14  
**测试文件**: `tests/test_outline_nodes.py`  
**测试模块**: `app/routes/short_story/generate.py`

#### 测试内容

- 从发散 Agent 输出的构思文本中解析节点列表
- 空文本 / 无节点 / 坏格式处理
- 节点 id 连续性校验
- `load_outline_nodes` 读取与容错（空 / 损坏 JSON）

#### 测试数量

- `TestParseOutlineNodes`: 5 个用例
- `TestLoadOutlineNodes`: 3 个用例
- 总计: **8 个**

### 2. 第一章生成测试 (`test_gen_ch1.py`)

**测试时间**: 2025-08-14  
**测试文件**: `tests/test_gen_ch1.py`  
**测试类型**: 一次性脚本测试

#### 测试内容

- CLI 触发第一章生成（非流式）
- 复用项目内的 prompt + deai + save_version
- 测试完整的章节生成流程

#### 运行测试

```bash
# 运行第一章生成测试
python tests/test_gen_ch1.py
```

---

## 待添加测试

- [ ] Prompt Builder 测试 (`test_prompt_builder.py`)
- [ ] De-AI Agent 测试 (`test_deai_agent.py`)
- [ ] Quality Audit 测试 (`test_quality_audit.py`)
- [ ] Causal Chain 测试 (`test_causal_chain.py`)
- [ ] Vector Memory 测试 (`test_vector_memory.py`)
- [ ] API 路由测试 (`test_routes.py`)
- [ ] 数据库模型测试 (`test_models.py`)

---

*最后更新: 2025-08-14*
