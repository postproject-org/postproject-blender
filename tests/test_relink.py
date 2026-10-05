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

    def test_adapter_returns_its_commit_and_reports_unchanged_save(self):
        from bl_ext.user_default.postproject_relink import production

        path = self.root / "receipt.pproj"
        media = self.root / "receipt.mov"
        media.write_bytes(b"record receipt fixture")
        strip = production.StripMedia("camera", "Camera", (media,))
        first = production.record(
            path,
            [strip],
            new_uuid=lambda: "new",
            blender_version=bpy.app.version_string,
        )
        self.assertIsNotNone(first.receipt.revision)
        self.assertEqual(first.receipt.revision.sequence, 1)
        second = production.record(
            path,
            [strip],
            new_uuid=lambda: "new",
            blender_version=bpy.app.version_string,
        )
        self.assertEqual(second.receipt.production_id, first.receipt.production_id)
        self.assertIsNone(second.receipt.revision)

    def test_confirm_location_uses_scoped_base_and_own_receipt(self):
        import postproject as pp
        from bl_ext.user_default.postproject_relink import production

        path = self.root / "confirm.pproj"
        media = self.root / "camera.mov"
        media.write_bytes(b"confirmation fixture")
        strip = production.StripMedia("camera", "Camera", (media,))
        production.record(path, [strip], new_uuid=lambda: "new", blender_version="test")
        with pp.Production.open(path) as prod, prod.read_session() as view:
            base = view.decision_base
        moved = self.root / "moved.mov"
        shutil.copy2(media, moved)
        receipt = production.confirm_location(
            path, "camera", moved, base=base, blender_version="test"
        )
        self.assertEqual(receipt.production_id, base.production_id)
        self.assertGreater(receipt.revision.sequence, base.revision.sequence)
        competitor = self.root / "competitor.mov"
        shutil.copy2(media, competitor)
        with self.assertRaises(pp.ConflictError):
            production.confirm_location(
                path, "camera", competitor, base=base, blender_version="test"
            )
        with pp.Production.open(path) as prod, prod.read_session() as view:
            current = view.decision_base
        unchanged = production.confirm_location(
            path, "camera", moved, base=current, blender_version="test"
        )
        self.assertIsNone(unchanged.revision)
        with (
            pp.Production.create(self.root / "wrong.pproj") as other,
            other.read_session() as view,
        ):
            wrong = view.decision_base
        with self.assertRaises(pp.InvalidArgumentError):
            production.confirm_location(
                path, "camera", competitor, base=wrong, blender_version="test"
            )
        with pp.Production.open(path) as prod:
            self.assertEqual(prod.latest_revision.id, receipt.revision.id)

    def test_render_record_returns_its_representation_and_commit(self):
        import postproject as pp
        from bl_ext.user_default.postproject_relink import production

        path = self.root / "render-receipt.pproj"
        media = self.root / "source.mov"
        media.write_bytes(b"source fixture")
        production.record(
            path,
            [production.StripMedia("camera", "Camera", (media,))],
            new_uuid=lambda: "new",
            blender_version="test",
        )
        output = self.root / "output.png"
        output.write_bytes(b"render fixture")
        result = production.record_render(
            path,
            ("camera",),
            output,
            blender_version="test",
            facts=production.RenderFacts("Scene", "BLENDER_EEVEE", 1, 3, "PNG"),
        )
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.receipt.revision)
        with pp.Production.open(path) as prod:
            self.assertEqual(
                prod.representation(result.representation_id).kind,
                pp.RepresentationKind.DERIVED,
            )
            self.assertEqual(prod.latest_revision.id, result.receipt.revision.id)

    def test_strip_binding_to_several_assets_is_rejected(self):
        import postproject as pp
        from bl_ext.user_default.postproject_relink import production

        path = self.root / "ambiguous-binding.pproj"
        media = self.root / "binding.mov"
        media.write_bytes(b"binding fixture")
        with (
            pp.Production.create(path) as prod,
            prod.read_session() as view,
            view.edit() as edit,
        ):
            for _ in range(2):
                asset = edit.import_media(media)
                edit.add_external_identifier(
                    pp.AssetRef(asset),
                    pp.ExternalIdentifier(
                        production.APPLICATION_SCHEME,
                        "camera",
                        production.STRIP_QUALIFIER,
                    ),
                )
            receipt = edit.commit()
        strip = production.StripMedia("camera", "Camera", (media,))
        with self.assertRaisesRegex(ValueError, "several logical assets"):
            production.record(
                path,
                [strip],
                new_uuid=lambda: "new",
                blender_version=bpy.app.version_string,
            )
        with pp.Production.open(path) as prod:
            self.assertEqual(prod.latest_revision.id, receipt.revision.id)

    def test_saving_records_media_in_a_sidecar(self):
        movie = make_movie(self.root / "rushes" / "A001.mkv", (1, 0, 0))
        strip = self.editor.strips.new_movie("A001", str(movie), 1, 1)
        self.save()
        self.assertTrue((self.root / "film.pproj").is_file())
        self.assertIsInstance(strip.get("postproject_uuid"), str)

    def test_explicit_shared_production_overrides_the_sidecar(self):
        movie = make_movie(self.root / "rushes" / "A001.mkv", (1, 0, 0))
        self.editor.strips.new_movie("A001", str(movie), 1, 1)
        shared = self.root / "shared" / "documentary.pproj"
        shared.parent.mkdir()
        preferences = bpy.context.preferences.addons[MODULE].preferences
        preferences.production_path = str(shared)
        try:
            self.save()
        finally:
            preferences.production_path = ""
        self.assertTrue(shared.is_file())
        self.assertFalse((self.root / "film.pproj").exists())

    def test_saving_adopts_media_recorded_by_another_host(self):
        movie = make_movie(self.root / "rushes" / "A001.mkv", (1, 0, 0))
        production_path = self.root / "film.pproj"
        import postproject as pp

        with (
            pp.Production.create(production_path, "Shared production") as production,
            production.transaction() as transaction,
        ):
            transaction.set_revision_context(
                pp.RevisionContext(pp.OriginIdentity("Kdenlive", "26.08.1"))
            )
            asset = transaction.import_media(movie, "A001")
            transaction.add_external_identifier(
                pp.AssetRef(asset),
                pp.ExternalIdentifier(
                    "https://postproject.org/id/application",
                    "kdenlive-clip",
                    "org.kde.kdenlive:control_uuid",
                ),
            )
            transaction.commit()

        strip = self.editor.strips.new_movie("A001", str(movie), 1, 1)
        self.save()

        with pp.Production.open(production_path) as production:
            assets = tuple(production.assets)
            self.assertEqual(len(assets), 1)
            identifiers = production.external_identifiers[pp.AssetRef(assets[0].id)]
        self.assertEqual(
            {identifier.qualifier for identifier in identifiers},
            {"org.kde.kdenlive:control_uuid", "org.blender:strip_uuid"},
        )
        self.assertIsInstance(strip["postproject_uuid"], str)

    def test_completed_render_records_observed_provenance(self):
        movie = make_movie(self.root / "rushes" / "A001.mkv", (1, 0, 0))
        self.editor.strips.new_movie("A001", str(movie), 1, 1)
        self.save()
        output = self.root / "renders" / "plate.png"
        output.parent.mkdir()
        self.scene.render.filepath = str(output)
        self.scene.render.image_settings.file_format = "PNG"
        self.scene.render.resolution_x, self.scene.render.resolution_y = 64, 36
        self.scene.render.resolution_percentage = 100
        bpy.ops.render.render(write_still=True, scene=self.scene.name)

        import postproject as pp

        with pp.Production.open(self.root / "film.pproj") as production:
            (asset,) = tuple(production.assets)
            representations = production.representations[asset.id]
            render = next(
                item
                for item in representations
                if item.kind is pp.RepresentationKind.DERIVED
            )
            (activity,) = production.activities_producing[render.id]
            self.assertEqual(activity.kind, "org.blender:render")
            self.assertEqual(len(activity.inputs), 1)
            self.assertEqual(
                production.evaluate_artifact(render.id).state,
                pp.ArtifactKnowledgeState.CURRENT,
            )
            self.assertFalse(
                production.artifact_reproducibility(render.id).reproducible
            )

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
