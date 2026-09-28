# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the installed extension in background Blender.

Run through tools/test.sh, which passes the extension package after `--`.
"""

import os
import shutil
import struct
import sys
import tempfile
import unittest
import wave
import zlib
from pathlib import Path

import bpy

PACKAGE = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
MODULE = "bl_ext.user_default.postproject_relink"


def install():
    bpy.ops.extensions.package_install_files(
        filepath=str(PACKAGE), repo="user_default", enable_on_install=True
    )
    assert MODULE in bpy.context.preferences.addons, "extension did not install"


def absolute(path: str) -> Path:
    return Path(bpy.path.abspath(path))


def make_movie(path: Path, color) -> Path:
    """Render a three-frame FFV1 movie of one colour through the sequencer."""

    scene = bpy.data.scenes.new("render")
    scene.render.resolution_x, scene.render.resolution_y = 64, 36
    scene.render.resolution_percentage = 100
    scene.frame_start, scene.frame_end = 1, 3
    strip = scene.sequence_editor_create().strips.new_effect(
        name="color", type="COLOR", channel=1, frame_start=1, length=3
    )
    strip.color = color
    scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MKV"
    scene.render.ffmpeg.codec = "FFV1"
    out = path.parent / "render_"
    scene.render.filepath = str(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.render.render(animation=True, scene=scene.name)
    bpy.data.scenes.remove(scene)
    rendered = next(path.parent.glob("render_*"))
    rendered.rename(path)
    return path


def make_frames(directory: Path, prefix: str, count: int) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for frame in range(1, count + 1):
        path = directory / f"{prefix}{frame:04d}.png"
        path.write_bytes(png(16, 16, os.urandom(16 * 16 * 3)))
        paths.append(path)
    return paths


def png(width: int, height: int, rgb: bytes) -> bytes:
    """Encode 8-bit RGB pixels as a PNG image."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(
        b"\0" + rgb[row * width * 3 : (row + 1) * width * 3] for row in range(height)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def make_sound(path: Path, seed: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(struct.pack("<800h", *((i * seed) % 30000 for i in range(800))))
    return path


class RelinkTest(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_homefile(use_empty=True)
        self.root = Path(tempfile.mkdtemp())
        self.blend = self.root / "film.blend"
        self.scene = bpy.context.scene
        self.editor = self.scene.sequence_editor_create()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def save_and_reopen(self):
        bpy.ops.wm.save_as_mainfile(filepath=str(self.blend))
        bpy.ops.wm.open_mainfile(filepath=str(self.blend))
        self.scene = bpy.context.scene
        self.editor = self.scene.sequence_editor

    def save(self):
        bpy.ops.wm.save_as_mainfile(filepath=str(self.blend))

    def reopen(self):
        bpy.ops.wm.open_mainfile(filepath=str(self.blend))
        self.scene = bpy.context.scene
        self.editor = self.scene.sequence_editor

    def strip_named(self, name):
        return self.editor.strips_all[name]

    def find(self):
        return bpy.ops.postproject.find_missing_media()

    def test_saving_records_media_in_a_sidecar(self):
        movie = make_movie(self.root / "rushes" / "A001.mkv", (1, 0, 0))
        strip = self.editor.strips.new_movie("A001", str(movie), 1, 1)
        self.save()
        self.assertTrue((self.root / "film.pproj").is_file())
        self.assertIsInstance(strip.get("postproject_uuid"), str)

    def test_renamed_movie_is_relinked_by_content(self):
        movie = make_movie(self.root / "rushes" / "A001.mkv", (1, 0, 0))
        make_movie(self.root / "rushes" / "B001.mkv", (0, 1, 0))
        self.editor.strips.new_movie("A001", str(movie), 1, 1)
        self.save()
        graded = self.root / "graded" / "A001-graded.mkv"
        graded.parent.mkdir()
        movie.rename(graded)
        self.reopen()
        self.assertEqual(self.find(), {"FINISHED"})
        self.assertEqual(absolute(self.strip_named("A001").filepath), graded)

    def test_relative_path_stays_relative(self):
        movie = make_movie(self.root / "rushes" / "A001.mkv", (1, 0, 0))
        strip = self.editor.strips.new_movie("A001", str(movie), 1, 1)
        self.save()
        strip.filepath = "//rushes/A001.mkv"
        self.save()
        day = self.root / "rushes" / "day1"
        day.mkdir()
        movie.rename(day / "A001-day1.mkv")
        self.reopen()
        self.find()
        self.assertEqual(
            self.strip_named("A001").filepath, "//rushes/day1/A001-day1.mkv"
        )

    # PostProject finds a moved sequence only under its recorded file names.
    @unittest.expectedFailure
    def test_renamed_image_sequence_is_relinked_as_a_whole(self):
        frames = make_frames(self.root / "plates", "shot_", 3)
        strip = self.editor.strips.new_image("plate", str(frames[0]), 1, 1)
        for frame in frames[1:]:
            strip.elements.append(frame.name)
        self.save()
        graded = self.root / "graded"
        graded.mkdir()
        for frame in frames:
            frame.rename(graded / frame.name.replace("shot_", "shot-graded_"))
        self.reopen()
        self.find()
        strip = self.strip_named("plate")
        self.assertEqual(absolute(strip.directory), graded)
        self.assertEqual(
            [element.filename for element in strip.elements],
            ["shot-graded_0001.png", "shot-graded_0002.png", "shot-graded_0003.png"],
        )

    def test_moved_image_sequence_is_relinked_as_a_whole(self):
        frames = make_frames(self.root / "plates", "shot_", 3)
        strip = self.editor.strips.new_image("plate", str(frames[0]), 1, 1)
        for frame in frames[1:]:
            strip.elements.append(frame.name)
        self.save()
        moved = self.root / "day1" / "plates"
        shutil.move(self.root / "plates", moved)
        self.reopen()
        self.find()
        self.assertEqual(absolute(self.strip_named("plate").directory), moved)

    def test_incomplete_sequence_is_not_relinked(self):
        frames = make_frames(self.root / "plates", "shot_", 3)
        strip = self.editor.strips.new_image("plate", str(frames[0]), 1, 1)
        for frame in frames[1:]:
            strip.elements.append(frame.name)
        self.save()
        moved = self.root / "day1"
        moved.mkdir()
        for frame in frames[:2]:
            frame.rename(moved / frame.name)
        frames[2].unlink()
        self.reopen()
        self.find()
        self.assertEqual(
            absolute(self.strip_named("plate").directory), self.root / "plates"
        )

    def test_identical_copies_are_left_to_the_user(self):
        movie = make_movie(self.root / "rushes" / "A001.mkv", (1, 0, 0))
        self.editor.strips.new_movie("A001", str(movie), 1, 1)
        self.save()
        for card in ("card1", "card2"):
            (self.root / card).mkdir()
            shutil.copy2(movie, self.root / card / "A001.mkv")
        movie.unlink()
        self.reopen()
        self.find()
        self.assertEqual(absolute(self.strip_named("A001").filepath), movie)

    def test_different_file_with_the_same_name_is_not_taken(self):
        movie = make_movie(self.root / "rushes" / "A001.mkv", (1, 0, 0))
        self.editor.strips.new_movie("A001", str(movie), 1, 1)
        self.save()
        movie.unlink()
        make_movie(self.root / "other" / "A001.mkv", (0, 0, 1))
        self.reopen()
        self.find()
        self.assertEqual(absolute(self.strip_named("A001").filepath), movie)

    def test_sound_strip_and_its_sound_are_relinked(self):
        sound = make_sound(self.root / "audio" / "voice.wav", 3)
        self.editor.strips.new_sound("voice", str(sound), 2, 1)
        self.save()
        moved = self.root / "audio" / "final" / "voice-final.wav"
        moved.parent.mkdir()
        sound.rename(moved)
        self.reopen()
        self.find()
        self.assertEqual(absolute(self.strip_named("voice").sound.filepath), moved)

    def test_cut_strips_share_their_media(self):
        movie = make_movie(self.root / "rushes" / "A001.mkv", (1, 0, 0))
        strip = self.editor.strips.new_movie("A001", str(movie), 1, 1)
        self.save()
        copy = strip.split(frame=2, split_method="SOFT")
        self.save()
        self.assertEqual(copy["postproject_uuid"], strip["postproject_uuid"])
        moved = self.root / "moved.mkv"
        movie.rename(moved)
        self.reopen()
        self.find()
        self.assertEqual(
            {absolute(s.filepath) for s in self.editor.strips_all}, {moved}
        )

    def test_duplicate_given_other_media_gets_its_own_uuid(self):
        movie = make_movie(self.root / "rushes" / "A001.mkv", (1, 0, 0))
        other = make_movie(self.root / "rushes" / "B001.mkv", (0, 1, 0))
        strip = self.editor.strips.new_movie("A001", str(movie), 1, 1)
        self.save()
        copy = self.editor.strips.new_movie("B001", str(other), 2, 10)
        copy["postproject_uuid"] = strip["postproject_uuid"]
        self.save()
        self.assertNotEqual(copy["postproject_uuid"], strip["postproject_uuid"])
        self.reopen()
        self.assertNotEqual(
            self.strip_named("B001")["postproject_uuid"],
            self.strip_named("A001")["postproject_uuid"],
        )

    def test_missing_sidecar_changes_nothing(self):
        movie = make_movie(self.root / "rushes" / "A001.mkv", (1, 0, 0))
        self.editor.strips.new_movie("A001", str(movie), 1, 1)
        self.save()
        (self.root / "film.pproj").unlink()
        movie.rename(self.root / "moved.mkv")
        self.reopen()
        self.assertEqual(self.find(), {"CANCELLED"})
        self.assertEqual(absolute(self.strip_named("A001").filepath), movie)

    def test_unreadable_sidecar_changes_nothing(self):
        movie = make_movie(self.root / "rushes" / "A001.mkv", (1, 0, 0))
        self.editor.strips.new_movie("A001", str(movie), 1, 1)
        self.save()
        (self.root / "film.pproj").write_bytes(b"not a production")
        movie.rename(self.root / "moved.mkv")
        self.reopen()
        self.assertEqual(self.find(), {"CANCELLED"})
        self.assertEqual(absolute(self.strip_named("A001").filepath), movie)

    def test_find_on_load_when_enabled(self):
        movie = make_movie(self.root / "rushes" / "A001.mkv", (1, 0, 0))
        self.editor.strips.new_movie("A001", str(movie), 1, 1)
        self.save()
        moved = self.root / "moved.mkv"
        movie.rename(moved)
        preferences = bpy.context.preferences.addons[MODULE].preferences
        preferences.find_on_load = True
        try:
            self.reopen()
        finally:
            preferences.find_on_load = False
        self.assertEqual(absolute(self.strip_named("A001").filepath), moved)

    def test_nothing_runs_on_load_by_default(self):
        movie = make_movie(self.root / "rushes" / "A001.mkv", (1, 0, 0))
        self.editor.strips.new_movie("A001", str(movie), 1, 1)
        self.save()
        movie.rename(self.root / "moved.mkv")
        self.reopen()
        self.assertEqual(absolute(self.strip_named("A001").filepath), movie)


@unittest.skipUnless(bpy.app.version >= (5, 3, 0), "Blender projects need 5.3")
class ProjectTest(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_homefile(use_empty=True)
        self.root = Path(tempfile.mkdtemp())
        self.project = self.root / "documentary"
        self.storage = self.root / "old-storage"
        self.write_project(self.storage)
        self.blend = self.project / "edit" / "film.blend"
        self.blend.parent.mkdir(parents=True)

    def tearDown(self):
        bpy.ops.wm.read_homefile(use_empty=True)
        shutil.rmtree(self.root, ignore_errors=True)

    def write_project(self, footage: Path):
        config = self.project / ".blender_project" / "project.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            "schema_version = 1\n"
            'name = "Documentary"\n'
            "[[variables]]\n"
            'name = "footage"\n'
            'type = "STRING"\n'
            'subtype = "FILEPATH"\n'
            f"value = {str(footage)!r}\n",
            encoding="utf-8",
        )

    def test_media_moved_to_new_storage_is_found_through_a_project_variable(self):
        movie = make_movie(self.storage / "A001.mkv", (1, 0, 0))
        bpy.ops.wm.save_as_mainfile(filepath=str(self.blend))
        self.assertIsNotNone(bpy.data.project)
        editor = bpy.context.scene.sequence_editor_create()
        editor.strips.new_movie("A001", str(movie), 1, 1)
        bpy.ops.wm.save_as_mainfile(filepath=str(self.blend))
        self.assertTrue((self.project / "postproject.pproj").is_file())
        self.assertFalse(self.blend.with_suffix(".pproj").exists())
        new_storage = self.root / "new-storage"
        (new_storage / "day1").mkdir(parents=True)
        movie.rename(new_storage / "day1" / "A001-day1.mkv")
        shutil.rmtree(self.storage)
        self.write_project(new_storage)
        bpy.ops.wm.read_homefile(use_empty=True)
        bpy.ops.wm.open_mainfile(filepath=str(self.blend))
        bpy.ops.postproject.find_missing_media()
        strip = bpy.context.scene.sequence_editor.strips_all["A001"]
        self.assertEqual(
            absolute(strip.filepath), new_storage / "day1" / "A001-day1.mkv"
        )


class DisabledTest(unittest.TestCase):
    def test_disabled_extension_leaves_blender_unchanged(self):
        bpy.ops.preferences.addon_disable(module=MODULE)
        try:
            bpy.ops.wm.read_homefile(use_empty=True)
            root = Path(tempfile.mkdtemp())
            movie = make_movie(root / "A001.mkv", (1, 0, 0))
            strip = bpy.context.scene.sequence_editor_create().strips.new_movie(
                "A001", str(movie), 1, 1
            )
            bpy.ops.wm.save_as_mainfile(filepath=str(root / "film.blend"))
            self.assertFalse((root / "film.pproj").exists())
            self.assertNotIn("postproject_uuid", strip.keys())
            self.assertFalse(hasattr(bpy.types, "POSTPROJECT_OT_find_missing_media"))
            shutil.rmtree(root)
        finally:
            bpy.ops.preferences.addon_enable(module=MODULE)


def main():
    install()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


main()
