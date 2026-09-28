#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the extension for one platform from a PostProject platform wheel.

The platform wheel carries the binding and its native library; Blender
installs it, and the binding loads the library inside it.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "postproject_relink"
#: Blender platform of each wheel platform tag PostProject publishes.
PLATFORMS = {
    "manylinux_2_28_x86_64": "linux-x64",
    "linux_x86_64": "linux-x64",
    "macosx_11_0_arm64": "macos-arm64",
    "win_amd64": "windows-x64",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--blender", required=True, type=Path, help="Blender executable"
    )
    parser.add_argument(
        "--wheel", required=True, type=Path, help="postproject platform wheel"
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    platform = PLATFORMS[args.wheel.stem.rsplit("-", 1)[1]]

    stage = ROOT / "build" / platform / PACKAGE.name
    shutil.rmtree(stage.parent, ignore_errors=True)
    shutil.copytree(PACKAGE, stage, ignore=shutil.ignore_patterns("__pycache__"))
    (stage / "wheels").mkdir()
    shutil.copy2(args.wheel, stage / "wheels" / args.wheel.name)
    manifest = stage / "blender_manifest.toml"
    text = manifest.read_text(encoding="utf-8")
    header, _, tables = text.partition("\n[")
    header += f'\nplatforms = ["{platform}"]\nwheels = ["./wheels/{args.wheel.name}"]\n'
    manifest.write_text(f"{header}\n[{tables}", encoding="utf-8")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    return subprocess.call(
        [
            str(args.blender),
            "--factory-startup",
            "--command",
            "extension",
            "build",
            "--source-dir",
            str(stage),
            "--output-dir",
            str(args.output_dir),
            "--split-platforms",
        ]
    )


if __name__ == "__main__":
    sys.exit(main())
