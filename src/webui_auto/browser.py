"""浏览器工厂：启动 Chrome、处理代理、cookie 存取（全部由 profile 参数驱动）。"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from selenium import webdriver
from selenium.webdriver.chrome.options import Options


def _bypass_local_proxy() -> None:
    """本机代理会截走 chromedriver 与浏览器的通信，这里放行本地回环地址。"""
    add = "localhost,127.0.0.1,::1"
    cur = os.environ.get("NO_PROXY", "") or os.environ.get("no_proxy", "")
    val = add if not cur else (cur.rstrip(",") + "," + add)
    os.environ["NO_PROXY"] = val
    os.environ["no_proxy"] = val


# 必须在页面任何脚本运行之前注入：window 捕获阶段、全页第一个注册的点击计数器。
# Selenium 原生 click 走 CDP 输入管线，实测会**静默丢失**——WebDriver 不报错，
# 页面上却一个 click 事件都没收到（连"最先注册"的监听都收不到，说明事件根本没投递）。
# 有了这个计数器，动作层才能可靠判断"这次点击到底有没有送达"，没送达就走 DOM 兜底。
_INPUT_SENTINEL = """
if (!window.__wbInputSentinel) {
  window.__wbInputSentinel = true;
  window.__wbClicks = 0;
  window.addEventListener('click', function () { window.__wbClicks++; }, true);
}
"""


def _install_input_sentinel(driver) -> None:
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument", {"source": _INPUT_SENTINEL})
    except Exception:
        # 拿不到 CDP 时动作层退化为"总是 DOM 兜底"，行为仍正确，只是少了验证
        pass


def create_driver(profile: Dict[str, Any], headless_override=None):
    """按 profile.browser 启动浏览器。"""
    b = profile.get("browser") or {}
    t = profile.get("timeouts") or {}

    headless = b.get("headless", True)
    if headless_override is not None:
        headless = headless_override

    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    ws = b.get("window_size")
    if ws:
        opts.add_argument(f"--window-size={ws}")
    else:
        opts.add_argument("--window-size=1920,1080")
    if b.get("user_agent"):
        opts.add_argument(f"--user-agent={b['user_agent']}")
    for a in b.get("extra_args") or []:
        opts.add_argument(str(a))

    # 稳定性参数（容器/沙箱里常见需求）
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--hide-scrollbars")
    opts.add_argument("--mute-audio")

    # 打开日志采集，供 no_console_error / no_http_error 断言使用
    opts.set_capability("goog:loggingPrefs", {"browser": "ALL", "performance": "ALL"})

    _bypass_local_proxy()

    driver = webdriver.Chrome(options=opts)
    _install_input_sentinel(driver)
    try:
        driver.set_page_load_timeout(int(t.get("page_load", 30)))
    except Exception:
        pass
    try:
        driver.set_script_timeout(int(t.get("script", 20)))
    except Exception:
        pass
    if not headless:
        try:
            driver.maximize_window()
        except Exception:
            pass
    return driver


def save_cookies(driver, path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(driver.get_cookies(), f, ensure_ascii=False)
    except Exception:
        pass


def load_cookies(driver, path: str, base_url: str) -> bool:
    """注入 cookie（必须先访问同域页面）。"""
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            cookies: List[Dict[str, Any]] = json.load(f)
    except Exception:
        return False
    try:
        driver.get(base_url)
    except Exception:
        pass
    ok = False
    for c in cookies:
        try:
            c.pop("expiry", None)
            c.pop("sameSite", None)
            driver.add_cookie(c)
            ok = True
        except Exception:
            continue
    return ok
