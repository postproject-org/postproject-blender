#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Run the tests in background Blender against a built extension package.
#
#   tools/test.sh BLENDER PACKAGE.zip
set -eu
blender=$1
package=$2
user=$(mktemp -d)
trap 'rm -rf "$user"' EXIT
BLENDER_USER_RESOURCES=$user "$blender" --background --factory-startup \
  --python-exit-code 1 --python "$(dirname "$0")/../tests/test_relink.py" \
  -- "$package"
