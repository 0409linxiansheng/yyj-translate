# Copyright (c) 2026, 云屿集 and contributors
# License: MIT. See LICENSE
"""针对自定义提取器的回归测试。

这些用例不依赖站点数据库，可以在 frappe / erpnext 升级后随时跑，确认
“别人新加的 JSON 界面类型 / 新写法”没有把我们的提取能力悄悄削弱：

	bench --site <site> run-tests --app yyj_translate
"""

import io
import json
import unittest

from babel.messages.extract import extract as babel_extract
from frappe.gettext.translate import PYTHON_KEYWORDS

from yyj_translate.translation import extractors


def run(extractor, payload: dict | str, filename: str = "sample.json"):
	"""按 babel 的真实调用方式跑一遍提取器（它会顺手把 pgettext 规范化）。"""
	raw = json.dumps(payload).encode() if isinstance(payload, dict) else payload.encode()
	return list(
		babel_extract(
			extractor,
			io.BytesIO(raw),
			keywords=PYTHON_KEYWORDS,
			comment_tags=(),
			options={},
		)
	)


def messages(records):
	return {record[1] for record in records if record[1]}


class TestExtractors(unittest.TestCase):
	def test_javascript_picks_up_strings_only_mentioned_in_comments(self):
		# frappe 的 desk.js 就是用注释保底登记模块名的
		code = '// __("Modules") __("Domains") __("Places")\nconst x = __("Real Label");'
		self.assertIn("Domains", messages(run(extractors.javascript, code, "desk.js")))
		self.assertIn("Real Label", messages(run(extractors.javascript, code, "desk.js")))

	def test_vue_multiline_call_with_arguments(self):
		# 这种写法正则匹配不到，必须靠 JS 解析器
		code = """<script>
			MSG = __('File "{0}" was skipped', [file.name]);
		</script>"""
		self.assertIn('File "{0}" was skipped', messages(run(extractors.html_template, code, "x.vue")))

	def test_page_display_names(self):
		page = {
			"doctype": "Page",
			"name": "point-of-sale",
			"page_name": "Point of Sale",
			"title": "Point Of Sale",
			"module": "Selling",
		}
		found = messages(run(extractors.page, page))
		self.assertIn("Point of Sale", found)
		self.assertIn("Point Of Sale", found)
		self.assertIn("Selling", found)

	def test_doctype_module_name(self):
		doctype = {
			"doctype": "DocType",
			"name": "Sales Invoice",
			"module": "Accounts",
			"fields": [{"fieldtype": "Data", "fieldname": "title", "label": "Title"}],
		}
		found = messages(run(extractors.doctype, doctype))
		self.assertIn("Accounts", found)
		self.assertIn("Title", found)

	def test_report_columns_filters_and_query_aliases(self):
		report = {
			"doctype": "Report",
			"report_name": "Sales Partners Commission",
			"columns": [{"label": "Invoiced Amount (Excl. Tax)"}],
			"filters": [{"label": "Sales Partner"}],
			"query": 'select sum(a) as "Average Commission Rate:Percent:220" from t',
		}
		found = messages(run(extractors.report, report))
		self.assertIn("Sales Partners Commission", found)
		self.assertIn("Invoiced Amount (Excl. Tax)", found)
		self.assertIn("Sales Partner", found)
		self.assertIn("Average Commission Rate", found)

	def test_non_page_json_is_ignored(self):
		self.assertEqual(messages(run(extractors.page, {"doctype": "DocType", "name": "x"})), set())


if __name__ == "__main__":
	unittest.main()
