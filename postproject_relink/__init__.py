# SPDX-License-Identifier: GPL-3.0-or-later
"""Relink Video Sequencer media by content through PostProject."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import bpy
from bpy.app.handlers import persistent

# The bundled PostProject platform wheel carries its own native library, which
# the binding loads when given no path. The extension never names one, so a
# newer wheel another extension bundles still brings a matching library.


class PostProjectPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    find_on_load: bpy.props.BoolProperty(
        name="Find Missing Media When Opening",
        description="Run Find Missing Media by Content whenever a file with "
        "missing sequencer media is opened",
        default=False,
    )

    def draw(self, _context):
        self.layout.prop(self, "find_on_load")


class POSTPROJECT_OT_find_missing_media(bpy.types.Operator):
    """Relink missing sequencer media to files with the same content"""

    bl_idname = "postproject.find_missing_media"
    bl_label = "Find Missing Media by Content"
    bl_options: ClassVar[set[str]] = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, _context):
        return bool(bpy.data.filepath)

    def execute(self, _context):
        from . import production, strips

        blend = Path(bpy.data.filepath)
        path = production.production_path(blend, _project_root())
        missing = []
        for scene, strip in strips.media_strips():
            value = strip.get(strips.UUID_PROPERTY)
            if not isinstance(value, str):
                continue
            media = strips.strip_media(scene, strip, value)
            if media is not None and not media.exists():
                missing.append(media)
        if not missing:
            self.report({"INFO"}, "No missing sequencer media")
            return {"CANCELLED"}
        if not path.is_file():
            self.report({"WARNING"}, f"No media recorded in {path.name}")
            return {"CANCELLED"}
        try:
            results = production.find(
                path,
                missing,
                [blend.parent, *_project_directories()],
            )
        except Exception as error:
            self.report({"WARNING"}, f"{path.name} could not be read: {error}")
            return {"CANCELLED"}
        paths = {}
        for result in results:
            paths.update(result.paths)
        strips.relink(paths)
        relinked = {r.uuid for r in results if r.outcome == "relinked"}
        for result in results:
            if result.outcome != "relinked":
                message = f"{result.name}: {result.outcome}"
                if result.detail:
                    message += f" ({result.detail})"
                self.report({"WARNING"}, message)
        left = len({r.uuid for r in results}) - len(relinked)
        self.report(
            {"INFO"}, f"Relinked {len(relinked)} media by content, {left} left missing"
        )
        return {"FINISHED"}


def _project():
    return getattr(bpy.data, "project", None)


def _project_root() -> Path | None:
    project = _project()
    return Path(bpy.path.abspath(project.root_path)) if project else None


def _project_directories() -> list[Path]:
    """Return the project root and every file-path project variable's folder."""

    project = _project()
    if project is None:
        return []
    directories = [Path(bpy.path.abspath(project.root_path))]
    for variable in project.variables:
        if (
            variable.type == "STRING"
            and getattr(variable, "subtype", "") == "FILEPATH"
            and variable.value
        ):
            directories.append(Path(bpy.path.abspath(variable.value)))
    return directories


@persistent
def _record_on_save(filepath="", *_args):
    from . import production, strips

    blend = Path(filepath or bpy.data.filepath)
    media, owners = [], []
    for scene, strip in strips.media_strips():
        item = strips.strip_media(scene, strip, strips.ensure_uuid(strip))
        if item is not None:
            media.append(item)
            owners.append(strip)
    try:
        report = production.record(
            production.production_path(blend, _project_root()),
            media,
            new_uuid=strips.new_uuid,
            blender_version=bpy.app.version_string,
        )
    except Exception as error:
        print(f"PostProject: sequencer media not recorded: {error}")
        return
    for index, value in report.new_uuids.items():
        owners[index][strips.UUID_PROPERTY] = value
    if report.ambiguous:
        print(
            "PostProject: sequencer media matched several assets and was not "
            f"adopted ({len(report.ambiguous)} strips)"
        )


@persistent
def _find_on_load(*_args):
    preferences = bpy.context.preferences.addons.get(__package__)
    if preferences is None or not preferences.preferences.find_on_load:
        return
    if bpy.ops.postproject.find_missing_media.poll():
        bpy.ops.postproject.find_missing_media()


def _menu(self, _context):
    self.layout.operator(POSTPROJECT_OT_find_missing_media.bl_idname)


_CLASSES = (PostProjectPreferences, POSTPROJECT_OT_find_missing_media)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_external_data.append(_menu)
    bpy.app.handlers.save_pre.append(_record_on_save)
    bpy.app.handlers.load_post.append(_find_on_load)


def unregister():
    bpy.app.handlers.load_post.remove(_find_on_load)
    bpy.app.handlers.save_pre.remove(_record_on_save)
    bpy.types.TOPBAR_MT_file_external_data.remove(_menu)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
