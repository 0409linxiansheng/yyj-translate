# Copyright (c) 2026, 云屿集 and contributors
# License: MIT. See LICENSE
"""在 frappe 自带提取器之上做的小补充。

三个原因：

1. frappe 的 JS / HTML 提取器用的是真正的解析器，会跳过注释；但 frappe / erpnext
   源码里有用注释写的翻译标记（例如 ``desk.js`` 里的
   ``// __('Modules') __('Domains') __('Places') __('Administration')``）。
   只靠解析器会把这些字符串漏掉，而老的 ``bench get-untranslated`` 反而能扫到。
   所以这里在解析器结果之后再补一次正则扫描。
2. ``.vue`` / ``.ts`` 只走 Jinja + 正则，而正则遇到 ``__("...", [参数])``
   这种跨行调用会漏，所以再补一次 JS 解析器。
3. 新提取器没有覆盖 ``page/*/*.json``（页面显示名）、doctype 的 ``module`` 字段、
   以及报表 SQL 里的列别名（``"列名:类型:宽度"``），这些都会出现在界面上。
"""

from __future__ import annotations

import io
import json
from contextlib import suppress

from frappe.gettext.extractors.doctype import extract as _doctype_extract
from frappe.gettext.extractors.html_template import extract as _jinja_extract
from frappe.gettext.extractors.javascript import extract as _javascript_extract
from frappe.gettext.extractors.report import extract as _report_extract
from frappe.gettext.extractors.utils import extract_messages_from_code, is_translatable
from frappe.translate import REPORT_TRANSLATE_PATTERN


def scan_untagged(code: str):
	"""正则兜底扫描：连写在注释里的翻译标记一起收进来。"""
	for lineno, message, context in extract_messages_from_code(code):
		if not message:
			continue
		if context:
			yield lineno, "pgettext", (context, message), []
		else:
			yield lineno, "_", message, []


def javascript(fileobj, *args, **kwargs):
	code = fileobj.read().decode("utf-8")
	yield from _javascript_extract(io.BytesIO(code.encode()), *args, **kwargs)
	yield from scan_untagged(code)


def html_template(fileobj, *args, **kwargs):
	"""``.html`` / ``.vue`` / ``.ts`` / ``.tsx``：Jinja + JS 解析器 + 正则三重扫描。"""
	code = fileobj.read().decode("utf-8")
	yield from _jinja_extract(io.BytesIO(code.encode()), *args, **kwargs)
	yield from _javascript_extract(io.BytesIO(code.encode()), *args, **kwargs)
	yield from scan_untagged(code)


def doctype(fileobj, *args, **kwargs):
	"""doctype JSON：保留 frappe 原本的提取结果，再补上 module 名称。"""
	data = json.load(fileobj)
	yield from _doctype_extract(io.BytesIO(json.dumps(data).encode()), *args, **kwargs)

	if isinstance(data, dict) and (module := data.get("module")):
		yield None, "_", module, ["Name of a module"]


def page(fileobj, *args, **kwargs):
	"""page JSON：补上页面的显示名（frappe 目前没有对应的提取器）。"""
	data = json.load(fileobj)

	if not isinstance(data, dict) or data.get("doctype") != "Page":
		return

	names = [data.get("title"), data.get("page_name")]
	if not any(names):
		names = [data.get("name")]

	for name in dict.fromkeys(name for name in names if name):
		yield None, "_", name, ["Display name of a Page"]

	if module := data.get("module"):
		yield None, "_", module, ["Name of a module"]


def report(fileobj, *args, **kwargs):
	"""report JSON：保留 frappe 的 report_name，再补上列名、筛选项和 SQL 列别名。"""
	data = json.load(fileobj)
	yield from _report_extract(io.BytesIO(json.dumps(data).encode()), *args, **kwargs)

	if not isinstance(data, dict):
		return

	name = data.get("report_name")
	columns, filters = data.get("columns"), data.get("filters")

	# 有些版本的 report JSON 会把列 / 筛选放在 json 字段里
	if isinstance(spec := data.get("json"), str):
		with suppress(Exception):
			spec = json.loads(spec)
			columns = columns or spec.get("columns")
			filters = filters or spec.get("filters")

	for column in columns or []:
		if isinstance(column, dict) and (label := column.get("label")) and is_translatable(label):
			yield None, "pgettext", (f"Column of report '{name}'", label), []

	for report_filter in filters or []:
		if isinstance(report_filter, dict) and (label := report_filter.get("label")) and is_translatable(label):
			yield None, "_", label, []

	for message in REPORT_TRANSLATE_PATTERN.findall(data.get("query") or ""):
		if is_translatable(message):
			yield None, "_", message, ["Column label from a report SQL query"]
