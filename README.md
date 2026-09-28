# webui-auto · 通用 Web UI 自动化测试框架

> **一句话**：配置驱动的 Web UI 自动化框架，**不绑定任何具体业务系统**。
> 站点地址、账号密码、页面结构、元素按钮、超时、健康检查阈值……全部参数化写到配置里；
> 换一个系统 = 换一份配置，框架代码一行不用改。

---

## 目录

1. [它能做什么](#1-它能做什么)
2. [目录结构](#2-目录结构)
3. [三层配置（核心设计）](#3-三层配置核心设计)
4. [元素定位策略清单](#4-元素定位策略清单)
5. [动作清单（用例里能做什么）](#5-动作清单用例里能做什么)
6. [断言清单（能判断什么）](#6-断言清单能判断什么)
7. [变量机制](#7-变量机制)
8. [登录：五种模式](#8-登录五种模式)
9. [安全护栏](#9-安全护栏)
10. [命令速查](#10-命令速查)
11. [接入一个新系统（5 步）](#11-接入一个新系统5-步)
12. [怎么看测试报告](#12-怎么看测试报告)
13. [环境准备与已验证结果](#13-环境准备与已验证结果)

---

## 1. 它能做什么

| 能力 | 说明 |
|---|---|
| **通用** | 只依赖 Selenium，被测系统是 Vue / React / jQuery / 静态页 / SPA / 传统后台都能测 |
| **零代码写用例** | 用例是 YAML，描述"打开哪页 → 做什么 → 断言什么"，不需要写 Python |
| **元素可维护** | 用例只写元素名（`element: username`），定位方式集中在 `config/pages`；前端改样式只需改配置 |
| **多站点** | 用 `--profile` 切换站点档案，互不干扰（并做了站点隔离，A 站用例不会跑到 B 站） |
| **多种登录** | `none / cookie / form / oauth / steps` 五种，覆盖免登、表单、单点、自定义多步 |
| **可视化报告** | 卡片式 HTML：彩色仪表盘 + 状态图标 + 每步操作/每个断言全展开 + 失败原因标红 |

---

## 2. 目录结构

```
webui-auto/
├── config/                      ← 所有"可变的东西"都在这
│   ├── profiles/                ← ① 站点档案：地址、浏览器、超时、登录、账号
│   │   ├── local.yaml           （本地自带示例站点，无需外网）
│   │   ├── noauth.yaml          （免登站点示例）
│   │   └── demo.yaml            （表单登录示例：the-internet 练习站）
│   ├── pages/                   ← ② 页面与元素：布局 + 按钮/输入框定位
│   │   ├── local.yaml  noauth.yaml  demo.yaml
│   └── cases/                   ← ③ 用例：测什么、怎么测
│       ├── local_smoke.yaml  noauth_smoke.yaml  demo_smoke.yaml
├── examples/local_site/         ← 内置静态站点（login/secure/tables 三个页面）
├── src/webui_auto/
│   ├── config_loader.py  配置加载与变量解析
│   ├── schema.py         配置校验（不启浏览器就能发现写错）
│   ├── locator.py        通用定位器（十几种策略）
│   ├── browser.py        浏览器工厂（headless / 代理 / cookie）
│   ├── auth.py           登录策略
│   ├── actions.py        动作引擎
│   ├── assertions.py     断言引擎
│   ├── runner.py         执行器
│   ├── report.py         报告（HTML / JSON / JUnit）
│   └── cli.py            命令行
├── scripts/
│   ├── run.py            运行入口
│   └── selftest.py       配置自检
└── reports/  screenshots/  state/   （运行时生成，已 gitignore）
```

**分层原则**：`config/` 描述"测什么"，`src/` 只管"怎么测"。`src/` 里没有任何写死的业务选择器。

---

## 3. 三层配置（核心设计）

### ① `config/profiles/<站点>.yaml` —— 环境参数

| 键 | 作用 | 示例 |
|---|---|---|
| `name` | 档案名（=`--profile` 用的名字） | `local` |
| `base_url` | 站点根地址 | `https://xxx.com`、`file://./examples/local_site` |
| `browser.headless` | 无界面/有界面 | `true` |
| `browser.window_size` | 窗口大小 | `"1920,1080"` |
| `browser.user_agent` / `extra_args` | UA、额外 Chrome 参数 | |
| `timeouts.page_load/element/script` | 三类超时 | `30 / 10 / 20` |
| `content_container` | **页面"有内容"判定用的容器**（关键通用化参数） | `#content`、`body`、`.app-main` |
| `healthy.console_ignore` | 控制台噪音白名单 | `[favicon]` |
| `healthy.http_error_threshold` | 接口错误阈值（`null`=不检查） | `400` |
| `login.*` | 登录方式（见第 8 节） | |
| `security.write_keywords` | 写操作护栏关键词 | 可覆盖默认列表 |

> `base_url` 支持 `file://./xxx`，会自动按项目根目录解析成绝对路径，本地静态页也能直接测。

### ② `config/pages/<站点>.yaml` —— 页面布局与元素

```yaml
pages:
  l_login:                    # 页面名（用例里引用）
    path: /login.html         # 相对 base_url 的路径
    wait_for: {id: username}  # 进入后等这个元素出现（可选）
    elements:                 # 元素名 → 定位方式
      username:  {id: username}
      password:  {id: password}
      login_btn: {css: "button[type=submit]"}
      flash:     {id: flash}
```

**这就是"页面布局 + 元素按钮参数化"的落点**：用例里永远只出现 `username` 这种名字。

### ③ `config/cases/<套件>.yaml` —— 用例

```yaml
suite: local
profile: local                # 绑定到哪个站点档案
defaults: {tags: [smoke]}
cases:
  - id: LOCAL-001
    name: 正确账号可进入安全页
    tags: [smoke, login]
    page: l_login             # 起始页面
    steps:                    # 做什么
      - input: {element: username, value: "${username}"}
      - click: {element: login_btn}
    assertions:               # 判断什么
      - page_healthy: {}
      - url_contains: {value: "secure.html"}
```

---

## 4. 元素定位策略清单

配置里可以任意选用（也支持组合，按优先级依次尝试）：

| 策略 | 写法 | 说明 |
|---|---|---|
| `id` | `{id: username}` | 最稳，优先用 |
| `css` | `{css: "button[type=submit]"}` | 万能 |
| `xpath` | `{xpath: "//div[@x]"}` | 兜底 |
| `name` | `{name: username}` | |
| `text` | `{text: 登录}` | 文案**完全相等**的元素（自动挑最合适的那个） |
| `contains` | `{contains: 登录}` | 文案**包含**即可 |
| `link_text` / `partial_link_text` | `{link_text: 更多}` | 链接专用 |
| `tag` | `{tag: h1}` | 标签名 |
| `class` | `{class: btn}` | class 名 |
| `aria_label` | `{aria_label: 搜索}` | 无障碍标签（React 组件常用） |
| `placeholder` | `{placeholder: 请输入}` | 输入框提示语 |
| `data_testid` | `{data_testid: submit}` | 前端埋的测试 id（最推荐） |
| `title` / `alt` | `{title: 提示}` | |
| `index` | `{css: "input", index: 2}` | 多个命中时取第 N 个（从 1 开始） |
| `frame` | `{id: x, frame: "#iframe"}` | 先切进 iframe 再找 |

> 小技巧：优先让前端加 `data-testid`，其次用 `id` / `aria_label` / `placeholder`，最后才用 `css/xpath`。
> 这样前端改样式、改结构时，你的用例基本不用动。

---

## 5. 动作清单（用例里能做什么）

| 动作 | 写法 | 说明 |
|---|---|---|
| 打开页面 | `goto: {page: l_tables}` 或 `goto: {url: /x}` | 也可用 `page:` 字段指定起始页 |
| 点击 | `click: {element: login_btn}` | 找不到会明确报"超时未找到元素" |
| 双击 | `dblclick: {element: x}` | |
| 悬停 | `hover: {element: x}` | |
| 输入 | `input: {element: username, value: "${username}"}` | 先清空再输入 |
| 清空 | `clear: {element: x}` | |
| 下拉选择 | `select: {element: x, option: 启用}` | 原生 select 与自定义下拉都支持 |
| 任意选中一项 | `select_any: {element: status}` | 不关心具体值，选一个有效选项：**跳过「请选择」这类占位项**，优先 启用/正常/否；原生 select 与自定义下拉都支持 |
| 勾选/取消 | `check: {element: x}` / `uncheck: {...}` | |
| 按键 | `press: {key: ENTER}` | |
| 滚动 | `scroll: {to: bottom}` 或 `scroll: {element: x}` | |
| 等待 | `wait: {seconds: 2}` / `wait: {element: x}` / `wait: {text: 完成}` | |
| 截图 | `screenshot: {name: 步骤1}` | |
| 存变量 | `store_text: {element: x, var: no}` | 之后用 `${no}` 引用 |
| 上传 | `upload: {element: x, file: 路径}` | |
| 执行 JS | `js: {script: "return 1+1"}` | 兜底用 |

---

## 6. 断言清单（能判断什么）

| 断言 | 写法 | 含义 |
|---|---|---|
| 元素可见 | `visible: {element: flash}` | 找得到且可见 |
| 元素不可见 | `not_visible: {element: x}` | |
| 元素存在 | `exists: {css: .el-table}` | 不要求可见 |
| 文本包含 | `text_contains: {value: 登录成功}` | 内容区包含（容器由 `content_container` 定） |
| 文本相等 | `text_equals: {value: 共 10 条}` | |
| 元素数量 | `count: {css: tr, min: 1}` | |
| 地址包含/相等 | `url_contains: {value: secure}` / `url_equals` | |
| 标题包含/相等 | `title_contains: {value: 后台}` / `title_equals` | |
| 属性相等 | `attribute_equals: {element: x, attr: class, value: active}` | |
| 表格列 | `table_columns: {element: table1, contains: [姓名, 状态]}` | 缺列会点名哪几列缺 |
| 表格行数 | `table_rows: {element: table1, min: 1}` | |
| 无控制台报错 | `no_console_error: {}` | 过滤 `console_ignore` 白名单 |
| 无接口报错 | `no_http_error: {}` | ≥ `http_error_threshold` 即计 |
| **页面健康** | `page_healthy: {}` | 综合：内容区渲染 + 控制台 + 接口 |

> `page_healthy` 的"内容区渲染"判定用的是你配置的 `content_container`，
> 所以**不会像写死 `.app-main` 那样换个系统就失效**——这是本框架通用化的关键设计。

---

## 7. 变量机制

用例里写 `${name}`，取值优先级：**`--var` 命令行 > 账号配置（`username` / `password`）> `.env` / 环境变量**。

```powershell
python scripts/run.py --profile local --var keyword=SELLO
```

账号密码由 `profile.login.credentials` 自动注入成 `${username}` / `${password}`：

```yaml
credentials:
  username_env: LOCAL_USERNAME     # 优先读环境变量 / .env
  password_env: LOCAL_PASSWORD
  username_default: tomsmith       # 环境变量缺失时的兜底
  password_default: SuperSecretPassword!
```

---

## 8. 登录：五种模式

`profile.login.mode`：

| 模式 | 适用 | 必填配置 |
|---|---|---|
| `none` | 无需登录的站点 | 无 |
| `form` | 普通账号密码表单 | `url`、`username_field`、`password_field`、`submit`、`success` |
| `oauth` | 表单提交后跳转外部认证再跳回 | 同 `form`（可加 `oauth_timeout`） |
| `cookie` | 复用已保存的登录态 | `cookie_file` |
| `steps` | 验证码、多步、特殊流程 | `steps:` —— **直接复用第 5 节的全部动作** |

`success` 判定（满足其一即可）：`url_contains` / `element` / `text_contains`。

`steps` 模式示例（登录本身就是一组参数化动作）：

```yaml
login:
  mode: steps
  steps:
    - goto: {url: /login}
    - input: {css: "#user", value: "${username}"}
    - input: {css: "#pwd", value: "${password}"}
    - click: {text: 登录}
```

登录只在**整轮执行开始时做一次**，所有用例复用会话；失败会把原因写进每条用例的报告里。

---

## 9. 安全护栏

框架**默认拦截写操作**（新建/保存/删除/提交/导入…）：命中关键词的步骤会被标记 `SKIPPED`，绝不偷偷改数据。
确需测试写操作时，两步缺一不可：

```yaml
- click: {element: create_btn, risk: write}   # 用例里声明有写风险
```
```powershell
python scripts/run.py --id XXX --allow-write  # 命令行开闸
```

关键词可用 `profile.security.write_keywords` 覆盖默认列表（默认含中英文常见写操作词）。

---

## 10. 命令速查

```powershell
# —— 不启浏览器 ——
python scripts/selftest.py --profile local        # 配置自检（有错退出码 1，可进 CI）
python scripts/run.py --profile local --list      # 列出用例
python scripts/run.py --dry-run                   # 只校验配置与元素引用

# —— 执行 ——
python scripts/run.py --profile local                      # 跑该站点全部用例
python scripts/run.py --profile local --tag smoke          # 按标签
python scripts/run.py --profile local --id LOCAL-001       # 按编号（可多个 --id）
python scripts/run.py --profile local --name 登录          # 按名称关键字
python scripts/run.py --profile local --suite local        # 按套件
python scripts/run.py --profile local --var keyword=SELLO  # 传变量
python scripts/run.py --profile local --headed             # 有界面跑（肉眼可见点击过程）
python scripts/run.py --profile local --allow-write        # 放开写操作护栏
python scripts/run.py --profile local --junit              # 额外出 JUnit XML（给 CI）
python scripts/run.py --base-url https://test.xxx.com      # 临时换地址（不改配置！）
python scripts/run.py --config-dir ./mycfg --profile s1    # 用另一套配置目录
```

参数可组合：`--tag` / `--id` / `--name` 任一命中即执行。

---

## 11. 接入一个新系统（5 步）

1. **复制站点档案**：`cp config/profiles/local.yaml config/profiles/mysite.yaml`，改：
   - `name: mysite`
   - `base_url: https://你的地址`
   - `content_container`（SPA 一般填内容区选择器，如 `.app-main`；普通页填 `body`）
   - `login.*`（登录方式与账号）
2. **写页面元素**：新建 `config/pages/mysite.yaml`，按页面把按钮/输入框/表格登记成名字。
3. **写用例**：新建 `config/cases/mysite_smoke.yaml`，`profile: mysite`。
4. **自检**：`python scripts/selftest.py --profile mysite`（会检查元素引用是否都对得上）。
5. **跑**：`python scripts/run.py --profile mysite --tag smoke`。

> 想先看看效果但系统还没配好？直接跑内置的 `local` 档案（自带静态站点，无需外网）。

---

## 12. 怎么看测试报告

打开 `reports/cases_<时间戳>.html`：

- **顶部彩色仪表盘**：总用例 / 通过 / 失败 / 异常 / 通过率；
- **每条用例一张卡片**，带状态徽标（✓ 通过 / ✗ 失败 / ⚠ 异常）；
- **操作和断言默认全展开**：每一步点击、每一次输入、每个断言的「实际值 / 期望值 / 耗时」都列出来；
- **失败标红并写明原因**：直接告诉你"哪一步挂了、期望什么、实际是什么"；
- **🔍 仅看失败**：一键过滤，只看红的和黄的。

同时产出 `cases_*.json`（给程序/CI 读），加 `--junit` 多一份 JUnit XML。

---

## 13. 环境准备与已验证结果

### 环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt   # selenium + PyYAML
```
需要本机已安装 **Google Chrome**（框架通过 Selenium Manager 自动匹配驱动）。

### 本机已验证（真实浏览器实跑）

| 档案 | 站点 | 结果 |
|---|---|---|
| `local` | 内置静态站点（file://，无需外网） | **3/3 通过，100%**（含表单登录、错误密码提示、表格断言） |
| `noauth` | https://example.com | **2/2 通过，100%** |
| `demo` | https://the-internet.herokuapp.com | 配置示例；**当前机器该域名被代理拦截（502）**，需外网畅通时跑 |

> `demo` 是 Selenium 圈最常用的公开练习站（标准表单登录），配置可直接复用；
> 本机跑不通是网络原因，框架已如实把"登录失败：打开登录页失败…"记进报告，不会静默假装通过。

---

## 设计小结：什么东西被参数化了

| 维度 | 落点 |
|---|---|
| 站点地址 | `profile.base_url`（可用 `--base-url` 临时覆盖） |
| 账号密码 | `profile.login.credentials`（环境变量 / `.env` / 兜底） |
| 浏览器与超时 | `profile.browser` / `profile.timeouts` |
| 页面布局 | `pages.<页>.path` / `wait_for` / `content_container` |
| 元素按钮 | `pages.<页>.elements.<名>`（十几种定位策略） |
| 登录方式 | `profile.login.mode` 五种 |
| 健康判定 | `content_container` + `healthy.*` |
| 写操作风险词 | `profile.security.write_keywords` |
| 用例数据 | `${变量}`（`--var` / 账号 / `store_text`） |
| 测试什么 | `cases.*`（步骤 + 断言） |

**框架代码里没有出现任何具体系统的地址、账号、选择器。**
