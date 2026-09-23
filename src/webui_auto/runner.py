"""执行器：登录一次 → 逐条跑用例 → 收集每步操作与每个断言的结果 → 出报告。"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from .actions import Actions
from .assertions import Assertions
from .auth import login
from .browser import create_driver
from .report import write_junit, write_report


class Runner:
    def __init__(self, cfg, allow_write: bool = False, headless=None,
                 report_dir: str = "reports", screenshot_dir: str = "screenshots",
                 junit: bool = False):
        self.cfg = cfg
        self.allow_write = allow_write
        self.headless = headless
        self.report_dir = report_dir
        self.screenshot_dir = screenshot_dir
        self.junit = junit
        self.driver = None
        self.actions: Optional[Actions] = None
        self.assertions: Optional[Assertions] = None
        self.login_info: Dict[str, Any] = {"mode": "none", "ok": True, "detail": ""}

    # ————————————————— 生命周期 —————————————————
    def start(self) -> None:
        self.driver = create_driver(self.cfg.profile, self.headless)
        self.actions = Actions(self.driver, self.cfg, self.allow_write, self.screenshot_dir)
        self.assertions = Assertions(self.driver, self.cfg)
        self.login_info = login(self.driver, self.cfg)

    def close(self) -> None:
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass

    # ————————————————— 单条用例 —————————————————
    def run_case(self, case: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.time()
        res: Dict[str, Any] = {
            "id": case.get("id", "-"),
            "name": case.get("name", ""),
            "tags": case.get("tags") or [],
            "suite": case.get("_suite"),
            "steps": [],
            "assertions": [],
            "status": "pass",
            "error": "",
            "elapsed": 0,
        }

        # 登录失败：整条用例直接判异常，原因写清楚
        if not self.login_info.get("ok", True):
            res["status"] = "error"
            res["error"] = f"登录失败（{self.login_info.get('mode')}）：{self.login_info.get('detail')}"
            res["elapsed"] = round(time.time() - t0, 2)
            return res

        page = case.get("page")
        try:
            # ① 起始页面
            if page:
                r = self.actions.goto({"page": page})
                res["steps"].append({"action": "goto", "detail": r.get("detail"),
                                     "status": r.get("status"), "elapsed": 0})
                if r.get("status") in ("fail", "error"):
                    res["status"] = "error"
                    res["error"] = r.get("detail", "打开起始页面失败")
                    res["elapsed"] = round(time.time() - t0, 2)
                    return res

            # ② 操作步骤
            for st in case.get("steps") or []:
                rr = self.actions.run(st)
                res["steps"].append(rr)
                if rr.get("status") in ("fail", "error"):
                    res["status"] = "error" if rr.get("status") == "error" else "fail"
                    res["error"] = rr.get("detail", "")
                    break

            # ③ 断言（步骤没挂才跑）
            if res["status"] == "pass":
                for a in case.get("assertions") or []:
                    res["assertions"].append(
                        self.assertions.run(a, page=self.actions.current_page)
                    )
        except Exception as ex:
            res["status"] = "error"
            res["error"] = f"{type(ex).__name__}: {ex}"

        # ④ 判定
        if res["status"] == "pass":
            if any(not a.get("ok") for a in res["assertions"]):
                res["status"] = "fail"

        res["elapsed"] = round(time.time() - t0, 2)

        # 失败留证
        if res["status"] != "pass" and self.driver:
            try:
                os.makedirs(self.screenshot_dir, exist_ok=True)
                p = os.path.join(self.screenshot_dir, f"{res['id']}_{int(time.time())}.png")
                self.driver.save_screenshot(p)
                res["screenshot"] = p
            except Exception:
                pass
        return res

    # ————————————————— 批量执行 —————————————————
    def run(self, cases: List[Dict[str, Any]]) -> tuple:
        t0 = time.time()
        started = datetime.now()
        results: List[Dict[str, Any]] = []

        try:
            self.start()
        except Exception as ex:
            msg = f"浏览器启动失败：{type(ex).__name__}: {ex}"
            self.login_info = {"mode": "-", "ok": False, "detail": msg}
            for c in cases:
                results.append({
                    "id": c.get("id", "-"), "name": c.get("name", ""),
                    "tags": c.get("tags") or [], "suite": c.get("_suite"),
                    "steps": [], "assertions": [], "status": "error",
                    "error": msg, "elapsed": 0,
                })
        else:
            try:
                for c in cases:
                    results.append(self.run_case(c))
            finally:
                self.close()

        total = len(results)
        p = sum(1 for r in results if r["status"] == "pass")
        f = sum(1 for r in results if r["status"] == "fail")
        e = sum(1 for r in results if r["status"] == "error")
        summary = {
            "total": total, "pass": p, "fail": f, "error": e,
            "rate": (round(p / total * 100, 1) if total else 0.0),
            "elapsed": round(time.time() - t0, 2),
        }
        report = {
            "meta": {
                "profile": self.cfg.profile_name,
                "base_url": self.cfg.base_url,
                "browser": ("headless" if (self.cfg.profile.get("browser") or {}).get("headless", True) else "headed"),
                "started": started.strftime("%Y-%m-%d %H:%M:%S"),
                "stamp": started.strftime("%Y%m%d_%H%M%S"),
                "login": self.login_info,
            },
            "summary": summary,
            "results": results,
        }
        paths = write_report(report, self.report_dir)
        if self.junit:
            paths["junit"] = write_junit(report, self.report_dir)
        return report, paths
