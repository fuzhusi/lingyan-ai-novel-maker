# 约束 Prompt Engineer —— AI 写小说「去 AI 味」约束提示词调研汇编

> 定位：本文档把网络上（小红书高赞笔记生态、知乎、今日头条、SMZDM、NGA、LINUX DO、GitHub 开源 skill、英文社区）流传的「AI 写小说去 AI 味」约束提示词做了一次集中调查与归纳，蒸馏成**可拼装的提示词模块（mod）**，并映射到灵砚现有体系。
> 关联文档：[ai-tone-research.md](ai-tone-research.md)（283 万字对照语料研究与朱雀实测校准）、CLAUDE.md「去 AI 化 / 一致性保障」章节。
> 调研日期：2026-08-26。
>
> **取证等级说明**（本次调研沙箱无法直连抓取网页全文，全部结论来自搜索引擎摘要片段与多来源交叉验证）：
> - ✅ = 原文 / 官方描述证实
> - ⚠️ = 镜像或转述，非原文
> - ❓ = 仅确认存在，正文未获取

---

## 一、平台侧现实约束（为什么必须去 AI 味）

中文网文平台已从「劝导」进入「处罚」阶段：

| 平台 | 动作 | 关键细节 |
|------|------|---------|
| **番茄小说** | 处罚最重 | 49 位金番作者被罚、15 万本书被处置（另一口径 2.8 万部直接下架）；**200+ 维度检测 AI 文**，设定冲突率超 60% 即封号；**百万字老书也要定期抽检**，不豁免存量 |
| **起点 / 阅文** | 限流割席 | 正文带明显 AI 痕迹即限流降权；**均订过万的爆款也照样下架** |
| **晋江文学城** | 规则最细 | 三道安全线：①可用 AI 查资料、梳理思路 ✓ ②可用 AI 润色**作者本人已写出**的文字 ✓ ③**不得让 AI 直接生成正文** ✗ |

行业共识方向：
1. 平台查的是**统计指纹**而非单句抄袭——维度化检测（叙事指纹、句式模式、设定一致性、困惑度）。逐词替换不够，必须改结构与信息密度。
2. 「AI 搭骨架、血肉必须是人的」，正文须人工主导深度改写；「人工改写占比 ≥30%」在多个来源被提及但无统一官方量化口径。
3. 编辑侧：AI 投稿使审稿工作量增加约 50%（中国作家网），「情节挑不出错但没灵魂」的伪人感文本是退稿重灾区。

来源：[马良写作·番茄治理指南](https://maliangwriter.com/blog/fanqie-ai-crackdown-2026-guide/)、[头条·番茄起点划红线](https://m.toutiao.com/article/7656774622511137331/)、[头条·200+维度检测](https://m.toutiao.com/article/7659398571036377600/)、[界面新闻·起点动刀均订过万AI书](https://www.jiemian.com/article/14971052.html)、[中国作家网·李玮](https://www.chinawriter.com.cn/n1/2025/0905/c404027-40557712.html)、[澎湃·网文作者困在AI味里](https://m.thepaper.cn/newsDetail_forward_33518939)（部分为片段级取证 ⚠️）

---

## 二、AI 味的本质：跨语言同构指纹

中英文社区的抱怨清单存在一一对应的同构关系，说明这些是**模型级指纹**而非某种语言的偶然现象：

| 中文圈高频抱怨 | 英文圈高频抱怨 | 同构关系 |
|--------------|--------------|---------|
| 「不是 A 而是 B」翻案腔（NGA、LINUX DO 有独立专帖求解，单项抱怨之王） | "it's not X, it's Y" / "not just X, but Y" | 否定—翻转修辞 |
| 排比三件套 / 三段式正则 | rule of three（三项并列节奏指纹） | 三项并列 |
| 破折号滥用、揭晓式停顿 | em-dash 过载（反 AI 文学圈刻意少用破折号，Wired 报道） | 揭晓式插入语 |
| 名词化、「带来一种…的感觉」 | nominalization / abstract inflation | 动词→抽象名词 |
| 万能喻体（「像一位智慧的导师」） | purple prose 拟人比喻（the city breathed） | 理想化喻体 |

底层机制与朱雀检测原理一致（详见 [ai-tone-research.md](ai-tone-research.md) §一）：困惑度过低（选词永远最优解）、句长突发性不足、跨段 n-gram 重复率高、风格均匀无波动。**解法不是换词，而是破坏统计规律性。**

---

## 三、约束规则总库（按层分类）

以下规则按「暴露 AI 的致命程度」从结构层到词表层排列。词表层已被社区普遍降级为入门手段。

### A. 结构与篇章层（流传度最高，最致命）

| # | 规则 | 来源与取证 |
|---|------|-----------|
| A1 | **人定结构、AI 填空**：严格按给定大纲写，「不许自己加引言/总结/额外小标题，详略按我标注来」——传播最广的去 AI 味秘籍核心原则 | [头条·去AI味秘籍](https://m.toutiao.com/w/1857472370196492/) ✅ |
| A2 | 禁列表、禁小标题、禁总分总八股：「只用完整段落……要连贯叙述」 | 同上 ✅ |
| A3 | 禁刻板逻辑词：「不要使用'首先、其次、最后''一方面、另一方面'这种刻板的逻辑词，段落长度要参差不齐，打破视觉对称感」 | [新浪·DeepSeek全套去AI味万能提示词整合](https://www.sina.cn/news/detail/5321037941833820.html) ✅ |
| A4 | 禁段末升华点题、金句收尾 | [y10reo/stop-slop-zh](https://github.com/y10reo/stop-slop-zh) ✅ |
| A5 | 删除解释性复述：同一信息出现两次（场景演一遍、叙述再讲一遍）即删 | [MikkoParkkola/anti-ai-tell](https://github.com/MikkoParkkola/anti-ai-tell) ✅ |
| A6 | 禁 essay 式「总起—分述—总结」进入叙事；开头禁模板句（"In the ever-evolving…"类） | [Anti_Slop_AI_Writing_Guide](https://raw.githubusercontent.com/louisfb01/ai-engineering-cheatsheets/main/Anti_Slop_AI_Writing_Guide.md) ✅ |
| A7 | 类比全篇最多 1 个（流传说法；与「零配额」方法论有张力，见 §四-9） | [头条·去AI味秘籍](https://m.toutiao.com/w/1857472370196492/) ✅ |
| A8 | 信息密度不均：有的密集推进，有的放慢写一个细节；重要多写、次要一句带过 | 多来源共识 |

### B. 句式构式层

| # | 规则 | 来源与取证 |
|---|------|-----------|
| B1 | 禁「不是 A 而是 B」全家族及变体（看似…实则 / 你以为…其实 / 说到底 / 与其说…不如说）→ 直接正面下判断 | NGA/LINUX DO 专帖 ✅ + 灵砚语料研究 R=3.4 |
| B2 | 拆排比三件套；「两项优于三项」；只有**跨相邻句**的同构才判违规（句内排比人类更高频） | [VincentOld/stop-slop-zh](https://github.com/VincentOld/stop-slop-zh) ✅ + humanizer-zh 家族 ⚠️ |
| B3 | 破折号限额：禁揭晓式用法（「答案很简单——专注」）；DeepSeek 高发（5.16‰ vs 人类 0.80‰） | Wired ✅ + 灵砚语料研究 |
| B4 | 去名词化：动词→抽象名词短语还原为动词；抽象主语换成具体细节 | stop-slop-zh 三大构式手术 ✅ |
| B5 | 提示语后禁冒号引出内容；对话后禁加「他沉声道」「她冷笑道」等情绪注解 | 灵砚语料研究 R=3.8 + 多来源 |
| B6 | 禁 "suddenly"/「霎时间」与程度副词堆叠；禁每个动作都带「了一下」式尾巴 | [gerimileva AI tells 清单](https://www.gerimileva.com/ai-writing-patterns-to-avoid-a-practical-list-of-ai-telltales/) ✅ + oh-story ✅ |
| B7 | 相邻句结构同款（逗号数/成分序相同连排）→ 打散其中一句句法 | 灵砚语料研究 R=2.0 |
| B8 | 顿号并列过密：一句内 ≥2 顿号串三项以上 → 概括或改一项句法 | 灵砚语料研究 R=1.8 |

### C. 词表层（辅助层，入门级手段）

中文高频套词（社区词表已工程化为开源禁用库）：
> 眼底闪过一丝、嘴角勾起一抹、不禁、不由得、心中五味杂陈、空气中仿佛凝固、不知过了多久、一抹微笑、如释重负、深深地、缓缓地、攥紧、若有所思、意味深长、眼中闪过、他深吸一口气、他知道/明白/意识到

英文 slop 词族（供英文创作或翻译腔参照）：
> delve、tapestry、testament、realm、landscape、navigate、underscore、pivotal、crucial、foster、leverage、showcase、vibrant、ever-evolving

感官陈话："barely above a whisper"、"eyes glinted"、"shivers down her spine"、"heart hammered"、"breath hitched"；膨胀套话："plays a significant role"、"serves as a testament"、"it is important to note"；悬念套路："couldn't help but"、"little did they know"。

工程形态参考：
- 词表做成**数据文件**而非散落 prompt：[oh-story banned-words.md](https://github.com/worldwonderer/oh-story-claudecode)、[Lniosy/qiqing-liuyu de-ai-patterns](https://github.com/Lniosy/qiqing-liuyu) ✅
- Wikipedia《Signs of AI writing》已被整体移植为中文 [Humanizer-zh](https://github.com/op7418/Humanizer-zh)（Show-Chan97 有镜像版）⚠️
- **Sukino Banned Tokens.txt** 不是提示词而是采样层禁用字符串表（SillyTavern/KoboldCPP 用 logit bias 直接压制生成）；其词条持续增删的历史证明**规则表必须随模型版本迭代维护** ✅
- antislop-sampler / auto-antislop：从基线语料自动挖掘超频 n-gram 再硬抑制——效果优于 prompt 内禁词 ✅

### D. 小说叙事 / 对话 / 视角层

| # | 规则 | 来源与取证 |
|---|------|-----------|
| D1 | 对话前角色要带「算盘」（潜台词与利益动机）：白开水对话的病因是对话不承载信息差 | [xs91](https://www.xs91.com/archives/5404.html) ✅ |
| D2 | 默认零对话标签或中性标签＋动作拍（action beat）；禁副词标签（"said angrily"）；禁为求变化轮换花哨动词（exclaimed/snickered/chortled） | gerimileva ✅ + [lguz/humanize-writing-skill](https://github.com/lguz/humanize-writing-skill) ✅ |
| D3 | POV 锁定禁 head-hopping；限缩全知旁白的意义点评（AI 爱替读者总结主题） | anti-ai-tell ✅ |
| D4 | 情绪禁直述标签（"a wave of sadness washed over"/「一股暖流涌上心头」）→ 改生理细节与可观察行为；镜头贴角色感知距离 | gerimileva ✅ |
| D5 | 禁「安排感/硬铺垫」：为后文强行交代背景、整段回忆倒叙 → 背景按角色此刻真实所需，用**闪念、半句话、物件零碎**带出，不集中交代 | oh-story anti-ai-writing 对照表 ✅ |
| D6 | 伪人感诊断：情节挑不出错但没灵魂 = 缺动机链与具体细节锚点 | [澎湃](https://www.thepaper.cn/newsDetail_forward_30189980) ⚠️ |

### E. 正向注入层（人味加法——比禁令更重要）

这是各来源分歧最小、也最被 2026 年后的新方案强调的一层：

| # | 规则 | 来源与取证 |
|---|------|-----------|
| E1 | 注入情绪化表达：「价格较高」→「贵死了」；让人物有态度、有脾气 | 墨云实验（100%→0% 案例，见 ai-tone-research §七）⚠️ |
| E2 | 拥抱不完美：话说一半、跑题、自我打断、人物说错话做错事被误会 | 墨云实验 + 灵砚约束第五条 |
| E3 | 制造不确定性：叙事者不确定的事就写成不确定，别给完美因果链 | 墨云实验 ⚠️ |
| E4 | 抽象一律落到具体动作/物件上；主语用人物名不用「某种情绪」 | stop-slop-zh + xs91 ✅ |
| E5 | 比喻只用角色职业范围内的日常喻体（「像个看了三十年的老中医」），禁理想化人格喻体 | 灵砚语料研究 R=7.3（拟人化理想化喻体是人类 7.3 倍） |
| E6 | **Verified restraint（经核实的克制）**：禁止堆假细节装具体——细节要么可核实要么省略 | [Anbeeld/WRITING.md](https://github.com/Anbeeld/WRITING.md) v1.3.0 第 6 条 ✅ |
| E7 | **C23 内心活动最低密度约束**：给内心活动占比设硬下限（注意是下限——纯禁令体系全是上限思维，这条反向补丁防止文本干瘪） | [DankerMu/novel-writer-cli issue #137](https://github.com/DankerMu/novel-writer-cli/issues/137) ✅ |
| E8 | **C24 结构呼吸/功能冗余**：句段长短交替、保留功能性冗余，防文本过密 | novel-writer-cli issue #176/#177 ✅ |
| E9 | 加入闲笔：路边的猫、收音机里的歌、窗台上的灰——看似无关的细节是人味标志 | 灵砚约束已有 + SMZDM 系列 |
| E10 | **正向锚例（few-shot ❌/✅ 对照）执行率显著高于纯规则堆叠**——给范文让模型模仿「怎么写」，而非罗列「别写什么」 | 各 skill 普遍采用此格式 ✅ + cybercorsairs 论证 |

---

## 四、失效机制与反直觉发现（比规则更值钱的部分）

1. **打地鼠效应**（cybercorsairs）：写作 tic 是分布层面的习惯，禁掉一个词，概率质量转移到近义表达或同一句构——清单越拉越长却治标不治本。[来源](https://cybercorsairs.com/kill-your-ais-favorite-word-for-good/) ✅
2. **粉红大象效应**（Semantic Gravity Wells）：负面指令提及目标反而激活它，实证研究显示否定约束会把模型表征拉向被禁内容。[arXiv 2404.15154](https://ar5iv.labs.arxiv.org/html/2404.15154) 等 ✅
3. **越改越重**：朱雀两次升级后，纯换词稿反而更易被判 AI——词汇层干净而篇章层均匀的文本恰好落进检测器的「高置信 AI」区间。[SMZDM](https://post.smzdm.com/p/a26zpo5q/) ⚠️
4. **过度去 AI 制造新 AI 味**：「整段只剩最短句、结构虚词被扫光、每个动作都带『了一下』式尾巴」的电报体本身就是可识别风格（oh-story 自检规则）；另有《别再用提示词去AI味了，方向就是错的》全盘否定词表路线。[新浪](https://www.sina.cn/news/detail/5266447188361356.html) ⚠️
5. **问题多半不在词上**：翻完 20 多篇小红书高赞笔记的总结论——稿子被认出来主要败在结构层面（小标题/列表/总分总/金句收尾的点名频率高于任何单词）。[SMZDM 主文](https://post.smzdm.com/p/a4qdpzzw/) ⚠️
6. **人机分工 ＞ 让 AI 洗自己**：传播最广的秘籍主张人接管大纲与详略、AI 只填空，而非丢一段文字让模型自检自改。手写文也会被误判，已有作者反向「加噪」自保。[SMZDM](https://post.smzdm.com/p/aqr0vgrk/) ⚠️
7. **写作时干预 ＞ 事后改写**：LLM 直接「带着人味写」句长 CV 可达 0.62，事后改写只能到 0.31（humanize-chinese 实证，见 ai-tone-research §3.1）。humanize-writing 系工具全部定位为事后 tone 校正，属于兜底而非主力。
8. **没有任何来源认为纯负面清单足够**。「正向锚例 ＋ 重写循环 ＋ 确定性检测 ＋ 采样层硬抑制」是共同架构（分层防御）。
9. **配额悖论**：流传的硬配额（类比≤1 个等）与 novel-writer-cli 的「零配额＋统计目标」方法论冲突——后者用统计指标替代机械禁词计数，避免为满足配额而牺牲表达。采纳流传配额时应降级为软指引。

---

## 五、可直接复制的约束提示词模块（mod 化交付）

以下模块按场景拼装使用。设计原则来自调研共识：
- 结构分工 ＞ 构式黑名单 ＞ 具体化指令 ＞ 防过头自查，词表只作辅助层；
- ❌/✅ 对照锚例必带，执行率远高于纯规则；
- 每个模块保持可单独引用（规则文件与执行入口分离，参照 Anbeeld/WRITING.md 架构）；
- 注意力预算：约束总量控制在千字级，放在 system 首尾位置（中间约束会被数千字上下文稀释——灵砚实测教训）。

### M0 · 角色设定模块（生成场景通用）

```text
【身份】你是签约平台的网文笔名作者，正在连载。任何一段被读者或编辑认出
"模板腔"，都会导致本章限流。你写的是给人追更的小说，不是给检测器看的范文。
```

### M1 · 结构分工模块（篇章层，优先级最高）

```text
【结构与详略 — 最高优先级】
- 严格按照我给出的大纲与详略标注写，不许自己加引言、总结、小标题或列表，
  不许总分总，不许每章结尾强行留钩子或升华点题。
- 只用完整段落连贯叙述；段落长度必须参差不齐（有的 2 行，有的 8 行），
  打破视觉对称感。
- 不用"首先/其次/最后""一方面/另一方面"这类刻板逻辑词组织段落。
- 信息密度故意不均：重要的地方放慢放大写，次要的一句带过；
  允许中途跳跃、打断和看似无关的闲笔（一只猫、一首歌、窗台上的灰）。
```

### M2 · 构式黑名单模块（句式层）

```text
【句式禁令】
- 禁"不是A而是B"及其一切变体（看似…实则／你以为…其实／说到底／与其说…不如说）
  ——想清楚就直接正面下判断。
- 并列两项即可，禁三项排比连发；相邻两句不要用同样的句法结构（逗号数、
  成分顺序都一样的那种对仗感）。
- 破折号全篇最多一两次，禁用它做揭晓式停顿；提示语后不用冒号引出内容。
- 动词别名词化："带来一种窒息的感觉"→"喘不上气"；抽象主语落到具体的人身上。
- 对话后不加"他沉声道""她冷笑道"式注解——直接写话，或用一个动作代替。
- 少用"了一下""微微""缓缓""深深"这类尾巴与叠词副词。
```

### M3 · 词表辅助模块（可选裁剪，随模型版本迭代维护）

```text
【禁用词（出现即扣分）】
眼底闪过一丝｜嘴角勾起一抹｜不禁｜不由得｜心中五味杂陈｜空气中仿佛凝固｜
不知过了多久｜一抹微笑｜如释重负｜深深地｜缓缓地开口｜攥紧｜若有所思｜
意味深长｜他深吸一口气｜他知道/明白/意识到（开头的内心独白）
```

### M4 · 具体化与正向注入模块（人味加法，权重不低于 M2）

```text
【怎么写才有人味】
- 情绪不许贴标签（"一股悲伤涌上来"），写到身体和动作上：
  ❌ 她不禁愣住，眼底闪过一丝复杂的神色，空气中仿佛凝固了。
  ✅ 她把筷子搁下，半天没夹那块排骨。
- 人物开口前先想好他的算盘：这句话他想得到什么？对话要承载信息差和博弈，
  不要互相通报剧情。
- 内心戏要有量：每个场景至少一处真实的内心活动（纠结、盘算、自我说服），
  不能全程只有外部动作。
- 比喻的喻体用这个角色的生活半径内的东西（"像个看了三十年的老中医"），
  禁用理想化人格（"像一位智慧的导师"）。
- 细节要么可核实要么省略，不许堆假细节装具体；保留功能性冗余，
  该啰嗦的地方允许啰嗦，别把句子削得太干净。
- 允许不完美：话说一半、跑题、自我打断、人物说错话做错事；
  叙事者不确定的事就写成不确定，别给完美因果链。
```

### M5 · 防矫枉过正自查模块（收尾必挂）

```text
【写完自查 — 不要矫枉过正】
- 通读一遍：如果整段只剩最短句、虚词被扫光、每个动作都带"了一下"式尾巴，
  你已经删过头了（电报体也是 AI 味），回去补血肉。
- 比喻、设问、句内排比是人类写作的自然特征，正常使用不要刻意回避；
  要删的是套路化的用法，不是这类修辞本身。
- 只删"怎么说"的 AI 味，不删"说什么"——废句先判能否整句删掉，
  删不掉再润色，第一动作是删不是换同义词。
- 保留自然的不完美，不要把所有毛边都磨平。
```

### M6 · 输出契约模块（改写/润色场景专用）

参照 sabialab/de-ai-flavor 的三段式契约 ✅：

```text
【输出格式】
第一步：体检报告 —— 给出 AI 味浓度评分(0-100)，列出命中的具体条目
        （引用原句），并明确指出"哪里本来就写得好"（这些地方一个字不动）。
第二步：改写后全文。
第三步：改动说明（三行以内）。
```

### M7 · 流程分工模块（项目级，非单次生成）

```text
【流程】人定全书大纲 → 人拆本章细纲（目标/冲突/钩子）→ 按细纲生成正文 →
确定性 lint（陈词滥调/构式指纹）→ 人工深改（平台要求正文人工主导）。
生成时一次只喂一章细纲，禁止模型自行扩纲。
```

### 拼装建议

| 场景 | 启用模块 |
|------|---------|
| 长篇章节生成 | M0 + M1 + M2 + M4 + M5 |
| 短篇逐节点生成 | 同上，另加「节点间措辞去重」指令（跨段三元组重复是逐节点生成的结构性病灶） |
| 已成稿去 AI 味改写 | M6 + M2 + M4 + M5（先体检后动手） |
| 快速轻量场景 | M1 + M2 + M5（结构+构式+防过头是性价比最高的三件） |

---

## 六、工程架构启示（开源项目的做法）

1. **三层纪律**（[MikkoParkkola/anti-ai-tell](https://github.com/MikkoParkkola/anti-ai-tell)，Claude Code 插件形态）✅：
   - 第一层 prompt constraints：能写成规则的进提示词，事前阻止；
   - 第二层 evidence-based linter：成稿后确定性检查器，只报可定位可复核的违规；
   - 第三层 judgment checklist：需要语感的交给评审模型/人按清单过。
   - 分层逻辑：**能形式化的自动化，依赖语境判断的留给人审，互不越权**。
   - 第三方落地佐证：`style_policy.toml` + `lint_writing_style.py` 的策略配置文件＋脚本 linter 可移植架构（[llm-tips](https://github.com/wernerkasselman-au/llm-tips)）。
2. **诊断→改写→汇报三段式输出契约**（de-ai-flavor）：体检报告里强制包含「哪里本来就写得好」——防止改写误伤亮点。这是多数 lint 工具缺失的一环。
3. **规则工程化**（novel-writer-cli）：编号约束体系（C23/C24）＋ cliché-lint 引擎＋ Narrative Health 指标；CS-A2 升级确立「零配额＋统计目标」——用统计指标替代禁词硬卡。
4. **写作前约束＋写完后清理双层**（oh-story-claudecode）：`anti-ai-writing.md` 注入写作约束，`story-deslop` 作为独立后置清理技能，两者规则不同职责不同；硬指纹（破折号等）直接机械过滤不等模型自觉。
5. **体裁感知 genre-aware**（Anbeeld/WRITING.md）：通用禁令之外按体裁定制正向风格；规则主文件与执行入口分离（WRITING.md + skills/writing/SKILL.md），保持可移植。
6. **必读链模式**（webnovel-handbook）：工作流文档明文要求 agent「必读 docs/core-writing/04-character-and-dialogue」——把规范文件路径强制注入 prompt，配合 06 号管去AI味、11 号管加人味的分档。
7. **审阅流水线独立阶段**（awesome-novel-skill）：reader 角色 10 维 60+ 细项深度评审，且必须对照章纲/设定/前文逐条取证，不凭感觉打分。
8. **采样层硬抑制**（antislop-sampler/auto-antislop/Sukino Banned Tokens）：从基线语料自动挖掘超频 n-gram，用 logit bias＋回溯重采样压制，效果优于提示内禁词——提示词管不到的地方在采样参数里管。

---

## 七、与灵砚现状对照与落地建议

| 社区做法 | 灵砚对应 | 差距/建议 |
|---------|---------|----------|
| 三层纪律（prompt/linter/judgment） | 三层防御：Prompt 约束 → deai_process + ai_metric → 17 维审计/Critic | ✅ 架构同构，已是社区公认最优形态 |
| evidence-based linter | skill_gate + ai_metric（11 项验证特征＋统计指标，零 LLM 成本） | ✅ 领先 |
| judgment checklist | Critic + Keepers 评审 | ⚠️ 可把评审输出收敛为逐项 checklist 格式，对照章纲/设定取证（awesome-novel-skill 模式） |
| 零配额＋统计目标（CS-A2） | ai_metric 统计指标方向一致 | ✅ 方向一致 |
| C23 内心活动最低密度 | 无（现有约束全是禁止/上限思维） | 🆕 在 DEFAULT_WRITER_CONSTRAINTS 加一条内心戏密度下限（M4） |
| C24 功能冗余/结构呼吸 | 部分（长短句交替已有，但整体偏"删"导向） | 🆕 明确"该啰嗦处允许啰嗦"的正向许可 |
| 三段式契约含「亮点保留」 | gate-check 报告只列违规 | 🆕 ai_metric/gate 报告增加「命中良好区」展示，防用户手改误伤人味特征 |
| 人定结构 AI 填空（M1/M7） | 大纲树＋章节大纲＋特别指示（末尾最高优先） | ✅ 机制已具备；可在生成页强调"细纲未确认不生成" |
| 采样层硬抑制 | writer/short_story frequency/presence penalty 0.5/0.5 | ✅ 已有；可参考 antislop-sampler 思路用 ai_metric 数据反哺惩罚词表 |
| 正向锚例 few-shot | 文风锚例（style anchor）＋技能 ❌/✅ 锚例＋few-shot 对比示例 | ✅ 已领先社区平均水平 |
| genre-aware 体裁覆写 | 短篇有体裁指导；长篇无类型覆写 | 🆕 长篇可按题材（都市/玄幻/悬疑）覆写部分规则权重 |
| 规则表随模型迭代维护 | deai_patterns 120+ 静态 | ⚠️ 建立季度复核机制：算子抽样检视 20 条命中实例再采信（lieflat 方法学礼物） |

### ⚠️ 冲突警示（照搬社区清单前必读）

1. **英文圈的"删设问"建议勿搬**：本项目 283 万字语料实测，人类正文设问是 AI 的 **17 倍**（R=0.05）——按流行建议删设问会更像 AI。
2. **句内排比人类更高频**（R=0.61）：gate 只查跨相邻句的同构，勿扩大到句内。
3. **短碎句导向已被针对**：朱雀 2026-03 升级专门识别短句 AI 模式——「优先短句」「碎片句」的老攻略方向反了，M5 电报体自查就是为此设的保险丝。
4. **流传硬配额降级为软指引**：见 §四-9 配额悖论。
5. **比喻简化规则是反向操作**：人类比喻密度是 AI 的 2.4 倍——任何"少用比喻"的建议都会帮倒忙（灵砚 Phase 0 已下线该规则，勿恢复）。

---

## 八、来源索引

### 中文社交平台 / 传媒
- [SMZDM·翻了20多篇"去AI味"高赞笔记](https://post.smzdm.com/p/a4qdpzzw/)（片段）｜[同站·老板开始用AI查周报里的AI味](https://post.smzdm.com/p/a6zwenq0/)｜[同站·越改越重](https://post.smzdm.com/p/a26zpo5q/)｜[同站·加噪自保](https://post.smzdm.com/p/aqr0vgrk/)
- [新浪·DeepSeek全套「去AI味」万能提示词整合](https://www.sina.cn/news/detail/5321037941833820.html)｜[新浪·别再用提示词去AI味了](https://www.sina.cn/news/detail/5266447188361356.html)
- [头条·去AI味秘籍（人定结构AI填空）](https://m.toutiao.com/w/1857472370196492/)｜[头条·全套洗AI痕迹指令](https://m.toutiao.com/article/7654070264153768448/)｜[头条·去味指令告别机器感](https://m.toutiao.com/article/7654152107360092699/)
- [知乎·AI写的小说太假三招](https://zhuanlan.zhihu.com/p/2033174636196787273)｜[知乎·humanizer-zh 五原则转述](https://zhuanlan.zhihu.com/p/2015723964958273629)
- [NGA·不是而是求解帖](https://ngabbs.com/read.php?tid=47191439)｜[LINUX DO·同主题帖](https://linux.do/t/topic/1996748/13)
- [xs91·对话白开水病因](https://www.xs91.com/archives/5404.html)｜[澎湃·伪人感](https://www.thepaper.cn/newsDetail_forward_30189980)
- 平台治理：[马良写作](https://maliangwriter.com/blog/fanqie-ai-crackdown-2026-guide/)、[界面新闻](https://www.jiemian.com/article/14971052.html)、[中国作家网](https://www.chinawriter.com.cn/n1/2025/0905/c404027-40557712.html)、[光明网·晋江公告](https://m.gmw.cn/2025-02/19/content_1303974281.htm)

### GitHub 开源项目
- 中文小说向：[miserylee/webnovel-handbook](https://github.com/miserylee/webnovel-handbook/blob/main/docs/core-writing/06-ai-writing-guidelines.md)（❓正文未获取）、[DankerMu/novel-writer-cli](https://github.com/DankerMu/novel-writer-cli/blob/main/docs/anti-ai-polish.md)（issue ✅）、[leenbj/novel-creator-skill](https://github.com/leenbj/novel-creator-skill/blob/main/references/humanizer-guide.md)（❓）、[sabialab/de-ai-flavor](https://github.com/sabialab/de-ai-flavor)（✅）、[limuxue0/awesome-novel-skill](https://github.com/limuxue0/awesome-novel-skill)（✅ 片段）、[duskpen/novel-craft](https://github.com/duskpen/novel-craft/blob/master/SKILL.md)（❓）
- Humanizer 向：[worldwonderer/oh-story-claudecode](https://github.com/worldwonderer/oh-story-claudecode/blob/main/skills/story-setup/references/agent-references/anti-ai-writing.md)（✅ 片段级）、[Anbeeld/WRITING.md](https://github.com/Anbeeld/WRITING.md)（✅）、[MikkoParkkola/anti-ai-tell](https://github.com/MikkoParkkola/anti-ai-tell)（✅）、[op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh)（⚠️ 转述）、[y10reo/stop-slop-zh](https://github.com/y10reo/stop-slop-zh) 与 [VincentOld/stop-slop-zh](https://github.com/VincentOld/stop-slop-zh)（✅）、[B1lli/remove-ai-flavor-writing-skill](https://github.com/B1lli/remove-ai-flavor-writing-skill)（❓）、[masterball-w/Master-humanizer-skill](https://github.com/masterball-w/Master-humanizer-skill)（❓）
- 采样层：[sam-paech/antislop-sampler](https://github.com/sam-paech/antislop-sampler)、[sam-paech/auto-antislop](https://github.com/sam-paech/auto-antislop)、[Sukino Banned Tokens.txt](https://huggingface.co/Sukino/SillyTavern-Settings-and-Presets/blob/main/Banned%20Tokens.txt)（✅）

### 英文社区
- [cybercorsairs·为什么禁词会失效](https://cybercorsairs.com/kill-your-ais-favorite-word-for-good/)｜[The Ad Pharm·anti-slop playbook](https://www.theadpharm.com/insights/claude-opus-anti-slop-playbook)｜[gerimileva·AI tells 清单](https://www.gerimileva.com/ai-writing-patterns-to-avoid-a-practical-list-of-ai-telltales/)｜[Wired·反AI文学圈少用破折号](https://www.wired.com/story/more-typos-fewer-em-dashes-writers-are-creating-an-anti-ai-literary-counterculture/)
- [lguz/humanize-writing-skill](https://github.com/lguz/humanize-writing-skill)｜[aaaronmiller/humanize-writing](https://github.com/aaaronmiller/humanize-writing)｜[haidrrrry/humanize-ai-writing](https://github.com/haidrrrry/humanize-ai-writing)｜[louisfb01 Anti_Slop_AI_Writing_Guide](https://raw.githubusercontent.com/louisfb01/ai-engineering-cheatsheets/main/Anti_Slop_AI_Writing_Guide.md)｜[jbaruch blog-writer ai-anti-patterns](https://tessl.io/registry/jbaruch/blog-writer/0.18.2/files/references/ai-anti-patterns.md)
- 否定指令反效果实证：[arXiv 2404.15154（粉红大象）](https://ar5iv.labs.arxiv.org/html/2404.15154)、[Semantic Gravity Wells](https://ar5iv.labs.arxiv.org/html/2601.08070)、[diglot·完整禁词表及其为何失败](https://diglot.ai/blog/chatgpt-words-to-avoid)

### 调研遗留缺口
以下文件的 ❌/✅ 对照示例与完整词表因沙箱网络限制未能提取原文，后续可在有外网的终端补抓（均为 raw URL，一次 curl 即可）：
`miserylee/webnovel-handbook 06-ai-writing-guidelines.md`、`DankerMu/novel-writer-cli docs/anti-ai-polish.md`、`leenbj/novel-creator-skill references/humanizer-guide.md`、`Anbeeld/WRITING.md WRITING.md 全文`、`Master-humanizer-skill SKILL.md`。
