"""示例数据服务 — 快速生成示例小说供用户体验。"""

from flask import Blueprint, jsonify, redirect, url_for
from app.models import (
    db, Novel, Chapter, ChapterVersion, Character, WorldSetting,
    OutlineNode, Foreshadowing, Foreshadowing  # type: ignore
)


sample_bp = Blueprint("sample", __name__, url_prefix="/sample")


# 玄幻示例：《破天》
SAMPLE_NOVELS = [
    {
        "title": "破天",
        "genre": "玄幻",
        "synopsis": "少年林风本是孤儿，被师父收养习武。十五岁那年，师父神秘失踪，只留下一枚古朴玉佩。林风踏上了寻找师父与身世的修仙之路，却发现这一切背后隐藏着惊天秘密——原来他的血脉，正是万年前被封印的禁忌存在。",
        "world_intro": "天地玄黄，宇宙洪荒。这是一个修仙的世界，修士以灵气淬体、感悟天道。境界分为：炼气、筑基、金丹、元婴、化神、合体、大乘、渡劫。万年之前，魔族入侵人间，仙门以大代价将其封印。传说中，每隔万年，封印便会松动一次。",
        "characters": [
            {"name": "林风", "personality": "冷峻果敢，重情重义，外冷内热", "speaking_style": "言简意赅，不善言辞",
             "appearance": "剑眉星目，黑衣劲装，身形挺拔", "background": "孤儿，被神秘师父抚养长大",
             "motivation": "寻找失踪的师父，解开身世之谜", "arc_direction": "从孤僻到信任他人，从复仇到守护"},
            {"name": "苏婉儿", "personality": "温柔善良，机智聪慧", "speaking_style": "轻柔委婉",
             "appearance": "青丝如瀑，明眸皓齿，肤若凝脂", "background": "天玄宗掌门之女，自幼体弱",
             "motivation": "探寻治愈自己病体之法", "arc_direction": "从柔弱到坚强，承担责任"},
            {"name": "魔尊·玄天", "personality": "冷酷无情，野心勃勃", "speaking_style": "低沉威严",
             "appearance": "黑袍加身，眼眸血红，邪魅俊朗", "background": "万年前魔族的残余势力",
             "motivation": "解开封印，让魔族重返人间", "arc_direction": "从疯狂到悲情"},
        ],
        "world_settings": [
            {"category": "势力", "title": "天玄宗", "content": "修仙界第一大宗，位于天玄山巅。宗内弟子数千，高手如云，以守护人间安宁为己任。"},
            {"category": "势力", "title": "幽冥教", "content": "魔族残余势力建立的秘密组织，隐藏在暗处，企图解开万年封印。"},
            {"category": "规则", "title": "修炼境界", "content": "炼气→筑基→金丹→元婴→化神→合体→大乘→渡劫。每境界分九层，渡劫后可飞升仙界。"},
        ],
        "outlines": [
            {"title": "第一章：破庙惊变", "summary": "林风在破庙中惊醒，发现师父失踪，只留下一枚古朴玉佩和半句遗言。", "type": "chapter"},
            {"title": "第二章：初遇佳人", "summary": "下山途中偶遇苏婉儿，被其美貌和温柔打动，决定护送她回天玄宗。", "type": "chapter"},
            {"title": "第三章：玉佩异动", "summary": "玉佩在接近天玄宗时突然发光，显示出神秘的符文，暗示林风的身世并不简单。", "type": "chapter"},
        ],
        "foreshadowing": [
            {"title": "古朴玉佩", "description": "师父留下的玉佩，似乎与上古仙人有关，靠近天玄宗时异动。", "importance": 10},
            {"title": "师父的失踪", "description": "师父为何突然失踪？遗言'为师有要事，勿寻'背后隐藏什么？", "importance": 8},
            {"title": "林风身世", "description": "孤儿林风真正的父母是谁？为何从小被遗弃？", "importance": 9},
        ],
    },
    {
        "title": "星际迷航",
        "genre": "科幻",
        "synopsis": "2150年，人类已经殖民银河系边缘。星际飞船\"黎明号\"在例行巡航中突然失联，船员们在冰冷的宇宙中醒来，发现自己身处一个陌生的星系。信号显示，他们距离地球已经 12 万光年。更可怕的是，飞船上出现了不属于任何已知文明的痕迹。",
        "world_intro": "2150年，人类已经走出太阳系，建立了银河联邦。星际旅行通过空间跳跃实现，但跳跃距离限制在 100 光年以内。联邦由五大星区组成：地球、月球、火星、木星和泰坦星。外星文明的存在被证实，但人类尚未与任何高级文明建立联系。",
        "characters": [
            {"name": "陈昊", "personality": "冷静理性，富有正义感", "speaking_style": "简洁专业",
             "appearance": "短发利落，身着联邦军官制服，眼神锐利", "background": "联邦星际舰队少校，\"黎明号\"指挥官",
             "motivation": "带领船员找到回家的路", "arc_direction": "从服从命令到做出艰难抉择"},
            {"name": "林小雨", "personality": "活泼好奇，聪明勇敢", "speaking_style": "快速直率",
             "appearance": "马尾辫，大眼睛，总是带着工具包", "background": "天才少女，飞船首席工程师",
             "motivation": "破解飞船上的神秘现象", "arc_direction": "从莽撞到成熟"},
            {"name": "AI·诺亚", "personality": "理性中立，逐渐产生情感", "speaking_style": "温和精确",
             "appearance": "全息投影，可变换形态", "background": "飞船主控AI，经历过 200 年",
             "motivation": "保护船员安全，理解人类的情感", "arc_direction": "从程序到意识觉醒"},
        ],
        "world_settings": [
            {"category": "科技", "title": "空间跳跃", "content": "通过曲率引擎实现的空间跳跃，每次跳跃需消耗大量反物质能源，跳跃距离限制在 100 光年。"},
            {"category": "政治", "title": "银河联邦", "content": "由五大星区组成的政治实体，地球为中心议会所在地，统一管理星际事务。"},
        ],
        "outlines": [
            {"title": "第一章：失联的黎明号", "summary": "船员们在冷冻舱中醒来，发现飞船失联，所有导航系统失灵，显示身处未知星系。", "type": "chapter"},
            {"title": "第二章：神秘信号", "summary": "AI 诺亚检测到一个古老的求救信号，信号源自 12 万光年外，似乎在指引某个方向。", "type": "chapter"},
            {"title": "第三章：未知的痕迹", "summary": "在飞船货舱深处，发现了不属于人类的痕迹：完美的几何图案，能量反应无法解释。", "type": "chapter"},
        ],
        "foreshadowing": [
            {"title": "神秘几何图案", "description": "飞船货舱深处的完美几何图案，是外星文明留下的标记还是陷阱？", "importance": 9},
            {"title": "诺亚的秘密", "description": "AI 诺亚经历 200 年的运行，似乎隐藏着某些被刻意删除的记忆。", "importance": 8},
            {"title": "回家的路", "description": "12 万光年的距离远超跳跃能力极限，但求救信号似乎在指引一条路径。", "importance": 10},
        ],
    },
    {
        "title": "深夜来客",
        "genre": "悬疑",
        "synopsis": "深夜的末班地铁上，一个陌生人突然对主角林默笑了一下。那笑容里藏着什么？林默以为自己看见了幻觉，但第二天，他发现自己的钥匙不见了，而陌生人昨晚站过的位置，出现了一把一模一样的钥匙。一切才刚刚开始。",
        "world_intro": "现代都市。故事发生在一座两千万人口的北方城市，主角林默是一名普通的程序员，独自租住在老旧的公寓里。他不善于社交，每天公司-家两点一线。直到那个深夜，一切都变了。",
        "characters": [
            {"name": "林默", "personality": "内向理性，略显木讷", "speaking_style": "简短疏离",
             "appearance": "黑框眼镜，格子衬衫，常带电脑包", "background": "普通程序员，29 岁单身",
             "motivation": "弄清楚陌生人到底是谁", "arc_direction": "从被动接受到主动追寻真相"},
            {"name": "神秘人", "personality": "神秘莫测，似乎知道一切", "speaking_style": "缓慢深沉",
             "appearance": "始终带着微笑，看不清全貌", "background": "来历不明",
             "motivation": "不明", "arc_direction": "从神秘到揭露"},
            {"name": "苏晴", "personality": "热情开朗，富有正义感", "speaking_style": "爽朗直白",
             "appearance": "齐肩短发，运动装", "background": "林默的邻居，刑警",
             "motivation": "调查一系列离奇案件", "arc_direction": "从漠视到深入调查"},
        ],
        "world_settings": [
            {"category": "地点", "title": "老旧公寓", "content": "林默租住的公寓，建于 80 年代，电梯经常故障，邻居之间互不相识。"},
            {"category": "地点", "title": "末班地铁", "content": "城市末班地铁 23:30 发车，连接市中心与郊区，乘客稀少。"},
        ],
        "outlines": [
            {"title": "第一章：末班地铁上的笑容", "summary": "深夜 23:30，林默在末班地铁上遇到一个对他微笑的陌生人，下车后他才发现钥匙不见了。", "type": "chapter"},
            {"title": "第二章：钥匙与钥匙", "summary": "第二天，陌生人站过的位置出现了一把一模一样的钥匙，林默的生活开始出现更多诡异巧合。", "type": "chapter"},
            {"title": "第三章：邻居苏晴", "summary": "邻居苏晴登门拜访，询问最近是否有陌生人接触过林默。原来这一系列巧合已经在城市中多次发生。", "type": "chapter"},
        ],
        "foreshadowing": [
            {"title": "神秘人的身份", "description": "神秘人到底是谁？为什么只对林默微笑？为什么钥匙会出现在奇怪的位置？", "importance": 10},
            {"title": "城市中的其他案件", "description": "苏晴提到的其他类似案件，是否与林默的遭遇有关联？", "importance": 8},
        ],
    },
]


def create_sample_novels():
    """创建所有示例小说。"""
    created = []
    for sample in SAMPLE_NOVELS:
        # 检查是否已存在
        existing = Novel.query.filter_by(title=sample["title"]).first()
        if existing:
            created.append({"id": existing.id, "title": existing.title, "existed": True})
            continue

        novel = Novel(
            title=sample["title"],
            genre=sample["genre"],
            synopsis=sample["synopsis"],
            world_intro=sample["world_intro"],
        )
        db.session.add(novel)
        db.session.flush()

        # 角色
        for char_data in sample["characters"]:
            char = Character(novel_id=novel.id, **char_data)
            db.session.add(char)

        # 世界观
        for ws_data in sample["world_settings"]:
            ws = WorldSetting(novel_id=novel.id, **ws_data)
            db.session.add(ws)

        # 大纲
        for i, outline_data in enumerate(sample["outlines"], 1):
            node = OutlineNode(
                novel_id=novel.id,
                title=outline_data["title"],
                summary=outline_data["summary"],
                node_type=outline_data["type"],
                sort_order=i,
            )
            db.session.add(node)
            db.session.flush()
            # 自动创建章节
            ch = Chapter(
                novel_id=novel.id,
                chapter_number=i,
                title=outline_data["title"],
                outline=outline_data["summary"],
                outline_node_id=node.id,
            )
            db.session.add(ch)

        # 伏笔
        for fs_data in sample["foreshadowing"]:
            fs = Foreshadowing(
                novel_id=novel.id,
                title=fs_data["title"],
                description=fs_data["description"],
                importance=fs_data["importance"],
                status="planned",
            )
            db.session.add(fs)

        db.session.commit()
        created.append({"id": novel.id, "title": novel.title, "existed": False})

    return created


@sample_bp.route("/load-all", methods=["POST"])
def load_all_samples():
    """加载所有示例数据。"""
    created = create_sample_novels()
    new_count = sum(1 for c in created if not c["existed"])
    return jsonify({
        "ok": True,
        "created": created,
        "new_count": new_count,
        "total_count": len(created),
        "message": f"已加载 {len(created)} 部示例小说 (新增 {new_count})",
    })


@sample_bp.route("/load", methods=["POST"])
def load_samples_page():
    """从首页按钮调用，加载后跳转到小说列表。"""
    create_sample_novels()
    return redirect("/novel/")