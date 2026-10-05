# SPDX-License-Identifier: GPL-3.0-or-later
"""Drive Blender's normal extension paths in the cross-host scenario."""

import shutil
import sys
from pathlib import Path

import bpy

PACKAGE, ROOT, ACTION = sys.argv[sys.argv.index("--") + 1 :]
ROOT = Path(ROOT).resolve()
MODULE = "bl_ext.user_default.postproject_relink"


def install():
    bpy.ops.extensions.package_install_files(
        filepath=str(Path(PACKAGE).resolve()),
        repo="user_default",
        enable_on_install=True,
    )
    assert MODULE in bpy.context.preferences.addons
    bpy.context.preferences.addons[MODULE].preferences.production_path = str(
        ROOT / "shared.pproj"
    )


def record_and_render():
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    scene.sequence_editor_create().strips.new_movie(
        "camera", str(ROOT / "camera.mkv"), 1, 1
    )
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "blender.blend"))
    strip = scene.sequence_editor.strips_all["camera"]
    assert isinstance(strip["postproject_uuid"], str)

    output = ROOT / "blender-render.png"
    scene.render.filepath = str(output)
    scene.render.image_settings.file_format = "PNG"
    scene.render.resolution_x, scene.render.resolution_y = 64, 36
    scene.render.resolution_percentage = 100
    bpy.ops.render.render(write_still=True, scene=scene.name)
    assert output.is_file()

    import postproject as pp

    with pp.Production.open(ROOT / "shared.pproj") as production:
        (asset,) = tuple(production.assets)
        qualifiers = {
            identifier.qualifier
            for identifier in production.external_identifiers[pp.AssetRef(asset.id)]
        }
        assert qualifiers == {
            "org.kde.kdenlive:control_uuid",
            "org.blender:strip_uuid",
        }
        render = next(
            item
            for item in production.representations[asset.id]
            if item.kind is pp.RepresentationKind.DERIVED
        )
        assert (
            production.evaluate_artifact(render.id).state
            is pp.ArtifactKnowledgeState.CURRENT
        )


def observe_relink():
    bpy.ops.wm.open_mainfile(filepath=str(ROOT / "blender.blend"))
    assert bpy.ops.postproject.find_missing_media() == {"FINISHED"}
    strip = bpy.context.scene.sequence_editor.strips_all["camera"]
    assert Path(bpy.path.abspath(strip.filepath)) == ROOT / "moved" / "camera.mkv"


def win_conflict():
    bpy.ops.wm.open_mainfile(filepath=str(ROOT / "blender.blend"))
    strip = bpy.context.scene.sequence_editor.strips_all["camera"]
    choice = ROOT / "blender-choice.mkv"
    shutil.copy2(ROOT / "moved" / "camera.mkv", choice)
    import postproject as pp

    base = pp.DecisionBase.from_token(
        (ROOT / "decision-base").read_text(encoding="ascii")
    )
    from bl_ext.user_default.postproject_relink import production

    receipt = production.confirm_location(
        ROOT / "shared.pproj",
        strip["postproject_uuid"],
        choice,
        base=base,
        blender_version=bpy.app.version_string,
    )
    assert receipt.production_id == base.production_id
    assert receipt.revision is not None and base.revision is not None
    assert receipt.revision.sequence > base.revision.sequence


install()
{
    "record-render": record_and_render,
    "observe-relink": observe_relink,
    "win-conflict": win_conflict,
}[ACTION]()
