# 第二轮开源扫描 · 融合评估（2026-09-04）

> 定位：第一轮调研（[open-source-survey.md](open-source-survey.md)，2026-06-07，45 项目）之后的新一轮扫描。
> 与两轮前例的区别：V3.6 是 OpenWrite 单项目借鉴；本轮是**多项目机制拆解 → 逐项裁决**。
> 方法：只拆机制不搬代码；每项对照灵砚现状给出结论（✅采纳 / 🔧改造采纳 / ⏸暂缓 / ❌拒收）、
> 落地要点与代价（S≈一天内 / M≈数天 / L≈需排期）。本文是候选清单，非已承诺的 roadmap——
> 排期决策在用户。

---

## 一、本轮扫描对象

| 项目 | 概况 | 为何入选 |
|------|------|---------|
| [ynnyh/jarvis-write](https://github.com/ynnyh/jarvis-write) | Python/FastAPI+React+Tauri，自述「consistency-first」，更新至 2026-09 | 本轮最大收获：大纲级联引擎、diff 逐条验收、去AI味收敛回滚环等多处与灵砚互补 |
| [RhythmicWave/NovelForge](https://github.com/RhythmicWave/NovelForge) | Electron+FastAPI，卡片式创作，面向百万字级 | JSON Schema 结构化生成 + 上下文注入 DSL + 抽取人审环节 |
| [YILING0013/AI_NovelGenerator](https://github.com/YILING0013/AI_NovelGenerator) | Python GUI，雪花法四步生成 | 分阶段模型路由 + 定稿时状态文件刷新 + 一致性校对按钮 |
| [xindoo/ai-novel-lab](https://github.com/xindoo/ai-novel-lab) | 实测产出 100 章 43 万字《大厂重生》 | 作为「全自动整本」路线的实证案例参与裁决（README 未能抓取，结论基于检索摘要） |
| [abligail/narralume](https://github.com/abligail/narralume)、[SuperMarioYL/branchtree](https://github.com/SuperMarioYL/branchtree)、[sidiangongyuan/living-to-tell](https://github.com/sidiangongyuan/living-to-tell)、[o-1717986918/arcvellum](https://github.com/o-1717986918/arcvellum) | topic 页轻量考察 | 体量小或与灵砚重合度高，仅记录 |

已在第一轮调研覆盖的（InkOS、AI-Novel-Writing-Assistant、RecurrentGPT、Dramatica-Flow、knowrite 等）不重复拆解；jarvis-write 自己注明其时序真相库借鉴 knowrite、伏笔四态借鉴 NovelClaw——灵砚对应实现（temporal_truth、伏笔状态机）已同等粒度，不构成新收益。

---

## 二、融合评估表（核心交付）

### A. 强烈建议采纳（补灵砚空白）

| # | 机制 | 来源 | 灵砚现状 | 落地要点 | 代价 |
|---|------|------|---------|---------|------|
| A1 | ✅ **已实现 v1（2026-09-04）**：失配标记部分。原计划——编辑任意章大纲 → 修改分级（标题微调零成本短路 / 情节变更触发下游影响分析）→ 用户勾选确认后级联重生成；受影响已生成章节自动标记「大纲失配」；大纲全量版本化可回滚 | jarvis-write | **空白**。章节大纲保存后不检查已生成正文的失配，长篇改纲是静默漂移源 | `chapters` 加 `outline_hash`（生成时记录所用大纲哈希）；大纲保存时 diff 分级，情节级变更→扫描未匹配章节→章节列表页批量标「失配」+ 一键重生成确认；先不做级联自动重生成（贵），只做失配标记 + 单章处理，与现有断点续跑衔接 | M |
| A2 | ✅ **已实现（2026-09-04）**。原计划——违规超标 → 定向重写 → 复测 → 人味分不升则丢弃重写保留原稿（「绝不保留更差版本」保证） | jarvis-write | 半环。有 ai_metric 检测 + 指纹注入（下一次生成规避），无「同稿自动收敛」；用户手改无质量兜底 | 写作页「一键收敛」按钮：调 rewrite 链路定向重写违规摘录段落 → 复测（ai_metric，可挂困惑度雷达）→ 分数提升才落库，否则原样保留并提示。复用 `run_dual_review` 的并行基建 | S-M |
| A3 | ✅ **已实现（2026-09-04）**。原计划——用户审批/手改过的段落 = 最真人语料，自动提取为锚例候选，用户确认入库 | jarvis-write（「从已接受章节提取样本」） | 文风锚例需用户手动粘贴 300-2000 字 | 审批通过且有人工改写痕迹（version source=human 或 diff 检测）时，提示「提取本段为文风锚例」；入库走现有 style_anchor 存储 | S |
| A4 | **知识抽取「预览-确认」人审环节**：实体/事实/关系自动抽取后先进待确认队列，人核验才写回真源 | NovelForge | 空白。causal_chain、实体状态自动写回，错抽会污染真源且难回滚 | 抽取结果落 `pending` 状态表 → 知识库页「待确认」列表逐条采纳/丢弃；先覆盖 causal_chain 与 CharacterRelation 两条自动写回链路 | M |
| A5 | ✅ **已实现压缩 pass（2026-09-04）**，拆章仍未做。原计划——超目标字数 → 压缩 pass 或原子拆章建议 | jarvis-write | 单侧。只有不足续写（CHAPTER_WORD_FLOOR），无超标处理 | v1 先做压缩 pass（保留情节 beats 的定向精简，走 rewrite 链路）；拆章涉及版本链与审批流，单独评估 | S（压缩）/ M（拆章） |

### B. 改造后采纳（不是照搬，要换形态）

| # | 机制 | 来源 | 灵砚现状 | 改造要点 | 代价 |
|---|------|------|---------|---------|------|
| B1 | **JSON Schema 结构化生成 + 字段级流式填充**：每种数据类型定义 schema 校验 AI 输出，字段逐个流式填充确认，避免「看起来能用、落地却混乱」 | NovelForge | 角色/世界观/大纲的 AI 生成是纯 prompt + 整块文本入库；结构化解析只有 `_extract_json_dict` | 不引入卡片模型（见 D1）；把 schema 校验加进两处：① `ai_metric`/记忆抽取的 JSON 解析（已有围栏剥离，补 schema 校验）② 知识库 AI 生成表单（character/world）逐字段返回。结构化记忆（ChapterMemory）天然是 schema 客户 | M |
| B2 | **上下文注入 DSL**：`@` 引用按类型/标题/位置/过滤表达式提取任意项目数据进 prompt | NovelForge | 只有 `@skill-id`（V3.6）。角色/设定注入靠勾选面板，特别指示里无法精确点名 | 扩展 `@` 语法族：`@char:名字`、`@lore:标题`、`@伏笔:标题` → 解析后注入对应档案（复用 assemble 逻辑）；未知 @词保留原文的纪律（V3.6 已定）沿用到新语法 | M |
| B3 | ✅ **已实现（2026-09-04，随 Agent 协同 P4）**。**风格备忘录自动累积**：每章定稿提取「本章文体要点」累积成册，注入后续章节 | jarvis-write | ~~无~~ | memory agent 增 `style_note` 字段，审批事务内累积至 `Novel.style_memo_json`（保留 10 条），写作包注入最近 3 条 | S-M |
| B4 | **纯逻辑一致性校对 pass**：角色逻辑/情节矛盾专查（与文笔评审分离） | AI_NovelGenerator（consistency proofread） | unified_review = Critic(文笔+结构) + 双盲审(市场+文学)，逻辑一致性散在 Keepers（已停用）与 causal_chain 注入，无独立复检 | 并入 unified_review 作为可选第三步（确定性优先：先跑因果链/伏笔/信息边界的交叉核对，LLM 只裁疑点），不用 LLM 全文重读 | S-M |
| B5 | **分阶段模型路由细化**：架构/大纲/草稿/终稿/校对五类各配模型 | AI_NovelGenerator | 已有 per-agent 配置（16 Agent 类型），粒度已超过它 | 仅吸收一个点：「终稿润色用强模型、草稿用快模型」的默认建议写进设置页文案；无需代码改动 | S |

### C. 暂缓观察

| 机制 | 来源 | 暂缓理由 |
|------|------|---------|
| 通用工作流引擎（触发器/后台执行/中断恢复/自然语言生成工作流代码） | NovelForge | 灵砚已有断点续跑与逐节点多轮；等「整本批量生产」成为真实需求再评估，现在引入是过度设计 |
| 知识图谱存储升级（SQLite → Neo4j） | NovelForge | FTS5 零依赖是 V3.6 明确立下的原则；关系模型 + 现有表够用 |
| 桌面壳（Tauri/Electron） | jarvis-write / NovelForge | 单机 Web 已满足使用场景，双端维护成本不值 |
| 拆书工作流（解析已有小说入库） | NovelForge | 借鉴改写模块（plagiarize）已覆盖上传/拆解/改写主链路 |
| 漫画/有声/多模态出口 | jarvis-write | 超出文本创作范围 |

### D. 拒收清单（去其糟粕）

| # | 机制 | 来源 | 拒收理由 |
|---|------|------|---------|
| D1 | **卡片模型整体迁移**（一切皆 card + 层级树） | NovelForge | 灵砚 23 个 SQLAlchemy 模型 + 关系约束是根基；V3.6 拒文件系统真源同理——迁移是灾难级成本，收益只是概念整齐 |
| D2 | **全自动整本生成路线**（一键产出 43 万字） | ai-novel-lab | 与平台「人工主导 ≥30%」红线冲突，与灵砚「人定结构、AI 填空」哲学冲突；且我们实测全自动稿落入朱雀「疑似桶」——量不解决质 |
| D3 | **正文生成改异步任务+进度轮询**（放弃逐 token 流式） | jarvis-write（其已知遗留事项） | SSE 逐字输出是灵砚的体验优势，倒退无理由 |
| D4 | **内置名家风格样本**（余华/鲁迅等「模仿而非摘录」） | jarvis-write | 版权与合规灰区；灵砚文风锚例坚持用户自有文本，边界更干净 |
| D5 | **自研 LLM 适配器替换 LangChain** | jarvis-write | llm.py 已统一封装且支持 11 厂商，重写无收益 |
| D6 | **角色定妆照/多模态辅助** | jarvis-write | 超出文本系统范围；其 README 自己承认文字锚「压不到零」，多模态是它补位的手法，不是我们的缺口 |

---

## 三、与既往决策的衔接

- A2 收敛回滚环与 **困惑度雷达**（ai-tone-research §八）天然耦合：复测侧挂 radar 可同时覆盖构式层与选词层，「不保留更差版本」的回滚纪律也适用于雷达实验。
- A3 与 **平台现实**（人工改写 ≥30%，ai-tone-research §七-5）互为印证：用户改稿即天然语料，提取闭环让「人工占比」直接转化为生成质量。
- A1 大纲失配标记是 **V3.6 写章事务保护**的姊妹篇：事务保护管「正文落库一致性」，级联标记管「正文与大纲的时序一致性」。
- D2 的裁决与 **ai-tone-research §八.2 已评估否决** 同源，两处已互相引用语义，不重复计分。

## 四、建议落地顺序（候选，待排期）

1. ~~A2 收敛回滚环~~ ✅ 已实现（`tone_convergence.converge_tone` + `POST /api/tone-converge` + 写作页「AI味收敛」按钮）
2. ~~A3 锚例反向提取~~ ✅ 已实现（`extract_anchor_candidate` + 审批返回候选 + 前端确认入库）
3. ~~A1 大纲失配标记 v1~~ ✅ 已实现（`chapters.outline_hash` + `outline_stale()` + 双页徽标）；级联自动重生成仍后置
4. ~~A5 字数超标压缩 pass~~ ✅ 已实现（`condense_text` + `POST /api/condense` + 写作页「压缩超标」按钮）；拆章后置
5. **A4 抽取人审队列**（M）——先覆盖 causal_chain 一条链路
6. **B3 风格备忘录**（S-M）→ **B2 注入 DSL**（M）→ **B1 Schema 校验**（M）
7. **B4 逻辑一致性 pass**（S-M）——并入 unified_review
8. **A3 之后的 diff 逐条验收**（L）——前端大件，建议独立版本排期（对齐 jarvis-write 与「agent harness」类产品的核心交互）
