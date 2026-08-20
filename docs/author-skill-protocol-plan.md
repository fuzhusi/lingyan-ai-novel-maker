# 作者技法协议集成方案（动态加载完整协议版）

> 状态：**已实现** · 目标：建立可扩展的"作者技法协议"框架，江南作为首个实例，并支持"像调用原 skill 一样加载完整协议"。
>
> **当前实现**：3 个江南技巧来自 `JiangNan-feeling-writing` v1.1.1（MIT，quote-free 通用原创协议）：
> https://github.com/zhichenghe34-design/JiangNan-feeling-writing
> - `jiangnan_fingerprint` 笔法指纹（4天生指纹+2后期工具+遮蔽梯+句子运动+结尾）
> - `jiangnan_preset` 阶段与声线（10 preset+四维定调+非融合规则）
> - `jiangnan_cost` 选择与代价（11协议卡+现实成本+信念付费+硬性失败）
>
> **两阶段演进**：
> 1. 阶段一（静态浓缩）：把协议核心提炼成 3 段浓缩 prompt 注入。
> 2. **阶段二（动态加载完整协议，当前）**：把 `core/*.md` 原文件存进 `app/skills/jiangnan/`，激活时后端
>    loader 按任务类型动态注入完整 core markdown（而非浓缩版），更接近"调用原 skill"。静态浓缩 prompt
>    保留为文件缺失时的回退。同协议包只整包加载一次（去重），三全开 ≈ 单开的 token 量。
>
> **变更历史**：初版提炼自 `jiangnan.skill` v2.0.3（龙族结局共创协议，CC BY-NC，含龙族同人专用补丁）；
> 后替换为 `JiangNan-feeling-writing`——后者 quote-free、通用原创、MIT 协议、模块化（core+adapters+agents+references）、
> 无同人专属包袱，更适合作为通用文风技巧对所有题材生效。初版 jiangnan.skill 分析见文末附录。

---

## 1. 背景与目标

### 1.1 江南技法协议是什么

当前采用的 `JiangNan-feeling-writing`（v1.1.1）是一套**江南感原创写作笔法协议**，模块化结构（core + adapters + agents + references），平台无关核心在 `core/`。它面向原创写作/改稿/诊断/大纲四件事，明确 quote-free（不摘原文、不用源作品专名/桥段），比初版 jiangnan.skill 更通用、合规性更好（MIT vs CC BY-NC）。

核心机制：
- **四维定调**：阶段轴(P1~P6+根系) × 题材语域轴 × 配置轴 × 指纹深度轴
- **10 个 preset**：P1校园/P1-P2武侠/P2史诗/P3都市热/P3都市冷/P4少年卷入/P5情感最大化/P6冷寂不在/P6商业奇幻/根系神话
- **4 个天生指纹**：物/动作替代心理、对话潜台词、大题小作/小题大作、段尾回疼
- **2 个后期工具**：比喻升维（必须回到人的代价）、双读双编码
- **遮蔽梯 6 层**：直接说情绪→委婉→物→动作→对话潜台词→段尾空白（至少走到第3层）
- **选择成本规则**：现实成本（钱/时间/身体/名誉/关系/阵营）+ 信念付费
- **11 张协议卡**：阶段配置/缺口/门外/叙述距离/遮蔽梯/糖苦/信念成本/现实成本/小物/远灯/开口结尾
- **24 分评分门**：12项×2分，原创安全=0直接阻断；<12失败/>16可用/>20强可用
- **非融合规则**：主 preset 只能一个，阶段专属工具不能当通用风格

本方案（方案 A）把这套协议的**文风/技法层**提炼为 3 个内置技巧，复用灵砚现有"激活技巧→注入 Writer system message"管线。其自带的 24 分评分门属"江南感专项审计"，接入灵砚 17 维度审计为可选增强（本期未做，见第 8 节演进路径）。

### 1.2 灵砚现状

| 模块 | 作用 | 注入位置 |
|---|---|---|
| `app/services/skill_system.py` | 13 内置技巧 + 自定义技巧，`build_skill_prompt()` 拼接 | Writer system message（`app/services/prompt_builder/writer.py:33`） |
| `app/services/style_fingerprint.py` | 参考文本风格特征 JSON | memory_context（`app/routes/generate.py:112`） |
| `app/routes/plagiarize/style.py` | 风格模仿 + "保存为 Skill" | 借鉴改写页 |

**关键契合**：`SKILL.md` 整体就是一个"巨型技巧 prompt 片段"，符合灵砚技巧数据模型 `{name, description, prompt, constraints}`。`build_skill_prompt()` 已被长篇 Writer 和短篇生成（`short_story/prompts.py`、`short_story/generate.py`）共用，江南技巧激活后**长篇短篇自动同时受益**。

### 1.3 目标

1. 把江南文风/叙事核心提炼为 **3 个内置技巧**，激活即注入。
2. 建立"作者技法协议"这一**可扩展分类**，江南是首个实例，未来可加古龙/金庸/刘慈欣等。
3. 改动最小化：复用现有 `build_skill_prompt` 管线与技巧页 UI，不新建路由/页面/状态机。
4. 合规：只用 `SKILL.md` 公开协议文本，提炼为指令，不带入受版权原文。

---

## 2. 提炼的三个内置技巧

> 来源：`JiangNan-feeling-writing` v1.1.1（MIT，quote-free 通用原创协议）。提炼为浓缩指令，非全文照搬。默认**不激活**，用户按需开启。完整 prompt 见 `app/services/skill_system.py` 的 `AUTHOR_PROTOCOL_SKILLS`。

### 技巧 1：`jiangnan_fingerprint` — 江南感·笔法指纹

- category: `作者文风协议` · author: `江南` · source: `JiangNan-feeling-writing v1.1.1 (MIT)`
- description: `页面级笔法：物/动作替代心理、对话潜台词、大题小作、段尾回疼、遮蔽梯、比喻升维`
- 用途：最常用，让生成的文字带江南感（页面级写法）。
- 核心内容：4 个天生指纹（物/动作替代心理、对话潜台词、大题小作/小题大作、段尾回疼）+ 2 个后期工具（比喻升维必须回到人的代价、双读双编码）+ 遮蔽梯 6 层（至少走到第3层）+ 句子运动（短/中/长句分工）+ 空白与沉默（行动失败）+ 结尾（落地+开口）。
- constraints: `禁止直接说情绪（走遮蔽梯≥3层）；禁止结尾总结主题/大团圆；禁止使用任何源作品专名/桥段/原文`

### 技巧 2：`jiangnan_preset` — 江南感·阶段与声线

- category: `作者文风协议` · author: `江南` · source: `JiangNan-feeling-writing v1.1.1 (MIT)`
- description: `10个preset定声线+四维定调+非融合规则：校园/武侠/史诗/都市热冷/少年卷入/情感最大化/冷寂/商业奇幻/根系`
- 用途：想要完整江南叙事质感时与技巧 1 同开，定声线和阶段。
- 核心内容：四维定调（阶段轴×语域轴×配置轴×指纹深度轴）+ 10 个 preset（P1校园/P1-P2武侠/P2史诗/P3都市热/P3都市冷/P4少年卷入/P5情感最大化/P6冷寂不在/P6商业奇幻/根系神话，每个含适用场景/声音/糖苦/签名杠杆/失败风险）+ 非融合规则（主 preset 只能一个）+ 糖衣/苦药分布。
- constraints: `主preset只能一个，禁止平均混合多阶段声线；阶段专属工具不能当通用风格`

### 技巧 3：`jiangnan_cost` — 江南感·选择与代价

- category: `作者文风协议` · author: `江南` · source: `JiangNan-feeling-writing v1.1.1 (MIT)`
- description: `让人物选择有现实成本：缺口/门外/信念付费/现实成本/小物/远灯/开口结尾（11张协议卡）`
- 用途：让人物选择"有代价"，避免"有感觉但不够硬"，三个全开时江南感最完整。
- 核心内容：选择成本规则（不选会失去什么+选择会付出什么，成本通过动作/物/对话/制度细节露出）+ 11 张协议卡（阶段配置/缺口/门外/叙述距离/遮蔽梯/糖苦/信念成本/现实成本/小物/远灯/开口结尾）+ 8 类硬性失败模式（表面悲伤/平均声线/错误泛化/纯苦/纯糖/情绪说穿/信念不付费/源作品依赖）+ 原创安全边界。
- constraints: `人物选择必须有可见现实成本（钱/时间/身体/名誉/关系/阵营等）；信念必须付费；禁止源作品依赖；禁止情绪说穿`

### 技巧组合建议（写入技巧页说明）

- 一般小说想带江南味：开 `jiangnan_fingerprint`
- 完整江南叙事质感：开 `jiangnan_fingerprint` + `jiangnan_preset`
- 让人物选择有重量、避免"有感觉但不硬":再加开 `jiangnan_cost`（三个全开最完整）
- 三技巧均 quote-free 通用原创，对所有题材生效，无同人专属限制

---

## 3. 通用框架改造

### 3.1 数据结构

`skill_system.py` 现有 `BUILTIN_SKILLS`（扁平 dict）+ `get_custom_skills()`。新增"作者技法协议"分类：

- 新增 `AUTHOR_PROTOCOL_SKILLS` dict，与 `BUILTIN_SKILLS` 并列。江南 3 技巧放入其中。
- 每个条目增加可选字段：`category`（默认"通用技法"）、`author`、`source`、`tag`。
- `get_all_skills()` 合并 `BUILTIN_SKILLS` + `AUTHOR_PROTOCOL_SKILLS` + 自定义，并透传新字段。
- 未来加古龙：在 `AUTHOR_PROTOCOL_SKILLS` 加条目，`author="古龙"`，UI 自动分组。

### 3.2 默认激活策略

- `get_active_skills()` 默认值**不变**（仍为 5 个去 AI 化核心技巧：`rhythm_breaking`/`sensory_concrete`/`imperfection`/`dialogue_humanize`/`deai_structure`）。
- 江南 3 技巧**默认不激活**，避免改变所有用户默认文风。用户主动激活。

### 3.3 注入复用（无需改动）

- `build_skill_prompt()` 已遍历 `get_all_skills()` 取激活项的 `prompt` 拼接 → 自动包含江南技巧。
- `app/services/prompt_builder/writer.py:33` 已把 `build_skill_prompt()` 注入 Writer system message。
- `app/routes/short_story/prompts.py`、`app/routes/short_story/generate.py` 已调用 `build_skill_prompt()` → 短篇自动受益。
- **无需改 `writer.py` / `generate.py` / `short_story/*`**。

---

## 4. 代码改动清单

| 文件 | 改动 | 工作量 |
|---|---|---|
| `app/services/skill_system.py` | 新增 `AUTHOR_PROTOCOL_SKILLS`（江南 3 技巧）；`get_all_skills()` 合并并透传 category/author/source/tag；`skills_page` 按三组返回（通用/作者协议/自定义） | 中 |
| `app/templates/skills.html` | 新增"作者文风协议"分组渲染；卡片显示作者徽标 + source 标注；顶部说明加组合建议（当前 3 技巧均无 tag） | 小 |
| `docs/author-skill-protocol-plan.md` | 本方案文档（留档） | — |
| ~~`app/services/prompt_builder/writer.py`~~ | 无需改（已复用） | — |
| ~~`app/routes/generate.py`~~ | 无需改（已复用） | — |
| ~~`app/routes/short_story/*`~~ | 无需改（已复用） | — |

### 4.1 `skill_system.py` 关键改动点

```python
AUTHOR_PROTOCOL_SKILLS = {
    "jiangnan_fingerprint": {
        "name": "江南感·笔法指纹",
        "description": "页面级笔法：物/动作替代心理、对话潜台词、大题小作、段尾回疼、遮蔽梯、比喻升维",
        "prompt": "<完整 prompt 见源码>",
        "constraints": "禁止直接说情绪（走遮蔽梯≥3层）；禁止结尾总结主题/大团圆；禁止使用任何源作品专名/桥段/原文",
        "category": "作者文风协议",
        "author": "江南",
        "source": "JiangNan-feeling-writing v1.1.1 (MIT)",
    },
    "jiangnan_preset": { ... },       # 技巧2 阶段与声线
    "jiangnan_cost": { ... },         # 技巧3 选择与代价
}

def get_all_skills():
    all_skills = {}
    for key, skill in BUILTIN_SKILLS.items():
        all_skills[key] = {**skill, "builtin": True, "category": skill.get("category", "通用技法")}
    for key, skill in AUTHOR_PROTOCOL_SKILLS.items():
        all_skills[key] = {**skill, "builtin": True, "category": "作者文风协议"}
    for key, skill in get_custom_skills().items():
        all_skills[key] = {**skill, "builtin": False, "category": "自定义"}
    return all_skills
```

`skills_page` 增加把 skills 按 category 分三组传给模板。

### 4.2 `skills.html` 改动点

- 在"内置技巧"与"自定义技巧"之间插入"作者文风协议"分组（循环渲染 `author_protocol_skills`）。
- 卡片头部加作者徽标（如 `🖋 江南`）和 source 小字。
- 顶部说明卡片追加："作者文风协议由公开技法协议提炼（如 jiangnan-feeling-writing），默认不激活，按需开启。"
- 当前 3 个江南技巧均无 `tag`（quote-free 通用，非同人专用），故无专用标签徽章。

### 4.3 动态加载完整协议（阶段二，当前实现）

为更接近"像调用原 skill 一样"，阶段二不再只用静态浓缩 prompt，而是把 `JiangNan-feeling-writing` 的完整 `core/*.md` 存进项目，激活时后端 loader 动态注入完整协议文本。

**资源文件**（`app/skills/jiangnan/`，12 个 markdown，来自仓库 core/ + references/ + SKILL.md）：
- `core_protocol.md`（92行）协议+选择成本规则
- `core_presets.md`（33行）10 preset+成本焦点
- `core_fingerprints.md`（69行）4天生指纹+2后期工具+遮蔽梯
- `core_evaluation.md`（42行）24分评分门+失败模式
- `core_install-and-use.md`、`SKILL.md` 入口/安装说明
- `references_*.md`（7个）细化参考：prose-style/longzu-evolution/protocol-cards/evaluation-gates/safety-and-boundary/workflow/language-layer-todo

**技巧字段**：3 个江南技巧各加 `protocol_pack: "jiangnan"`，指向资源目录。

**Loader**（`skill_system.py`）：
- `_PROTOCOL_PACK_FILES` 定义每个协议包按任务类型注入哪些 core 文件：
  - `write` → protocol + presets + fingerprints（写作必需三模块）
  - `diagnose` → evaluation（24分评分门+失败模式诊断）
  - `polish` → fingerprints + evaluation（笔法指纹+质检）
  - `full` → protocol + presets + fingerprints + evaluation（完整最小调用包）
- `_load_protocol_pack(pack, task_type)` 从 `app/skills/<pack>/` 读对应文件拼接，文件缺失返回 None。
- `build_skill_prompt(task_type="write")` 检测 `protocol_pack` 字段，优先加载完整文件协议；文件缺失回退静态浓缩 prompt（不中断）。

**去重**：同一协议包（三个江南技巧都指向 jiangnan）**只整包加载一次**，约束自动合并。三全开 ≈ 单开的 token 量（实测 3.3KB ≈ 3.2KB），不重复注入。

**调用方兼容**：现有所有调用点（`writer.py`、`short_story/prompts.py`、`short_story/generate.py`）都用默认 `task_type="write"`，自动加载完整协议的 write 模块，无需改动。诊断/润色场景传 `diagnose`/`polish` 是后续增强。

**实测**：
- 单开 fingerprint，write 模式：注入完整 protocol+presets+fingerprints，3.2KB，文件标题各 1 次 ✓
- 三全开，write 模式：3.3KB（去重生效，≈单开），约束合并 ✓
- diagnose 模式：只加载 evaluation（0.7KB），不含 protocol ✓
- full 模式：4 个 core 文件全加载，3.8KB ✓
- 还原后无江南协议残留 ✓

---

## 5. 合规

- 只使用 `JiangNan-feeling-writing` 的 `core/` 公开协议文本，提炼为可执行指令。
- 该协议本身 **quote-free**：明确禁止摘录受版权原文、使用源作品专名/桥段/源近句式、写成官方续作口吻（见 `references/safety-and-boundary.md`）。
- 协议 **MIT License**（比初版 jiangnan.skill 的 CC BY-NC 4.0 更宽松，商用亦允许）。
- 每个技巧 `source` 字段标注 `JiangNan-feeling-writing v1.1.1 (MIT)`。
- 提炼版只含技法指令，不含任何原文引文。

---

## 6. 验证清单

1. 启动 Flask，访问 `/api/skills/page`，看到三组：**通用技巧**（13 个）/ **作者文风协议**（江南 3 个，含作者徽标，龙族补丁有专用标签）/ **自定义技巧**。
2. 江南 3 技巧默认未激活，激活计数仍为 5。
3. 激活 `jiangnan_voice`，调用 `build_skill_prompt()`，确认输出含江南句式 DNA 段。
4. 生成一章长篇，检查输出是否出现长短句交错/软转折/通感等江南特征。
5. 新建一篇短篇并生成，确认短篇也受江南技巧影响（因 `short_story` 共用 `build_skill_prompt`）。
6. token 占用：3 技巧 prompt 合计约 3.7KB（fingerprint~1.1KB + preset~1.3KB + cost~1.3KB），可接受。
7. 关闭江南技巧后，`build_skill_prompt()` 输出恢复原状，无残留。

---

## 7. 风险与权衡

| 项 | 说明 | 对策 |
|---|---|---|
| ~~提炼版非全文~~ | 阶段二已改为动态加载完整 core markdown，不再是浓缩版 | references 细化参考未默认注入（按需可扩展 loader 读取） |
| 默认文风被改变 | 用户可能不希望所有小说都江南味 | 江南 3 技巧默认不激活 |
| 多 preset 难以一次性执行 | preset 选择需用户判断题材阶段，一次性生成中模型可能默认某 preset | 可在 user_directive 里指明 preset；未来方案 C 可做引导式选 preset |
| 协议自带 24 分评分门未接入 | 评分门属"江南感专项审计"，本期只做 prompt 注入未接审计 | 见第 8 节演进路径：可接入灵砚 17 维度审计作为条件启用维度 |

> 注：当前协议 MIT License，无 CC BY-NC 商用限制；quote-free 设计使三技巧对所有原创题材通用，无同人专属污染风险（初版 jiangnan.skill 的龙族补丁污染问题已随替换消除）。

---

## 8. 未来扩展（方案 D 演进路径）

- `AUTHOR_PROTOCOL_SKILLS` 框架天然支持新增作者：加古龙（短句+留白+意境）、金庸（武侠人物模板）、刘慈欣（硬科幻宏大叙事）等，各为一条目，UI 自动按 author 分组。
- **接入 24 分评分门到审计**：`build_skill_prompt(task_type="diagnose")` 已能加载 evaluation 模块。下一步把灵砚的质检/诊断调用点（`app/services/audit.py`、`app/routes/review.py`）在激活江南技巧时传 `task_type="diagnose"`，让审计额外跑 12 项江南感评分 + 9 类失败模式诊断（表面悲伤/平均声线/情绪说穿/信念不付费等）。这是当前协议独有的、上一个 jiangnan.skill 没有的能力。
- 进阶可演进到方案 C（独立共创工作流页面，多阶段引导式选 preset + 填协议卡 + 24 分评分门回执）。方案 B（导入完整协议包，支持上传 markdown）的"存文件+loader"机制已由阶段二实现，只差上传 UI。
- 可与现有 `style_fingerprint`（从参考文本提取风格）打通：用户既能用预设作者协议，也能从自己的参考文本提炼自定义文风。

---

## 附录：初版 jiangnan.skill 分析（已被替换，存档对照）

初版三技巧提炼自 `jiangnan.skill` v2.0.3（https://github.com/dmlin7777777/jiangnan.skill ，CC BY-NC 4.0），那是一个 38KB 单文件 `SKILL.md` 的"龙族结局共创叙事协议"。初版三技巧为：

- `jiangnan_voice`（句式DNA与润色：时间折叠/反差构图/缺失驱动/5必用句式/5步润色管线）
- `jiangnan_narrative`（9心智模型/5伦理铁律/Fragment与Grand Finale结构骨架）
- `jiangnan_longzu_patch`（龙族同人专用：伏笔意象化/温暖底色/角色一致性速查，tag=龙族同人专用）

**替换原因**：`jiangnan.skill` 是龙族专用共创协议（含同人专用补丁，CC BY-NC 非商业），整段 38KB 注入吃 token，且共创工作流层（引导式提问/配方卡/Checkpoint STOP）与灵砚一次性流式生成形态不匹配。`JiangNan-feeling-writing` quote-free 通用原创、MIT 协议、模块化（最小调用包 4 文件 ~6KB）、无同人专属包袱，更适合作为通用文风技巧对所有题材生效，故替换。
