// Dock / rail 条目名称的中文翻译。
//
// frappe 的 `Sidebar.dock_entry` 直接把 stored dock 行的 title 当成 label 用
// （`label: row.title || page?.title || sidebar?.label || row.link_to`），没有走 `__()`。
// 而 `erpnext/dock/erpnext/erpnext.json` 里每个条目的 title 就是模块的英文名
// （Setup / Accounts / Selling …），于是「管理停靠栏」列表、左侧停靠栏、
// 排列编辑器里的条目名全都显示英文——即使 erpnext / frappe 的 mo 里早就有对应译文。
//
// frappe 自己是预期客户端回传译文的：`dock.settle_reference` 里判空 override 用的是
// `settled[field] in (inherited, _(inherited))`，所以在这里补一次 `__()` 正好合它的意，
// 保存时带 context 的译文也会被识别为继承而不是覆盖。
//
// 与 account_tree.js 同样的做法：只包一层，运行时读现有的 mo，不需要改动 PO。
(() => {
    const proto = frappe.ui?.Sidebar?.prototype;
    if (!proto || typeof proto.dock_entry !== "function") {
        console.warn("wlh_translate: Sidebar.dock_entry 未就绪，停靠栏名称保持原样");
        return;
    }

    const original = proto.dock_entry;
    proto.dock_entry = function (row) {
        const entry = original.call(this, row);
        if (entry && entry.label) {
            entry.label = __(entry.label);
        }
        return entry;
    };
})();