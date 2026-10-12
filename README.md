### YYJ Translate

ERPNext Chinese Translation Extensions

### Installation

仓库地址：<https://github.com/0409linxiansheng/yyj-translate>

仓库名是 `yyj-translate`，但这个 app 的名字（`pyproject.toml` 里的包名）是 `wlh_translate`。
`bench get-app` 是「克隆目录用仓库名、安装时用 app 名拼路径」，两者不一致时最后那步
`pip install -e apps/wlh_translate` 会找不到目录，所以在新 bench 上请手动克隆到 `apps/wlh_translate`：

```bash
cd ~/frappe-bench
git clone https://github.com/0409linxiansheng/yyj-translate.git apps/wlh_translate
env/bin/python -m pip install -e apps/wlh_translate
echo wlh_translate >> sites/apps.txt            # frappe 靠 apps.txt 认识这个 app
bench --site <站点> install-app wlh_translate   # after_install 钩子会自动编译 mo，装完即中文
```

已经在用的 bench 不需要上面这些，`cd apps/wlh_translate && git pull` 即可（origin 与分支跟踪已配好）；
拉完跑一次 `bench --site <站点> migrate`（或 `install-app`）让 `after_migrate` 钩子重新编译 mo。

### 整体安装流程（本套改动）

本套中文环境由下面这些仓库组成，**安装顺序 = `installed_apps` 顺序**，`wlh_translate` 必须放最后
（译文优先级最高）。telephony / helpdesk 的仓库名与 app 名一致，`bench get-app` 可直接使用；
只有本 app 因仓库名（`yyj-translate`）≠ app 名（`wlh_translate`）需要手动克隆。

| 顺序 | 应用 | 仓库地址 | 分支 |
| --- | --- | --- | --- |
| 1 | frappe | 官方 | — |
| 2 | erpnext | 官方 | — |
| 3 | hrms | 官方 | — |
| 4 | telephony | <https://github.com/0409linxiansheng/telephony> | develop |
| 5 | helpdesk | <https://github.com/0409linxiansheng/helpdesk> | main |
| 6 | wlh_translate | <https://github.com/0409linxiansheng/yyj-translate> | main |

```bash
cd ~/frappe-bench

# 官方应用（照常）
bench get-app erpnext
bench get-app hrms

# telephony / helpdesk：仓库名与 app 名一致，get-app 直接用
bench get-app https://github.com/0409linxiansheng/telephony --branch develop
bench get-app https://github.com/0409linxiansheng/helpdesk

# wlh_translate：仓库名(yyj-translate) ≠ app 名，必须手动克隆到 apps/wlh_translate
git clone https://github.com/0409linxiansheng/yyj-translate.git apps/wlh_translate
env/bin/python -m pip install -e apps/wlh_translate
echo wlh_translate >> sites/apps.txt

# 按顺序装到站点（wlh_translate 必须最后，after_install 会自动编译 mo）
bench --site <站点> install-app telephony
bench --site <站点> install-app helpdesk
bench --site <站点> install-app wlh_translate
```

已经在用的 bench 不需要重装：各仓库 `cd apps/<名> && git pull`，再跑一次
`bench --site <站点> migrate` 让 `wlh_translate` 的 `after_migrate` 重新编译 mo 即可。

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

Frappe 运行时会**按已安装顺序**把所有 app 的 mo 叠加起来，后面的覆盖前面的。本 app 通常排在
frappe / erpnext 之后，所以它的译文会覆盖这两家的；但若站点还装了别的带翻译的 app
（hrms、helpdesk 等），且它们装在本 app 之后，就会反过来覆盖本 app 的同名词条。
影响通常很小（实测仅十余条、且多为「措辞偏好」差异）；想让本 app 的译文绝对优先，可以把
`wlh_translate` 调到 `installed_apps` 的最后（见文末「译文优先级」），或用 `Translation`
单据单独覆盖个别词条（它永远最高优先）。

### 1. 提取

```bash
cd ~/frappe-bench
bench --site erp.local wlh-extract-translations
```

它会扫描**所有已安装 app**（用 frappe v16 的新提取器 `frappe.gettext`，而不是
`bench get-untranslated` 那条老路径）。除了各 app 的 Python / JS / 模板源码，还额外覆盖：

* **记录型 JSON**（随 app 安装的标准数据，一个记录一个文件）：Number Card、
  Dashboard Chart / Dashboard、Print Format / Print Style、Letter Head、Web Template、
  Website Theme、Form Tour、Financial Report Template、Email Template、Notification。
  这些文件里界面上会显示的标签字段，以及字段里内嵌的 `__()` 模板代码都会被扫到；
* **界面 JSON**：workspace、sidebar、workspace sidebar、desktop icon、dock、
  onboarding、list filter、kanban、web form、report（含列名 / 筛选项 / SQL 列别名）、
  page、custom fixtures；
* **注释里的翻译标记**（`// __('X')`），以及 `.vue` / `.ts` / `.tsx` 里的模板字符串。

然后：

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
  界面上**新建**的 Number Card / Dashboard Chart / Email Template / Client Script /
  自定义打印格式（随 app 安装的标准记录已能扫到，这里说的是你自己在界面里加的）。
  这些可以用 `Translation` 单据（`/app/translation`）补，或先导出成 app 的
  `fixtures/`、`custom/*.json` 再跑上面这条命令。
* 通知（Notification）的「主题 subject」：它渲染时不走 `_()`、属纯数据，所以不进工作清单
  （通知的正文、模板里写的 `__()` 标记是能扫到的）。

另外，同一句英文在不同上下文需要不同译法的词条（约 160 条，例如图片裁剪器的 `16:9`）
在工作清单里会合并成一条，用同一个译文——客户端查不到带上下文的译文时会退回无上下文的
那条，所以仍然会生效。

### 升级安全

扫描只读取 erpnext / frappe 的源码，所有输出都写在本 app 自己的目录和 bench 根目录，
不会修改其他 app 的任何文件。erpnext / frappe 升级（`git pull`、`bench update`）之后
重新跑一次命令，就能看到新版本新增了哪些待翻译词条。

另外注意：`main.pot` / `zh.po` 是生成物，重新提取会重写它们；`zh.po` 里的译文不会丢
（合并是只增不删），但 `main.pot` 建议和 app 一起提交，方便对比升级后新增了哪些词条。

### 译文优先级

运行时译文按 `installed_apps` 的顺序叠加，越靠后优先级越高。本 app 若装在 hrms、
helpdesk 等带翻译的 app **之前**，个别同名词条会被它们覆盖（实测仅十余条、且都还是中文，
只是措辞不同）。想让本 app 的译文绝对优先，用 `bench console` 把它挪到最后：

```python
# bench --site erp.local console
import frappe
order = frappe.get_installed_apps()
order.remove("wlh_translate")
order.append("wlh_translate")
frappe.db.set_global("installed_apps", frappe.as_json(order))
frappe.db.commit()
frappe.clear_cache()
```

注意：以后再 `bench install-app` 装新 app 时，它会**追加**在末尾、又排到本 app 之后；
装完重跑一次上面的命令即可。若只是个别词条想覆盖，直接用 `Translation` 单据更省事
（它永远最高优先，不受安装顺序影响）。
