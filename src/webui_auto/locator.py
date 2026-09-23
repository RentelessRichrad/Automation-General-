"""通用元素定位器。

把配置里"人话"的定位描述（id / css / xpath / 文案 / 标签 / aria / placeholder / data-testid…）
翻译成 Selenium 能用的定位方式。框架里没有任何写死的业务选择器。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement

# 支持的定位策略（配置里出现的键）
STRATEGY_KEYS = (
    "id", "css", "xpath", "name", "link_text", "partial_link_text",
    "tag", "class", "class_name",
    "text", "contains", "aria_label", "placeholder", "data_testid",
    "title", "alt",
)
META_KEYS = ("index", "frame", "risk", "desc")


class LocatorError(Exception):
    pass


def _xstr(s: str) -> str:
    """生成安全的 XPath 字符串字面量。"""
    s = str(s)
    if "'" not in s:
        return "'" + s + "'"
    if '"' not in s:
        return '"' + s + '"'
    parts = s.split("'")
    return "concat(" + ",".join(("'%s'" % p) if p else "\"'\"" for p in parts) + ")"


class Locator:
    """一个元素定位描述。"""

    def __init__(self, spec: Dict[str, Any], name: str = "", desc: str = ""):
        if not isinstance(spec, dict):
            raise LocatorError(f"定位描述必须是字典，收到：{spec!r}")
        self.spec = spec
        self.name = name
        self.desc = desc or spec.get("desc") or ""
        self.index = spec.get("index")
        self.frame = spec.get("frame")
        if not any(k in spec for k in STRATEGY_KEYS):
            raise LocatorError(
                f"定位描述缺少有效策略键（可用：{', '.join(STRATEGY_KEYS)}），收到：{spec!r}"
            )

    # —— 生成 (by, value) 候选，按优先级 ——
    def _candidate_expressions(self) -> List[Tuple[str, str]]:
        s = self.spec
        out: List[Tuple[str, str]] = []
        if s.get("id"):
            out.append((By.ID, str(s["id"])))
        if s.get("data_testid"):
            out.append((By.CSS_SELECTOR, f"[data-testid='{s['data_testid']}']"))
        if s.get("name"):
            out.append((By.NAME, str(s["name"])))
        if s.get("css"):
            out.append((By.CSS_SELECTOR, str(s["css"])))
        if s.get("xpath"):
            out.append((By.XPATH, str(s["xpath"])))
        if s.get("text"):
            out.append((By.XPATH, f".//*[normalize-space(.)={_xstr(s['text'])}]"))
        if s.get("contains"):
            out.append((By.XPATH, f".//*[contains(normalize-space(.),{_xstr(s['contains'])})]"))
        if s.get("aria_label"):
            out.append((By.CSS_SELECTOR, f"[aria-label='{s['aria_label']}']"))
        if s.get("placeholder"):
            out.append((By.CSS_SELECTOR, f"[placeholder='{s['placeholder']}']"))
        if s.get("link_text"):
            out.append((By.LINK_TEXT, str(s["link_text"])))
        if s.get("partial_link_text"):
            out.append((By.PARTIAL_LINK_TEXT, str(s["partial_link_text"])))
        if s.get("class") or s.get("class_name"):
            out.append((By.CLASS_NAME, str(s.get("class") or s.get("class_name"))))
        if s.get("tag"):
            out.append((By.TAG_NAME, str(s["tag"])))
        if s.get("title"):
            out.append((By.CSS_SELECTOR, f"[title='{s['title']}']"))
        if s.get("alt"):
            out.append((By.CSS_SELECTOR, f"[alt='{s['alt']}']"))
        return out

    def describe(self) -> str:
        label = self.name or self.desc or ""
        keys = {k: v for k, v in self.spec.items() if k in STRATEGY_KEYS}
        s = ", ".join(f"{k}={v}" for k, v in keys.items())
        if self.index:
            s += f", index={self.index}"
        return f"{label}({s})" if label else s

    # —— 查找 ——
    def _switch_frame(self, driver) -> None:
        driver.switch_to.default_content()
        if self.frame:
            f = self.frame
            if isinstance(f, int):
                driver.switch_to.frame(f)
            else:
                driver.switch_to.frame(
                    driver.find_element(By.CSS_SELECTOR, str(f))
                )

    def _raw_matches(self, driver) -> List[WebElement]:
        for by, value in self._candidate_expressions():
            try:
                els = driver.find_elements(by, value)
            except Exception:
                continue
            if els:
                return els
        return []

    @staticmethod
    def _pick(els: List[WebElement]) -> WebElement:
        """多个命中时挑最合适的：优先可见，其次 button/a/input，最后取最后一个（最内层）。"""
        visible = []
        for e in els:
            try:
                if e.is_displayed():
                    visible.append(e)
            except Exception:
                continue
        pool = visible or els
        preferred = []
        for e in pool:
            try:
                if (e.tag_name or "").lower() in ("button", "a", "input"):
                    preferred.append(e)
            except Exception:
                continue
        if preferred:
            return preferred[0]
        return pool[-1]

    def find(self, driver, timeout: int = 10, visible: bool = False) -> WebElement:
        """等待元素出现并返回；找不到抛 LocatorError。"""
        self._switch_frame(driver)
        end = time.time() + max(0.5, timeout)
        while time.time() < end:
            els = self._raw_matches(driver)
            if visible:
                els = [e for e in els if _safe_displayed(e)]
            if els:
                if self.index:
                    i = int(self.index) - 1
                    if 0 <= i < len(els):
                        return els[i]
                    raise LocatorError(
                        f"{self.describe()}：index={self.index} 越界（实际匹配 {len(els)} 个）"
                    )
                return self._pick(els)
            time.sleep(0.25)
        raise LocatorError(f"超时未找到元素：{self.describe()}")

    def find_all(self, driver, timeout: int = 10) -> List[WebElement]:
        self._switch_frame(driver)
        end = time.time() + max(0.5, timeout)
        while time.time() < end:
            els = self._raw_matches(driver)
            if els:
                return els
            time.sleep(0.25)
        return []

    def exists(self, driver, timeout: int = 3) -> bool:
        try:
            self.find(driver, timeout=timeout)
            return True
        except Exception:
            return False


def _safe_displayed(e: WebElement) -> bool:
    try:
        return bool(e.is_displayed())
    except Exception:
        return False
