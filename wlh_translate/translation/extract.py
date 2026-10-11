# Copyright (c) 2026, 云屿集 and contributors
# License: MIT. See LICENSE
"""跨 app 汇总提取可翻译字符串，并维护 wlh_translate 自己的 PO 归档。

两个文件，各司其职
------------------

``wlh_translate/locale/zh.po``
	**唯一归档**。所有译文最终都存在这里，也是运行时真正被读取的东西：
	``bench wlh-extract-translations`` 会把它编译成
	``sites/assets/locale/zh/LC_MESSAGES/wlh_translate.mo``。
	本 app 是最后安装的，所以这个 mo 会覆盖 frappe / erpnext 自带的 mo。

``all_translation_worklist.csv``
	**翻译工作台**。只有还没译文的词条，第 4 列填中文，译完跑
	``bench wlh-import-translations`` 回填进 zh.po 并重新编译。
	再次提取时会保留你已填、但还没导入的译文（状态标成「待导入」）。

为什么不能直接用 frappe 的 ``bench update-po-files``
---------------------------------------------------

``Catalog.update()`` 会把模板里已经不存在的老词条**删掉**。这里用「只增不删」的合并
（``merge_pot_into_po``），这样你手工补的、源码里扫不到的词条（比如界面定制的标签）
不会被下一次提取冲掉。

扫描范围上的两处补充见 ``extractors.py``。
"""

from __future__ import annotations

import csv
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import frappe
from babel.messages.catalog import Catalog
from babel.messages.extract import extract_from_dir
from babel.messages.mofile import read_mo, write_mo
from babel.messages.pofile import read_po, write_po
from frappe.gettext.translate import (
	PYTHON_KEYWORDS,
	get_catalog,
	get_method_map,
	get_mo_path,
	get_po_path,
	new_catalog,
)

APP_NAME = "wlh_translate"
DEFAULT_LANG = "zh"
LEGACY_CSV_SUFFIX = ".migrated-to-po"

HTML_PATTERN = re.compile(r"<[a-zA-Z/!][^>]*>")
PLACEHOLDER_PATTERN = re.compile(r"\{[^{}]*\}|%\(\w+\)[sdif]|%[sdif]")

WORKLIST_HEADERS = (
	"编号",
	"英文原文",
	"原始文本键",
	"中文译文",
	"包含HTML",
	"包含参数占位符",
	"包含换行标记",
	"检查状态",
)

STATUS_TODO = "待翻译"
STATUS_PENDING_IMPORT = "待导入"

# escape_newlines 的逆操作，顺带兼容 Excel 自动补的空格
NEWLINE_RESTORES = (
	("|||||", "\\\n"),
	("| | | | |", "\\\n"),
	("||||", "\\n"),
	("| | | |", "\\n"),
	("|||", "\n"),
	("| | |", "\n"),
)


# --------------------------------------------------------------------------- 路径


def default_pot_path() -> Path:
	"""汇总后的 POT 默认写在本 app 的 locale 目录里。"""
	return Path(frappe.get_app_path(APP_NAME)) / "locale" / "main.pot"


def default_po_path(lang: str) -> Path:
	return Path(get_po_path(APP_NAME, lang))


def legacy_csv_path(lang: str) -> Path:
	return Path(frappe.get_app_path(APP_NAME)) / "translations" / f"{lang}.csv"


def installed_apps() -> list[str]:
	return list(frappe.get_installed_apps())


def app_source_path(app: str) -> Path:
	"""app 仓库根目录，也就是 apps/<app>。"""
	return Path(frappe.get_app_source_path(app))


# --------------------------------------------------------------------------- 扫描


def merged_method_map(app: str) -> list[tuple[str, str]]:
	"""合并「本 app 的提取器映射 + 目标 app 自己的映射 + frappe 默认映射」。

	本 app 的映射放在最前面：它是 frappe 默认映射的副本 + 几处补充
	（注释里的翻译标记、page / 报表列名、module 名称），内部再委托给 frappe 的提取器，
	所以既不会漏，也能跟上 frappe 的升级。
	"""
	merged: dict[str, str] = {}
	for source in (APP_NAME, app, "frappe"):
		for pattern, method in get_method_map(source) or []:
			merged.setdefault(pattern, method)
	return list(merged.items())


def directory_filter(dirpath: str) -> bool:
	"""跳过隐藏目录、__pycache__、node_modules 和打包产物目录。"""
	subdir = os.path.basename(dirpath)
	if subdir.startswith(".") or subdir.startswith("_"):
		return False
	if subdir == "node_modules":
		return False
	return "/public/dist" not in dirpath.replace(os.sep, "/")


def message_text(message: Any) -> str:
	"""把提取器给出的消息统一成字符串（复数形式取单数那一条）。"""
	if isinstance(message, (list, tuple)):
		return str(message[0]) if message else ""
	return str(message)


def build_master_catalog(
	apps: list[str], on_app=None
) -> tuple[Catalog, list[tuple[str, str | None]]]:
	"""扫描 apps，返回 (POT 目录, 去重后的 (字符串, 上下文) 列表)。"""
	catalog = new_catalog(APP_NAME)
	seen: dict[tuple[str, str | None], None] = {}

	for app in apps:
		root = app_source_path(app)
		if not root.exists():
			continue

		count = 0
		for filename, lineno, message, comments, context in extract_from_dir(
			root,
			merged_method_map(app),
			keywords=PYTHON_KEYWORDS,
			directory_filter=directory_filter,
		):
			if not message:
				continue

			catalog.add(
				message,
				locations=[(f"{app}/{filename}", lineno)],
				auto_comments=comments or [],
				context=context,
			)
			seen.setdefault((message_text(message), context), None)
			count += 1

		if on_app:
			on_app(app, count)

	return catalog, list(seen)


# --------------------------------------------------------------------------- PO 归档


def po_catalog(lang: str) -> Catalog:
	"""读取（或新建）本 app 的 PO 归档。"""
	return get_catalog(APP_NAME, lang)


def merge_pot_into_po(po: Catalog, pot: Catalog) -> int:
	"""把 POT 里的新词条补进 PO；只增不删，已有译文原样保留。"""
	existing = {(message.id, message.context) for message in po}
	added = 0

	for message in pot:
		if not message.id or (message.id, message.context) in existing:
			continue
		po.add(
			message.id,
			context=message.context,
			locations=list(message.locations),
			auto_comments=list(message.auto_comments),
		)
		added += 1

	return added


def translated_ids(catalog: Catalog) -> set[str]:
	"""PO 里已经有译文的词条 id。"""
	return {
		message_text(message.id)
		for message in catalog
		if message.id and str(message.string or "").strip()
	}


def apply_translations(
	catalog: Catalog,
	pairs,
	overwrite: bool = True,
	add_missing: bool = True,
	plain_only: bool = False,
) -> tuple[int, int]:
	"""把 (原文, 译文) 写进目录。返回 (更新条数, 新增词条数)。

	``plain_only`` 只写不带 context 的词条：迁移旧的两列 CSV 时用它，避免用
	没有上下文信息的旧译文去覆盖 frappe / erpnext 官方带 context 的译文。
	"""
	by_id: dict[Any, list] = defaultdict(list)
	for message in catalog:
		by_id[message.id].append(message)
		if isinstance(message.id, tuple) and message.id:
			by_id[message.id[0]].append(message)

	updated = added = 0
	for message_id, string in pairs:
		if not message_id or not string:
			continue

		targets = by_id.get(message_id) or []
		if plain_only:
			targets = [message for message in targets if not message.context]

		if not targets:
			if not add_missing:
				continue
			message = catalog.add(message_id, string=string)
			by_id[message_id].append(message)
			added += 1
			continue

		for message in targets:
			if not overwrite and str(message.string or "").strip():
				continue
			message.string = (string, string) if isinstance(message.id, tuple) else string
			updated += 1

	return updated, added


def write_po_file(path: Path, catalog: Catalog) -> Path:
	path.parent.mkdir(parents=True, exist_ok=True)
	with open(path, "wb") as po_file:
		write_po(po_file, catalog, sort_output=True, ignore_obsolete=True, width=None)
	return path


def compile_mo(lang: str) -> Path:
	"""把 zh.po 编译成运行时真正读取的 wlh_translate.mo。"""
	po_path = default_po_path(lang)
	mo_path = Path(get_mo_path(APP_NAME, lang))

	with open(po_path, "rb") as po_file:
		catalog = read_po(po_file)

	add_context_fallbacks(catalog)
	mo_path.parent.mkdir(parents=True, exist_ok=True)
	with open(mo_path, "wb") as mo_file:
		write_mo(mo_file, catalog)

	# 立刻读回来验证，避免写出坏文件后悄悄丢掉全部译文
	with open(mo_path, "rb") as mo_file:
		compiled = [message for message in read_mo(mo_file) if str(message.string or "").strip()]

	if not compiled and translated_ids(catalog):
		raise RuntimeError(f"{mo_path} 编译后是空的，已中止")

	return mo_path


def add_context_fallbacks(catalog: Catalog) -> int:
	"""给只有「带 context 译文」的词条补一条无 context 的译文。

	frappe 的 ``get_translations_from_mo`` 文档说会做这件事，实现里其实没做
	（只在字典里放 ``原文:context`` 这个键）。而客户端的 ``__()`` 是
	「先查带 context 的，查不到再查不带 context 的」，少了这一条，同一个英文
	在不传 context 的调用点就会漏译。
	"""
	plain_ids = {message.id for message in catalog if message.id and not message.context}
	extras = [
		(message.id, str(message.string))
		for message in catalog
		if message.id
		and message.context
		and str(message.string or "").strip()
		and message.id not in plain_ids
	]

	for message_id, string in extras:
		catalog.add(message_id, string=string)
		plain_ids.add(message_id)

	return len(extras)


def refresh_runtime(lang: str) -> None:
	"""清掉 frappe 的译文缓存，让新 mo 立刻生效。

	顺手在 ``frappe.local.lang`` 已经设对的情况下预热一次：``get_all_translations``
	是按语言缓存的，而它内部的 ``get_translated_countries()`` 用的是
	``frappe.local.lang``，在后台 / 脚本里没设语言时会被算成英文——趁这里
	语言明确，先把正确的合并字典算好放进缓存。
	"""
	from frappe.translate import clear_cache, get_all_translations

	previous = getattr(frappe.local, "lang", None)
	frappe.local.lang = lang
	clear_cache()
	get_all_translations(lang)
	if previous:
		frappe.local.lang = previous


# --------------------------------------------------------------------------- CSV


def escape_newlines(text: str) -> str:
	"""把真实换行转成标记，保证一条消息占一行。"""
	return text.replace("\\\n", "|||||").replace("\\n", "||||").replace("\n", "|||")


def restore_newlines(text: str) -> str:
	for marker, newline in NEWLINE_RESTORES:
		text = text.replace(marker, newline)
	return text


def yes_no(value: bool) -> str:
	return "是" if value else "否"


def read_worklist_csv(path: str | os.PathLike[str]) -> tuple[list[tuple[str, str]], dict[str, str]]:
	"""读工作清单，返回 (全部译文对, 原文 -> 译文)。两种格式都认：

	* 本命令生成的 8 列格式（取「英文原文」和「中文译文」）
	* 简单的两列格式 ``原文,译文``
	"""
	path = Path(path)
	if not path.exists():
		return [], {}

	with open(path, encoding="utf-8-sig", newline="") as handle:
		rows = list(csv.reader(handle))
	if not rows:
		return [], {}

	if tuple(rows[0][:3]) == WORKLIST_HEADERS[:3]:
		source_col, target_col, first_row = 1, 3, 1
	else:
		source_col, target_col, first_row = 0, 1, 0

	pairs: list[tuple[str, str]] = []
	lookup: dict[str, str] = {}
	for row in rows[first_row:]:
		if len(row) <= max(source_col, target_col):
			continue

		message_id = row[source_col] or (restore_newlines(row[2]) if len(row) > 2 else "")
		string = row[target_col].replace("\r\n", "\n")
		if message_id and string.strip():
			pairs.append((message_id, string))
			lookup[message_id] = string

	return pairs, lookup


def read_legacy_csv(lang: str) -> list[tuple[str, str]]:
	"""读旧版 ``translations/<lang>.csv``（两列或三列）。"""
	path = legacy_csv_path(lang)
	if not path.exists():
		return []

	pairs = []
	with open(path, encoding="utf-8", newline="") as handle:
		for row in csv.reader(handle):
			if len(row) >= 2 and row[0] and row[1].strip():
				pairs.append((row[0].replace("\\n", "\n"), row[1].replace("\\n", "\n")))
	return pairs


def write_untranslated(path: Path, messages: list[str]) -> Path:
	path.parent.mkdir(parents=True, exist_ok=True)
	with open(path, "w", encoding="utf-8", newline="\n") as out:
		for message in messages:
			out.write(escape_newlines(message) + "\n")
	return path


def write_worklist(
	path: Path, messages: list[str], pending: dict[str, str] | None = None
) -> Path:
	"""写待翻译 CSV，并保留上一次已填、但还没导入的译文。"""
	pending = pending or {}
	path.parent.mkdir(parents=True, exist_ok=True)

	with open(path, "w", encoding="utf-8-sig", newline="") as out:
		writer = csv.writer(out, lineterminator="\n")
		writer.writerow(WORKLIST_HEADERS)
		for index, message in enumerate(messages, start=1):
			escaped = escape_newlines(message)
			filled = pending.get(message, "")
			writer.writerow(
				[
					index,
					message,
					escaped,
					filled,
					yes_no(bool(HTML_PATTERN.search(message))),
					yes_no(bool(PLACEHOLDER_PATTERN.search(message))),
					yes_no("|||" in escaped),
					STATUS_PENDING_IMPORT if filled.strip() else STATUS_TODO,
				]
			)
	return path


def untranslated(
	messages: list[tuple[str, str | None]], lang: str, known: set[str] | None = None
) -> list[str]:
	"""既不在站点现有译文里、也不在 PO 归档里的词条。"""
	from frappe.translate import get_all_translations

	translations = get_all_translations(lang) or {}
	known = known or set()
	missing: set[str] = set()

	for message, context in messages:
		if not message or message in known or message in translations:
			continue
		if context and f"{message}:{context}" in translations:
			continue
		missing.add(message)

	return sorted(missing)


# --------------------------------------------------------------------------- 命令入口


def run_extraction(
	apps: list[str] | None = None,
	lang: str = DEFAULT_LANG,
	pot_path: str | os.PathLike[str] | None = None,
	untranslated_path: str | os.PathLike[str] | None = None,
	worklist_path: str | os.PathLike[str] | None = None,
	include_all: bool = False,
	on_app=None,
) -> dict:
	"""扫描所有已安装 app，写 POT，同步 PO 归档，编译 mo，导出工作清单。"""
	apps = list(apps) if apps else installed_apps()
	pot = Path(pot_path) if pot_path else default_pot_path()
	po_path = default_po_path(lang)

	# 1. 扫描 + 写 POT
	catalog, messages = build_master_catalog(apps, on_app=on_app)
	pot.parent.mkdir(parents=True, exist_ok=True)
	with open(pot, "wb") as pot_file:
		write_po(pot_file, catalog, sort_output=True, ignore_obsolete=True, width=None)

	# 2. 同步 PO 归档（只增不删）
	po = po_catalog(lang)
	added = merge_pot_into_po(po, catalog)

	# 3. 把旧的 translations/zh.csv 归档进 PO（不覆盖 PO 里已有的译文）
	archived, legacy_path = 0, None
	legacy_pairs = read_legacy_csv(lang)
	if legacy_pairs:
		archived, _extra = apply_translations(
			po, legacy_pairs, overwrite=False, add_missing=True, plain_only=True
		)
		legacy_path = legacy_csv_path(lang)

	write_po_file(po_path, po)
	mo_path = compile_mo(lang)
	refresh_runtime(lang)

	# 4. 归档成功后再把旧 CSV 改名，避免它以后和新流程互相干扰
	if legacy_pairs and legacy_path and legacy_path.exists():
		legacy_path.rename(legacy_path.with_suffix(legacy_path.suffix + LEGACY_CSV_SUFFIX))

	# 5. 导出待翻译清单 / 工作清单
	known = translated_ids(po)
	if include_all:
		missing = sorted({message for message, _context in messages if message})
	else:
		missing = untranslated(messages, lang, known=known)

	_, pending = read_worklist_csv(worklist_path) if worklist_path else ([], {})
	if untranslated_path:
		write_untranslated(Path(untranslated_path), missing)
	if worklist_path:
		write_worklist(Path(worklist_path), missing, pending=pending)

	return {
		"apps": apps,
		"messages": len(messages),
		"untranslated": len(missing),
		"pot": str(pot),
		"po": str(po_path),
		"mo": str(mo_path),
		"po_added": added,
		"archived_from_csv": archived,
		"translated_in_po": len(known),
		"untranslated_path": str(untranslated_path) if untranslated_path else None,
		"worklist_path": str(worklist_path) if worklist_path else None,
	}


def run_import(
	worklist_path: str | os.PathLike[str],
	lang: str = DEFAULT_LANG,
	overwrite: bool = True,
) -> dict:
	"""把工作清单里填好的译文回填进 PO，然后重新编译 mo。"""
	pairs, _lookup = read_worklist_csv(worklist_path)
	po_path = default_po_path(lang)

	po = po_catalog(lang)
	before = len(translated_ids(po))
	updated, added = apply_translations(po, pairs, overwrite=overwrite, add_missing=True)

	write_po_file(po_path, po)
	mo_path = compile_mo(lang)
	refresh_runtime(lang)

	return {
		"po": str(po_path),
		"mo": str(mo_path),
		"rows": len(pairs),
		"updated": updated,
		"added": added,
		"translated_before": before,
		"translated_after": len(translated_ids(po)),
	}
