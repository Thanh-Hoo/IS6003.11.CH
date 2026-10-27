"""Chạy các notebook trên một run bằng nbclient; tương đương `uv run jira-ad notebooks ...`.

Dùng: uv run python scripts/execute_notebooks.py --run-dir outputs/runs/<run_id>
"""

import sys

from jira_ad.cli import main

if __name__ == "__main__":
    sys.exit(main(["notebooks", *sys.argv[1:]]))
