# AI_NovelGenerator 源码审核吸收报告（2026-09-17）

> 审核形式：4 路专项 agent 并行深审（生成管线 / 提示词体系 / 检索与一致性 / LLM 适配与配置），每个结论均要求双边 file:line 证据。
> 被审：YILING0013/AI_NovelGenerator（9336 行 Python，customtkinter 桌面端，txt 文件即数据库 + Chroma 向量）。
> 基准：灵砚（Flask + SQLite/FTS5，数据库即状态）。
> 源码留档：`D:\Project\_vendor_reference\AI_NovelGenerator`（仓库外，不进 git）。

## 总判断

**两项目的根本分野**：ANG 是"文件即数据库"——全管线围绕 4 个 txt + Chroma 目录，被迫发明原子写/断点续传/100 章裁剪这些手工数据库功能；灵砚是"数据库即状态"，事务/版本表/FTS/hash 缓存齐备。**ANG 的价值不在架构，在零散的实战细节**；它的流程级"智能"（每章 3 次额外 LLM 调用做摘要/检索词/过滤）多为伪精确指令（LLM 无法自校准"相似度>40%"），照搬会使灵砚倒退。

灵砚设计纪律（吸收时必须保持）：**确定性的事用确定性代码做，LLM 只做生成/更新文本状态，不做判断百分比/打标签。**

## 已落地吸收（第一批，全部小改动 + 11 个回归测试）

| # | 吸收项 | 来源证据 | 落点 |
|---|---|---|---|
| 1 | **下一章方向注入写手**：本章结尾须给下一章留接口，不把戏写满 | ANG chapter.py:334-343 + prompt 渲染 :572-579 | context.py 查下一章大纲取 200 字要点 → writer_chain 透传 → writer.py「下一章方向」块 |
| 2 | **空产出视为可重试失败**：200+零输出（安全过滤/网关异常）此前记 ok=1/output=0，统计失真 | ANG common.py:67-77 invoke_with_cleaning | llm.py 流式 collected==0 / 同步 out 为空 → LLMError（加入瞬态标记重试） |
| 3 | **`<think>` 内联思维链剥离**：Ollama/llama.cpp 类网关把它内联在 content（reasoning_content 之外的第三条路） | ANG common.py:40-42 | llm.py 同步正则剥离 + 流式状态机 `_strip_think_stream`（处理标签跨片切断） |
| 4 | **custom base_url /v1 归一 + # 逃逸**：用户漏 /v1 吃 404 是高频坑 | ANG llm_adapters.py:15-32 check_base_url | llm.py get_llm（仅 custom 类型生效，预设厂商豁免） |
| 5 | **per-agent 超时**：长章生成顶 300s 上限、短任务不能快速失败——灵砚配置粒度最后一块短板 | ANG config.example.json:12 预设级 timeout | config_utils `timeout_{agent}` 键 → get_llm(request_timeout/default_request_timeout)，writer_chain 已接线 |
| 6 | **激动值曲线回注大纲生成**：excitement_history 此前只写不读（单向数据流）；ANG 蓝图层的"事前节奏规划"（每3-5章悬念单元/认知过山车）补上"事前规划+事后测量"闭环 | ANG prompt_definitions.py:267-309 蓝图 | context.get_excitement_recent() → outline_stream/chapter_runner → outline prompt「近章激动值曲线」块 |
| 7 | **悬念类型受控词表 + 认知过山车配方**进大纲 prompt | ANG prompt_definitions.py:276,280 | writer.py【本章定位】标注主悬念类型（信息差/道德困境/时间压力/身份谜团/危机迫近） |
| 8 | **场景节拍做语义检索 query**：节拍是"地点+人物+动作"实体密集短句，嵌入质量高于叙事性长文大纲（ANG 检索词生成思想的确定性版，零额外 LLM 调用） | ANG prompt_definitions.py:61-109 思想 | writer_chain 优先取【场景节拍】段，旧格式大纲回退全文 |
| 9 | **runner 落库 prompt_used**：审批页可查本章发模型的完整 prompt（透明度第一步；ANG 的"生成前可编辑 prompt"思想的低成本版） | ANG generation_handlers.py:183-280 | chapter_runner auto_save 传 prompt_used |

## 建议后续吸收（第二批候选，涉及产品决策）

| 项 | 内容 | 决策点 |
|---|---|---|
| 角色状态回写闭环 | 审批时用已提取的 character_changes（零额外提取成本，需一次 LLM 合并调用）更新 Character.status_json——灵砚唯一真实缺口：角色状态停留在拆书期静态规划，越写越陈旧 | 每章审批 +1 次 LLM 调用 |
| 章目批量导入 `/outline/import-text` | ANG chapter_directory_parser.py 的容错手法（树形字符剥离/括号解包/字段别名/永不返回 None）+ 灵砚自有中文数字章号正则，批量建大纲树节点 | 新端点形态 |
| 正向技法词库模块 L1_writer_scene_craft | 非对称对话长度（权力关系信号）/短句加速+比喻减速等场景级配方，~300 字进词库预算；需先与 anti_ai_taste 细节节制条款做兼容核对（剔除感官数量配额类） | 词库预算分配 |
| 角色状态宽覆盖 LLM 扫查 | ANG CONSISTENCY_PROMPT 的五要素清单当检查面——灵砚确定性核查缺"角色状态类矛盾"（已死之人又开口）一类 | 并入哪条评审链 |
| 建书引导文案 | 雪花核心种子公式（当[主角]遭遇[核心事件]，必须[行动]，否则[灾难]）作 author_intent 占位符；角色驱动力三角/弧线五段作表单引导 | 纯文案 |

## 明确摒弃（四路审核一致，含理由）

- **Chroma 向量库**：无 metadata（"按类型检索"是对关键词字符串的子串匹配假象）、k=2、维度不匹配静默返回空、SSL 关闭；灵砚 FTS5+EntityEmbedding 是互补分层，已有真向量检索
- **LLM 检索词生成 + 三级过滤 + 百分比应用规则**：每章 ≥2 次额外 LLM 调用；"重复率>40%必须重构"类指令 LLM 无法自校准，是给作者的虚假安全感；其确定性预处理层实测失效（章号提取正则从正文找"第N章"，而切块不含章节标记——chapter.py:181,202 两个实锤 bug）
- **enrich 短章全文重写扩写**：可能丢已生成内容+全量 token 成本；灵砚增量续写循环（断点+戏剧纪律）更优
- **11 厂商适配类群**：无流式/无计量/类重复；火山/硅基/Grok 适配器硬编码 system prompt 污染用户意图
- **字符串外键配置**（llm_configs 以名字为引用）：背上改名传播/legacy 迁移/normalize 三套补丁；灵砚代理键正确。若做"命名预设"层必须以 preset id 落库
- **工程反面教材**：异常吞没成风（过滤失败占位符"（内容过滤过程出错）"直接混入正文上下文）、7 处重复 logging.basicConfig、UI 层承担业务编排（825 行 handler + 占位符字符串 hack）、火忘线程无单飞锁、`ssl._create_unverified_context`、plot_arcs 全库无写入方的死功能

## 审核方法备注

- 每个 agent 只审一个切片，且必须"对照灵砚实际代码给裁决"，防止"看起来很美"的机制盲目引入
- 三段式数据流校验（路由参数→服务函数→数据来源）应成为固定动作：ANG 的 plot_arcs/novel_setting 参数齐备但 UI 硬编码传空（generation_handlers.py:442,453），灵砚自己也刚在 consistency_check 修过同款"参数存在但没接数据"问题
