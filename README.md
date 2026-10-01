# PostProject Blender pilot

An experimental Blender extension that relinks missing Video Sequencer media by
content through [PostProject](https://postproject.org). Blender's *Find
Missing Files* compares file names only: it cannot find a renamed file, and of
several files with the same name it takes the largest. *Find Missing Media by
Content* finds a movie, sound, or image sequence that was renamed or moved, and
relinks it only when exactly one file has the recorded content.

The extension changes nothing in Blender. The [per-target brief](BRIEF.md)
records Blender's behavior, checked against its source for 5.2.2 and 5.3
alpha. What the pilot taught PostProject is recorded in PostProject's
[`docs/release-0.4-integration-findings.md`](https://github.com/postproject-org/postproject/blob/main/docs/release-0.4-integration-findings.md).
This is not a Blender project, and nothing here has been proposed to or
reviewed by Blender's developers.

## What it does

- On every save, the extension records the files of each movie, sound, and
  image strip in a PostProject production. Inside a Blender 5.3 project it
  uses `postproject.pproj` at the project root, shared by every `.blend` file
  of the project; otherwise it uses a sidecar `film.pproj` next to
  `film.blend`.
- *Production file* in the extension preferences selects an explicit `.pproj`
  instead of that default. The folder button uses Blender's file browser. A
  strip whose current locator identifies exactly one asset already recorded by
  another host adopts that asset and adds only Blender's qualified identifier;
  ambiguous matches are reported and never chosen automatically.
- Each media strip gets a UUID in the custom property `postproject_uuid`,
  which names the media the strip uses. It is the only change to the `.blend`
  file. Cut and duplicated strips share it; a strip whose files are changed
  gets a new one on the next save.
- *File > External Data > Find Missing Media by Content* resolves every
  missing strip in one PostProject call. It searches the `.blend` file's
  folder, the project root and every file-path project variable, and the
  folders the media was in before. A strip is relinked through Blender's
  `bpy.data.file_path_foreach()` only when one file matches by content; an
  image sequence is relinked with all its frames or not at all. Everything
  else is reported and left to *Find Missing Files*.
- Nothing runs when a file opens unless *Find Missing Media When Opening* is
  enabled in the extension's preferences.
- After a completed still render, the extension records the existing output as
  a derived representation with its source dependency and observed Blender
  settings. It does not invent a PostProject job: Blender exposes no reliable
  failure callback for an extension-owned worker lifecycle.

Disable or uninstall the extension and Blender behaves as before. The
`postproject_uuid` properties are inert and can be deleted; deleting a
`.pproj` file forgets the media recorded in it.

## Build and test

The extension bundles one PostProject platform wheel, which carries the
Python binding and the native library of the same build. `tools/build.py`
builds the package for that wheel's platform:

```sh
tools/build.py --blender /path/to/blender \
  --wheel postproject-0.4.0a1-py3-none-manylinux_2_28_x86_64.whl
```

To build both from a PostProject checkout and run the tests in background
Blender:

```sh
git clone https://github.com/postproject-org/postproject
tools/fetch_blender.py 5.2.2 blender    # or 5.3-alpha for today's daily build
tools/dev.sh blender/blender postproject
```

The tests install the built package into a temporary user directory and cover
a renamed movie, a relative path, moved and incomplete image sequences, two
identical copies, a different file with the same name, a sound strip, cut and
duplicated strips, a missing or unreadable production, relinking on open, a
Blender 5.3 project, explicit production selection, cross-host adoption,
completed-render provenance, and the disabled extension.

The Kdenlive pilot's `tools/shared-production.sh` runs the built extension in
background Blender against the same production as Kdenlive and the
OpenAssetIO Manager. Its Blender driver is
`tests/shared_production.py`; it uses the installed extension and public
PostProject binding rather than editing the production database.

CI runs them nightly against PostProject `main` on Blender 5.2.2, and on the
newest 5.3 alpha without blocking. PostProject's `blender-pilot` workflow
calls the same workflow for a PostProject revision.

## License

GPL-3.0-or-later, as Blender requires of add-ons. PostProject itself is MIT or
Apache-2.0.
