#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the extension for one platform from PostProject release artifacts.

The extension bundles the platform-neutral `postproject` wheel and the native
library for its platform; Blender installs the wheel and the package passes
the library's path to the binding.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "postproject_relink"
LIBRARIES = {
    "linux-x64": "libpostproject.so",
    "macos-arm64": "libpostproject.dylib",
    "macos-x64": "libpostproject.dylib",
    "windows-x64": "postproject.dll",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", required=True, type=Path, help="Blender executable")
    parser.add_argument("--wheel", required=True, type=Path, help="postproject wheel")
    parser.add_argument(
        "--library", required=True, type=Path, help="PostProject shared library"
    )
    parser.add_argument("--platform", required=True, choices=sorted(LIBRARIES))
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()

    stage = ROOT / "build" / args.platform / PACKAGE.name
    shutil.rmtree(stage.parent, ignore_errors=True)
    shutil.copytree(PACKAGE, stage, ignore=shutil.ignore_patterns("__pycache__"))
    (stage / "wheels").mkdir()
    shutil.copy2(args.wheel, stage / "wheels" / args.wheel.name)
    (stage / "lib").mkdir()
    shutil.copy2(args.library, stage / "lib" / LIBRARIES[args.platform])
    manifest = stage / "blender_manifest.toml"
    text = manifest.read_text(encoding="utf-8")
    header, _, tables = text.partition("\n[")
    header += (
        f'\nplatforms = ["{args.platform}"]\n'
        f'wheels = ["./wheels/{args.wheel.name}"]\n'
    )
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
