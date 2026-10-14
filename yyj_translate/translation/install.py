# Copyright (c) 2026, 云屿集 and contributors
# License: MIT. See LICENSE
"""安装 / 升级后的收尾工作。

本 app 的译文归档在 ``locale/<lang>.po``，但运行时真正读取的是
``sites/assets/locale/<lang>/LC_MESSAGES/yyj_translate.mo``——那是构建产物，不在 git 里。
所以新 bench 上 ``bench get-app`` + ``bench install-app`` 之后，
（以及每次 ``bench update`` 之后）必须重新编译一次，否则译文不会生效。

钩子挂在 ``after_install`` / ``after_migrate`` 上，这两处都会执行，
失败只记日志，不阻断安装或升级。
"""

from pathlib import Path

import frappe


def compile_po_files():
	"""把本 app 的每个 ``locale/<lang>.po`` 编译成对应的 mo。"""
	po_dir = Path(frappe.get_app_path("yyj_translate")) / "locale"
	if not po_dir.exists():
		return

	from yyj_translate.translation.extract import compile_mo

	for po_path in sorted(po_dir.glob("*.po")):
		try:
			mo_path = compile_mo(po_path.stem)
			print(f"yyj_translate: compiled {po_path.name} -> {mo_path}")
		except Exception:
			frappe.log_error(
				title="yyj_translate: failed to compile translations",
				message=frappe.get_traceback(),
			)
