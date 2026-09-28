#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Download and unpack a Linux Blender build for the tests.

`5.2.2` is the pinned release; any other value names the newest daily build
of that version, such as `5.3-alpha`. Each download is checked against its
published SHA-256.
"""

import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

RELEASES = {
    "5.2.2": (
        "https://download.blender.org/release/Blender5.2/blender-5.2.2-linux-x64.tar.xz",
        "84098912789dc450e95697c4184fb8a90acbe5111c2ba4aede3fecb57806a168",
    ),
}
DAILY = "https://builder.blender.org/download/daily/?format=json&v=1"
# Blender's servers refuse Python's default user agent.
HEADERS = {
    "User-Agent": "postproject-blender (+https://github.com/postproject-org/postproject-blender)"
}


def fetch(url: str):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS))


def daily(version: str) -> tuple[str, str]:
    number, _, cycle = version.partition("-")
    with fetch(DAILY) as response:
        builds = json.load(response)
    for build in builds:
        if (
            build["platform"] == "linux"
            and build["file_extension"] == "xz"
            and build["version"].startswith(number)
            and build["release_cycle"] == cycle
        ):
            with fetch(build["url"] + ".sha256") as response:
                return build["url"], response.read().decode().split()[0]
    raise SystemExit(f"no daily Linux build of Blender {version}")


def main() -> None:
    version, target = sys.argv[1], Path(sys.argv[2])
    url, sha256 = RELEASES[version] if version in RELEASES else daily(version)
    with tempfile.TemporaryDirectory() as scratch:
        archive = Path(scratch) / "blender.tar.xz"
        with fetch(url) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != sha256:
            raise SystemExit(f"{url}: SHA-256 {digest}, expected {sha256}")
        with tarfile.open(archive) as tar:
            tar.extractall(scratch, filter="tar")
        unpacked = next(p for p in Path(scratch).iterdir() if p.is_dir())
        shutil.rmtree(target, ignore_errors=True)
        shutil.move(unpacked, target)
    print(f"Blender {version} from {url} in {target}")


if __name__ == "__main__":
    main()
