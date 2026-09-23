"""断言引擎：判断"页面对不对"。每个断言都返回 实际值 / 期望值 / 是否通过 / 说明。"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from selenium.webdriver.common.by import By

from .config_loader import resolve_vars
from .locator import STRATEGY_KEYS, Locator, LocatorError


class Assertions:
    def __init__(self, driver, cfg):
        self.driver = driver
        self.cfg = cfg
        self.timeout = cfg.timeout("element", 10)

        self._dispatch = {
            "visible": self.visible,
            "not_visible": self.not_visible,
            "exists": self.exists,
            "text_contains": self.text_contains,
            "text_equals": self.text_equals,
            "count": self.count,
            "url_contains": self.url_contains,
            "url_equals": self.url_equals,
            "title_contains": self.title_contains,
            "title_equals": self.title_equals,
            "attribute_equals": self.attribute_equals,
            "table_columns": self.table_columns,
            "table_rows": self.table_rows,
            "no_console_error": self.no_console_error,
            "no_http_error": self.no_http_error,
            "page_healthy": self.page_healthy,
        }

    # ————————————————— 工具 —————————————————
    def _locator(self, body: Any, page: Optional[str] = None):
        body = body or {}
        if "element" in body:
            name = str(body["element"])
            pg = page or getattr(self, "current_page", None)
            spec = self.cfg.element(pg, name) if pg else None
            if spec is None:
                raise LocatorError(f"页面 '{pg}' 下没有定义元素 '{name}'")
            return Locator(spec, name=name)
        spec = {k: v for k, v in body.items() if k in STRATEGY_KEYS or k in ("index", "frame")}
        if not spec:
            raise LocatorError(f"断言缺少定位参数：{body!r}")
        return Locator(spec)

    def _container_text(self) -> str:
        """取内容容器的可见文本（page_healthy / text_* 用）。"""
        sel = self.cfg.content_container
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, sel)
            txt = self.driver.execute_script(
                "return (arguments[0].innerText||arguments[0].textContent||'');", el)
            if txt and txt.strip():
                return txt.strip()
        except Exception:
            pass
        try:
            return (self.driver.find_element(By.TAG_NAME, "body").text or "").strip()
        except Exception:
            return ""

    def _console_ignore(self) -> List[str]:
        return list((self.cfg.profile.get("healthy") or {}).get("console_ignore") or [])

    def _console_errors(self) -> List[str]:
        ignore = [str(x) for x in self._console_ignore()]
        out = []
        try:
            logs = self.driver.get_log("browser") or []
        except Exception:
            return out
        for e in logs:
            if str(e.get("level", "")).upper() not in ("SEVERE", "ERROR"):
                continue
            msg = str(e.get("message", ""))
            if any(k and k in msg for k in ignore):
                continue
            out.append(msg[:300])
        return out

    def _http_errors(self) -> List[str]:
        thr = (self.cfg.profile.get("healthy") or {}).get("http_error_threshold", 400)
        if not thr:
            return []
        ignore = [str(x) for x in self._console_ignore()]
        out = []
        try:
            logs = self.driver.get_log("performance") or []
        except Exception:
            return out
        for e in logs:
            try:
                msg = json.loads(e.get("message", "{}"))
                m = (msg.get("message") or {})
                if m.get("method") != "Network.responseReceived":
                    continue
                resp = (m.get("params") or {}).get("response") or {}
                status = resp.get("status")
                url = resp.get("url") or ""
                if status is None or int(status) < int(thr):
                    continue
                if any(k and k in url for k in ignore):
                    continue
                out.append(f"{status} {url}")
            except Exception:
                continue
        return out

    # ————————————————— 执行入口 —————————————————
    def run(self, a: Any, page: Optional[str] = None) -> Dict[str, Any]:
        t0 = time.time()
        if not isinstance(a, dict) or not a:
            return {"type": str(a), "ok": False, "actual": "-", "expected": "-",
                    "detail": "断言格式错误", "elapsed": 0.0}
        key = str(list(a.keys())[0])
        body = resolve_vars(a.get(key), self.cfg.vars)
        self.current_page = page
        fn = self._dispatch.get(key)
        if fn is None:
            return {"type": key, "ok": False, "actual": "-", "expected": "-",
                    "detail": f"不支持的断言：{key}", "elapsed": round(time.time() - t0, 3)}
        try:
            r = fn(body)
        except LocatorError as e:
            r = {"ok": False, "actual": "未找到", "expected": "-", "detail": str(e)}
        except Exception as e:
            r = {"ok": False, "actual": "-", "expected": "-", "detail": f"{type(e).__name__}: {e}"}
        r.setdefault("actual", "-")
        r.setdefault("expected", "-")
        r["type"] = key
        r["elapsed"] = round(time.time() - t0, 3)
        return r

    # ————————————————— 各类断言 —————————————————
    def visible(self, body):
        loc = self._locator(body)
        el = loc.find(self.driver, timeout=self.timeout, visible=True)
        return {"ok": True, "actual": "可见", "expected": "可见", "detail": f"元素 {loc.describe()} 可见"}

    def not_visible(self, body):
        loc = self._locator(body)
        try:
            el = loc.find(self.driver, timeout=2)
            shown = el.is_displayed()
        except LocatorError:
            shown = False
        return {"ok": not shown,
                "actual": ("可见" if shown else "不可见"),
                "expected": "不可见",
                "detail": f"元素 {loc.describe()} {'仍然可见' if shown else '不可见/不存在'}"}

    def exists(self, body):
        loc = self._locator(body)
        loc.find(self.driver, timeout=self.timeout)
        return {"ok": True, "actual": "存在", "expected": "存在", "detail": f"元素 {loc.describe()} 存在"}

    def text_contains(self, body):
        want = str(body.get("value", ""))
        got = self._container_text()
        ok = want in got
        return {"ok": ok, "actual": (got[:200] + ("..." if len(got) > 200 else "")),
                "expected": f"包含「{want}」",
                "detail": ("页面内容包含该文本" if ok else f"页面内容未包含「{want}」")}

    def text_equals(self, body):
        want = str(body.get("value", ""))
        got = self._container_text()
        ok = got == want
        return {"ok": ok, "actual": got[:200], "expected": want,
                "detail": ("内容区文本一致" if ok else "内容区文本不一致")}

    def count(self, body):
        loc = self._locator(body)
        els = loc.find_all(self.driver, timeout=self.timeout)
        n = len(els)
        mn, mx = body.get("min"), body.get("max")
        ok = True
        exp_parts = []
        if mn is not None:
            ok = ok and n >= int(mn)
            exp_parts.append(f"≥{mn}")
        if mx is not None:
            ok = ok and n <= int(mx)
            exp_parts.append(f"≤{mx}")
        exp = " 且 ".join(exp_parts) or "-"
        return {"ok": ok, "actual": str(n), "expected": exp,
                "detail": f"{loc.describe()} 匹配数量 {n}"}

    def url_contains(self, body):
        want = str(body.get("value", ""))
        got = self.driver.current_url or ""
        ok = want in got
        return {"ok": ok, "actual": got, "expected": f"包含「{want}」",
                "detail": ("URL 符合预期" if ok else f"当前 URL 未包含「{want}」")}

    def url_equals(self, body):
        want = str(body.get("value", ""))
        got = (self.driver.current_url or "").rstrip("/")
        ok = got == want.rstrip("/")
        return {"ok": ok, "actual": got, "expected": want, "detail": "URL 一致" if ok else "URL 不一致"}

    def title_contains(self, body):
        want = str(body.get("value", ""))
        got = self.driver.title or ""
        ok = want in got
        return {"ok": ok, "actual": got, "expected": f"包含「{want}」",
                "detail": "标题符合预期" if ok else f"标题「{got}」未包含「{want}」"}

    def title_equals(self, body):
        want = str(body.get("value", ""))
        got = self.driver.title or ""
        return {"ok": got == want, "actual": got, "expected": want, "detail": "标题一致" if got == want else "标题不一致"}

    def attribute_equals(self, body):
        loc = self._locator(body)
        attr = str(body.get("attr") or body.get("attribute") or "")
        want = str(body.get("value", ""))
        el = loc.find(self.driver, timeout=self.timeout)
        got = str(el.get_attribute(attr))
        return {"ok": got == want, "actual": got, "expected": want,
                "detail": f"属性 {attr}" + ("一致" if got == want else "不一致")}

    def _table(self, body):
        loc = self._locator(body)
        return loc.find(self.driver, timeout=self.timeout)

    def table_columns(self, body):
        tb = self._table(body)
        ths = tb.find_elements(By.TAG_NAME, "th")
        cols = [t.text.strip() for t in ths if (t.text or "").strip()]
        want = [str(x) for x in (body.get("contains") or [])]
        missing = [w for w in want if w not in cols]
        return {"ok": not missing, "actual": ", ".join(cols) or "(无表头)",
                "expected": "包含 " + ", ".join(want) if want else "-",
                "detail": ("表头齐全" if not missing else f"表头缺少列：{', '.join(missing)}")}

    def table_rows(self, body):
        tb = self._table(body)
        rows = tb.find_elements(By.CSS_SELECTOR, "tbody tr")
        if not rows:
            rows = tb.find_elements(By.CSS_SELECTOR, "tr")
        n = len(rows)
        mn, mx = body.get("min"), body.get("max")
        ok = True
        parts = []
        if mn is not None:
            ok = ok and n >= int(mn)
            parts.append(f"≥{mn}")
        if mx is not None:
            ok = ok and n <= int(mx)
            parts.append(f"≤{mx}")
        return {"ok": ok, "actual": str(n), "expected": " 且 ".join(parts) or "-",
                "detail": f"表格行数 {n}"}

    def no_console_error(self, body=None):
        errs = self._console_errors()
        return {"ok": not errs, "actual": f"{len(errs)} 条", "expected": "0 条",
                "detail": ("控制台无严重报错" if not errs else "控制台报错：" + " | ".join(errs[:3]))}

    def no_http_error(self, body=None):
        errs = self._http_errors()
        return {"ok": not errs, "actual": f"{len(errs)} 条", "expected": "0 条",
                "detail": ("无失败接口请求" if not errs else "接口错误：" + " | ".join(errs[:3]))}

    def page_healthy(self, body=None):
        """综合健康检查：内容区渲染 + 控制台 + 接口。"""
        problems: List[str] = []
        sel = self.cfg.content_container
        try:
            containers = self.driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            containers = []
        if not containers:
            problems.append(f"内容容器不存在：{sel}（可能白屏/未渲染）")
        else:
            txt = self.driver.execute_script(
                "return (arguments[0].innerText||arguments[0].textContent||'').trim();",
                containers[0])
            if not txt:
                problems.append("内容区无可见文本（白屏/占位容器）")
        for e in self._console_errors():
            problems.append(f"控制台报错：{e}")
        for e in self._http_errors():
            problems.append(f"接口错误：{e}")
        return {"ok": not problems,
                "actual": "健康" if not problems else f"{len(problems)} 个问题",
                "expected": "页面健康（有内容、无报错）",
                "detail": ("页面健康" if not problems else "；".join(problems[:5]))}
