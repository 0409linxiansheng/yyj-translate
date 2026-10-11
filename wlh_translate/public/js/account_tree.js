(() => {
    const settings = frappe.treeview_settings["Account"];

    if (!settings || typeof settings.get_label !== "function") {
        console.warn("wlh_translate: Account tree settings not ready");
        return;
    }

    const originalGetLabel = settings.get_label;

    settings.get_label = function (node) {
        const accountName = node?.data?.account_name;

        if (!accountName) {
            return originalGetLabel.call(this, node);
        }

        return frappe.utils.escape_html(__(accountName));
    };
})();
