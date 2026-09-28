#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Build the extension against a PostProject checkout and run the tests.
#
#   tools/dev.sh BLENDER POSTPROJECT_CHECKOUT
#
# The platform wheel is tagged linux_x86_64, as it is built for this machine's
# glibc rather than in PostProject's manylinux_2_28 release container.
set -eu
blender=$1
postproject=$(cd "$2" && pwd)
root=$(cd "$(dirname "$0")/.." && pwd)
cargo build --release --locked -p postproject-ffi --manifest-path "$postproject/Cargo.toml"
rm -rf "$root/build/wheel" "$root/dist"
python3 -m pip wheel --no-deps --quiet "$postproject/python" --wheel-dir "$root/build/wheel/neutral"
python3 "$postproject/tools/build_platform_wheel.py" "$root"/build/wheel/neutral/postproject-*.whl \
  "$postproject/target/release/libpostproject.so" linux_x86_64 --output-dir "$root/build/wheel"
python3 "$root/tools/build.py" --blender "$blender" \
  --wheel "$(ls "$root"/build/wheel/postproject-*-linux_x86_64.whl)"
"$root/tools/test.sh" "$blender" "$(ls "$root"/dist/*.zip)"
