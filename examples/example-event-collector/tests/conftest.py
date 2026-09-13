"""このサンプルはワークスペースのメンバーではないため、import 経路を自分で足す。

作者の手元では ``uv sync`` / ``pip install -e .`` でインストール済みになるので、
この conftest は不要である。ここではリポジトリのテストからも実行できるように
置いている。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
