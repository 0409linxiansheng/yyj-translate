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
4. 有些界面文字是「记录里的数据字段」而不是 ``_()`` 调用的字面量：标准记录 JSON
   （Number Card、Print Format、通知…）和 helpdesk 标准视图（``setup/default_views.py``）。
   前端会用 ``__(record.label)`` 渲染它们，所以要把这些数据串也收进 PO。
"""

from __future__ import annotations

import ast
import io
import json
from contextlib import suppress

from frappe.gettext.extractors.doctype import extract as _doctype_extract
from frappe.gettext.extractors.html_template import extract as _jinja_extract
from frappe.gettext.extractors.javascript import extract as _javascript_extract
from frappe.gettext.extractors.python import extract as _python_extract
from frappe.gettext.extractors.report import extract as _report_extract
from frappe.gettext.extractors.utils import (
	TRANSLATE_PATTERN,
	add_line_number,
	extract_messages_from_code,
	is_translatable,
)
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


def scan_raw(code: str):
	"""不跑 Jinja 的正则扫描。``scan_untagged`` 会先让 Jinja 渲染一遍，
	``{{ _("X") }}`` 会被就地求值、正则就再也看不到 ``_("X")`` 了。
	记录 JSON 的字段里正是这种写法（例如通知正文、打印模板），所以单独用这个。
	"""
	messages = []
	for match in TRANSLATE_PATTERN.finditer(code):
		message = match.group("message")
		context = match.group("py_context") or match.group("js_context")
		if is_translatable(message):
			messages.append([match.start(), message, context])

	for lineno, message, context in add_line_number(messages, code):
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


def dock(fileobj, *args, **kwargs):
	"""dock JSON：把每个条目的标题也收进来。

	停靠栏（左侧竖栏、排列编辑器、管理停靠栏）显示的条目名，取的是 Dock 记录里每个
	item 的 ``title``，渲染时直接显示、不过 gettext。标准 dock 的 title 恰好等于模块名，
	早已随模块名进 PO；这里单独再扫一遍，是为了让站点上自定义过的停靠栏标题也能进工作清单。
	"""
	data = json.load(fileobj)

	if not isinstance(data, dict) or data.get("doctype") != "Dock":
		return

	for row in data.get("items") or []:
		if isinstance(row, dict) and (title := row.get("title")) and is_translatable(title):
			yield None, "_", title, ["Title of a Dock entry"]


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


# 标准记录 JSON（随 app 安装的数据）里，界面上会显示、且渲染走 _() 的标签字段。
# 需要新增一类记录时，在这里补一行即可（匹配规则见 babel_extractors.csv 最后一条）。
RECORD_LABEL_FIELDS = {
	"Number Card": ("label", "name"),
	"Dashboard Chart": ("chart_name", "label", "name"),
	"Dashboard": ("dashboard_name",),
	"Print Format": ("name",),
	"Print Format Field Template": ("name",),
	"Print Style": ("name",),
	"Letter Head": ("name",),
	"Web Template": ("name",),
	"Website Theme": ("name",),
	"Form Tour": ("title",),
	"Financial Report Template": ("name",),
	"Dashboard Chart Source": ("name",),
	"Email Template": ("name",),
}


def iter_strings(value):
	"""递归取出 JSON 里所有的字符串值。"""
	if isinstance(value, str):
		yield value
	elif isinstance(value, dict):
		for item in value.values():
			yield from iter_strings(item)
	elif isinstance(value, (list, tuple)):
		for item in value:
			yield from iter_strings(item)


def record_json(fileobj, *args, **kwargs):
	"""标准记录 JSON：取界面上会显示的标签字段，并扫描字段里嵌的 ``__()`` 调用。

	Number Card / Dashboard Chart / Dashboard / Print Format / Notification 这些
	doctype，「随 app 安装的标准记录」是各自目录下的一个 JSON 文件
	（``number_card/<名字>/<名字>.json`` 这种），没有任何 ``doctype/*.json`` 之类的
	规则能扫到它们，于是卡片标题、图表名称、打印模板里的文案全都漏掉。

	这里兜两层：

	* 把 JSON 解出来后，对每个字符串字段跑一次 ``_("...")`` 正则，收进
	  ``print_format.html``、``notification.message``、``web_template`` 这类
	  「把模板代码放在字符串字段里」的翻译标记。
	  （必须在解码后扫：JSON 会把 ``_("X")`` 转义成 ``_(\\"X\\")``，直接对原文跑正则
	  认不出双引号写法。）
	* 再按 doctype 从 ``RECORD_LABEL_FIELDS`` 取标签字段（这些会走 ``_()`` 渲染）。
	"""
	data = None
	with suppress(Exception):
		data = json.loads(fileobj.read().decode("utf-8"))

	if not isinstance(data, dict):
		return

	for value in iter_strings(data):
		yield from scan_raw(value)

	for field in RECORD_LABEL_FIELDS.get(data.get("doctype"), ()):
		value = data.get(field)
		if isinstance(value, str) and value and is_translatable(value):
			yield None, "_", value, [f"{field} of a {data['doctype']} record"]


def literal_string(node):
	"""从 AST 节点取出字符串字面量，取不到就返回 None。"""
	if isinstance(node, ast.Constant) and isinstance(node.value, str):
		return node.value
	return None


def hd_view(fileobj, *args, **kwargs):
	"""helpdesk 标准视图（``setup/default_views.py``）里的视图名与列名。

	这些是纯数据字符串（没包 ``_()``，而且列名藏在 ``columns`` 字段的 JSON 文本里），
	普通提取器扫不到；但前端用 ``__(view.label)`` / ``__(column.label)`` 渲染它们，
	所以把词条收进 PO 就能翻——tickets 列表页的视图标签和列头就是这么来的。
	"""
	source = fileobj.read().decode("utf-8")
	yield from _python_extract(io.BytesIO(source.encode()), *args, **kwargs)

	tree = None
	with suppress(Exception):
		tree = ast.parse(source)
	if tree is None:
		return

	for node in ast.walk(tree):
		if not isinstance(node, ast.Dict):
			continue

		fields = {
			key.value: value
			for key, value in zip(node.keys, node.values)
			if isinstance(key, ast.Constant) and isinstance(key.value, str)
		}

		label = literal_string(fields.get("label"))
		if label and is_translatable(label):
			yield None, "_", label, ["Title of a Helpdesk view"]

		columns = literal_string(fields.get("columns"))
		if not columns:
			continue

		with suppress(Exception):
			for column in json.loads(columns):
				name = column.get("label") if isinstance(column, dict) else None
				if name and is_translatable(name):
					yield None, "_", name, ["Column label of a Helpdesk view"]
