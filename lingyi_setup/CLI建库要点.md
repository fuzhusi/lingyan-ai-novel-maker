# CLI 建库要点（已实测核验）

> 本文件记录**读源码 + 实跑**核出来的 CLI 行为，专治"命令跑成功了、数据却没进去"。
> 核验对象：`cli.py`（3508 行），核验时间：建库准备阶段。
> 与 `docs/cli操作指引.md` 的分工：那份讲"怎么用"，这份讲"哪里会咬人"。

---

## 一、十个坑（会丢数据 / 会建错 / 会让脚本误判成功）

### 坑 1 ★ `novel create` 不接受 `--author-intent` / `--current-focus`（静默丢弃）

`--author-intent` / `--current-focus` 定义在 `novel` 的**父 parser** 上，所以 `novel create --author-intent "…"` 语法上完全合法、不报错、退出码 0 —— 但 `cmd_novel` 的 create 分支只写 `title / genre / synopsis / world_intro` 四个字段（`cli.py:166-175`），**罗盘内容直接消失**。

正确做法（二选一）：

```bash
# 建书时留空，随后补
python cli.py novel create --title X --genre X --synopsis X --world-intro X
python cli.py novel update --id N --author-intent "全书承诺…" --current-focus "阶段目标…"

# 或走罗盘命令（有长度保护：intent 截断 500 字 / focus 截断 300 字）
python cli.py compass set --novel N --intent "…" --focus "…"
python cli.py compass show --novel N
```

### 坑 2 ★ `* update` 系列忽略空字符串，无法用 CLI 清空字段

`novel update` / `character update` / `world update` 的判定都是 `val is not None and str(val).strip()`（如 `cli.py:225`）。传 `--personality ""` **不会清空**，会被当作"未指定"。清空只能进 Web，或直接 SQL。

### 坑 3 ★ `foreshadow create` 不接受 `--status`，新建恒为 `open`

create 分支根本不读 `status`（`cli.py:863-870`），而 `update` / `status` 都带**单向状态机校验**（`cli.py:885-897`）：

```
open        → planned | buried
planned     → buried | abandoned
buried      → advancing | abandoned
advancing   → reclaimable | buried | abandoned     ← 唯一允许回退的一条
reclaimable → resolved | abandoned
resolved    → ∅（终态）
abandoned   → ∅（终态）
```

结论：
- 建库时**不能直接标 planned**，必须 `create`（得 open）→ 再 `foreshadow status --id N --status planned`。
- 想从 `open` 直接标到 `buried` 可以；但 `open → advancing` 之类的跨级一律被拒。
- 已 `resolved` 的伏笔**无法复活**。

### 坑 4 ★ `outline create-chapter` 不校验节点类型，且章号 = 当前最大值 + 1

`cli.py:1110-1138`：**对 volume 节点误用也会造出一章**（不检查 `node_type`），章号取 `max(chapter_number)+1`。

结论：
- 只对 `--type chapter` 的节点调用；
- **必须严格按叙事顺序调用**（章号靠调用次序累加，乱序会得到错位章号）；
- 它的额外好处：写 `outline_node_id`（章节↔大纲节点建立关联）+ 把 scene 子节点自动拼成「分幕指引」附在大纲尾部。

### 坑 5 ★ `chapter create` 不写 `outline_node_id`

`cli.py:306-321` 建的章节与大纲树**不关联**。本项目的一致性检查（`outline_stale`）与大纲联动都依赖这个关联。
**建章统一走 `outline create-chapter`**，不要用 `chapter create` 建正文章（`chapter create` 仅适合临时补一章）。

### 坑 6 ★★ `sys backup` 曾完全失效（已修复）

`cmd_sys` 里 `info` 分支内有一句**函数局部 `import os`**（旧 `cli.py:2920`），这会让 `os` 在整个函数作用域内变成局部名，于是 `backup` 分支里的 `os.path.exists()` 抛：

```
✗ 命令执行失败: cannot access local variable 'os' where it is not associated with a value
```

即 **"每天收工 sys backup" 这条被文档推荐的备份习惯，之前一次都跑不成**；且因为坑 7，它退出码还是 0，完全看不出来。已删除该局部 import（模块级第 39 行本来就有 `import os`），`02` 行的同类写法（旧 `cli.py:1762`，在 `cmd_blind` 里）一并清掉。**实测已修复**：`sys backup --output …` 生成 13.7 MB 副本。

### 坑 7 ★★ 失败靠文字 ✗，**退出码不可靠**

`cli.py` 里有大量 `print("✗ …"); return` 的写法，这些路径**退出码仍是 0**。抽查确认（沙箱内）：

```
queue adopt --id 99999                            exit=0
relation update --id 99999 --type rival           exit=0
foreshadow status --id 99999 --status buried      exit=0
llm agent-set --agent-type bogus --llm-model 1:x  exit=0
```

这意味着**只看退出码的脚本会把失败当成功**（坑 6 就是这么藏了很久）。

对策两层：
1. 工具层：`_lib.run_cli_expect_ok()` 要求 stdout 里出现 `✓`，否则中止——写操作一律走它。
2. 根因层：已给全局异常兜底（旧 `cli.py:3500`）补上 `sys.exit(1)`——**未捕获异常**现在正确返回 1（已实测：注入 RuntimeError → `exit=1`，此前为 0）。

> 注意：`sys.exit(1)` 只覆盖未捕获异常；被内部 `try/except` 吞掉的那些路径仍然是 `exit=0`，所以**判 `✓` 这一层不能省**。

### 坑 8 ★★ 一键本章在终稿门禁失败时，会把已生成的正文整个丢掉（**已修复**）

`cli.py:474-476`（旧写法）：`run_chapter_pipeline` 若返回 `error`（终稿门禁未通过），CLI **只打印一行错误就 return**：

- 不打印 `stages`（各阶段诊断全丢）；
- 不打印 `result["text"]`（约 2500 字正文直接丢弃）；
- `--out` 也不会写（写文件在 return 之后）。

**这个坑实测咬人**：试写第 3 章时门禁未通过，**470 秒（7.8 分钟）的生成成果当场作废**，`--out` 文件也没生成——三章里踩中一次。而 `chapter_runner.py:130-133` 其实**是把 `text` 带回来了的**，纯粹是 CLI 扔掉的。

**已修**（`cli.py` pipeline 分支）：无论成败都打印 stages 与人味分；有 `text` 时照样写 `--out`（并注明"门禁未过、未落库，仅供人工取用或改后重跑"）；失败路径补 `sys.exit(1)`，让脚本能识别。修后重跑第 3 章，正文不再丢失。

### 坑 9 ★★ CLI **没有任何命令能改章节正文**（人工润稿只能走 Web）

`chapter` 命令组只有 list / content（读）/ update（改标题）/ delete / version-*（查删）/ deai / pipeline / converge / condense。**没有 `save-content` 之类的写正文入口**。所以：

- 生成出来的正文要手工润色，只能在 **Web 写作页**改（保存会生成新版本）；
- 想在 CLI 侧"修一句硬伤"，只能**重新生成**（或写脚本直接改 `chapter_versions.content`，属绕过产品逻辑，谨慎）。

**对策**：正文级问题尽量在**生成前**用 `--directive`（特别指示，最高优先级注入）拦掉，见 `content/writing_directives.md`。别指望事后用命令行批量修稿。

### 坑 10 ★★ `writer_chain` 的"行文指纹修正指令"长期静默失效（已修复）

`app/services/writer_chain.py:170` 旧写法：

```python
sample_text = "\n\n".join(ch.content or "" for ch in reversed(recent))   # Chapter 没有 content 字段
```

正文存在 `ChapterVersion` 上，`Chapter` 没有 `content`，所以这里恒抛 `AttributeError: 'Chapter' object has no attribute 'content'`，被外层 `except` 吞成一句 warning —— 即**取最近两章正文生成 AI 痕迹修正指令**这个功能**从未生效过**，日志里只留一行 `writer_chain 上下文注入降级: …`。

修法（对齐 `prompt_builder/context.py` 的既有取法）：`ch.versions[-1].content`（`versions` 关系已按 `version_number` 排序）。**实测验证**：修复后该 warning 消失；连续生成第 2、3 章时不再出现。

> 注：验证时 `tone_instructions` 仍为空，查证是**真的没违规**（近两章人味分 95、违规 0 条 → `build_tone_instructions` 按设计返回空），不是修复没生效。

---

## 一之二、生产层实测（glm-5.3-flash · 沙箱真跑一章）

来源：`tests/test_generation.py`（12/12 通过），样本假角色、只验管线不验文笔。

| 项 | 实测值 | 说明 |
|---|---|---|
| 单章全流程用时 | **约 13 分钟**（773s） | 正文（含字数不足自动续写轮）+ 门禁 + 收敛重写；大纲已有则跳过 |
| 每章 LLM 调用 | 约 2-4 次 | 正文 1-3 轮（writer）+ 收敛 1 轮（rewrite） |
| 门禁行为 | 首测 ✗ → 收敛后通过 | `should_converge` 在人味分 <90 时触发；收敛后复测 |
| 人味分 | 92 | 收敛后 |
| 人工闸门 | 有效 | 版本落库但 `approved=0`，不自动审批 ✓ |
| `--out` | 正常写出 | .tmp-test/chapter_1.md（7585 字节） |
| 困惑度雷达 | **智谱不支持 logprobs** → 自动降级不可用 | 降级纪律生效，不崩；要此功能需换支持 logprobs 的厂商 |
| embedding 调用 | stderr 报 SSL/400 后降级字符频率 | 无害（语义记忆降级），量产时可忽略或排查 `text-embedding-3-small` 配置 |

**对 50 万字排期的意义**：200 章 × 13 分钟 ≈ **44 小时纯生成时间**（不含人工审阅/质检/返工）。量产后这是按天计的活，宜按"每天 N 章 + 审批 + 备份"的节奏走，而不是一口气跑完。

---

## 二、参数与默认值（建库时要用到的）

| 命令 | 要点 |
|---|---|
| `world create` | 需要 `--novel`；`update` / `delete` 只要 `--id`（不要 `--novel`） |
| `character create` | `--arc` 映射到模型的 `arc_direction`（角色弧光） |
| `outline create` | `--type` 取 `volume/chapter/scene`，缺省 `chapter`；`sort_order` 按 `(novel, parent)` 自增；`--parent` 必须属于同一本书 |
| `outline delete` | **级联删除子节点** |
| `foreshadow create` | 重要度→超时阈值自动映射：`≥9→30 章`、`≥7→20`、`≥4→15`、`<4→10`；用 `--threshold` 可覆盖 |
| `foreshadow timeout-check` | 活跃集含 `reclaimable`（口径与 Web 一致）；基准章缺省为最新章节号 |
| `template-outline apply` | 直接往书里灌 12–15 个节点，**无防重跑**，只能 apply 一次 |
| `novel export` | 走 `app.test_client()` 复用 Web 导出代码路径（同一实现）；输出默认「标题.格式」 |
| `sys backup` | 用 SQLite backup API（非裸拷贝，WAL 下不会撕裂）；`--output` 支持绝对路径 |
| `chapter pipeline` | `--dry-run` 不调 LLM，可零成本验证流程 |

**模型字段（导出/核验用）**：`characters(personality, speaking_style, appearance, background, motivation, arc_direction)`、`world_settings(category, title, content)`、`outline_nodes(parent_id, sort_order, node_type, title, summary)`、`foreshadowing(title, description, planted_chapter, status, importance, timeout_threshold, notes, earliest_resolve_chapter, expected_resolve_chapter)`。

> ⚠️ `earliest_resolve_chapter` / `expected_resolve_chapter`（不可提前收 / 预期回收）**CLI 无法写入**——那是拆书复刻的专用字段。长篇自己的回收排期只能写进 `--description` / `--notes`，或靠 `--planted` + 阈值来表达。

---

## 三、建库脚本（内容文件驱动）

**设计**：创意内容放 JSON（`lingyi_setup/content/`），脚本只负责搬运与校验 ——
内容能 diff、能逐条评审、改内容不用改代码。所有脚本支持 `--dry-run`（只打印将执行的
cli.py 调用，不写库）与 `--content-dir <目录>`（换内容目录，便于沙箱演练）。

| 脚本 | 读 | 写 | 防重跑 |
|---|---|---|---|
| `00_preflight.py` | — | 无（加 `--backup` 才写备份） | 书名占用检查 |
| `01_create_novel.py` | `novel.json` | novels + 创作罗盘 | 同名书中止 |
| `02_characters.py` | `characters.json` | characters（6 字段） | characters 非空中止 |
| `03_world.py` | `world.json` | world_settings | world_settings 非空中止 |
| `04_outline.py` | `outline.json`（嵌套） | outline_nodes（卷/章/景） | outline_nodes 非空中止 |
| `05_foreshadow.py` | `foreshadow.json` | foreshadowing + 状态推进 | foreshadowing 非空中止 |
| `06_relations.py` | `relations.json` | character_relations（按**姓名**引用角色） | character_relations 非空中止 |
| `07_instantiate_chapters.py` | `_state.json` 里的大纲清单 | chapters（写 outline_node_id） | chapters 非空中止 |
| `99_dump_review.py <id>` | 只读 | `review/*.md` + 完整性检查 | — |

**执行顺序**：`00 → 01 → 02 → 03 → 04 → 05 → 06 → 07 → 99`

JSON 结构直接照 `lingyi_setup/tests/sample_content/`（一份可运行的样本）。
状态文件 `content/_state.json` 由脚本自己维护（novel_id / 角色名→ID / 大纲 ID 清单），**不要手改**。

**纪律**：每个脚本都用 `_lib.py` 的 `assert_novel_absent` / `assert_novel_empty` 做防重跑；同名字段在 DB 层**无唯一约束**，重复跑会灌出两份数据。所有脚本用 `.venv/Scripts/python.exe` 跑，内部经 `_lib.run_cli()` 调 `cli.py`。

## 三之二、沙箱演练（对真库动刀前的必做动作）

```
.venv/Scripts/python.exe lingyi_setup/tests/test_build_chain.py [--keep]
```

它用 SQLite backup API 把真库复制成 `.tmp-test/lingyi_sandbox.db`，设 `DATABASE_PATH`
指向副本，跑完 `01→07` 全链后逐项核验（角色 6 字段完整性 / 世界观分类 / 大纲层级 /
伏笔状态推进 / 章号连续且顺序正确 / scene 并入分幕指引 / 防重跑保险丝 / dry-run /
只读导出 / **真库零改动**），当前 **37 项断言全绿**，结束自动清理。

`DATABASE_PATH` 由 `app/config.py:14` 支持（相对路径按项目根解析），cli.py 与全部
导出/检查脚本都会跟随——这是"先演练、再动真库"的实现基础。

> 沙箱注意：`%TEMP%` 系统临时目录在本机沙箱下**不可写**，临时目录一律放工作区
> `.tmp-test/`。

## 三之三、为什么工具链是 Python 而不是 bash / PowerShell（实测）

`longzu_setup/` 用的是 bash，但这台机器上两条路都不通：

| 方案 | 实测结果 |
|---|---|
| bash | 只有 `C:\Users\gen\AppData\Local\Microsoft\WindowsApps\bash.exe`（WSL 桩子），不可用 |
| `pwsh` | **不存在**（脚本里调 `pwsh` 报 CommandNotFound） |
| `powershell`（5.1.26100） | 按 ANSI 读取无 BOM 的 .ps1 → 脚本里的中文被误码，直接抛 `Unexpected token '}'` 语法错误 |
| Python（`.venv`） | ✅ `subprocess.run(capture_output=True, encoding="utf-8")` 抓 `cli.py` 输出 rc=0、中文正常 |

所以建库脚本统一走 Python，共用工具在 `_lib.py`。**不要**为了跟 `longzu_setup` 保持一致而回头写 .ps1。


---

## 四、本仓库当前状态快照（体检所得）

- Python 3.14.7（`.venv\Scripts\python.exe`）；`data.db` 约 13.1 MB
- 外壳：Windows PowerShell **5.1**（无 `pwsh`）；`bash` 只有 WSL 桩子 → 建库工具链走 Python（见 §三之二）
- 已有长篇 3 本（ID 1《你应该好好爱自己》24 章 / ID 2《长生无线》60 章 / ID 3《龙族：同级生》18 章）——**建库脚本不得误伤**
- 启用厂商：智谱 GLM（`glm-5.3-flash` 为唯一勾选模型）；16 个 Agent 全部走在它上面
- 文风：全局锚例为《龙族》江南原文（1643 字，启用中）；`jiangnan_fingerprint` + `jiangnan_preset` 已激活
- 去 AI 味约束词库：启用
- Web：`http://127.0.0.1:5000` 已在运行
- **本次已修的 cli.py 缺陷**（两处，均已实测）：坑 6 `sys backup` 因局部 `import os` 完全失效；坑 7 未捕获异常退出码为 0（现为 1）
