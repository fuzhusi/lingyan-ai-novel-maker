# 约束词库（Constraint Bank）

> 来源：`docs/约束promote engineer.md` 网络调研（小红书高赞笔记生态 / 知乎 / 今日头条 / SMZDM /
> NGA / LINUX DO / GitHub 开源 skill / 英文社区）+ 项目原有手写约束（DEFAULT_WRITER_CONSTRAINTS）
> + 283 万字对照语料研究（docs/ai-tone-research.md）三方合并去重而成，非单一主观来源。
> 建库日期：2026-08-26。

## 分层设计（解决「词库完整性 ↔ attention 稀释」矛盾）

| 层 | 内容 | 进 prompt？ | 预算 |
|----|------|-----------|------|
| `L0_core.md` | 核心约束：结构分工 + Top 构式禁令 + 防矫枉过正底线 | ✅ 永远注入（system 首） | ≤700 字符 |
| `L1_*.md` | 场景模块：按 agent/场景按需装配，每模块 ≤320 字符含 1 组锚例 | ✅ 装配器挑选 | 单模块 ≤320 |
| `L2_dynamic.yaml` | 动态修正文案：ai_metric 检出什么违规才注入对应条目 | ✅ 按命中注入 | 只注命中项 |
| `L3_reference.yaml` | 完整禁用词表 + 不可禁白名单 + 迭代纪律 | ❌ **永不进 prompt** | — |

词汇层枚举的执行者是 `deai_patterns.py` / `skill_gate`（确定性检查），
prompt 里只留规则与锚例——依据调研结论：打地鼠效应下，全量禁词进 prompt
是双份预算买一遍效果，且负面指令有粉红大象反效果。

## 文件格式约定（Phase B 装配器解析契约）

L0/L1 为 Markdown + 顶部 front matter（`---` 包围的 YAML）：

```markdown
---
id: writer_positive          # 全局唯一
layer: L1
agents: [writer, short_story] # 适用 Agent 类型（对齐项目 16 种 agent_type 命名）
genre: any                   # any 或具体体裁
priority: P0                 # P0=不可裁剪(正向要求类) P1=常规 P2=超预算先砍
budget_chars: 320            # 正文预算上限
enabled: true                # 总开关
source: 出处（调研文档章节/项目研究）
---
正文（将被原样注入 prompt 的部分）
```

装配保护序（超预算时的丢弃顺序）：**P2 → P1 按整模块裁剪**；L0 核心层与全部
P0 条目（正向要求类）永不裁剪——防止系统滑向「全是禁止、没有正向注入」。
L2 动态层只在检测命中时注入对应条目。

## Phase B 接线状态（2026-08-26 完成）

- [x] `assembler.py`: `assemble_constraints(agent_type, genre, budget)` 渲染器（front matter 解析 / 预算裁剪 / P0 保护 / 进程内缓存）
- [x] `writer.py build_writer_prompt` 接入；优先级 DB 模板 > 词库装配 > DEFAULT 常量兜底（兼容 CLI/MCP）
- [x] 注入量日志（`constraint assembled: modules/chars/dropped`）
- [ ] gate-check 报告回显实际装配清单（Phase D 度量时一并做）
- [ ] A/B 度量：全量 vs 预算制对比 ai_metric 人味分（Phase D）

自检记录：writer 装配 774/1800 字符；budget=600 时 P2 词表正确被裁、P0 全保；
critic 仅得检查清单；端到端 system 头部以词库核心层开头，旧全量词表未泄漏。

## Phase C 接线状态（2026-08-26 完成）

- [x] `review.py build_rewrite_prompt`：rewrite 场景装配（core+editor_preserve = 572 字符）> 静态常量兜底；
      原「特别注意」块与模块重复的两条已去重
- [x] `review.py build_critic_prompt`：注入 critic_checklist 模块——**critic 链路首次拥有 AI 味评审约束**
      （证据化逐项检查 + 强制亮点保留），角色设定与 JSON 契约保持不变
- [x] `keepers.py build_editor_prompt`：editor 场景装配（core+editor_preserve = 572 字符）；
      原"特别注意"块与模块重复的两条已并入模块去重
- [x] `ai_metric.build_tone_instructions` 改由 L2_dynamic.yaml 文案表驱动：
      行为兼容 + 新增「提示语冒号」修正指令（检测已有 R=3.8，旧函数漏生成）
- [x] code review 修复（2026-08-26 第二轮）：human_score=0 边界、load_bank 逐文件异常隔离 +
      BOM 兼容、_LAST_ASSEMBLY 按 agent 分键并记录 reason、genre 归一化、静默异常补日志
- character_check / lore_check / foreshadow_check 三个事实型 keeper 不接清单
  （它们查设定一致性而非文风，清单对它们是噪音）
- ⚠️ ~~short_story 场景已声明未接线~~ → **2026-08-26 已全部接线**：
  prompts.py×4（灵感/设定/细心/逐节点）+ generate.py×4（续写/扩写选中/重写选中/分段）
  + review.py×2（全文重写/单节点重写）共 10 处经 `_bank_constraints(story)` 接入，
  旧 `DEFAULT_WRITER_CONSTRAINTS` 同步瘦身为应急迷你兜底（1566→约330字符）

## Phase D 状态（2026-08-26 完成基建，校准待真实数据）

- [x] 全局开关 `Setting.constraint_bank_enabled`（`is_constraint_bank_enabled()`，无上下文缺省启用；
      停用时装配返回空串，各链路自然走兜底）
- [x] `_LAST_ASSEMBLY` 快照注册表 + `get_last_assembly()`
- [x] gate-check 响应回显 `constraint_assembly` 字段
- [x] CLI `constraint show/status/toggle`（cli.py 第 19 个命令组；CLAUDE.md 已登记）
- [ ] A/B 度量本身需真实生成流量：协议＝同一章节细纲分别在与库开/关下各生成 2 章，
      对比 gate-check 的 ai_tone.human_score 与朱雀抽检——由用户日常创作积累，攒够样本回填
      docs/ai-tone-research.md 记录表后校准预算数字与锚例数量
