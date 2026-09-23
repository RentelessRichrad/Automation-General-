"""命令行入口：所有运行参数都可在这里覆盖（换站点 = --profile，换地址 = --base-url）。"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Optional

from .config_loader import filter_cases, load_config
from .runner import Runner
from .schema import validate


def _parse_vars(pairs: Optional[List[str]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for p in pairs or []:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="webui-auto",
        description="通用 Web UI 自动化测试框架（配置驱动，换系统只改配置）",
    )
    p.add_argument("--config-dir", help="配置目录（默认 ./config）")
    p.add_argument("--profile", help="站点档案名（config/profiles 下的文件名，如 demo）")
    p.add_argument("--tag", action="append", help="按标签筛选用例，可重复")
    p.add_argument("--id", action="append", help="按用例编号筛选，可重复")
    p.add_argument("--name", action="append", help="按用例名称关键字筛选，可重复")
    p.add_argument("--suite", action="append", help="按套件名筛选，可重复")
    p.add_argument("--var", action="append", metavar="K=V", help="传入变量，用例里用 ${K} 引用")
    p.add_argument("--base-url", help="临时覆盖站点地址")
    p.add_argument("--headless", dest="headless", action="store_true", default=None,
                   help="无界面模式运行")
    p.add_argument("--headed", dest="headless", action="store_false",
                   help="有界面模式运行（可肉眼看到点击过程）")
    p.add_argument("--allow-write", action="store_true",
                   help="放开写操作护栏（配合用例里的 risk: write）")
    p.add_argument("--junit", action="store_true", help="额外产出 JUnit XML（给 CI 用）")
    p.add_argument("--report-dir", default="reports", help="报告输出目录")
    p.add_argument("--list", action="store_true", help="只列出用例，不执行")
    p.add_argument("--dry-run", action="store_true", help="只校验配置和用例引用，不打开浏览器")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    cfg = load_config(
        config_dir=args.config_dir,
        profile_name=args.profile,
        cli_vars=_parse_vars(args.var),
        base_url_override=args.base_url,
    )
    cases = filter_cases(cfg.cases, tags=args.tag, ids=args.id,
                         names=args.name, suites=args.suite)

    # 站点隔离：用例若声明了 profile，只跑与当前档案匹配的（防止 A 站用例跑到 B 站上）
    if cfg.profile_name:
        cases = [c for c in cases
                 if (c.get("_profile") or None) in (None, cfg.profile_name)]

    # —— 只列用例 ——
    if args.list:
        print(f"站点档案：{cfg.profile_name}  地址：{cfg.base_url}")
        print(f"用例共 {len(cases)} 条：")
        for c in cases:
            tags = ",".join(c.get("tags") or [])
            print(f"  {c.get('id'):<12} {c.get('name')}  [{tags}]  page={c.get('page') or '-'}")
        return 0

    # —— 干跑：校验配置 ——
    errors, warnings = validate(cfg)
    for w in warnings:
        print(f"[提醒] {w}")
    if errors:
        print(f"[配置错误] 共 {len(errors)} 处：")
        for e in errors:
            print(f"  - {e}")
        return 1
    if args.dry_run:
        print(f"配置校验通过。站点={cfg.base_url} profile={cfg.profile_name} 将执行 {len(cases)} 条用例。")
        for c in cases:
            print(f"  {c.get('id')}: {c.get('name')}")
        return 0

    if not cases:
        print("没有匹配到任何用例（检查 --tag/--id/--name 筛选条件）")
        return 1

    # —— 实跑 ——
    runner = Runner(cfg, allow_write=args.allow_write, headless=args.headless,
                    report_dir=args.report_dir, junit=args.junit)
    report, paths = runner.run(cases)
    s = report["summary"]
    print(f"共 {s['total']} 条 · 通过 {s['pass']} · 失败 {s['fail']} · 异常 {s['error']} · 通过率 {s['rate']}%")
    print(f"报告: {paths.get('html')}")
    if paths.get("junit"):
        print(f"JUnit: {paths.get('junit')}")
    return 0 if s["fail"] == 0 and s["error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
