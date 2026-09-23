"""登录策略：一个站点一种登录方式，全部由 profile.login 参数化。

支持五种模式：
  none    —— 无需登录
  cookie  —— 直接复用已保存的 cookie
  form    —— 表单登录（填用户名/密码 → 点登录按钮）
  oauth   —— 同表单，但提交后会跳转到外部认证再跳回（等待更久）
  steps   —— 自定义步骤（复用通用动作引擎，适合验证码/多步登录等复杂场景）
"""
from __future__ import annotations

import time
from typing import Any, Dict

from selenium.webdriver.support.ui import WebDriverWait

from .browser import load_cookies, save_cookies
from .locator import Locator, LocatorError


def _full_url(cfg, url: str) -> str:
    url = str(url or "/")
    if url.startswith("http"):
        return url
    return cfg.base_url + "/" + url.lstrip("/")


def _wait_success(driver, login_cfg: Dict[str, Any], cfg, timeout: int) -> bool:
    """按 login.success 判定登录是否成功。"""
    succ = login_cfg.get("success") or {}
    if not succ:
        time.sleep(1.0)
        return True

    if succ.get("url_contains"):
        want = str(succ["url_contains"])
        try:
            WebDriverWait(driver, timeout).until(lambda d: want in d.current_url)
            return True
        except Exception:
            return False

    if succ.get("element"):
        try:
            Locator(succ["element"], name="登录成功标志").find(
                driver, timeout=timeout, visible=True
            )
            return True
        except LocatorError:
            return False

    if succ.get("text_contains"):
        want = str(succ["text_contains"])
        try:
            WebDriverWait(driver, timeout).until(lambda d: want in (d.page_source or ""))
            return True
        except Exception:
            return False
    return True


def login(driver, cfg) -> Dict[str, Any]:
    """执行登录，返回描述字典（不会抛异常，失败体现在 ok=False）。"""
    login_cfg = (cfg.profile.get("login") or {})
    mode = str(login_cfg.get("mode") or "none").lower()
    timeout = cfg.timeout("element", 10)
    base = cfg.base_url

    if mode == "none":
        return {"mode": "none", "ok": True, "detail": "该站点无需登录"}

    if mode == "cookie":
        cf = login_cfg.get("cookie_file") or "state/cookies.json"
        ok = load_cookies(driver, cf, base)
        try:
            driver.get(base)
        except Exception:
            pass
        return {
            "mode": "cookie", "ok": ok,
            "detail": f"复用 cookie 文件 {cf}" if ok else f"cookie 文件不存在或注入失败：{cf}",
        }

    if mode == "steps":
        from .actions import Actions  # 延迟导入，避免循环依赖
        acts = Actions(driver, cfg)
        detail_parts = []
        ok = True
        for st in login_cfg.get("steps") or []:
            r = acts.run(st)
            detail_parts.append(f"{r.get('action')}:{r.get('status')}")
            if r.get("status") not in ("ok", "skipped"):
                ok = False
                break
        if ok and login_cfg.get("cookie_file"):
            save_cookies(driver, login_cfg["cookie_file"])
        return {"mode": "steps", "ok": ok, "detail": "自定义登录步骤 -> " + "; ".join(detail_parts)}

    if mode in ("form", "oauth"):
        if mode == "oauth":
            timeout = max(timeout, int(login_cfg.get("oauth_timeout", 30)))
        url = login_cfg.get("url") or "/login"
        try:
            driver.get(_full_url(cfg, url))
        except Exception as e:
            return {"mode": mode, "ok": False, "detail": f"打开登录页失败：{e}"}

        username = cfg.vars.get("username", "")
        password = cfg.vars.get("password", "")
        if not username and login_cfg.get("require_credentials", True):
            return {"mode": mode, "ok": False, "detail": "没有取到账号（检查 credentials 配置或 --var）"}

        try:
            uel = Locator(login_cfg["username_field"], name="用户名").find(
                driver, timeout=timeout, visible=True)
            uel.clear()
            uel.send_keys(str(username))

            pel = Locator(login_cfg["password_field"], name="密码").find(
                driver, timeout=timeout, visible=True)
            pel.clear()
            pel.send_keys(str(password))

            Locator(login_cfg["submit"], name="登录按钮").find(
                driver, timeout=timeout, visible=True).click()
        except LocatorError as e:
            return {"mode": mode, "ok": False, "detail": f"登录表单元素定位失败：{e}"}
        except Exception as e:
            return {"mode": mode, "ok": False, "detail": f"登录过程异常：{e}"}

        ok = _wait_success(driver, login_cfg, cfg, timeout)
        if ok and login_cfg.get("cookie_file"):
            save_cookies(driver, login_cfg["cookie_file"])
        return {
            "mode": mode, "ok": ok,
            "detail": ("登录成功，已保存 cookie" if ok
                       else f"登录失败：未满足成功条件 {login_cfg.get('success')}（当前 {driver.current_url}）"),
        }

    return {"mode": mode, "ok": False, "detail": f"不支持的登录模式：{mode}"}
