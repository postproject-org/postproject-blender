# Blender per-target brief

Checked on 2026-09-28 against Blender tag `v5.2.2`, commit
`d13f752e3b9c4f8c261cda552b1021f8bcc0382c` (committed 2026-09-14), the latest
stable release. Line numbers refer to that commit. None of the search, strip,
proxy, or library logic cited below differs in substance on `main` at
`b2e7faa4` (2026-09-28, version 5.3 alpha). What 5.3 adds around projects and
paths is described [below](#in-blender-53-alpha), with line numbers for that
commit.

## Current behavior

**Media in the Video Sequencer.** A movie or sound strip stores a directory in
`StripData::dirpath` and one file name in a `StripElem`
(`source/blender/makesdna/DNA_sequence_types.h:249` and `:306`). An image strip
stores one `StripElem` per frame, so an image sequence is an explicit list of
file names under one directory, not a pattern. A strip is identified only by its
`name` (`DNA_sequence_types.h:354`), which is unique within a scene and renamed
freely. Nothing identifies a strip's content. `ID::session_uid`
(`DNA_ID.h:457`) exists only for the running session. Strips accept custom
properties (`source/blender/makesrna/intern/rna_sequencer.cc:2575`), and
duplicating a strip copies them (`source/blender/sequencer/intern/sequencer.cc:665`).

**Finding missing files.** Blender does nothing automatically when a file is
missing. The user runs *File > External Data > Find Missing Files*
(`FILE_OT_find_missing_files`, `source/blender/editors/space_info/info_ops.cc:553`)
and picks one directory. `BKE_bpath_missing_files_find()`
(`source/blender/blenkernel/intern/bpath.cc:486`) visits every external path,
including strips (`blenkernel/intern/scene.cc:978`) and linked libraries
(`blenkernel/intern/library.cc:148`). For each missing file,
`missing_files_find__recursive()` (`bpath.cc:373`) searches the chosen directory
up to 16 levels deep for a file with **the same name** (`bpath.cc:411`). Among
several, it takes **the largest** (`bpath.cc:413`), which is meant to avoid
thumbnails. Content is never compared. A renamed file is not found, and a
different file with the same name is taken without comment. For an image strip,
each frame is searched separately.

**Proxies.** New movie strips get proxies automatically, because the
preference `sequencer_proxy_setup` defaults to automatic
(`DNA_userdef_types.h:1253`). `seq_build_proxy()`
(`source/blender/editors/space_sequencer/sequencer_add.cc:1181`) enables the
proxy and sets *skip existing* (`sequencer_add.cc:1198`). A movie proxy is
stored at `<source folder>/BL_proxy/<source file name>/proxy_<size>.avi`
(`source/blender/imbuf/movie/intern/movie_proxy_indexer.cc:73` and `:92`). An
image proxy is stored at `BL_proxy/images/<size>/<frame name>_proxy.jpg`
(`source/blender/sequencer/intern/proxy.cc:170` and `:177`). Both names derive
from the source's file name, never its content. A proxy is used whenever its
file exists (`proxy.cc:258`), and a rebuild with *skip existing* keeps existing
proxies (`proxy.cc:370`). A source replaced under the same name therefore keeps
its old proxy. Proxies are built in-process by a window-manager job
(`WM_JOB_TYPE_SEQ_BUILD_PROXY`, `sequencer/intern/proxy_job.cc:89`), not by a
subprocess.

**Libraries and catalogs.** A linked library is a `Library` ID holding one file
path (`DNA_ID.h:539` and `:547`). A linked datablock whose library cannot be
read becomes a placeholder (`blenloader/intern/readfile.cc:2672`), and the user
repairs it with *Relocate* (`WM_OT_lib_relocate`,
`windowmanager/intern/wm_files_link.cc:1052`) or *Find Missing Files*. Asset
catalogs, by contrast, are identified by UUID in the catalog definition file
(`source/blender/asset_system/intern/asset_catalog_definition_file.cc:124`).
Remote asset libraries identify downloaded files by SHA-256
(`scripts/modules/_bpy_internal/assets/remote_library/hashing.py:33`), cached
by size and modification time in a private SQLite-backed service
(`scripts/modules/_bpy_internal/disk_file_hash_service/`). Nothing uses content
identity for local media.

**Extensions and Python.** Blender 5.2 bundles Python 3.13
(`build_files/build_environment/cmake/versions.cmake:381`). An extension is a
zip with `blender_manifest.toml`. Its `wheels` field lists bundled wheels, and
`platforms` restricts the platforms it installs on
(`scripts/addons_core/bl_pkg/cli/blender_ext.py:1990`–`1991`). Wheel tags are
mapped to Blender platform names (`blender_ext.py:2164`). Extensions observe
file events through `bpy.app.handlers`, among them `load_post` and `save_post`
(`source/blender/python/intern/bpy_app_handlers.cc:121` and `:127`).
`SequenceEditor.strips_all` lists every strip, including those inside meta
strips (`rna_sequencer.cc:2955`).

**Rewriting paths from Python.** `bpy.data.file_path_foreach()` calls a
function for every external path and replaces a path with the string it
returns. It is Blender's supported way for scripts, such as render-farm
packers, to remap paths. For a strip, the visited data-block is the scene, not
the strip, and an image strip is visited once per frame; each rewritten frame
also sets the strip's directory (`blenkernel/intern/scene.cc:1005`–`1043` on
`main`). The metadata object says only whether a path is expanded, a cache, or
read-only.

## In Blender 5.3 alpha

Blender 5.3 changes nothing about how strips reference files, find missing
files, or build proxies. It adds *Blender Projects* and fixes one detail of
*Find Missing Files*. Both bear on where a PostProject production belongs and
what the extension should leave to Blender.

**Projects.** A folder containing `.blender_project/config.toml` is a project
root, and every file below it belongs to that project
(`scripts/startup/bl_operators/project.py:50`, `:405`). Opening a file inside a
project loads the project (`project.py:364`), and Python reaches it as
`bpy.data.project` (`makesrna/intern/rna_main.cc:664`) with a name, a
`root_path`, variables, and asset libraries
(`makesrna/intern/rna_blender_project.cc:793`–`857`). A project is currently
defined by the open file; an open design proposes the working directory instead
([#162176](https://projects.blender.org/blender/blender/issues/162176)). The
project's design principle is that its settings stay human-readable and
diffable ([#133001](https://projects.blender.org/blender/blender/issues/133001)).

**Project variables.** A project defines typed variables. A string variable
with subtype `FILEPATH` is a directory such as footage storage
(`rna_blender_project.cc:605`–`616`), and `{project_root}` and
`{project_name}` are built in (`blenkernel/intern/path_templates.cc:296`–`298`).
Variables are substituted only in paths that accept templates: render and
file-output paths (`rna_scene.cc:7675`, `rna_nodetree.cc:7121`) and project
asset-library paths (`rna_userdef.cc:7209`–`7210`, flag
`PROP_VARIABLES_PROJECT`, `RNA_types.hh:577`). Strip sources do not accept
them (`rna_sequencer.cc:3374`, `:3579`). A `FILEPATH` variable is the closest
Blender comes to a PostProject logical root: a portable name with a
machine-local directory.

**Find Missing Files.** After a search that changed paths, Blender 5.3 refreshes
every scene's sequencer so found media plays without *Refresh All*
(`editors/space_info/info_ops.cc:539`–`545`, commit `d19a9b13`). In 5.2 a
script that rewrites strip paths has to refresh the sequencer itself.

**Not yet in code.** *VSE: Media Bin*
([#154922](https://projects.blender.org/blender/blender/issues/154922)) is an
open design. Strips would reference image, sound, and scene data-blocks
organized in bins, and the design names the bin as the place to manage
proxies. A *Virtual File System*
([#158319](https://projects.blender.org/blender/blender/issues/158319)) is a
design expected to take years, listing file relocation without rewriting
references among its goals. Neither has code on `main`.

**Consequences for the pilot.**

- The production belongs to the project when there is one. Inside a project,
  the extension uses one production, `<project_root>/postproject.pproj`, for
  every `.blend` file in it, and searches the project root and every `FILEPATH`
  variable's directory. It writes nothing into `.blender_project/`, whose
  contents Blender keeps human-readable. Without a project, and in 5.2, it uses
  the `<file>.pproj` sidecar. The extension never creates a project or a
  variable.
- Relinking goes through `bpy.data.file_path_foreach()`, mapping each missing
  path to its found path, rather than editing strip fields. That is the path
  API Blender maintains and that media data-blocks from the Media Bin would
  also pass through. The extension refreshes the sequencer only where Blender
  does not (5.2).
- The strip UUID is held behind one adapter function, so it can move to a media
  data-block if the Media Bin lands.
- Proxies stay out of scope. If the Media Bin becomes the place that manages
  proxies, a managed-proxy experiment on today's `BL_proxy` folders would be
  obsolete.

## User pain

Media renamed or reorganized outside Blender, such as graded shots renamed
`-graded` or rushes sorted into day folders, leaves strips pointing at missing
files. *Find Missing Files* cannot find a renamed file at all. When two files
share a name, for example the same `A001_C002.mov` from two cards, it silently
relinks to the larger one. Every image of a sequence is searched separately. A
source replaced under its old name keeps playing a proxy made from the old
content, and nothing tells the user.

## Smallest PostProject experiment

This is a resolver experiment, delivered as an extension with no change to
Blender. On `save_post`, the extension records each movie, sound, and image
strip whose files exist in a production: `<project_root>/postproject.pproj`
when the file belongs to a Blender 5.3 project, otherwise a sidecar `film.pproj`
next to `film.blend`. A movie or sound strip becomes an asset with a single-file
representation. An image strip becomes one image-sequence representation.

Blender has no durable strip identity, so the extension gives each strip a UUID
in a string custom property and records it as an application identifier with
the qualifier `org.blender:strip_uuid`. It is the one change the extension
makes to a `.blend` file. Duplicating a strip copies the property, so on save
the extension gives every strip after the first with a duplicated UUID a new
one. In a project production, several `.blend` files, and copies made with
*Save As*, can carry the same UUID. The UUID names the media the strip uses,
so that is intended, but a strip whose files were changed with *Change
Data/Files* must be recorded as different media on the next save. Search
directories are never recorded.

The extension adds *Find Missing Media by Content* next to *Find Missing
Files*. The operator resolves every recorded strip with a missing file in one
PostProject call. It searches the `.blend` file's folder, the project root and
every `FILEPATH` project variable's directory when there is a project, and each
strip's former folders, all as unnamed search directories. It relinks a strip
only when exactly one candidate is found, by rewriting its paths through
`bpy.data.file_path_foreach()`. For an image strip, all frames are relinked
together from one representation, or none are. An ambiguous or missing strip
is listed in the report and left for *Find Missing Files* or manual repair.
Nothing runs when a file is opened unless the user enables that in the
extension's preferences.

Proxies as managed artifacts are not part of this pilot. Unlike Kdenlive,
Blender builds proxies in-process in a window-manager job. The extension cannot
run as that job's worker, and Python gets no notice when the job finishes. It
would have to start the rebuild itself, watch for the job's end with a timer,
and then record the proxy files. The Media Bin design names the bin as the
place to manage proxies, so that experiment waits for Blender's own proxy
model.

## Files and modules that change

None in Blender. The pilot is a separate extension: `blender_manifest.toml`,
one Python package of a few hundred lines (handlers, the operator, a menu
entry, preferences, and an adapter over the PostProject Python binding), its
tests run with `blender --background --factory-startup --python`, and a build
script producing one extension zip per platform.

## Additional dependency cost

The extension bundles the platform-neutral `postproject` wheel (pure Python,
requires 3.11 or newer) and PostProject's native library for its platform
(about 4.5 MiB, SQLite included). The binding loads the library from an explicit
path, so the extension passes `library_path=` next to its own files and never
reads `POSTPROJECT_LIBRARY`. Because of the native library, the extension is
built per platform and declares `platforms`. Blender itself gains nothing, and
no service runs.

## How to remove or revert it

Disable or uninstall the extension, and Blender behaves as before. Deleting a
`.pproj` sidecar forgets that file's recorded media, and deleting
`<project_root>/postproject.pproj` forgets the project's. The strip UUID properties
stay in `.blend` files saved with the extension. They are inert and can be
deleted from each strip's custom properties.

## What counts as success

An installed extension relinks a renamed movie strip and a renamed image
sequence by content, in one operation. It never picks between two identical
copies and never takes a different file that only shares the name. With the
extension disabled, Blender is unchanged. The extension builds from released
PostProject artifacts, and its tests run in background Blender on Linux in CI.

## Integration questions

- **Identifier persisted by the host:** a UUID per strip in a custom property,
  recorded as an application identifier under
  `https://postproject.org/id/application` with qualifier
  `org.blender:strip_uuid`. A host binding (ADR 0011) would replace it once
  Blender persists PostProject identities itself.
- **Database owner and location:** the extension creates and updates
  `<project_root>/postproject.pproj` for files in a Blender project, and
  `<file>.pproj` next to `<file>.blend` otherwise, on every save. It follows
  Blender's project and never defines one of its own. The `.blend` file stays
  authoritative. The production holds only content identity and locations.
- **PostProject or database absent:** without the extension nothing changes. A
  missing or unreadable sidecar makes the operator report that nothing is
  recorded, and *Find Missing Files* works as before. A missing sidecar is
  created at the next save.
- **Uninstall:** uninstall the extension and delete the `.pproj` files. The
  strip UUID properties remain and are harmless.

## Common assumptions this corrects

Blender is sometimes thought to relink by content or to track catalogued media
by UUID. *Find Missing Files* compares file names only, and picks the largest
of several matches. UUIDs identify asset catalogs, not media or strips.
Proxies are keyed by the source's file name and path, never by its content.
