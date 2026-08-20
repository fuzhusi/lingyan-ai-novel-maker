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
BUILTIN_SKILLS = {
    "chapter_hook": {
        "name": "章节钩子",
        "description": "在章节开头制造悬念，吸引读者继续阅读",
        "prompt": """章节开头技巧：
- 以一个悬念问题开头（"他没想到，这竟然是最后一次见面"）
- 以一个动作场景开头（直接进入冲突）
- 以一个感官细节开头（"空气中弥漫着焦糊的味道"）
- 避免以"阳光透过窗户"等陈词滥调开头""",
        "constraints": "",
    },
    "pacing_control": {
        "name": "节奏控制",
        "description": "控制叙事节奏，张弛有度",
        "prompt": """节奏控制技巧：
- 高潮场景：短句为主，每句不超过15字，段落不超过3句
- 过渡场景：可以适当放长，加入环境描写
- 对话场景：对话和动作交替，不要连续超过5句对话
- 每1000字至少有一次节奏变化（快→慢 或 慢→快）""",
        "constraints": "",
    },
    "show_dont_tell": {
        "name": "展示而非讲述",
        "description": "用动作和细节代替直接描述",
        "prompt": """展示而非讲述技巧：
- 不要写"他很紧张"，写"他的手指在桌面上敲了三下"
- 不要写"她很伤心"，写"她把杯子放下时，水洒了一桌"
- 不要写"气氛很尴尬"，写"谁也没说话，只有钟在滴答响"
- 不要写"他很厉害"，写具体的行为让读者自己判断""",
        "constraints": "禁止使用'他很X'、'她很Y'等直接心理描述",
    },
    "dialogue_realism": {
        "name": "对话写实",
        "description": "让对话更自然、更像真人说话",
        "prompt": """对话写实技巧：
- 对话不要加"他沉声道""她轻笑道"等修饰语
- 用动作代替修饰语（"他放下杯子"比"他沉声道"更好）
- 对话要有潜台词，不要让人物直接说出自己的感受
- 每个人物的说话方式应该不同（参考角色设定中的说话风格）
- 避免连续超过3句纯对话，中间插入动作或环境""",
        "constraints": "禁止使用'X声道'、'X笑道'、'X怒道'等对话修饰语",
    },
    "sensory_detail": {
        "name": "感官细节",
        "description": "加入具体的感官描写，增强画面感",
        "prompt": """感官细节技巧：
- 每500字至少一个具体的感官细节
- 优先使用不常见的感官（触觉、嗅觉、味觉）而不是视觉
- 视觉：避免"阳光""月光"等陈词滥调
- 听觉：具体的声音（"远处传来狗叫"而非"听到声音"）
- 触觉：温度、质感（"指尖碰到冰凉的铁栏杆"）
- 嗅觉：具体的气味（"空气里有股炸葱花的味道"而非"闻到香味"）""",
        "constraints": "",
    },
    "foreshadow_weaving": {
        "name": "伏笔编织",
        "description": "自然地在文中埋设伏笔",
        "prompt": """伏笔编织技巧：
- 伏笔要埋在看似无关紧要的细节中
- 用"三次暗示"法则：同一个伏笔至少暗示3次才回收
- 第一次：读者不会注意
- 第二次：读者会觉得"好像在哪里见过"
- 第三次：回收，读者恍然大悟
- 伏笔不要埋得太明显（"他总觉得那把钥匙不一般"太直白）""",
        "constraints": "",
    },
    "emotion_layering": {
        "name": "情感层次",
        "description": "让人物情感更丰富、更有层次",
        "prompt": """情感层次技巧：
- 人物的情感应该是混合的，不是单一的（"愤怒中带着一丝恐惧"）
- 用环境烘托情感（"雨下得更大了"暗示悲伤）
- 用矛盾行为展示内心冲突（"他笑着说，但手在发抖"）
- 避免情感的直接表达（"他很伤心"→"他把烟掐灭，又点了一根"）""",
        "constraints": "",
    },
    # --- 去 AI 味结构级技巧 ---
    "rhythm_breaking": {
        "name": "句式节奏打散",
        "description": "打破 AI 匀称的句式结构，制造自然的阅读节奏",
        "prompt": """句式节奏打散技巧（去AI味核心）：
- 长短句交替：连续2-3个短句后接一个长句，或反过来，不要每句都差不多长
- 碎片句：偶尔用不完整的句子（"嗯。""算了。""不对。"）打破工整感
- 避免三连排比：AI 最爱写"有的…有的…有的…"，如果写了排比，打散它
- 段落长度不均：有的段落2行，有的段落8行，不要每段都4-5行
- 避免每段开头都是"他/她"或人名，偶尔用代词、用动作、用对话开头
- 对话和叙述的比例不固定：有的地方连续对话，有的地方大段叙述""",
        "constraints": "",
    },
    "sensory_concrete": {
        "name": "感官具象化",
        "description": "用具体的感官细节替代抽象描述，消除 AI 的空洞感",
        "prompt": """感官具象化技巧（去AI味核心）：
- 用动词替代形容词："他疲惫地走着"→"他拖着步子，鞋底蹭着地面"
- 用具体替代抽象："周围很安静"→"能听见墙上时钟的秒针在走"
- 用实物替代概念："桌上很乱"→"桌上摊着三本没合上的书，烟灰缸满了"
- 用身体反应替代心理描写："他很紧张"→"他攥着手机，指节发白"
- 用环境细节替代情感标签："她很难过"→"她盯着碗里的饭，筷子戳了半天没夹起来"
- 一个场景至少有一个"无用"的感官细节（远处的狗叫、空气里的油烟味、脚底硌到的石子）""",
        "constraints": "",
    },
    "imperfection": {
        "name": "留白与不完美",
        "description": "适当留白、跳跃、不解释，模仿真实写作的不完美",
        "prompt": """留白与不完美技巧（去AI味核心）：
- 不必每件事都解释因果：有时候事情就是发生了，不需要"因为…所以…"
- 不必每段都有总结句：AI 爱在段末加一句总结/升华，删掉它
- 避免结尾升华：不要在章节结尾写人生道理、哲学感悟、"他终于明白了…"
- 思维跳跃：人物的思路可以突然拐弯（"他想起来了——不对，现在不是想这个的时候"）
- 省略：有时候"他没说话"比"他沉默了一会儿，然后缓缓开口"更好
- 留白：不把所有情感都说透，让读者自己感受（"她转过身走了。"不加任何修饰）""",
        "constraints": "",
    },
    "dialogue_humanize": {
        "name": "对话人味化",
        "description": "让对话更像真人说话，去除 AI 的书面腔",
        "prompt": """对话人味化技巧（去AI味核心）：
- 加入语气词："嗯""啊""哦""呃""那个…"（不是每句都加，偶尔用）
- 不完整句："算了不——""你别说，还真——"真人说话经常说一半
- 打断和重叠："不是，你听我说——""我听你说了，但——"
- 口癖：给人物设定1-2个口头禅（"说真的""反正""你知道吗"）
- 答非所问：真人对话经常不直接回答问题（"你去不去？""外面下雨了吗？"）
- 废话和寒暄：不要每句对话都推动剧情，偶尔加点"今天真热""吃了吗"
- 避免每句对话都带动作描写：有时直接写对话，不需要每句都加「他说」「她叹了口气说」""",
        "constraints": "",
    },
    "deai_structure": {
        "name": "结构去模板化",
        "description": "打破 AI 的总分总/三段式/逐条罗列结构",
        "prompt": """结构去模板化技巧（去AI味核心）：
- 避免"首先…其次…再次…最后…"结构，这是 AI 最明显的标志
- 避免总分总：不要开头概述、中间展开、结尾总结
- 不要每段都只讲一个点然后总结，让段落之间有交叉和流动
- 加入闲笔：写一段看似和主线无关的内容（路边的猫、收音机里的歌、窗台上的灰）
- 时间线不要完全线性：偶尔插叙、倒叙、或者"那天的事他后来才想起来"
- 场景切换不要用过渡句："与此同时""另一边"→直接切，读者能跟上
- 打破信息密度均匀：有的地方密集推进，有的地方放慢写一个细节""",
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


def build_skill_prompt(task_type="write"):
    """Build the combined skill prompt from active skills.

    task_type: write / diagnose / polish / full —— 决定文件型协议加载哪些模块。
    普通 Writer 调用用 write；质检/诊断调用用 diagnose；润色用 polish。
    带协议包字段的技巧优先加载完整文件协议，回退到静态浓缩 prompt。

    同一协议包（如三个江南技巧都指向 jiangnan）只整包加载一次，避免重复注入
    浪费 token。约束来自该包下所有激活技巧的 constraints（去重合并）。
    """
    active = get_active_skills()
    all_skills = get_all_skills()

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
        if skill.get("prompt"):
            parts.append(f"【{skill['name']}技巧】\n{skill['prompt']}")
            if skill.get("constraints"):
                parts.append(f"约束：{skill['constraints']}")

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
