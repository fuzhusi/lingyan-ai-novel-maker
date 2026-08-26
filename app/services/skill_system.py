"""Skill System — modular, pluggable writing techniques.

Inspired by InkOS's skill system and show-me-the-story's writing techniques.

Skills are reusable prompt fragments that can be:
- Built-in (chapter hooks, pacing, rhythm control)
- User-created (custom writing techniques)
- Applied per-chapter or globally

Each skill contains:
- Name and description
- A prompt fragment to inject into the writer system prompt
- Optional constraints (similar to writing constraints)
"""
import json
from flask import Blueprint, render_template, request, jsonify
from app.models import db, Setting

skill_bp = Blueprint("skills", __name__, url_prefix="/api")

# Built-in skills
# 结构说明：prompt 只放纯规则（行为空间约束），examples 放「❌ AI味 → ✅ 技巧写法」
# 中文锚例（解释收敛）。实证依据：规则+单个对照例的组合执行率远高于纯规则堆叠，
# 参见 agentpatterns《Example-Driven vs Rule-Driven Instructions》。
BUILTIN_SKILLS = {
    "chapter_hook": {
        "name": "章节钩子",
        "description": "在章节开头制造悬念，吸引读者继续阅读",
        "prompt": """章节开头技巧：
- 用悬念、动作场景或具体感官细节开场，不用天气/晨起等套话
- 开头第一段就出现与主线冲突相关的具体信息""",
        "examples": [
            ("阳光透过窗户洒进房间，他睁开眼，开始了新的一天。",
             "等他再睁眼，床头那杯水已经凉透——昨晚答应送他去机场的人，终究没来。"),
            ("今天注定是不同寻常的一天。",
             "他把信封里的钱数了三遍，还是四张。老周明明说好了五张。"),
        ],
        "constraints": "",
    },
    "pacing_control": {
        "name": "节奏控制",
        "description": "控制叙事节奏，张弛有度",
        "prompt": """节奏控制技巧：
- 高潮/冲突场景：短句为主，段落不超过三句
- 过渡段落：允许放长，可带环境描写
- 对话与动作交替，不连排超过五句对白
- 每千字至少一次快慢切换""",
        "examples": [
            ("两人展开了激烈的搏斗，场面十分惊险刺激，双方你来我往互不相让，打得难解难分。",
             "刀光一闪。他侧身，慢了半拍。肩头开了道口子。"),
            ("他们聊了很多最近发生的事情，气氛十分融洽，时间不知不觉就过去了。",
             "从孩子聊到房价，又绕回孩子。茶续了两壶，谁也没提那件事。"),
        ],
        "constraints": "",
    },
    "show_dont_tell": {
        "name": "展示而非讲述",
        "description": "用动作和细节代替直接描述",
        "prompt": """展示而非讲述技巧：
- 心理状态用可见的动作、物件与身体反应承载
- 判断标准：删掉情绪词之后，读者仍然能感觉到那种情绪""",
        "examples": [
            ("她非常伤心，眼泪止不住地流了下来。",
             "她把碗端起来，又放下。饭粒粘在筷子尖上，她半天没夹起来。"),
            ("他是个出了名的吝啬鬼，对金钱看得很重。",
             "会议室空调开到二十六度，他路过顺手关了，说怕大伙儿着凉。"),
        ],
        "constraints": "禁止使用'他很X'、'她很Y'等直接心理描述",
    },
    "dialogue_realism": {
        "name": "对话写实",
        "description": "让对话更自然、更像真人说话",
        "prompt": """对话写实技巧：
- 不用「X声道/X笑道/X怒道」类修饰语，用动作或留白代替
- 对白要有潜台词：表面说小事，底下压真话
- 不同人物有不同的说话习惯
- 连续纯对白不超过三句，中间垫动作或环境""",
        "examples": [
            ("\u201c你竟然敢骗我！\u201d她愤怒地质问道。",
             "\u201c你骗我。\u201d她把他递过来的伞推了回去。外面雨更大了。"),
            ("\u201c哼，咱们走着瞧。\u201d他冷冷地说。",
             "\u201c行。\u201d他蹲下去，捡起那份摔湿的合同，掸了掸土，\u201c我先走了。\u201d"),
        ],
        "constraints": "禁止使用'X声道'、'X笑道'、'X怒道'等对话修饰语",
    },
    "sensory_detail": {
        "name": "感官细节",
        "description": "加入具体的感官描写，增强画面感",
        "prompt": """感官细节技巧：
- 优先调用触觉、嗅觉、听觉等非视觉感官
- 声音要具体到发声物；气味要具体到来源
- 视觉避开阳光/月光类陈词""",
        "examples": [
            ("房间里弥漫着一股难闻的味道。",
             "推开门，隔夜的烟味泡着方便面的汤气一起涌了出来。"),
            ("深夜的街道格外安静。",
             "巷口只剩烧烤摊翻动铁签子的声音，一下，又一下。"),
        ],
        "constraints": "",
    },
    "foreshadow_weaving": {
        "name": "伏笔编织",
        "description": "自然地在文中埋设伏笔",
        "prompt": """伏笔编织技巧：
- 把伏笔藏进看似无关紧要的日常细节里
- 同一伏笔至少暗示三次再回收：不见→眼熟→恍然
- 禁止旁白式提醒（「他没有想到…」「这将改变一切」）""",
        "examples": [
            ("那把钥匙看起来很不寻常，他隐隐觉得它将来一定会派上用场。",
             "钥匙和两节废电池、一张过期彩票一起躺在抽屉的最里层。"),
            ("她没有意识到，自己的这个决定将会彻底改变她的一生。",
             "她在辞职申请上签了名，笔画比平时潦草。"),
        ],
        "constraints": "",
    },
    "emotion_layering": {
        "name": "情感层次",
        "description": "让人物情感更丰富、更有层次",
        "prompt": """情感层次技巧：
- 情感写成混合态，不写单一标签（愤怒里掺着一点别的）
- 用环境变化烘托；用矛盾动作展示内心拉扯
- 情绪不点破，交给动作收尾""",
        "examples": [
            ("他又气又恨，心里像打翻了五味瓶，久久不能平静。",
             "他笑着给父亲满上酒，瓶底磕在桌沿上，响得他自己都皱了下眉。"),
            ("离别的时候她难过极了，泪水在眼眶里打转。",
             "检票员催到第三遍，她还举着手机，屏幕上其实什么都没有。"),
        ],
        "constraints": "",
    },
    # --- 去 AI 味结构级技巧 ---
    "rhythm_breaking": {
        "name": "句式节奏打散",
        "description": "打破 AI 匀称的句式结构，制造自然的阅读节奏",
        "prompt": """句式节奏打散技巧：
- 长短句交替；偶尔用碎片句（「嗯。」「算了。」）
- 段落长短不均，不每段都四五行
- 段首别总以人名/「他她」开头
- 出现三连排比立即打散""",
        "examples": [
            ("有的山峰雄伟壮观，有的山峰秀丽多姿，还有的山峰云雾缭绕。",
             "山一座比一座高。最远那座，看不见顶。"),
            ("他缓缓地走在熟悉的街道上，思绪万千，往事一幕幕浮现在眼前。",
             "他走得很慢。这条街变样了。"),
        ],
        "constraints": "",
    },
    "sensory_concrete": {
        "name": "感官具象化",
        "description": "用具体的感官细节替代抽象描述，消除 AI 的空洞感",
        "prompt": """感官具象化技巧：
- 动词换形容词；实物换概念；身体反应换心理陈述
- 每个场景至少一个「无用」的具体细节（远处的狗叫、硌脚的石子）""",
        "examples": [
            ("他疲惫不堪地走在回家的路上。",
             "他拖着步子，鞋底蹭着地面。楼道的声控灯，坏了一盏。"),
            ("出租屋里一片狼藉，乱得不成样子。",
             "茶几上摊着三本没合上的书。烟灰缸满了，外卖盒摞着外卖盒。"),
        ],
        "constraints": "",
    },
    "imperfection": {
        "name": "留白与不完美",
        "description": "适当留白、跳跃、不解释，模仿真实写作的不完美",
        "prompt": """留白与不完美技巧：
- 不逐事解释因果；不做段末总结
- 结尾禁止升华（人生道理/哲学感悟/「他终于明白」）
- 思路可以急转弯；该省略的就省略
- 情感不说透，用一个具体动作停住""",
        "examples": [
            ("这一刻，他终于读懂了父亲沉默背后的良苦用心，眼眶不禁湿润了。",
             "他把那条烟放回柜子最上层。柜门没关严，留了一道缝。"),
            ("她伤心欲绝，感觉整个世界都塌了下来，但她知道，生活还要继续。",
             "第二天她照常去上班。中午一个人吃了两碗面。"),
        ],
        "constraints": "",
    },
    "dialogue_humanize": {
        "name": "对话人味化",
        "description": "让对话更像真人说话，去除 AI 的书面腔",
        "prompt": """对话人味化技巧：
- 偶尔加语气词与口头禅（不是每句都加）
- 允许说不完整句、打断重叠、答非所问
- 夹一两句不推动剧情的废话寒暄
- 别每句对白都挂动作描写""",
        "examples": [
            ("\u201c您好，请问有什么可以帮到您的吗？\u201d店员微笑着询问道。",
             "\u201c要点啥？刚出炉的。\u201d"),
            ("\u201c我个人认为，你的这个方案还存在一些问题。\u201d经理表情严肃地说。",
             "\u201c这方案嘛……\u201d经理把笔帽按上，又拔开，\u201c你再拿回去琢磨琢磨？\u201d"),
        ],
        "constraints": "",
    },
    "deai_structure": {
        "name": "结构去模板化",
        "description": "打破 AI 的总分总/三段式/逐条罗列结构",
        "prompt": """结构去模板化技巧：
- 禁「首先/其次/再次/最后」式推进与总分总收束
- 加闲笔（路边的猫、收音机里的歌）；时间线偶尔跳出线性
- 场景直接切，不用过渡句；信息密度刻意不均""",
        "examples": [
            ("与此同时，在城市另一端的豪华别墅里，神秘人也在紧锣密鼓地策划着下一个阴谋。",
             "三天后他才听说，那天夜里老宅进了人。"),
            ("首先，他需要找到一份工作；其次，租一间房子；最后，重新开始自己的生活。",
             "工作的事他没跟任何人提。房子倒是先看好了，就在菜市场楼上。"),
        ],
        "constraints": "",
    },
}


# ---------------------------------------------------------------------------
# 作者技法协议（Author Protocol Skills）
# 由公开写作技法协议提炼的"作者文风"类技巧，江南为首个实例。
# 默认不激活，用户按需开启；激活后通过 build_skill_prompt() 注入 Writer。
# 未来可扩展：新增古龙 / 金庸 / 刘慈欣等条目即可，UI 自动按 author 分组。
#
# 当前江南三技巧提炼自 JiangNan-feeling-writing v1.1.1（MIT，quote-free 通用原创协议）：
#   https://github.com/zhichenghe34-design/JiangNan-feeling-writing
# 该协议明确禁止使用源作品专名/桥段/原文，适用所有原创题材，无同人专属包袱。
# ---------------------------------------------------------------------------
AUTHOR_PROTOCOL_SKILLS = {
    "jiangnan_fingerprint": {
        "name": "江南感·笔法指纹",
        "description": "页面级笔法：物/动作替代心理、对话潜台词、大题小作、段尾回疼、遮蔽梯、比喻升维",
        "prompt": """江南感笔法指纹 — 页面级写法（提炼自 JiangNan-feeling-writing v1.1.1，quote-free 通用原创协议）

目标是在原创文本里调出江南式笔法运动，不是仿壳，不是同人，不使用任何源作品专名/桥段/原文。

【四个天生指纹（优先挂，稳定承重）】
1 物/动作替代心理：少写"他很难过"，写他对物、空间、身体、日常动作做了什么。
   可用承重物：一行字、一张表、一把钥匙、一个坏掉的按钮、一截线头、一只没拨出的手机。
   物必须改变动作，不是摆设。判断：删掉心理词后，读者还能不能知道他疼。
2 对话潜台词：表面说小事，底下压真正的话。字面层（借书/还水/问路/确认名单/修机器）
   潜台词层（你有没有忘/你还在不在/你是不是还相信）。不让角色直接解释自己为什么疼。
3 大题小作/小题大作：大命运落在小动作上，小物件承担大情绪。
   大题小作：战争/毕业/拆迁/死亡，只落到"他把纸按平"。
   小题大作：一行铅笔字/一条短信/一张值日表，承载十年或一生。小物必须改变人物动作。
4 段尾回疼：段尾用低、静、具体的事实或动作收住，让疼慢半拍到。
   好结尾不总结主题，留下一个小动作/小事实/小空白（动作停住/物还在/名字没被叫出/
   光线落在不该还在的东西上/人没做那个原本应做的动作）。

【两个后期系统化工具（按需，必须回到人的代价）】
- 比喻升维：小物→大尺度(天空/机器/历史/神话/文明)→回到人的代价。
  结构：铅笔印先是灰，后是十年，最后落回指腹上的木刺。不回到人的代价就不要升维。
- 双读/双编码：一句话/一个物件/一个承诺有表层意义和迟到的第二层意义。
  例：当年一句随口提醒，十年后变成未完成的召唤。

【遮蔽梯（从浅到深，至少走到第3层，强江南感走到4-6层）】
1 直接说情绪 → 2 委婉形容情绪 → 3 换成物 → 4 换成动作 → 5 换成对话潜台词 → 6 换成段尾空白

【句子运动】短句：冲击/决定/段尾/冷收。中句：行动/对话/移动。长句：回望/环境压迫/比喻升维。
不要全短（故作深沉），也不要全长（散）。

【空白与沉默】沉默不是留白符号，是行动失败：电话没拨出/字没擦掉/门没打开/名字没念完。空白要有物证支撑。

【结尾】落地+开口：有一个具体动作或物（落地）；命运没完全关上，读者还会在后面想（开口）。
不要大团圆，不要强行虐，不要解释主题。

【禁忌】不摘录受版权原文；不用源作品人物/组织/设定/专名/桥段/源近句式；不写成官方续作口吻。""",
        "constraints": "禁止直接说情绪（走遮蔽梯≥3层）；禁止结尾总结主题/大团圆；禁止使用任何源作品专名/桥段/原文",
        "category": "作者文风协议",
        "author": "江南",
        "source": "JiangNan-feeling-writing v1.1.1 (MIT)",
        "protocol_pack": "jiangnan",
    },
    "jiangnan_preset": {
        "name": "江南感·阶段与声线",
        "description": "10个preset定声线+四维定调+非融合规则：校园/武侠/史诗/都市热冷/少年卷入/情感最大化/冷寂/商业奇幻/根系",
        "prompt": """江南感阶段与声线 — 先选preset再动笔（提炼自 JiangNan-feeling-writing v1.1.1）

江南感不是一种固定声线。稳定的是底层指纹，不稳定的是叙述声音/糖衣密度/历史距离/冷寂程度/设定压力。
写前必须先选一个主preset，不要把多个时期的声线平均混合。

【四维定调（写前必填，内部卡不完整暴露给读者）】
1 阶段轴：P1校园/P1-P2武侠/P2史诗/P3都市过渡/P4少年被卷入/P5情感最大化/P6冷寂或商业奇幻/根系神话
2 题材语域轴：校园、武侠、史诗、都市热、都市冷线、根系神话、商业奇幻
3 配置轴：温暖微苦、史诗距离、都市热线、都市冷线、情感最大化、冷寂不在、商业奇幻等
4 指纹深度轴：四个天生指纹优先；两个后期工具按需；阶段专属工具不能乱用

【10个preset（只选一个主preset）】
- P1 校园/温暖微苦：青春回望/同学/普通人错过。第三人称温和俯瞰(像十年后回头看)。
  温和群像幽默不冷嘲。签名杠杆：双层少年视角/段尾回疼/物动作。失败：写成普通怀旧散文或滑成冷寂。
- P1-P2 武侠：江湖/个体英雄/早期悲剧。说书人，少量装饰性文白。近零糖。
  签名：仪式化死亡/古歌名号命运。失败：堆伪古风。
- P2 史诗：文明/战争/家族/历史距离。全知史官，半文白结构。近零糖。
  签名：物仪式化/格言式重收/单层史诗情绪。失败：用史官腔写现代校园。
- P3 都市热线：都市/暗恋/末日边缘/第一人称。自嘲吐槽有温度。中高糖。
  签名：延后告白/文本物作为载体。失败：直接告白或滑成召唤。
- P3 都市冷线：政治/谍战/军事/系统压力。第三人称多POV冷叙事。近零糖。
  签名：棋盘式对话/临床哥特/档案细节。失败：写成无情无味。
- P4 少年被卷入：普通少年被迫进入大世界。第一人称低语言防御。高糖。
  签名：反高潮被选中/烂话到静默。失败：直接变龙族开场。
- P5 情感最大化：长日常后的丧失/多人关系。多声部复调。最高糖。
  签名：长糖衣/受限表达/延后抒情。失败：只有甜没有苦药。
- P6 冷寂/不在：记忆磨损/缺席/物证/重建失败。冷化，少解释少烂话。低糖。
  签名：空白即存在/物证替代/减法。失败：把它当所有P6通用。
- P6 商业奇幻：架空/机械/权力/兄弟/系列化。第三人称有限多POV。中糖。
  签名：机械物人格化/悬念收束/盟约。失败：堆设定不让人承担。
- 根系/神话支线：远古/起源/侧传/根系记忆。双时间层，口语框架加正式历史层。历史层近零糖。
  签名：语域切换/物仪式化/临床哥特。失败：把历史腔当普通都市声。

【非融合规则】主preset只能一个，其它元素降级为局部工具/背景噪声或删除。
- 不要把烂话当通用江南感。
- 不要把冷寂当全部后期江南。
- 不要把史官声用于现代校园。
- 不要把前传历史腔当普通都市声线。
- 不要把商业奇幻的设定推进当成青春回望。
- 不要平均混合多个阶段。

【糖衣/苦药】不是所有preset都需要强糖苦：P4-P5龙族式完整双层最强；P6冷寂糖减少靠缺席物证；
九州史诗多为单层史诗情绪；天之炽偏商业热多线推进。""",
        "constraints": "主preset只能一个，禁止平均混合多阶段声线；阶段专属工具不能当通用风格",
        "category": "作者文风协议",
        "author": "江南",
        "source": "JiangNan-feeling-writing v1.1.1 (MIT)",
        "protocol_pack": "jiangnan",
    },
    "jiangnan_cost": {
        "name": "江南感·选择与代价",
        "description": "让人物选择有现实成本：缺口/门外/信念付费/现实成本/小物/远灯/开口结尾（11张协议卡）",
        "prompt": """江南感选择与代价 — 让物把人物推到有成本的位置（提炼自 JiangNan-feeling-writing v1.1.1）

江南感不能只靠"物件触动人物"。物件要把人物推到一个有成本的位置。
合格选择至少回答两问：①不选会失去什么(人/机会/尊严/旧承诺/离开机会/被承认可能)
②选择会付出什么(钱/时间/身体/名誉/关系/工作风险/阵营身份/生存压力)。
如果人物只是看见旧物/沉默/转身但没有任何现实代价，文本有感觉但不够硬。
成本不必写大，可以很小：回复短信留审计记录/按确认改家庭安排/交齿轮被群体视为背叛/回旧教室错过重要现实安排。
成本通过动作/物/对话/制度细节露出来，不用议论文解释。

【11张协议卡（写前内部填写，不完整暴露给读者）】
卡0 阶段与配置：题材语域/preset/配置/四个天生指纹重点/允许后期工具/阶段专属工具/必须避免误用
卡1 缺口：他缺什么/缺口何时开始/用什么假装不缺/拒绝哪种安全但窒息的人生。缺口必须影响后面选择。
卡2 门外：定义那扇门——一个可能承认他的人/可能接纳他的集体/可能选择他的任务/他以为自己永远进不去的地方。
   江南式人物常不是站在门里，而是站在门外看灯。
卡3 叙述距离：回望(已知青春会失去)/当下(还不知代价)/反怀旧(拒绝美化过去)。
   P1校园常用回望，都市冷线常用克制当下，不要混乱。
卡4 遮蔽梯：直接说情绪→委婉形容→物→动作→对话潜台词→段尾空白。至少走到第3层。
卡5 糖衣/苦药：糖=日常/幽默/群像/轻微愿望/可读具体目标；苦=糖后来被反向照亮/轻松小事变迟到的疼/选择留下成本。
   不是所有preset都需要强糖苦。
卡6 信念成本：他相信什么/这个相信为什么不划算/他为此失去什么/不付费信念就不成立。
卡7 现实成本：钱/时间/身体/机会/名誉/社群关系/生存风险。不让理想悬空。
卡8 小物：必须能改变动作(一行字/一张表/一把钥匙/坏掉的按钮/线头/没拨出的手机)。小物是情绪承重梁不是摆设。
卡9 远灯：温暖不要太近(很久前递过来的水/没拨出的电话/还没碎的纸/远处亮着但进不去的窗)。温暖越近越容易变甜腻。
卡10 开口结尾：留一个小开口——人走了但东西还在/电话没打但名字亮过/门关上了但灰被抹平/车来了但他没回头。不总结主题。

【硬性失败（出现必须重写）】
- 只有雨/天台/青春/孤独/短句，没有人物缺口（表面悲伤）
- 把多阶段声线揉成平均声线（平均龙族声）
- 把阶段专属工具当通用江南感（错误泛化）
- 纯苦(沉重哲学难进入)或纯糖(顺滑但没有迟到的疼)
- 人物直接解释自己为什么难过（情绪说穿）
- 人物说相信但什么都没失去（信念不付费）
- 人物做了关键动作但没有可见现实成本或选择理由（选择不付费）
- 靠源作品人物/组织/设定/关系才成立（源作品依赖）

【原创安全】不摘录受版权原文；不用源作品人物/组织/设定/专名/桥段；不写官方续作口吻；不生成源近句式。
看到"像某某角色/沿用某某设定/接着某本书写/复刻某段名场面"要停。""",
        "constraints": "人物选择必须有可见现实成本（钱/时间/身体/名誉/关系/阵营等）；信念必须付费；禁止源作品依赖；禁止情绪说穿",
        "category": "作者文风协议",
        "author": "江南",
        "source": "JiangNan-feeling-writing v1.1.1 (MIT)",
        "protocol_pack": "jiangnan",
    },
}


def get_active_skills():
    """Get list of active skill names."""
    setting = Setting.query.get("active_skills")
    if setting and setting.value:
        try:
            return json.loads(setting.value)
        except json.JSONDecodeError:
            pass
    # 默认激活核心去AI化技能
    return ["rhythm_breaking", "sensory_concrete", "imperfection", "dialogue_humanize", "deai_structure"]


def set_active_skills(skill_names):
    """Set active skills."""
    setting = Setting.query.get("active_skills")
    if setting:
        setting.value = json.dumps(skill_names, ensure_ascii=False)
    else:
        setting = Setting(key="active_skills", value=json.dumps(skill_names, ensure_ascii=False))
        db.session.add(setting)
    db.session.commit()


def get_custom_skills():
    """Get user-created custom skills."""
    setting = Setting.query.get("custom_skills")
    if setting and setting.value:
        try:
            return json.loads(setting.value)
        except json.JSONDecodeError:
            pass
    return {}


def save_custom_skill(name, skill_data):
    """Save a custom skill."""
    skills = get_custom_skills()
    skills[name] = skill_data
    setting = Setting.query.get("custom_skills")
    if setting:
        setting.value = json.dumps(skills, ensure_ascii=False)
    else:
        setting = Setting(key="custom_skills", value=json.dumps(skills, ensure_ascii=False))
        db.session.add(setting)
    db.session.commit()


def delete_custom_skill(name):
    """Delete a custom skill."""
    skills = get_custom_skills()
    if name in skills:
        del skills[name]
        setting = Setting.query.get("custom_skills")
        if setting:
            setting.value = json.dumps(skills, ensure_ascii=False)
            db.session.commit()


def get_all_skills():
    """Get all available skills (built-in + author-protocol + custom)."""
    all_skills = {}
    for key, skill in BUILTIN_SKILLS.items():
        all_skills[key] = {**skill, "builtin": True,
                           "category": skill.get("category", "通用技法")}
    for key, skill in AUTHOR_PROTOCOL_SKILLS.items():
        all_skills[key] = {**skill, "builtin": True, "category": "作者文风协议"}
    for key, skill in get_custom_skills().items():
        all_skills[key] = {**skill, "builtin": False, "category": "自定义"}
    return all_skills


# ---------------------------------------------------------------------------
# 文件型协议加载器（File-based Protocol Loader）
# 当技巧带 protocol_pack 字段时，build_skill_prompt 优先从 app/skills/<pack>/ 读取
# 完整 core markdown 注入，而非静态浓缩 prompt。这更接近"调用原 skill"——
# 保留协议全貌与模块化设计，而非浓缩版。
# 任务类型 task_type 决定注入哪些模块：
#   write   → protocol + presets + fingerprints（写作必需的三模块）
#   diagnose→ evaluation（24分评分门 + 失败模式诊断）
#   polish  → fingerprints + evaluation（润色走笔法指纹 + 质检）
#   默认    → protocol + presets + fingerprints + evaluation（完整最小调用包）
# 文件缺失时回退到静态 prompt 字段（浓缩版），保证不中断。
# ---------------------------------------------------------------------------
import os as _os

_SKILLS_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "skills")

# 协议包 → 各任务类型对应的 core 文件清单
_PROTOCOL_PACK_FILES = {
    "jiangnan": {
        "write":    ["core_protocol.md", "core_presets.md", "core_fingerprints.md"],
        "diagnose": ["core_evaluation.md"],
        "polish":   ["core_fingerprints.md", "core_evaluation.md"],
        "full":     ["core_protocol.md", "core_presets.md", "core_fingerprints.md", "core_evaluation.md"],
    },
}


def _load_protocol_pack(pack_name, task_type="write"):
    """从 app/skills/<pack_name>/ 读取对应任务类型的 core markdown，拼接返回。
    文件缺失或为空时返回 None（调用方回退到静态 prompt）。"""
    files = _PROTOCOL_PACK_FILES.get(pack_name, {}).get(task_type)
    if not files:
        return None
    pack_dir = _os.path.join(_SKILLS_DIR, pack_name)
    if not _os.path.isdir(pack_dir):
        return None
    parts = []
    for fname in files:
        fpath = _os.path.join(pack_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                parts.append(content)
        except (OSError, IOError):
            continue
    return "\n\n---\n\n".join(parts) if parts else None


def _render_static_skill(skill):
    """静态技巧 → 「规则 + ❌/✅ 对照锚例」文本块。

    实证依据（agentpatterns《Example-Driven vs Rule-Driven Instructions》）：
    规则限定行为空间，示例锚定解释；规则+对照例的组合执行率远高于纯规则。
    """
    if not skill.get("prompt"):
        return ""
    block = f"【{skill['name']}技巧】\n{skill['prompt']}"
    examples = skill.get("examples") or []
    if examples:
        ex_lines = ["对照示例（❌ 为要避开的写法，✅ 为目标写法）："]
        for bad, good in examples:
            ex_lines.append(f"❌ {bad}\n✅ {good}")
        block += "\n" + "\n".join(ex_lines)
    if skill.get("constraints"):
        block += f"\n约束：{skill['constraints']}"
    return block


def build_skill_prompt(task_type="write"):
    """Build the combined skill prompt from active skills.

    task_type: write / diagnose / polish / outline
      - write    → 协议包加载 protocol + presets + fingerprints（写作三模块）
      - diagnose → 协议包仅 evaluation（24分评分门 + 失败模式诊断）
      - polish   → 协议包 fingerprints + evaluation（润色走笔法指纹 + 质检）
      - outline  → 跳过协议包（页面级笔法对大纲是噪音），只注入静态技法
    普通章节生成用 write；按评审改写用 write；Editor 润色用 polish；
    大纲生成用 outline。
    带协议包字段的技巧优先加载完整文件协议，回退到静态浓缩 prompt。

    同一协议包（如三个江南技巧都指向 jiangnan）只整包加载一次，避免重复注入
    浪费 token。约束来自该包下所有激活技巧的 constraints（去重合并）。
    """
    active = get_active_skills()
    all_skills = get_all_skills()
    skip_packs = (task_type == "outline")

    parts = []
    # 先处理文件型协议包：同包只加载一次
    loaded_packs = {}  # pack_name -> constraints 去重列表
    pack_skills_order = {}  # pack_name -> [skill, ...] 保留顺序用于命名
    static_skills = []
    for skill_name in active:
        skill = all_skills.get(skill_name)
        if not skill:
            continue
        pack = skill.get("protocol_pack")
        if pack:
            if skip_packs:
                continue
            loaded_packs.setdefault(pack, [])
            pack_skills_order.setdefault(pack, [])
            pack_skills_order[pack].append(skill)
            cs = skill.get("constraints")
            if cs and cs not in loaded_packs[pack]:
                loaded_packs[pack].append(cs)
        else:
            static_skills.append(skill)

    # 加载每个协议包一次
    for pack_name, constraints_list in loaded_packs.items():
        full = _load_protocol_pack(pack_name, task_type=task_type)
        if full:
            # 用该包下第一个技巧的名字做标题（或包名）
            first_name = pack_skills_order[pack_name][0]["name"]
            author = pack_skills_order[pack_name][0].get("author", "")
            label = f"{first_name}（{author}完整协议）" if author else f"{first_name}完整协议"
            parts.append(f"【{label}】\n{full}")
            if constraints_list:
                parts.append(f"约束：{'；'.join(constraints_list)}")
        else:
            # 文件缺失：该包下所有技巧回退静态浓缩 prompt
            for skill in pack_skills_order[pack_name]:
                if skill.get("prompt"):
                    parts.append(f"【{skill['name']}技巧】\n{skill['prompt']}")
                    if skill.get("constraints"):
                        parts.append(f"约束：{skill['constraints']}")

    # 再处理静态技巧（无 protocol_pack）
    for skill in static_skills:
        block = _render_static_skill(skill)
        if block:
            parts.append(block)

    if not parts:
        return ""

    return "【写作技巧 — 请在写作中运用以下技巧】\n\n" + "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@skill_bp.route("/skills/page")
def skills_page():
    """技能管理页面。"""
    all_skills = get_all_skills()
    active = get_active_skills()
    builtin_skills = []
    author_protocol_skills = []
    custom_skills = []
    for key, skill in all_skills.items():
        item = {
            "key": key,
            "name": skill.get("name", key),
            "description": skill.get("description", ""),
            "prompt": skill.get("prompt", ""),
            "constraints": skill.get("constraints", ""),
            "builtin": skill.get("builtin", True),
            "active": key in active,
            "category": skill.get("category", "通用技法"),
            "author": skill.get("author"),
            "source": skill.get("source"),
            "tag": skill.get("tag"),
            "protocol_pack": skill.get("protocol_pack"),
        }
        if skill.get("category") == "作者文风协议":
            author_protocol_skills.append(item)
        elif skill.get("builtin", True):
            builtin_skills.append(item)
        else:
            custom_skills.append(item)
    return render_template("skills.html",
                           builtin_skills=builtin_skills,
                           author_protocol_skills=author_protocol_skills,
                           custom_skills=custom_skills,
                           active_count=len(active))


@skill_bp.route("/skills")
def list_skills():
    """List all available skills."""
    all_skills = get_all_skills()
    active = get_active_skills()
    result = []
    for key, skill in all_skills.items():
        result.append({
            "key": key,
            "name": skill.get("name", key),
            "description": skill.get("description", ""),
            "builtin": skill.get("builtin", True),
            "active": key in active,
            "category": skill.get("category", "通用技法"),
            "author": skill.get("author"),
            "source": skill.get("source"),
            "tag": skill.get("tag"),
            "protocol_pack": skill.get("protocol_pack"),
        })
    return jsonify(result)


@skill_bp.route("/skills/active", methods=["POST"])
def update_active():
    """Update active skills."""
    data = request.get_json(silent=True) or {}
    skill_names = data.get("skills", [])
    set_active_skills(skill_names)
    return jsonify({"ok": True, "active": skill_names})


@skill_bp.route("/skills/gate-check", methods=["POST"])
def gate_check():
    """技能质量门禁：对文本做确定性校验，报告活跃技巧的违规情况。

    Body: JSON {"text": "..."} 或表单 text 字段。
    Returns: {"passed": bool, "checks": [{skill, name, passed, violations[]}],
              "ai_tone": {passed, human_score, checks[], stats{}},   # 篇章层 AI 痕迹
              "constraint_assembly": {agent_type: 最近一次词库装配快照}}  # 可观测性回显
    """
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or request.form.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400
    from app.services.skill_gate import run_gate
    from app.services.ai_metric import analyze_ai_tone
    rep = run_gate(text)
    try:
        rep["ai_tone"] = analyze_ai_tone(text)
    except Exception:
        pass
    # 约束装配回显：展示最近一次生成实际注入的词库模块（可观测性闭环）
    try:
        from app.services.constraint_bank import get_last_assembly
        asm = get_last_assembly()
        if asm:
            rep["constraint_assembly"] = asm
    except Exception:
        pass
    return jsonify(rep)


@skill_bp.route("/skills/custom", methods=["POST"])
def create_custom():
    """Create a custom skill."""
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400

    skill_data = {
        "name": name,
        "description": data.get("description", ""),
        "prompt": data.get("prompt", ""),
        "constraints": data.get("constraints", ""),
    }
    save_custom_skill(name, skill_data)
    return jsonify({"ok": True})


@skill_bp.route("/skills/custom/<name>", methods=["DELETE"])
def delete_custom(name):
    """Delete a custom skill."""
    delete_custom_skill(name)
    return jsonify({"ok": True})
