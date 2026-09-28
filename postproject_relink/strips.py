# SPDX-License-Identifier: GPL-3.0-or-later
"""Sequencer strips as the extension sees them."""

from __future__ import annotations

import re
import uuid
from fractions import Fraction
from itertools import pairwise
from pathlib import Path

import bpy

from .production import Sequence, StripMedia

#: The strip's custom property naming the media it uses. It is the only data
#: the extension adds to a .blend file.
UUID_PROPERTY = "postproject_uuid"

_NUMBERED = re.compile(r"^(?P<prefix>.*?)(?P<frame>\d+)(?P<suffix>\D*)$")


def media_strips():
    """Yield every movie, sound, and image strip of every scene, with its scene."""

    for scene in bpy.data.scenes:
        editor = scene.sequence_editor
        if editor is None:
            continue
        for strip in editor.strips_all:
            if strip.type in {"MOVIE", "SOUND", "IMAGE"}:
                yield scene, strip


def ensure_uuid(strip) -> str:
    """Return the strip's media UUID, giving it one first if it has none."""

    value = strip.get(UUID_PROPERTY)
    if not isinstance(value, str):
        value = str(uuid.uuid4())
        strip[UUID_PROPERTY] = value
    return value


def new_uuid() -> str:
    return str(uuid.uuid4())


def strip_media(scene, strip, uuid_value: str) -> StripMedia | None:
    """Describe the files a strip uses, or None for media the pilot skips."""

    if strip.type == "MOVIE":
        return StripMedia(uuid_value, strip.name, (_absolute(strip.filepath),))
    if strip.type == "SOUND":
        sound = strip.sound
        if sound is None or sound.packed_file is not None:
            return None
        return StripMedia(uuid_value, strip.name, (_absolute(sound.filepath, sound),))
    directory = _absolute(strip.directory)
    names = [element.filename for element in strip.elements]
    paths = tuple(directory / name for name in names)
    if len(names) == 1:
        return StripMedia(uuid_value, strip.name, paths)
    sequence = _sequence(directory, names)
    if sequence is None:
        # Frames that are not one numbered sequence are left to Blender.
        return None
    rate = Fraction(scene.render.fps) / Fraction(
        scene.render.fps_base
    ).limit_denominator(1001)
    return StripMedia(
        uuid_value,
        strip.name,
        paths,
        sequence,
        (rate.numerator, rate.denominator),
    )


def relink(paths: dict[Path, Path]) -> int:
    """Point every use of the old paths at the new ones and return how many.

    Paths change through Blender's own path API, which also covers a sound
    strip's sound data-block. A relative path stays relative.
    """

    wanted = {str(old): new for old, new in paths.items()}
    # Rewriting one frame of an image strip also moves the strip's shared
    # directory, so its later frames are visited under the new directory with
    # their old names.
    for old, new in paths.items():
        wanted.setdefault(str(new.parent / old.name), new)
    changed = 0

    def visit(owner, path, _meta):
        nonlocal changed
        new = wanted.get(str(_absolute(path, owner)))
        if new is None:
            return None
        changed += 1
        if path.startswith("//"):
            try:
                return bpy.path.relpath(str(new), start=_library_directory(owner))
            except ValueError:
                pass
        return str(new)

    bpy.data.file_path_foreach(visit)
    if changed:
        _refresh()
    return changed


def _refresh() -> None:
    """Reload relinked media where Blender itself does not.

    Blender 5.3 refreshes the sequencer after its own path search; 5.2 leaves
    the old, missing media loaded until the user refreshes.
    """

    if bpy.app.version >= (5, 3, 0):
        return
    for _scene, strip in media_strips():
        if strip.type == "MOVIE":
            strip.filepath = strip.filepath
        elif strip.type == "IMAGE":
            strip.directory = strip.directory
        elif strip.type == "SOUND" and strip.sound is not None:
            strip.sound.filepath = strip.sound.filepath


def _absolute(path: str, owner=None) -> Path:
    library = getattr(owner, "library", None) if owner is not None else None
    return Path(bpy.path.abspath(path, library=library)).resolve()


def _library_directory(owner) -> str | None:
    library = getattr(owner, "library", None)
    if library is None:
        return None
    return str(Path(bpy.path.abspath(library.filepath)).parent)


def _sequence(directory: Path, names: list[str]) -> Sequence | None:
    matches = [_NUMBERED.match(name) for name in names]
    if not all(matches):
        return None
    prefix, suffix = matches[0]["prefix"], matches[0]["suffix"]
    padding = len(matches[0]["frame"])
    frames = []
    for match in matches:
        if (match["prefix"], match["suffix"], len(match["frame"])) != (
            prefix,
            suffix,
            padding,
        ):
            return None
        frames.append(int(match["frame"]))
    step = frames[1] - frames[0]
    if step <= 0 or any(b - a != step for a, b in pairwise(frames)):
        return None
    return Sequence(directory, prefix, suffix, padding, frames[0], frames[-1], step)
