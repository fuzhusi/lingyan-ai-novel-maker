# CLI 操作指引 —— 从零写成一本书

> 面向**创作流程**的实操手册：怎么按顺序把一本书从建档案到导出成稿。
> 完整命令参考见 [MCP & CLI 使用指南](mcp-cli-guide.md)，本文只讲"怎么用"。
> 以《你应该好好爱自己》为贯穿示例。

---

## 0. 开始之前

所有命令都在项目根目录执行。Windows Git Bash 下二选一：

```bash
# 跑法一：显式用虚拟环境的 Python（本文后续统一用这种写法）
.venv/Scripts/python.exe cli.py novel list

# 跑法二：先激活虚拟环境，之后直接 python
source .venv/Scripts/activate
python cli.py novel list
```

> 直接敲 `python cli.py` 报 `No module named 'flask'`，说明用的是系统 Python，
> 换成上面任一跑法即可。PowerShell 用户用 `.\.venv\Scripts\Activate.ps1`。

**CLI 与 Web 的分工原则**：

| 干什么 | 在哪干 |
|--------|--------|
| 建小说、角色、世界观、大纲、伏笔、关系 | CLI 或 Web 均可 |
| 写正文、续写、一键本章（流式生成） | Web 写作页（`python run.py` 后访问 http://127.0.0.1:5000） |
| 统一评审（Critic + 双盲审合并报告） | Web 写作页 |
| 盲审工作台勾选意见改稿 | Web `/blind/` |
| 审批章节、去AI化诊断、全书诊断、导出 | CLI 即可（blind run/rewrite 也在 CLI） |

CLI 免登录，直接读写 `data.db`，与 Web 看到的是同一份数据。

---

## 1. 第一次使用：配好模型（只做一次）

没有厂商配置，所有生成类操作都会失败。四步配完：

```bash
PY=.venv/Scripts/python.exe   # 下文用 $PY 代指

# 1) 看有哪些预设（11 家：deepseek/openai/moonshot/zhipu/qwen/...）
$PY cli.py llm preset-list

# 2) 按预设添加厂商，填 key 即用（Ollama 本地无需 key）
$PY cli.py llm provider-add --preset deepseek --api-key sk-xxxx

# 3) 拉取该厂商的模型列表
$PY cli.py llm fetch-models --provider 1

# 4) 勾选要用的模型（勾选后即进入自动默认池）
$PY cli.py llm model-list --provider 1     # 先看编号
$PY cli.py llm model-toggle --model 2      # ● = 已勾选
$PY cli.py llm test --provider 1           # 连通性测试
```

不配置 Per-Agent 也能用：**自动默认**会给快速类 Agent（writer/outline/summary…）
优先挑 flash/lite/mini 系模型，深度类（critic/rewrite/…）优先挑 pro/max/plus 系。

想精细控制时：

```bash
$PY cli.py llm agent-list                                # 16 个 Agent 当前生效模型
$PY cli.py llm agent-set --agent-type critic --llm-model 1:deepseek-v4-pro
$PY cli.py llm agent-param --agent-type writer --temperature 0.9 --max-tokens 4096
$PY cli.py llm effective --agent-type writer             # 查实际生效配置（排错用）
```

---

## 2. 创建小说

```bash
$PY cli.py novel create --title "你应该好好爱自己" --genre "都市情感" \
    --synopsis "一句话故事概括" --world-intro "故事发生的时代与城市背景"
$PY cli.py novel list      # 拿到小说 ID，下文假设为 1
$PY cli.py novel info --id 1
```

剧情讨论清楚后随时补全/修改：`novel update --id 1 --genre X --synopsis Y --world-intro Z`。

---

## 3. 搭知识库（写正文前最重要的一步）

生成质量 = 注入上下文的质量。正文生成时会自动带上这些设定，
**先在 CLI 把角色/大纲/伏笔录好，再去 Web 生成，效果远好于空库裸写**。

### 3.1 角色

```bash
$PY cli.py character create --novel 1 --name "林晚" \
    --personality "讨好型人格，习惯把所有人排在自己前面" \
    --speaking-style "语气温和，道歉是口头禅" \
    --background "重症监护室护士，长女，弟弟的学费她出" \
    --motivation "让所有人都满意" \
    --arc "从'为别人活着'到'先好好爱自己'"

$PY cli.py character list --novel 1        # 拿到角色 ID
$PY cli.py character update --id 2 --personality "..."   # 随剧情推进随时改
$PY cli.py character info --id 2
```

小技巧：`character template-list` 有 6 种模板可快速起步，但现言/都市题材
通常手写更贴合。

### 3.2 角色关系（可选，评分会随事件自动演化）

```bash
$PY cli.py relation create --novel 1 --char-a 2 --char-b 3 --type friend --desc "..."
$PY cli.py relation event --id 1 --event open_talk --intensity 1.2   # 推进关系
```

### 3.3 世界观（都市文也建：城市、行业规则、时间线）

```bash
$PY cli.py world create --novel 1 --category "背景" --title "江城" \
    --content "南方二线城市，故事跨度一年，从深秋到次年夏末"
```

### 3.4 大纲（推荐：先大纲后章节）

```bash
# 卷 → 章 → 场景 三级结构；先建卷
$PY cli.py outline create --novel 1 --title "第一卷：熄灯的人" --type volume --summary "..."

# 卷下建章节点（--parent 指向卷 ID）
$PY cli.py outline create --novel 1 --title "第1章" --type chapter \
    --parent 1 --summary "本章要发生什么、结束在哪个钩子上"

# 需要更细的分镜时挂场景节点
$PY cli.py outline create --novel 1 --title "天台谈话" --type scene --parent 2 --summary "..."

# 大纲节点一键转章节：标题/大纲预填，子场景自动并入"分幕指引"
$PY cli.py outline create-chapter --novel 1 --id 2
```

Web 端还有 4 种大纲模板（节拍式 15 节点 / 三幕式 / 英雄之旅 / 四幕式）可套用。

### 3.5 伏笔（长篇生命线）

```bash
$PY cli.py foreshadow create --novel 1 --title "母亲的体检报告" \
    --description "第3章一闪而过的信封，中段引爆" --importance 8 --planted 3

# 状态机: open → planned → buried → advancing → reclaimable → resolved
$PY cli.py foreshadow status --id 1 --status buried
$PY cli.py foreshadow timeout-check --novel 1    # 超期未回收的伏笔预警
```

### 3.6 故事状态（可选，管节奏）

```bash
$PY cli.py state set --novel 1 --quest "林晚学会先爱自己" --phase setup --intensity 2
$PY cli.py state snapshot --novel 1 --chapter 10 --checkpoint   # 关键节点存档
$PY cli.py state rollback --novel 1 --snapshot 3 -y             # 走歪了回滚
```

---

## 4. 章节与生成

```bash
$PY cli.py chapter list --novel 1
$PY cli.py chapter create --novel 1 --number 1 --title "熄灯" \
    --outline "本章大纲" --directive "给生成器的特别指示（可含 @技能id）"
$PY cli.py chapter content --novel 1 --number 1 [--full | --length 2000]
```

**写正文有两条路**：

```bash
# 路线A：CLI 一键本章（整章生成→质量门禁→AI味收敛→自动落版本，全程在终端）
$PY cli.py chapter pipeline --novel 1 --number 1 --save
$PY cli.py chapter pipeline --novel 1 --number 1 --save --directive "给生成器的特别指示"

# 路线B：Web 写作页（流式逐字输出，交互更丰富）
python run.py  # → http://127.0.0.1:5000 → 小说 → 写作页
```

1. 写作页右侧勾选"本章出场角色"（少勾 = 上下文更聚焦）；
2. 「一键本章」：缺大纲先生成大纲 → 正文 → 质量门禁 → AI味收敛 → 停在人工审阅；
3. 不满意用「统一评审」拿 Critic 分数 + 阎浮/白骨双盲审意见，勾选意见改写二稿。

---

## 5. 质检三件套（零 LLM 成本的先跑）

```bash
$PY cli.py audit run --novel 1 --number 1 --detailed  # 词法层 AI 痕迹统计
$PY cli.py chapter deai --novel 1 --number 1 [--save] # 去AI化诊断，--save 存新版本
$PY cli.py optimize diagnose --novel 1                # 全书逐章体检

# 要 LLM 的深检（花钱但狠）
$PY cli.py blind run --novel 1 --number 1             # 双盲审，追读/弃稿二值判决
$PY cli.py blind latest --novel 1 --number 1          # 看最近一次盲审
$PY cli.py blind rewrite --novel 1 --number 1 [--only baigu] --out 二稿.md
```

---

## 6. 审批与导出

```bash
$PY cli.py chapter approve --novel 1 --number 1   # 审批最新版（生成摘要+结构化记忆）
$PY cli.py novel export --id 1 --format docx      # txt/docx/md/html/epub
$PY cli.py novel export --id 1 --format epub --output 你应该好好爱自己.epub
```

审批是分水岭：审批后生成摘要、写入记忆，供后续章节上下文注入；
每章改到满意再审批，节奏最好。

---

## 7. 速查表

```bash
$PY cli.py novel list / info / update / export / delete
$PY cli.py chapter list / content / update / approve / version-list / version-content / deai / delete / stale / pipeline / converge / condense / consistency-check
$PY cli.py character list / create / info / update / delete / template-list
$PY cli.py world list / create / update / delete
$PY cli.py outline list / create / update / delete / create-chapter
$PY cli.py foreshadow list / create / status / update / timeout-check / delete
$PY cli.py relation list / create / update / event / delete
$PY cli.py state get / set / auto-detect / snapshot / snapshots / rollback
$PY cli.py short list / create / content / version-list / approve / export
$PY cli.py llm preset-list / provider-* / fetch-models / model-* / test / agent-* / effective
$PY cli.py skill list / active / toggle / info / preview / create / delete
$PY cli.py constraint show / status / toggle
$PY cli.py audit run · blind run/latest/rewrite · optimize diagnose/deai
$PY cli.py setting list / set / get / apply-recommended
$PY cli.py compass show / set                       # 创作罗盘（全书承诺+阶段目标）
$PY cli.py queue list / adopt / discard              # 抽取待确认队列（错抽不落真相库）
$PY cli.py preferences show / set                    # 创作偏好档案（长期有效写作约束）
$PY cli.py tone check / converge / radar             # 去AI味检测/收敛/困惑度雷达
$PY cli.py style-anchor view / set / toggle / preview # 文风锚例（真人原文直插prompt）
$PY cli.py template-outline list / show / apply       # 大纲模板（节拍式/三幕/英雄之旅/四幕）
$PY cli.py pipeline --novel 1 --number 5 --save      # 一键本章流水线（CLI版，生成→门禁→收敛→落版本）
$PY cli.py sys info / backup / sample-data
```

> 备份习惯：每天收工 `sys backup`，写崩了有退路。
