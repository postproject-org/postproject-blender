# SPDX-License-Identifier: GPL-3.0-or-later
"""Capture normal Blender save/render/relink writes between two checkpoints.

Run in background Blender with an installed extension; the SDK's separate
process checker verifies the resulting passive mirrors.
"""

import shutil
import sys
from pathlib import Path

import bpy

package, directory = sys.argv[sys.argv.index("--") + 1 :]
root = Path(directory).resolve()
root.mkdir(parents=True, exist_ok=True)
module = "bl_ext.user_default.postproject_relink"
bpy.ops.extensions.package_install_files(
    filepath=str(Path(package).resolve()), repo="user_default", enable_on_install=True
)
bpy.context.preferences.addons[module].preferences.production_path = str(
    root / "authority.pproj"
)

# The wheel becomes importable only after extension installation.
import postproject as pp  # noqa: E402

# Make real media through Blender; no fabricated decoder observations.
bpy.ops.wm.read_homefile(use_empty=True)
scene = bpy.context.scene
scene.render.resolution_x, scene.render.resolution_y = 64, 36
scene.render.resolution_percentage = 100
scene.frame_start, scene.frame_end = 1, 3
editor = scene.sequence_editor_create()
color = editor.strips.new_effect(
    name="fixture", type="COLOR", channel=1, frame_start=1, length=3
)
color.color = (0.25, 0.5, 0.75)
scene.render.image_settings.media_type = "VIDEO"
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MKV"
scene.render.ffmpeg.codec = "FFV1"
scene.render.filepath = str(root / "camera_")
bpy.ops.render.render(animation=True)
movie = next(root.glob("camera_*.mkv"))
editor.strips.remove(color)

with pp.Production.create(root / "authority.pproj", "Blender exchange") as source:
    source.export_checkpoint(root / "initial.ppxc")

strip = editor.strips.new_movie("camera", str(movie), 1, 1)
project = root / "receiving.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(project))
strip_uuid = strip["postproject_uuid"]
with pp.Production.open(root / "authority.pproj") as source:
    with source.read_session() as view:
        assert len(tuple(view.assets())) == 1
    source.export_checkpoint(root / "later.ppxc")

scene.render.image_settings.media_type = "IMAGE"
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = str(root / "render.png")
bpy.ops.render.render(write_still=True)
assert (root / "render.png").is_file()
(root / "moved").mkdir()
moved = root / "moved" / movie.name
shutil.move(movie, moved)
assert bpy.ops.postproject.find_missing_media() == {"FINISHED"}
assert Path(bpy.path.abspath(strip.filepath)) == moved
bpy.ops.wm.save_as_mainfile(filepath=str(project))

with pp.Production.open(root / "authority.pproj") as source:
    with source.read_session() as view:
        (asset,) = tuple(view.assets())
    assert any(
        identifier.qualifier == "org.blender:strip_uuid"
        and identifier.value == strip_uuid
        for identifier in source.external_identifiers[pp.AssetRef(asset.id)]
    )
    derived = next(
        item
        for item in source.representations[asset.id]
        if item.kind is pp.RepresentationKind.DERIVED
    )
    assert source.activities_producing[derived.id][0].kind == "org.blender:render"
    assert (
        source.evaluate_artifact(derived.id).state is pp.ArtifactKnowledgeState.CURRENT
    )
    for name in ("initial", "later"):
        position = pp.Production.validate_checkpoint(root / f"{name}.ppxc")
        source.export_changes(position, root / f"{name}.ppxd")

bpy.ops.preferences.addon_disable(module=module)
bpy.ops.wm.open_mainfile(filepath=str(project))
assert (
    bpy.context.scene.sequence_editor.strips_all["camera"]["postproject_uuid"]
    == strip_uuid
)
print("Blender native save/render/relink captured; plugin-free project reopen passed")
