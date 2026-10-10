#!/usr/bin/env bash
# macOS / Linux から共通の Python bootstrap を呼ぶ互換入口。
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec python3 "$script_dir/link_skills.py" "$@"
