# -*- coding: utf-8 -*-
"""一次性脚本：把开篇改成「自我介绍 / 百团大战 / 日常」，后面全部顺延。

用法：python lingyi_setup/tools_reflow_opening.py [--dry-run]
改完 outline.json 后必须再跑 09_sync_outline_to_chapters.py（或直接重建库）。
"""
from __future__ import annotations

import json
import os
import re
import sys

CONTENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "content")
PATH = os.path.join(CONTENT, "outline.json")

NEW1 = {
    "title": "第1章 玄学佬",
    "type": "chapter",
    "summary": "开场先自我介绍：陈屿，湘西人，家里三代干端公道士，老家有一座传了几代的坛；他爸信科学、不接这门手艺，带着他妈在外地上班，他从小跟爷爷在坛前长大——会一点，心里不信。考到常德来上学，一半是为了离开这一行，只想当个正常人。然后进摆摊环节：后街第二个路灯底下，折叠桌、三枚旧铜钱、写着周易咨询奶茶抵资的纸板，室友马千军在旁边吆喝拉客。他自己对这套半信半疑，客人问准吗，他答图个心安。收摊前一个姑娘坐下来闲聊——苏晚，话直、问得也刁，聊了两句两人都听出来了：对方也是对这个有兴趣、而且不是外行的人。他躲开一个女生的表白，被她当场笑话，甩出一句：玄学佬，你怎么就那么胆小呢。章末钩：她起身前说明天百团大战，民俗社那摊子正缺人，你这种会算的来不来；走到半路又回头问他一句：你猜我们明天能招到几个。",
}
NEW2 = {
    "title": "第2章 百团大战",
    "type": "chapter",
    "summary": "百团大战。民俗文化研究社的摊子冷清，隔壁国学社摆茶席、挂横幅、请了汉服队走场，两边从抢位子吵到抢人，社长们当场立赌：谁今天招得多，谁把活动室的空调让出来，谁请客一个月。马千军把这活接了下来，连桌带摊把陈屿搬到民俗社摊位旁边——会算卦的活招牌比横幅好使。排球队来凑热闹，他随口算了一卦；当晚比赛分毫不差，全队折回来喊他陈半仙，人流被带得哗哗的，民俗社一天招满。他一点得意都没有，反而心口发堵：他宁可自己是在蒙。章末钩：收摊清点人数，两边数出一模一样的数，赌成了平手，谁也不服，约定下周再比一场。",
}
NEW3 = {
    "title": "第3章 日常",
    "type": "chapter",
    "summary": "不急着上山，先过日常。社团活动室里抢空调、分任务、凑人头，马千军把社团做成了买卖，他把摊子摆到了窗边。民俗社要办一场校内民俗小活动（贴门神、写春联、讲节气），满社只有他一个人真懂，被按着头干活；他一边嫌烦，一边把活干得漂亮。苏晚天天来，占座、带饭、拆台三件套，两人相处越来越顺；他嘴上躲，脚下没躲，连马千军都看出来了。章末钩：活动收尾她提起周末要去一趟清微观——她在那边做了几年义工，观里库房要腾出来修缮，堆着一批旧东西，缺个认得的人。",
}
# 旧的「上山」章要把库房写成寻常旧物，并接上「下山进古玩街」
PATCH_UP_HILL = {
    "旧句": "清点的时候道长讲规矩：",
    "新句": "库里都是些寻常旧物：旧幡帐、缺了角的磬、几摞发霉的经书、落灰的香炉，没什么稀奇。清点的时候道长讲规矩：",
}


def main():
    dry = "--dry-run" in sys.argv
    tree = json.load(open(PATH, encoding="utf-8"))
    vols = tree[0]["children"]
    print("原章节数 =", len(vols))

    up_hill = vols[2]           # 旧第3章 上山
    assert up_hill["title"].startswith("第3章"), up_hill["title"]

    # 给「上山」补一句库房是寻常旧物
    if PATCH_UP_HILL["新句"] not in up_hill["summary"]:
        up_hill["summary"] = up_hill["summary"].replace(
            PATCH_UP_HILL["旧句"], PATCH_UP_HILL["新句"], 1)

    # 新的前三章 + 旧的「上山」及其后（丢掉旧第2章 陈半仙，其内容并入新第2章）
    new_children = [NEW1, NEW2, NEW3] + vols[2:]
    for i, ch in enumerate(new_children, 1):
        old = ch["title"]
        name = re.sub(r"^第\d+章\s*", "", old)
        ch["title"] = "第%d章 %s" % (i, name)
    tree[0]["children"] = new_children
    print("新章节数 =", len(new_children))
    for i, ch in enumerate(new_children[:6], 1):
        print("   %s" % ch["title"])

    if dry:
        print("[dry-run] 未写入")
        return
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(tree, f, ensure_ascii=False, indent=2)
    print("已写入 %s" % PATH)


if __name__ == "__main__":
    main()
