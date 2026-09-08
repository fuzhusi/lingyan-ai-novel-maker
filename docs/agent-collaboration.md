# Agent 协同方案（2026-09-04）

> 定位：多 Agent 评审已改为双 Agent（阎浮×白骨，旧 pipeline 休眠保留）之后，
> 回答「下一步 Agent 之间应该怎么协作」。本文是**设计方案**，不是已实现清单——
> 分期落地条目在批准前不进入 roadmap 承诺。
> 证据基础：2026-09-04 全库盘点（16 类 Agent 配置、18 个 LLM 调用方、休眠 pipeline、
> [merge-assessment.md](merge-assessment.md) 未完成项）。
> **状态：P1-P4 已于 2026-09-04 全部实施**（含配置卫生）；观察项仍为观察项。

---

## 一、现状盘点

### 1.1 在役能力

| 链路 | 组成 | 状态 |
|------|------|------|
| 写作链 | outline → writer（SSE + 字数保障续写）→ 门禁束（skill_gate ∥ ai_metric ∥ 困惑度雷达可选） | ✅ 主链路 |
| 评审链 | unified_review：Critic 结构化评分 → 阎浮∥白骨并行盲审 → 合并报告 | ✅ 主链路（细节断点见 1.3） |
| 修订链 | rewrite（按评审）/ blind_rewrite（按盲审意见）/ tone_convergence（按检测，回滚兜底）/ condense（按字数） | ✅ 但四条互不相通 |
| 定稿链 | approve → chapter_approval 单事务（空检/摘要兜底/结构化记忆/状态推进）+ 锚例候选 + 大纲指纹 | ✅ |
| 记忆链 | 分层摘要 + FTS5 检索 + 因果链 + 信息边界 + 时序真相 + 伏笔状态机（注入侧）；summary/memory/causal_chain agent（抽取侧） | ✅ |

### 1.2 休眠/遗留

| 资产 | 状态 | 处置倾向 |
|------|------|---------|
| pipeline.py（Critic + 3 Keepers 并行 → Editor） | blueprint 注册、零调用 | 保留停用（决策已留痕）；**其"壳"可被 P3 编排器吸收** |
| character_check / lore_check / foreshadow_check 三个 Agent 配置 | 设置页仍可配置，但**无任何调用方** | P2 一致性链复活为「裁决者」角色（见 3.2），复活前在设置页标注「预留」 |

### 1.3 缺口清单（检索结论）

| # | 缺口 | 影响 | 归属 |
|---|------|------|------|
| G1 | **评审→改写意见无统一契约**：blind_rewrite 吃盲审意见、rewrite-stream 吃 user_feedback，Critic 分项意见没有结构化进入任何改写链路；三个意见源各走各的 | 用户在评审页勾了意见，改写时却可能只吃到一部分 | 评审链 |
| G2 | **无编排层**：大纲→正文→门禁→评审→修订→审批 全靠用户手动逐步点击；无带进度、可跳过阶段的 runner | 每章 6-8 次手动操作；批量生产不可能 | 编排 |
| G3 | **一致性无主动复核**：Keepers 休眠后，角色/世界观/伏笔一致性只剩"生成时注入"（因果链/边界/时序），定稿前无人复核「正文是否真的遵守了」 | 长篇漂移只能靠读者发现 | 一致性链 |
| G4 | **agent 各自重建上下文**：每次调用独立 assemble，无章级「写作包」封装；罗盘/指纹指令/风格备忘录（B3 未做）散在各自的注入点 | 注入口径漂移；新增维度要改多处 | 契约 |
| G5 | **收敛环只覆盖 tone**：critic 评分、盲审判决没有对应收敛机制 | 评审问题修完是否真的改善，无量化回滚 | 修订链 |
| G6 | **长篇缺逐节点机制**：短篇有逐节点多轮+盲审返写，长篇整章一次生成，粒度粗 | 长篇无法定点返工某一场戏 | 写作链 |
| G7 | **抽取无人审队列**（merge-assessment A4 未做）：因果链/实体状态自动写回，错抽污染真源 | 一致性注入被脏数据误导 | 定稿链 |

---

## 二、设计原则（从项目哲学推导，不做例外）

1. **人是总编排者**。平台红线（人工主导 ≥30%）与「人定结构、AI 填空」的立身哲学决定：本方案是**带人工闸门的流水线**，不是自主多 Agent 对话。任何自动化到「待人工审阅」为止。
2. **确定性优先**。能 lint 的不问 LLM：每条链的入口先跑零成本检测（ai_metric / radar / skill_gate / 确定性交叉核对），LLM 只处理确证或存疑部分。
3. **单一上下文源**。所有 Agent 取料只经「写作包」（见 3.1），禁止各自拼 prompt——注入口径只有一处。
4. **复用即编排**。编排器只串联既有服务函数，不引入 LangGraph/AutoGen 类框架；每个阶段可独立跳过。

---

## 三、协同拓扑（四条链 + 两个契约）

### 3.1 契约一：写作包（WritingPacket）

`assemble_chapter_context` 的输出 + 罗盘 + tone_instructions + 风格备忘录（B3 待做）
的**单一封装对象**。写作链/评审链/修订链全部从写作包取料：

```
WritingPacket = assemble_chapter_context()
             + build_compass_block()
             + tone_instructions（上一稿检测违规）
             + style_memo[]（B3：逐章累积的文体要点）
             + boundary_context（信息边界+时序真相，豁免压缩）
```

收益：G4 消除；新增注入维度只改一处；预算压缩（apply_context_budget）的豁免清单有了唯一执掌点。

### 3.2 契约二：统一意见 Schema（打通 G1）

评审链三个意见源（Critic 分项、阎浮、白骨）统一降维成同一结构，rewrite 只吃这个结构：

```json
{"source": "critic | yafu | baigu",
 "verdict": "追读 | 弃稿 | 分数",
 "opinions": [{"quote": "原文摘录", "issue": "问题", "suggestion": "方向", "severity": "high|mid"}]}
```

落地：unified_review 产出合并报告时同步产出 `merged_opinions[]`；rewrite-stream 增加按
`opinion_ids` 勾选注入（现在只有盲审返写支持勾选）。**这是 P1，改动最小、收益最直接。**

### 3.3 四条链的协同图

```
【写作链】
  outline → writer(写作包) → 门禁束[skill_gate ∥ ai_metric ∥ radar?]
      ├─ 违规 → tone_convergence（重写→复测→回滚） ─┐
      └─ 通过 ────────────────────────────────────┤
                                                   ▼
                              ⏸ 人工闸门①：审阅/保存版本
                                                   ▼
【评审链】
  unified_review（critic → 阎浮∥白骨）→ merged_opinions
      → ⏸ 人工闸门②：勾选采纳意见
      → rewrite(意见+写作包) → 复评（至多一轮，防循环）
      → ⏸ 人工闸门③：接受/再改
                                                   ▼
【定稿链】
  approve → chapter_approval 事务（空检/摘要/记忆/状态）→ 锚例候选 → 大纲指纹
      → [P2] 抽取待确认队列（G7）
                                                   ▼
【一致性链】（P2，复活 Keepers 为裁决者）
  确定性交叉核对：因果链×正文命中 / 伏笔状态×正文提及 / 信息边界×对话归属
      → 疑点清单 → character_check/lore_check/foreshadow_check 只裁疑点（不重读全文）
      → ⏸ 人工闸门④：矛盾处理（改文 / 改设定 / 忽略——jarvis-write 三选项同构）
```

要点：
- **一致性链复活 Keepers 的方式是「裁决者」而非「全文重读者」**——确定性核对把 suspects
  缩到极小集合，三个 deep Agent 只回答「这处是否矛盾、以哪条设定为准」，token 成本可控。
  这与休眠 pipeline 的"并行全文重读"是本质不同的职责，旧壳不复用逻辑、只吸收其配置。
- **复评至多一轮**（G5 的评分收敛用同一纪律：分数不升则回退上一稿，复用 convergence 的回滚语义）。
- 人工闸门落为**版本状态机**：`draft → gated → reviewed → revised → approved`，
  存版本元数据，前端按状态渲染可用动作——这也是 diff 逐条验收（A 系列最后一个大件）的状态地基。

### 3.4 编排器（P3）

- 新 service `chapter_runner`：把写作链串成可一次触发的流水线（生成大纲→生成正文→门禁→
  收敛→停在闸门①），阶段=既有函数，SSE 推阶段进度，任一阶段失败即停且不跨闸门。
- 休眠 pipeline.py 的**壳**（blueprint + SSE 骨架）由 runner 吸收后，旧模块保持休眠原样。
- MCP 暴露 `run_chapter_pipeline` 工具；CLI 同源。
- 短篇已有逐节点多轮（G6 的短篇侧），长篇等价物 = 场景节拍级生成（jarvis-write 的
  3-5 节拍/章），**列为观察项**——等 P3 落地后按需评估，不在本方案承诺。

---

## 四、分期落地（建议顺序，批准后进 roadmap）

| 期 | 内容 | 对应缺口 | 状态 |
|----|------|---------|------|
| P1 | 统一意见 Schema（`opinions.py`）+ unified_review 产出 `merged_opinions` + rewrite-stream 按勾选注入 + 评审面板勾选 UI | G1 | ✅ 已实现 |
| P2 | 一致性链（`consistency_check.py`：时序真相回潮/伏笔排期/已回收复现三查 → Keepers 三 Agent 只裁疑点）+ 抽取待确认队列（`PendingExtraction` + truths/extract `queue=1`） | G3、G7 | ✅ 已实现 |
| P3 | 写作链公共层（`writer_chain.py`：写作包+生成流单一实现）+ `chapter_runner` 编排器 + `POST /api/chapter-pipeline` + MCP `run_chapter_pipeline` + 写作页「一键本章」 | G2 | ✅ 已实现 |
| P4 | 写作包契约固化（writer_chain 单一取料口）+ 风格备忘录（`Novel.style_memo_json`，审批时经 memory agent 采集，注入最近 3 条）+ 创作偏好档案（设置页卡 + 注入写作链） | G4 | ✅ 已实现 |
| 观察 | 长篇场景节拍生成、评分收敛环（G5/G6） | G5、G6 | ⏸ 观察项 |

配置卫生（✅ 已随 P2 落地）：`character_check / lore_check / foreshadow_check` 在
AGENT_TYPES 中已标注「预留·一致性裁决者」。

实现载体（2026-09-04）：`opinions.py` / `consistency_check.py` / `extraction_queue.py` /
`writer_chain.py` / `chapter_runner.py`；路由 `/api/consistency-check`、
`/api/chapter-pipeline`、`/settings/api/creator-preferences`、
`/novels/<id>/pending-extractions`；测试 `tests/test_agent_collab.py`（13 例）。

## 五、与既有决策的衔接

- 双盲审两角色格局**不动**——本方案所有链路的评审权威仍是 阎浮×白骨 + Critic 评分，
  Keepers 只复活为一致性裁决者，不回到「并行全文评审」的旧形态。
- tone_convergence / condense / 收敛回滚纪律（2026-09-04 已实现）是修订链的既有成员，
  P1 的意见 Schema 让 rewrite 与它们共享同一份输入格式。
- merge-assessment 未完成项的归属：A4→P2，B1/B2→P4 前置，diff 逐条验收→闸门状态机的
  下游大件，均已在各自文档留痕，本文不重复计分。
