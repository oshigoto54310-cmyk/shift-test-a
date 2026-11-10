#!/usr/bin/env bash
# フォントはリポジトリに含めない（約23MB）。初回のみ実行して public/fonts に取得する。
set -euo pipefail
cd "$(dirname "$0")/../public/fonts"
base="https://raw.githubusercontent.com"
[ -f NotoSansJP.ttf ]    || curl -fsSL -o NotoSansJP.ttf    "$base/google/fonts/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf"
[ -f NotoSerifJP.ttf ]   || curl -fsSL -o NotoSerifJP.ttf   "$base/google/fonts/main/ofl/notoserifjp/NotoSerifJP%5Bwght%5D.ttf"
[ -f JetBrainsMono.ttf ] || curl -fsSL -o JetBrainsMono.ttf "$base/JetBrains/JetBrainsMono/master/fonts/variable/JetBrainsMono%5Bwght%5D.ttf"
ls -la
