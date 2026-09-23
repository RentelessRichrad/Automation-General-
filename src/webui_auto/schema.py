"""配置校验：不打开浏览器就能发现"写错了的配置"。

检查项：
1. profile 必填字段（base_url）
2. pages 里每个元素定位是否含有效策略键
3. cases 引用的 page 是否存在
4. cases 里 element: 引用的元素名，在"当前页面"下是否真的有定义
   （会跟随 goto 切换页面，做一次静态推演）
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .locator import STRATEGY_KEYS, META_KEYS


def _is_valid_element_spec(spec: Any) -> Tuple[bool, str]:
    if not isinstance(spec, dict):
        return False, "元素定位必须是字典"
    if not any(k in spec for k in STRATEGY_KEYS):
        return False, f"缺少定位策略键（可用：{', '.join(STRATEGY_KEYS)}）"
    return True, ""


def validate(cfg) -> Tuple[List[str], List[str]]:
    """返回 (errors, warnings)。"""
    errors: List[str] = []
    warnings: List[str] = []

    # 1) profile
    profile = cfg.profile or {}
    if not profile.get("base_url"):
        errors.append("profile 缺少 base_url")
    if not cfg.pages:
        warnings.append("没有加载到任何页面定义（config/pages 为空？）")
    if not cfg.cases:
        warnings.append("没有加载到任何用例（config/cases 为空？）")

    login = profile.get("login") or {}
    mode = (login.get("mode") or "none").lower()
    if mode == "form":
        for f in ("username_field", "password_field", "submit"):
            if not login.get(f):
                errors.append(f"login.mode=form 但缺少 login.{f}")
        cr = login.get("credentials") or {}
        if not (cr.get("username") or cr.get("username_env") or cr.get("username_default")):
            warnings.append("login.credentials 未配置用户名（也无 *_env / *_default 兜底）")

    # 2) pages 元素
    for pname, p in (cfg.pages or {}).items():
        els = p.get("elements") or {}
        if not els:
            warnings.append(f"页面 '{pname}' 没有定义任何元素")
        for ename, spec in els.items():
            ok, msg = _is_valid_element_spec(spec)
            if not ok:
                errors.append(f"页面 '{pname}' 元素 '{ename}' 配置无效：{msg}")
        wf = p.get("wait_for")
        if wf is not None:
            ok, msg = _is_valid_element_spec(wf)
            if not ok:
                errors.append(f"页面 '{pname}' 的 wait_for 配置无效：{msg}")

    # 3) cases：静态推演当前页面，检查元素引用
    for c in cfg.cases:
        cid = c.get("id") or "<无 id>"
        cur = c.get("page")
        if cur and cur not in cfg.pages:
            errors.append(f"用例 {cid}: 引用了不存在的页面 '{cur}'")
            cur = None

        def check_target(t: Any, where: str):
            nonlocal cur
            if not isinstance(t, dict):
                return
            if "element" in t:
                en = t["element"]
                if not cur:
                    errors.append(
                        f"用例 {cid} {where}: 用了 element='{en}' 但没有确定当前页面"
                        "（先写 page: 或 goto: {page: ...}）"
                    )
                elif en not in (cfg.pages.get(cur, {}).get("elements") or {}):
                    errors.append(
                        f"用例 {cid} {where}: 页面 '{cur}' 下没有元素 '{en}'"
                    )

        for st in c.get("steps") or []:
            if not isinstance(st, dict):
                errors.append(f"用例 {cid}: step 不是字典：{st!r}")
                continue
            key = str(list(st.keys())[0]) if st else ""
            body = st.get(key)
            if key == "goto" and isinstance(body, dict) and body.get("page"):
                pg = body["page"]
                if pg not in cfg.pages:
                    errors.append(f"用例 {cid}: goto 引用了不存在的页面 '{pg}'")
                else:
                    cur = pg
                continue
            check_target(body, f"step '{key}'")

        for a in c.get("assertions") or []:
            if not isinstance(a, dict):
                errors.append(f"用例 {cid}: assertion 不是字典：{a!r}")
                continue
            key = str(list(a.keys())[0]) if a else ""
            check_target(a.get(key), f"assertion '{key}'")

        if not c.get("assertions"):
            warnings.append(f"用例 {cid}: 没有任何断言")

    return errors, warnings
