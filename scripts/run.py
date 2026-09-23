"""运行入口：python scripts/run.py --profile demo --tag smoke"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from webui_auto.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
