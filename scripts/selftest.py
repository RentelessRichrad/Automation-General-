"""配置自检：不打开浏览器，检查 profile / pages / cases 是否写对了。

用法：python scripts/selftest.py [--profile demo] [--config-dir config]
有错误时退出码 1（可直接放进 CI 做门禁）。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from webui_auto.config_loader import load_config  # noqa: E402
from webui_auto.schema import validate  # noqa: E402
from webui_auto import __version__  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="配置自检（不启动浏览器）")
    ap.add_argument("--config-dir")
    ap.add_argument("--profile")
    args = ap.parse_args(argv)

    print(f"webui-auto v{__version__} 配置自检")
    try:
        cfg = load_config(config_dir=args.config_dir, profile_name=args.profile)
    except SystemExit as e:
        print(f"[失败] {e}")
        return 1
    except Exception as e:
        print(f"[失败] 配置加载异常：{type(e).__name__}: {e}")
        return 1

    print(f"  profile      : {cfg.profile_name}")
    print(f"  base_url     : {cfg.base_url}")
    print(f"  登录模式     : {(cfg.profile.get('login') or {}).get('mode', 'none')}")
    print(f"  内容容器     : {cfg.content_container}")
    print(f"  页面定义     : {len(cfg.pages)} 个 -> {', '.join(sorted(cfg.pages))}")
    print(f"  用例         : {len(cfg.cases)} 条")
    print(f"  变量         : {', '.join(sorted(cfg.vars)) or '(无)'}")

    errors, warnings = validate(cfg)
    for w in warnings:
        print(f"[提醒] {w}")
    if errors:
        print(f"[错误] 共 {len(errors)} 处：")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("[通过] 配置校验 OK，可以直接跑： python scripts/run.py --profile "
          f"{cfg.profile_name} --tag smoke")
    return 0


if __name__ == "__main__":
    sys.exit(main())
