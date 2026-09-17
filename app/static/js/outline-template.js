// 固定格式大纲模板：与 AI 生成大纲的提示词契约保持一致（7 字段）。
// 手写大纲套同一骨架，自动勾选出场角色（infer_cast 按人名匹配）与
// 写手侧的节拍施工指令才能吃到同样的收益。
const OUTLINE_FIELDS = [
    "【本章定位】", "【核心事件】", "【出场人物】", "【场景节拍】",
    "【情感基调】", "【伏笔操作】", "【结尾钩子】",
];

const OUTLINE_TEMPLATE = `【本章定位】推进：
【核心事件】1.
【出场人物】（人名须与人物卡完全一致；仅提及的标（背景提及））
【场景节拍】1.
【情感基调】→
【伏笔操作】埋设：
【结尾钩子】`;

function insertOutlineTemplate(targetId) {
    const ta = document.getElementById(targetId);
    if (!ta) return;
    if (ta.value.trim()) {
        if (!confirm('当前内容不为空，模板将追加到末尾，继续？')) return;
        ta.value = ta.value.replace(/\s*$/, '') + '\n' + OUTLINE_TEMPLATE;
    } else {
        ta.value = OUTLINE_TEMPLATE;
    }
    ta.focus();
}

// 软校验：手写大纲是否含全部 7 字段（空大纲不检查）。与 CLI 的
// outline_template.check_outline_format 同一契约。
function checkOutlineFormat(text) {
    if (!(text || "").trim()) return { ok: true, missing: [] };
    const missing = OUTLINE_FIELDS.filter(f => !(text || "").includes(f));
    return { ok: missing.length === 0, missing: missing };
}

// 硬校验：返回错误文案（null = 合规）。空大纲视为未填写（由调用方决定是否放行）。
function outlineFormatError(text) {
    if (!(text || "").trim()) return null;
    const chk = checkOutlineFormat(text);
    return chk.ok ? null
        : ('大纲必须按 7 字段固定格式填写（缺：' + chk.missing.join('、') + '）。\n'
           + '点编辑框旁的「插入大纲模板」套用骨架后填充；'
           + '自动勾选出场角色与按节拍铺写正文都依赖此格式。');
}

// 缺字段时的统一确认文案；返回 true = 用户坚持保存
function confirmOutlineFormat(text) {
    const chk = checkOutlineFormat(text);
    if (chk.ok) return true;
    return confirm('大纲未遵循 7 字段固定格式（缺：' + chk.missing.join('、') + '）。\n'
        + '自动勾选出场角色与按节拍铺写正文都依赖此格式，仍要保存吗？');
}

// 展示层：把 7 字段名渲染为高亮加粗（保留换行）；非固定格式文本原样转义
function _escapeOutlineHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function formatOutlineDisplay(text) {
    if (!text) return '';
    const html = _escapeOutlineHtml(text);
    return html.replace(
        /【(本章定位|核心事件|出场人物|场景节拍|情感基调|伏笔操作|结尾钩子)】/g,
        '<strong class="outline-field">【$1】</strong>');
}
