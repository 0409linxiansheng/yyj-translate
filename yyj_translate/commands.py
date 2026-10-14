# Copyright (c) 2026, 云屿集 and contributors
# License: MIT. See LICENSE
"""yyj_translate 自带的 bench 命令。

放在 ``<app>/commands.py`` 里，bench 启动时会自动发现 ``commands`` 列表，
不需要改 frappe / erpnext 的任何文件。
"""

import click

import frappe
from frappe.commands import get_site, pass_context
from frappe.utils import get_bench_path
from frappe.utils.bench_helper import CliCtxObj


@click.command("yyj-extract-translations")
@click.option(
	"--apps",
	default=None,
	help="逗号分隔的 app 列表，默认扫描站点上所有已安装的 app（例如 frappe,erpnext）",
)
@click.option("--lang", default="zh", show_default=True, help="语言代码，用来判断哪些还没翻译")
@click.option("--pot", "pot_path", default=None, help="POT 输出路径，默认 <app>/locale/main.pot")
@click.option(
	"--untranslated",
	"untranslated_path",
	default=None,
	help="未翻译清单输出路径（每行一条），默认 bench 目录下的 all_untranslated.txt",
)
@click.option(
	"--worklist",
	"worklist_path",
	default=None,
	help="带标记的待翻译 CSV 工作清单输出路径，默认 bench 目录下的 all_translation_worklist.csv",
)
@click.option(
	"--all",
	"include_all",
	is_flag=True,
	default=False,
	help="导出全部字符串，而不是只导出还没有译文的",
)
@pass_context
def yyj_extract_translations(
	context: CliCtxObj,
	apps: str | None,
	lang: str,
	pot_path: str | None,
	untranslated_path: str | None,
	worklist_path: str | None,
	include_all: bool,
):
	"""汇总扫描所有已安装 app 的可翻译字符串（含 workspace / sidebar / onboarding 等 JSON 来源）"""
	from yyj_translate.translation.extract import run_extraction

	site = get_site(context)
	frappe.init(site)
	frappe.connect()
	try:
		bench_path = get_bench_path()
		summary = run_extraction(
			apps=[app.strip() for app in apps.split(",") if app.strip()] if apps else None,
			lang=lang,
			pot_path=pot_path,
			untranslated_path=untranslated_path or f"{bench_path}/all_untranslated.txt",
			worklist_path=worklist_path or f"{bench_path}/all_translation_worklist.csv",
			include_all=include_all,
			on_app=lambda app, count: click.echo(f"  {app}: {count} 条"),
		)
	finally:
		frappe.destroy()

	click.echo(f"已扫描 app：{', '.join(summary['apps'])}")
	click.echo(f"可翻译字符串合计：{summary['messages']}")
	click.echo(f"其中还没有译文：{summary['untranslated']}")
	click.echo(f"POT：{summary['pot']}")
	click.echo(f"PO 归档：{summary['po']}（词条 {summary['po_added']} 条为新增，已有译文 {summary['translated_in_po']} 条）")
	if summary["archived_from_csv"]:
		click.echo(f"已把旧 translations/zh.csv 的 {summary['archived_from_csv']} 条译文归档进 PO")
	click.echo(f"MO（运行时读取）：{summary['mo']}")
	if summary["untranslated_path"]:
		click.echo(f"未翻译清单：{summary['untranslated_path']}")
	if summary["worklist_path"]:
		click.echo(f"工作清单：{summary['worklist_path']}")


@click.command("yyj-import-translations")
@click.option(
	"--worklist",
	"worklist_path",
	default=None,
	help="填好译文的工作清单 CSV，默认 bench 目录下的 all_translation_worklist.csv",
)
@click.option("--lang", default="zh", show_default=True, help="语言代码")
@click.option(
	"--no-overwrite",
	is_flag=True,
	default=False,
	help="只补 PO 里还没有译文的词条，不覆盖已有译文",
)
@pass_context
def yyj_import_translations(
	context: CliCtxObj, worklist_path: str | None, lang: str, no_overwrite: bool
):
	"""把工作清单里填好的译文回填进 yyj_translate 的 PO 归档，并重新编译 mo"""
	from yyj_translate.translation.extract import run_import

	site = get_site(context)
	frappe.init(site)
	frappe.connect()
	try:
		bench_path = get_bench_path()
		summary = run_import(
			worklist_path=worklist_path or f"{bench_path}/all_translation_worklist.csv",
			lang=lang,
			overwrite=not no_overwrite,
		)
	finally:
		frappe.destroy()

	click.echo(f"读入工作清单：{summary['rows']} 条有译文的行")
	click.echo(f"PO 更新：{summary['updated']} 条，新增词条：{summary['added']} 条")
	click.echo(f"PO 中已有译文：{summary['translated_before']} -> {summary['translated_after']}")
	click.echo(f"PO：{summary['po']}")
	click.echo(f"MO：{summary['mo']}")
	click.echo("已清缓存，刷新界面即可看到新译文。")


commands = [yyj_extract_translations, yyj_import_translations]
