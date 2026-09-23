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
        try:
            el.click()
        except Exception:
            self.driver.execute_script("arguments[0].click();", el)
        return {"action": "click", "detail": f"点击 {desc}", "status": "ok"}

    def dblclick(self, body: Any) -> Dict[str, Any]:
        loc, desc = self._locator(body)
        el = loc.find(self.driver, timeout=self.timeout, visible=True)
        ActionChains(self.driver).double_click(el).perform()
        return {"action": "dblclick", "detail": f"双击 {desc}", "status": "ok"}

    def hover(self, body: Any) -> Dict[str, Any]:
        loc, desc = self._locator(body)
        el = loc.find(self.driver, timeout=self.timeout, visible=True)
        ActionChains(self.driver).move_to_element(el).perform()
        return {"action": "hover", "detail": f"悬停 {desc}", "status": "ok"}

    def input(self, body: Any) -> Dict[str, Any]:
        loc, desc = self._locator(body)
        value = body.get("value", "")
        el = loc.find(self.driver, timeout=self.timeout, visible=True)
        try:
            el.clear()
        except Exception:
            pass
        el.send_keys(str(value))
        return {"action": "input", "detail": f"向 {desc} 输入「{value}」", "status": "ok"}

    def clear(self, body: Any) -> Dict[str, Any]:
        loc, desc = self._locator(body)
        el = loc.find(self.driver, timeout=self.timeout, visible=True)
        el.clear()
        return {"action": "clear", "detail": f"清空 {desc}", "status": "ok"}

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
        # 自定义下拉（Element UI / AntD 等）：先点开，再点选项
        try:
            el.click()
        except Exception:
            self.driver.execute_script("arguments[0].click();", el)
        time.sleep(0.4)
        opt_loc = Locator({"text": str(option)})
        try:
            opt_loc.find(self.driver, timeout=3, visible=True).click()
            return {"action": "select", "detail": f"{desc} 选择「{option}」（自定义下拉）", "status": "ok"}
        except LocatorError:
            opt_loc2 = Locator({"contains": str(option)})
            try:
                opt_loc2.find(self.driver, timeout=3, visible=True).click()
                return {"action": "select", "detail": f"{desc} 选择「{option}」（自定义下拉）", "status": "ok"}
            except LocatorError:
                return {"action": "select", "detail": f"未找到下拉选项「{option}」", "status": "fail"}

    def check(self, body: Any) -> Dict[str, Any]:
        loc, desc = self._locator(body)
        el = loc.find(self.driver, timeout=self.timeout)
        if not el.is_selected():
            el.click()
        return {"action": "check", "detail": f"勾选 {desc}", "status": "ok"}

    def uncheck(self, body: Any) -> Dict[str, Any]:
        loc, desc = self._locator(body)
        el = loc.find(self.driver, timeout=self.timeout)
        if el.is_selected():
            el.click()
        return {"action": "uncheck", "detail": f"取消勾选 {desc}", "status": "ok"}

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
