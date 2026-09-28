"""动作引擎：把用例里的"人话步骤"翻译成浏览器操作。

用例里只写元素名（element: username），具体怎么定位全在 config/pages 里。
这样前端改了样式/结构，只改配置，用例一行不用动。
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, Tuple

from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait

from .config_loader import resolve_vars
from .locator import STRATEGY_KEYS, Locator, LocatorError

# 自定义下拉（Element UI / AntD / ARIA 通用）的选项选择器，按常见度排序
_DROPDOWN_OPTION_CSS = (
    ".el-select-dropdown__item",      # Element UI
    ".ant-select-item-option",        # Ant Design
    "[role='option']",                # ARIA 通用
    "li.el-dropdown-menu__item",      # Element UI 下拉菜单
)
# 「任意选中一个」时的取值偏好：查询类用例要的是"查得出数据"，
# 所以优先选大概率有数据的选项，而不是下拉第一项（第一项常是空结果那一档）。
_PREFERRED_OPTIONS = ("启用", "正常", "否", "有效", "全部")


class Actions:
    def __init__(self, driver, cfg, allow_write: bool = False, screenshot_dir: str = "screenshots"):
        self.driver = driver
        self.cfg = cfg
        self.allow_write = allow_write
        self.screenshot_dir = screenshot_dir
        self.current_page: Optional[str] = None
        self.vars: Dict[str, Any] = dict(cfg.vars or {})
        self.timeout = cfg.timeout("element", 10)

        self._dispatch = {
            "goto": self.goto,
            "click": self.click,
            "dblclick": self.dblclick,
            "hover": self.hover,
            "input": self.input,
            "clear": self.clear,
            "select": self.select,
            "select_any": self.select_any,
            "check": self.check,
            "uncheck": self.uncheck,
            "press": self.press,
            "scroll": self.scroll,
            "wait": self.wait,
            "sleep": self.wait,
            "screenshot": self.screenshot,
            "store_text": self.store_text,
            "upload": self.upload,
            "js": self.js,
        }

    # ————————————————— 目标解析 —————————————————
    def _locator(self, body: Any, need: bool = True) -> Tuple[Optional[Locator], str]:
        """把 step 的 body 解析成 Locator + 描述。

        body 可以是：
          {element: 元素名}              —— 查当前页面的元素表
          {css: ...} / {text: ...} 等    —— 直接内联定位
        """
        if not isinstance(body, dict):
            raise LocatorError(f"步骤参数必须是字典，收到 {body!r}")
        if "element" in body:
            name = str(body["element"])
            if not self.current_page:
                raise LocatorError(f"使用 element='{name}' 前需先指定页面（page: 或 goto: {{page: ...}}）")
            spec = self.cfg.element(self.current_page, name)
            if spec is None:
                raise LocatorError(
                    f"页面 '{self.current_page}' 下没有定义元素 '{name}'（请检查 config/pages）")
            return Locator(spec, name=name), name
        spec = {k: v for k, v in body.items() if k in STRATEGY_KEYS or k in ("index", "frame")}
        if spec:
            return Locator(spec), Locator(spec).describe()
        if need:
            raise LocatorError(f"无法识别的定位参数：{body!r}")
        return None, ""

    # ————————————————— 写操作护栏 —————————————————
    def _write_guard(self, body: Dict[str, Any], describe: str) -> Optional[str]:
        """命中"写操作"关键词时默认拦截，返回跳过原因（None=放行）。"""
        if not isinstance(body, dict):
            return None
        kws = [str(k).lower() for k in self.cfg.write_keywords()]
        hay = " ".join(
            [describe or ""] + [str(v) for v in body.values() if isinstance(v, str)]
        ).lower()
        hits = [k for k in kws if k and k in hay]
        if not hits:
            return None
        declared = str(body.get("risk", "")).lower() == "write"
        if declared and self.allow_write:
            return None
        return (f"写操作 '{hits[0]}' 未执行：需用例里声明 risk: write "
                f"且命令行带 --allow-write（默认拦截，防止误改数据）")

    # ————————————————— 可靠性基石：点击/输入必须验证真的生效 —————————————————
    #
    # Selenium 原生 click / send_keys 走 CDP 输入管线，实测会**静默丢失**：
    # WebDriver 不抛任何异常，页面上却一个事件都没收到。只看"有没有抛异常"会把空操作
    # 当成成功，报告里全是假 ok。所以这里每一步都回读验证，没生效就走 JS 兜底。
    def _probe_ready(self) -> bool:
        """点击计数器（browser.py 在页面脚本之前注入）是否可用。"""
        try:
            return bool(self.driver.execute_script(
                "return typeof window.__wbClicks === 'number';"))
        except Exception:
            return False

    def _probe_reset(self) -> None:
        try:
            self.driver.execute_script("window.__wbClicks = 0;")
        except Exception:
            pass

    def _probe_count(self) -> int:
        try:
            return int(self.driver.execute_script("return window.__wbClicks || 0;"))
        except Exception:
            return 0

    def _effective_click(self, el) -> Tuple[bool, str]:
        """点击并验证事件真的送达；没送达用 DOM API 兜底。返回 (是否送达, 方式)。

        1. 原生 click（保真：触发真实激活行为、focus、hover 链路）；
        2. 计数器没涨 -> DOM API `el.click()`（走 JS 必定派发，同样触发 @click
           与 button/a 的激活行为）；
        3. 还是没有 -> 如实告诉调用方这次点击没生效。
        """
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        except Exception:
            pass
        has_probe = self._probe_ready()
        if has_probe:
            self._probe_reset()
        native_err = None
        try:
            el.click()
        except Exception as e:        # noqa: BLE001 - 抛了也要继续走兜底
            native_err = e
        if has_probe:
            time.sleep(0.25)
            if self._probe_count() > 0:
                return True, "native"
        try:
            self.driver.execute_script("arguments[0].click();", el)
        except Exception as e:
            # 元素因为这次点击而失效（页面跳转、局部重绘）是正常结果，不是失败。
            # 注意：整页跳转时计数器会随新文档清零，所以这里不能靠计数判断。
            if native_err is not None:
                raise e
            return True, "native"
        if has_probe:
            time.sleep(0.15)
            return self._probe_count() > 0, "dom"
        return True, "dom"

    @staticmethod
    def _click_note(how: str) -> str:
        return "（原生点击未送达，已用 DOM 点击兜底）" if how == "dom" else ""

    def _is_inert(self, el) -> bool:
        """元素是否处于"点了也不该有反应"的禁用态（禁用元素本来就不派发 click）。"""
        try:
            return bool(self.driver.execute_script(
                "const el = arguments[0];"
                "if (el.disabled) return true;"
                "if (el.getAttribute('aria-disabled') === 'true') return true;"
                "return /(^|\\s)is-disabled(\\s|$)/.test(el.className || '');", el))
        except Exception:
            return False

    def _ensure_editable(self, el):
        """命中的未必是输入控件：按文案定位可能命中 label / 外层容器 / 表头单元格，
        对它们 send_keys 会抛 ElementNotInteractable。这里下钻找真正的 input/textarea。"""
        try:
            if (el.tag_name or "").lower() in ("input", "textarea"):
                return el
        except Exception:
            return el
        try:
            found = self.driver.execute_script(
                "const el = arguments[0];"
                "if (el.querySelector) {"
                "  const i = el.querySelector('input, textarea');"
                "  if (i) return i;"
                "}"
                "let p = el.parentElement;"
                "for (let i = 0; i < 3 && p; i++) {"
                "  const j = p.querySelector('input, textarea');"
                "  if (j) return j;"
                "  p = p.parentElement;"
                "}"
                "return el;", el)
            return found or el
        except Exception:
            return el

    def _value_matches(self, el, value) -> bool:
        """回读输入框的真实值。读不到值时不误判（返回 True）。"""
        try:
            cur = self.driver.execute_script(
                "const el = arguments[0];"
                "return el.value === undefined ? null : String(el.value);", el)
        except Exception:
            return True
        return True if cur is None else cur == str(value)

    # ————————————————— 下拉 —————————————————
    def _dropdown_container(self, el):
        """自定义下拉的 @click 通常绑在容器上（.el-select / .ant-select），
        点内部 input 只能靠冒泡间接触发——直接点容器更稳。"""
        try:
            box = self.driver.execute_script(
                "let c = arguments[0];"
                "for (let i = 0; i < 5 && c; i++) {"
                "  const cls = (c.className || '').toString();"
                "  if (/(^|\\s)(el-select|ant-select)(\\s|$)/.test(cls)) return c;"
                "  c = c.parentElement;"
                "} return arguments[0];", el)
            return box or el
        except Exception:
            return el

    def _open_options(self, box, timeout: float = 5.0):
        """点开下拉并等选项出现；返回可见选项列表（可能为空）。"""
        self._effective_click(self._dropdown_container(box))
        end = time.time() + max(0.5, timeout)
        while time.time() < end:
            opts = self._visible_options()
            if opts:
                return opts
            time.sleep(0.3)
        return []

    def _visible_options(self):
        """按常见 UI 库的选择器收集当前可见的下拉选项。"""
        out = []
        for css in _DROPDOWN_OPTION_CSS:
            try:
                for e in self.driver.find_elements(By.CSS_SELECTOR, css):
                    try:
                        if not e.is_displayed():
                            continue
                    except Exception:
                        continue
                    if e not in out:
                        out.append(e)
            except Exception:
                continue
        return out

    def _pick_option(self, timeout: float = 5.0, prefer: bool = True):
        """从可见选项里挑一个：偏好值优先，否则第一项。"""
        opts = self._visible_options()
        end = time.time() + max(0.5, timeout)
        while time.time() < end and not opts:
            time.sleep(0.3)
            opts = self._visible_options()
        if not opts:
            return None
        if prefer:
            texts = [(e.text or "").strip() for e in opts]
            for want in _PREFERRED_OPTIONS:
                for e, t in zip(opts, texts):
                    if t == want:
                        return e
        return opts[0]

    # ————————————————— 动作 —————————————————
    def run(self, step: Any) -> Dict[str, Any]:
        t0 = time.time()
        if not isinstance(step, dict) or not step:
            return {"action": str(step), "detail": "步骤格式错误", "status": "error",
                    "elapsed": round(time.time() - t0, 3)}
        key = str(list(step.keys())[0])
        body = resolve_vars(step.get(key), self.vars)
        fn = self._dispatch.get(key)
        if fn is None:
            return {"action": key, "detail": f"不支持的动作：{key}", "status": "error",
                    "elapsed": round(time.time() - t0, 3)}
        try:
            r = fn(body)
        except LocatorError as e:
            r = {"action": key, "detail": str(e), "status": "fail"}
        except Exception as e:
            r = {"action": key, "detail": f"{type(e).__name__}: {e}", "status": "error"}
        r.setdefault("action", key)
        r["elapsed"] = round(time.time() - t0, 3)
        return r

    def goto(self, body: Any) -> Dict[str, Any]:
        body = body or {}
        if isinstance(body, str):
            body = {"page": body}
        if body.get("page"):
            pg = str(body["page"])
            url = self.cfg.url_of(pg)
            self.current_page = pg
            desc = f"打开页面 '{pg}' -> {url}"
        elif body.get("url"):
            url = str(body["url"])
            if not url.startswith("http"):
                url = self.cfg.base_url + "/" + url.lstrip("/")
            self.current_page = None
            desc = f"打开地址 {url}"
        else:
            return {"action": "goto", "detail": "goto 需要 page 或 url", "status": "error"}
        self.driver.get(url)
        # 页面级等待
        wf = None
        if self.current_page:
            wf = self.cfg.page(self.current_page).get("wait_for")
        if wf:
            try:
                Locator(wf, name="wait_for").find(self.driver, timeout=self.timeout, visible=True)
            except LocatorError:
                pass
        return {"action": "goto", "detail": desc, "status": "ok"}

    def click(self, body: Any) -> Dict[str, Any]:
        loc, desc = self._locator(body)
        guard = self._write_guard(body, desc)
        if guard:
            return {"action": "click", "detail": guard, "status": "skipped"}
        el = loc.find(self.driver, timeout=self.timeout, visible=True)
        delivered, how = self._effective_click(el)
        if not delivered and self._is_inert(el):
            return {"action": "click", "status": "ok",
                    "detail": f"点击 {desc}（元素为禁用态，无点击事件属预期）"}
        if not delivered:
            return {"action": "click", "status": "fail",
                    "detail": f"点击 {desc} 没有产生任何事件——元素可能已被页面重新渲染"
                              f"替换，或当前不可交互"}
        return {"action": "click", "detail": f"点击 {desc}{self._click_note(how)}", "status": "ok"}

    def dblclick(self, body: Any) -> Dict[str, Any]:
        loc, desc = self._locator(body)
        el = loc.find(self.driver, timeout=self.timeout, visible=True)
        try:
            ActionChains(self.driver).double_click(el).perform()
        except Exception:
            self.driver.execute_script(
                "const el = arguments[0];"
                "['mousedown','mouseup','click','dblclick'].forEach(t =>"
                "  el.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true, view:window})));",
                el)
        return {"action": "dblclick", "detail": f"双击 {desc}", "status": "ok"}

    def hover(self, body: Any) -> Dict[str, Any]:
        loc, desc = self._locator(body)
        el = loc.find(self.driver, timeout=self.timeout, visible=True)
        ActionChains(self.driver).move_to_element(el).perform()
        return {"action": "hover", "detail": f"悬停 {desc}", "status": "ok"}

    def input(self, body: Any) -> Dict[str, Any]:
        loc, desc = self._locator(body)
        value = str(body.get("value", ""))
        el = self._ensure_editable(loc.find(self.driver, timeout=self.timeout, visible=True))
        try:
            el.clear()
        except Exception:
            pass
        typed = False
        try:
            el.send_keys(value)
            typed = self._value_matches(el, value)
        except Exception:
            typed = False
        if typed:
            return {"action": "input", "detail": f"向 {desc} 输入「{value}」", "status": "ok"}
        # send_keys 被吞掉（不抛异常、值却没进去）-> JS 赋值 + 手动派发事件
        try:
            self.driver.execute_script(
                "const el = arguments[0]; el.focus(); el.value = arguments[1];"
                "el.dispatchEvent(new Event('input', {bubbles: true}));"
                "el.dispatchEvent(new Event('change', {bubbles: true}));", el, value)
        except Exception as e:
            return {"action": "input", "status": "fail",
                    "detail": f"向 {desc} 输入失败：{type(e).__name__}: {e}"}
        if not self._value_matches(el, value):
            return {"action": "input", "status": "fail",
                    "detail": f"向 {desc} 输入「{value}」后输入框的值没有变化——"
                              f"输入事件被页面或环境吞掉，请人工核对该输入框"}
        return {"action": "input", "detail": f"向 {desc} 输入「{value}」（JS 兜底）", "status": "ok"}

    def clear(self, body: Any) -> Dict[str, Any]:
        loc, desc = self._locator(body)
        el = self._ensure_editable(loc.find(self.driver, timeout=self.timeout, visible=True))
        try:
            el.clear()
            if self._value_matches(el, ""):
                return {"action": "clear", "detail": f"清空 {desc}", "status": "ok"}
        except Exception:
            pass
        try:
            el.send_keys(Keys.CONTROL, "a")
            el.send_keys(Keys.DELETE)
            if self._value_matches(el, ""):
                return {"action": "clear", "detail": f"清空 {desc}", "status": "ok"}
        except Exception:
            pass
        self.driver.execute_script(
            "const el = arguments[0]; el.value = '';"
            "el.dispatchEvent(new Event('input', {bubbles: true}));", el)
        return {"action": "clear", "detail": f"清空 {desc}（JS）", "status": "ok"}

    def select(self, body: Any) -> Dict[str, Any]:
        loc, desc = self._locator(body)
        option = body.get("option", body.get("value", body.get("label")))
        if option is None:
            return {"action": "select", "detail": "select 缺少 option/value/label", "status": "error"}
        el = loc.find(self.driver, timeout=self.timeout, visible=True)
        # 原生 select
        try:
            if (el.tag_name or "").lower() == "select":
                Select(el).select_by_visible_text(str(option))
                return {"action": "select", "detail": f"{desc} 选择「{option}」", "status": "ok"}
        except Exception:
            pass
        # 自定义下拉（Element UI / AntD 等）：点开容器，再点选项
        opts = self._open_options(el, timeout=min(self.timeout, 6))
        if not opts:
            return {"action": "select", "status": "fail",
                    "detail": f"{desc} 点不开或没有可用选项"}
        target = None
        want = str(option).strip()
        for e in opts:
            if ((e.text or "").strip() == want):
                target = e
                break
        if target is None:
            for e in opts:
                if want in ((e.text or "").strip()):
                    target = e
                    break
        if target is None:
            return {"action": "select", "status": "fail",
                    "detail": f"未找到下拉选项「{option}」（已展开 {len(opts)} 项）"}
        delivered, how = self._effective_click(target)
        time.sleep(0.3)
        if not delivered:
            return {"action": "select", "status": "fail",
                    "detail": f"下拉选项「{option}」点击未生效"}
        return {"action": "select", "status": "ok",
                "detail": f"{desc} 选择「{option}」（自定义下拉）{self._click_note(how)}"}

    def select_any(self, body: Any) -> Dict[str, Any]:
        """任意选中一项：用例只关心"选了个有效值"，不关心具体是哪个。

        典型场景：查询条件里的状态/类型筛选，Excel 里写「任意选中」「选择任意选项」。
        打开下拉后优先挑大概率有数据的选项（启用/正常/否…），再点它。
        """
        loc, desc = self._locator(body)
        el = loc.find(self.driver, timeout=self.timeout, visible=True)
        try:
            if (el.tag_name or "").lower() == "select":
                sel = Select(el)
                opts = [o for o in sel.options if (o.text or "").strip()]
                if not opts:
                    return {"action": "select_any", "status": "fail",
                            "detail": f"{desc} 没有可选项"}
                texts = [(o.text or "").strip() for o in opts]
                chosen = None
                for want in _PREFERRED_OPTIONS:
                    for o, t in zip(opts, texts):
                        if t == want:
                            chosen = o
                            break
                    if chosen is not None:
                        break
                chosen = chosen or opts[0]
                sel.select_by_visible_text((chosen.text or "").strip())
                return {"action": "select_any", "status": "ok",
                        "detail": f"{desc} 任意选择「{(chosen.text or '').strip()}」"}
        except Exception:
            pass
        opts = self._open_options(el, timeout=min(self.timeout, 6))
        chosen = self._pick_option(timeout=3.0)
        if chosen is None:
            return {"action": "select_any", "status": "fail",
                    "detail": f"{desc} 点不开或没有可用选项"}
        text = (chosen.text or "").strip()
        delivered, how = self._effective_click(chosen)
        time.sleep(0.3)
        try:  # 多选下拉点完不收起会挡住后面的按钮
            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass
        if not delivered:
            return {"action": "select_any", "status": "fail",
                    "detail": f"下拉选项「{text}」点击未生效"}
        return {"action": "select_any", "status": "ok",
                "detail": f"{desc} 任意选择「{text}」{self._click_note(how)}"}

    def check(self, body: Any) -> Dict[str, Any]:
        loc, desc = self._locator(body)
        el = loc.find(self.driver, timeout=self.timeout)
        if not el.is_selected():
            delivered, how = self._effective_click(el)
            if not delivered:
                return {"action": "check", "status": "fail", "detail": f"勾选 {desc} 点击未生效"}
            return {"action": "check", "detail": f"勾选 {desc}{self._click_note(how)}", "status": "ok"}
        return {"action": "check", "detail": f"勾选 {desc}（已勾选）", "status": "ok"}

    def uncheck(self, body: Any) -> Dict[str, Any]:
        loc, desc = self._locator(body)
        el = loc.find(self.driver, timeout=self.timeout)
        if el.is_selected():
            delivered, how = self._effective_click(el)
            if not delivered:
                return {"action": "uncheck", "status": "fail", "detail": f"取消勾选 {desc} 点击未生效"}
            return {"action": "uncheck", "detail": f"取消勾选 {desc}{self._click_note(how)}", "status": "ok"}
        return {"action": "uncheck", "detail": f"取消勾选 {desc}（本就未勾选）", "status": "ok"}

    def press(self, body: Any) -> Dict[str, Any]:
        key = str(body.get("key", "ENTER")).upper()
        code = getattr(Keys, key, None)
        if code is None:
            return {"action": "press", "detail": f"未知按键 {key}", "status": "error"}
        if isinstance(body, dict) and any(k in body for k in STRATEGY_KEYS + ("element",)):
            el, desc = self._locator(body)
            tgt = el.find(self.driver, timeout=self.timeout, visible=True)
            tgt.send_keys(code)
        else:
            desc = "当前页面"
            ActionChains(self.driver).send_keys(code).perform()
        return {"action": "press", "detail": f"在 {desc} 按键 {key}", "status": "ok"}

    def scroll(self, body: Any) -> Dict[str, Any]:
        to = str(body.get("to", "bottom")).lower()
        if to == "bottom":
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        elif to == "top":
            self.driver.execute_script("window.scrollTo(0, 0);")
        elif isinstance(body, dict) and ("element" in body or any(k in body for k in STRATEGY_KEYS)):
            loc, desc = self._locator(body)
            el = loc.find(self.driver, timeout=self.timeout)
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            return {"action": "scroll", "detail": f"滚动到 {desc}", "status": "ok"}
        else:
            return {"action": "scroll", "detail": f"不支持的滚动目标 {to}", "status": "error"}
        return {"action": "scroll", "detail": f"滚动到页面{to}", "status": "ok"}

    def wait(self, body: Any) -> Dict[str, Any]:
        body = body or {}
        if isinstance(body, (int, float)):
            time.sleep(float(body))
            return {"action": "wait", "detail": f"等待 {body}s", "status": "ok"}
        if body.get("seconds") is not None:
            s = float(body["seconds"])
            time.sleep(s)
            return {"action": "wait", "detail": f"等待 {s}s", "status": "ok"}
        if "element" in body or any(k in body for k in STRATEGY_KEYS):
            loc, desc = self._locator(body)
            loc.find(self.driver, timeout=self.timeout, visible=True)
            return {"action": "wait", "detail": f"等待元素出现：{desc}", "status": "ok"}
        if body.get("text"):
            t = str(body["text"])
            WebDriverWait(self.driver, self.timeout).until(
                lambda d: t in (d.find_element(By.TAG_NAME, "body").text or ""))
            return {"action": "wait", "detail": f"等待文本出现：{t}", "status": "ok"}
        time.sleep(1.0)
        return {"action": "wait", "detail": "等待 1s（未指定等待条件）", "status": "ok"}

    def screenshot(self, body: Any) -> Dict[str, Any]:
        body = body or {}
        name = str(body.get("name") or f"step_{int(time.time())}")
        os.makedirs(self.screenshot_dir, exist_ok=True)
        path = os.path.join(self.screenshot_dir, f"{name}.png")
        try:
            self.driver.save_screenshot(path)
            return {"action": "screenshot", "detail": f"截图已保存 {path}", "status": "ok"}
        except Exception as e:
            return {"action": "screenshot", "detail": f"截图失败：{e}", "status": "error"}

    def store_text(self, body: Any) -> Dict[str, Any]:
        loc, desc = self._locator(body)
        var = str(body.get("var") or "value")
        el = loc.find(self.driver, timeout=self.timeout)
        txt = (el.text or "").strip()
        self.vars[var] = txt
        return {"action": "store_text", "detail": f"把 {desc} 的文本存入 ${{{var}}} = 「{txt}」", "status": "ok"}

    def upload(self, body: Any) -> Dict[str, Any]:
        loc, desc = self._locator(body)
        f = str(body.get("file") or "")
        if not os.path.exists(f):
            return {"action": "upload", "detail": f"文件不存在：{f}", "status": "fail"}
        el = loc.find(self.driver, timeout=self.timeout)
        el.send_keys(os.path.abspath(f))
        return {"action": "upload", "detail": f"{desc} 上传文件 {f}", "status": "ok"}

    def js(self, body: Any) -> Dict[str, Any]:
        script = str(body.get("script") or "")
        if not script:
            return {"action": "js", "detail": "js 缺少 script", "status": "error"}
        res = self.driver.execute_script(script)
        return {"action": "js", "detail": f"执行 JS，返回 {str(res)[:120]}", "status": "ok"}
