# -*- coding: utf-8 -*-
"""只读：核验 novel 3 的角色/世界观并导出全文审查 Markdown。"""
import sqlite3, os, io, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
NID = 3
con = sqlite3.connect(os.path.join(os.path.dirname(__file__), "..", "data.db"))
con.row_factory = sqlite3.Row

novel = con.execute("SELECT id,title,genre,length(synopsis),length(world_intro) FROM novels WHERE id=?", (NID,)).fetchone()
chars = con.execute("SELECT * FROM characters WHERE novel_id=? ORDER BY id", (NID,)).fetchall()
worlds = con.execute("SELECT * FROM world_settings WHERE novel_id=? ORDER BY id", (NID,)).fetchall()

print("书:", dict(novel))
print("角色数:", len(chars), "| 世界观数:", len(worlds))

# ---- 完整性检查 ----
cfields = [("personality", "性格"), ("speaking_style", "说话风格"), ("appearance", "外貌"),
           ("background", "背景"), ("motivation", "动机"), ("arc_direction", "弧光")]
problems = []
names = [c["name"] for c in chars]
if len(set(names)) != len(names):
    problems.append("角色重名")
for c in chars:
    for f, zh in cfields:
        if not (c[f] or "").strip():
            problems.append(f"角色《{c['name']}》{zh}为空")
titles = [w["title"] for w in worlds]
if len(set(titles)) != len(titles):
    problems.append("世界观重名")
for w in worlds:
    if not (w["content"] or "").strip():
        problems.append(f"世界观《{w['title']}》正文为空")
    if not (w["category"] or "").strip():
        problems.append(f"世界观《{w['title']}》分类为空")
print("问题:", problems if problems else "无")

# 分类计数
from collections import Counter
print("世界观分类分布:", dict(Counter(w["category"] for w in worlds)))

# ---- 导出角色全文 ----
out = [f"# 《龙族：同级生》角色卡审查（共 {len(chars)} 张）\n"]
for i, c in enumerate(chars, 1):
    out.append(f"## {i}. {c['name']}（ID {c['id']}）\n")
    out.append(f"**性格**：{c['personality']}\n")
    out.append(f"**说话风格**：{c['speaking_style']}\n")
    out.append(f"**外貌**：{c['appearance']}\n")
    out.append(f"**背景**：{c['background']}\n")
    out.append(f"**动机**：{c['motivation']}\n")
    out.append(f"**角色弧光**：{c['arc_direction']}\n")
with io.open(os.path.join(os.path.dirname(__file__), "review", "角色卡全文.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(out))

# ---- 导出世界观全文（按类别分组） ----
out = [f"# 《龙族：同级生》世界观审查（共 {len(worlds)} 条）\n"]
cats = []
for w in worlds:
    if w["category"] not in cats:
        cats.append(w["category"])
for cat in cats:
    items = [w for w in worlds if w["category"] == cat]
    out.append(f"\n# 【{cat}】（{len(items)} 条）\n")
    for w in items:
        out.append(f"## {w['title']}（ID {w['id']}）\n")
        out.append(w["content"] + "\n")
with io.open(os.path.join(os.path.dirname(__file__), "review", "世界观全文.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(out))

print("已导出: longzu_setup/review/角色卡全文.md, 世界观全文.md")
con.close()
