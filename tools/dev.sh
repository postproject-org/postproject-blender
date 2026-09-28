#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Build the extension against a PostProject checkout and run the tests.
#
#   tools/dev.sh BLENDER POSTPROJECT_CHECKOUT
set -eu
blender=$1
postproject=$(cd "$2" && pwd)
root=$(cd "$(dirname "$0")/.." && pwd)
cargo build --release --locked -p postproject-ffi --manifest-path "$postproject/Cargo.toml"
rm -rf "$root/build/wheel" "$root/dist"
python3 -m pip wheel --no-deps --quiet "$postproject/python" --wheel-dir "$root/build/wheel"
python3 "$root/tools/build.py" --blender "$blender" \
  --wheel "$(ls "$root"/build/wheel/postproject-*.whl)" \
  --library "$postproject/target/release/libpostproject.so" --platform linux-x64
"$root/tools/test.sh" "$blender" "$(ls "$root"/dist/*.zip)"
