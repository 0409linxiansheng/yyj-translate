### YYJ Translate

ERPNext Chinese Translation Extensions

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch HEAD
bench install-app wlh_translate
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/wlh_translate
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit

## 中文翻译工作流

两个文件各司其职：

| 文件 | 角色 |
| --- | --- |
| `wlh_translate/locale/zh.po` | **唯一归档**。所有译文最终都存这里，也是运行时真正被读取的东西 |
| `all_translation_worklist.csv` | **翻译工作台**。只有还没译文的词条，第 4 列填中文 |

运行时链路：`zh.po` →（编译）`sites/assets/locale/zh/LC_MESSAGES/wlh_translate.mo`。
本 app 是最后安装的，所以这个 mo 会覆盖 frappe / erpnext 自带的 mo。

### 1. 提取

```bash
cd ~/frappe-bench
bench --site erp.local wlh-extract-translations
```

它会扫描**所有已安装 app**（用 frappe v16 的新提取器 `frappe.gettext`，而不是
`bench get-untranslated` 那条老路径，所以 workspace、sidebar、desktop icon、
onboarding、list filter、kanban、web form、report、page、custom fixtures
这些 JSON 里定义的界面文字也能扫到），然后：

* 写 `locale/main.pot`（全部词条 + 来源文件行号）
* 把新词条**只增不删**地并进 `locale/zh.po`（已有译文不动）
* 编译 `wlh_translate.mo` 并清译文缓存，界面立刻生效
* 写 `all_untranslated.txt`（还没译文的词条，换行用 `\|\|\|` 标记）
* 写 `all_translation_worklist.csv`，并保留上次已填、还没导入的译文（状态标成「待导入」）

### 2. 翻译

打开 `all_translation_worklist.csv`，只在第 4 列「中文译文」填中文，其它列不要动。

### 3. 回填

```bash
bench --site erp.local wlh-import-translations
```

把工作清单里的译文回填进 `zh.po`、重新编译 mo、清缓存。之后这些词条就不再出现在
下一次的工作清单里。

### 常见参数

```bash
bench --site erp.local wlh-extract-translations --apps frappe,erpnext   # 只扫指定 app
bench --site erp.local wlh-extract-translations --all                   # 导出全部词条，不只未译的
bench --site erp.local wlh-extract-translations --worklist /tmp/w.csv    # 换个工作清单路径
bench --site erp.local wlh-import-translations --no-overwrite            # 只补空译，不覆盖已有
```

手工补 PO 里没有的字符串：在任意 CSV 里写一行「原文,译文」（两列格式也认），
`wlh-import-translations --worklist <那个文件>` 就会把它加进 `zh.po`。

早先的 `wlh_translate/translations/zh.csv` 已经在第一次提取时自动归档进 `zh.po`，
原文件改名为 `zh.csv.migrated-to-po` 留档（不会再被读取）。运行时以 mo 为准，
所以以后请只改 PO / 工作清单，不要再改那个旧 CSV。

### 不扫描的内容

* 第三方打包产物：`*/node_modules/*`、`*/public/dist/*`，以及 `frappe/public/js/lib` 里的库
* 命名系列（`ACC-SINV-.YYYY.-`）和色值（`00ec`）这类不是界面文案的选项值
* 只存在于数据库、源码里没有的东西：用 Customize Form 改的标签（Property Setter）、
  界面上新建的 Custom Field / Number Card / Dashboard Chart / Email Template /
  Client Script / 自定义打印格式。这些可以用 `Translation` 单据（`/app/translation`）补，
  或先导出成 app 的 `fixtures/`、`custom/*.json` 再跑上面这条命令。

另外，同一句英文在不同上下文需要不同译法的词条（约 160 条，例如图片裁剪器的 `16:9`）
在工作清单里会合并成一条，用同一个译文——客户端查不到带上下文的译文时会退回无上下文的
那条，所以仍然会生效。

### 升级安全

扫描只读取 erpnext / frappe 的源码，所有输出都写在本 app 自己的目录和 bench 根目录，
不会修改其他 app 的任何文件。erpnext / frappe 升级（`git pull`、`bench update`）之后
重新跑一次命令，就能看到新版本新增了哪些待翻译词条。

另外注意：`main.pot` / `zh.po` 是生成物，重新提取会重写它们；`zh.po` 里的译文不会丢
（合并是只增不删），但 `main.pot` 建议和 app 一起提交，方便对比升级后新增了哪些词条。
