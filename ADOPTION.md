# Blender extension review packet

Development package: **PostProject Relink 0.3.0**, SDK **0.9.0a1**, ABI **53**.
The Linux x64 package is locally prepared and unpublished. Other platforms
have build routes but no current host-install qualification.

## Try the package

In Blender 5.2.2, choose **Preferences → Get Extensions → Install from Disk**,
select `postproject_relink-0.3.0-linux_x64.zip`, and enable the extension.
Add a movie to the Sequencer and save the `.blend`. Rename the movie, then use
**File → External Data → Find Missing Media by Content**. A unique exact
match is relinked; duplicates remain missing. Save and reopen to retain the
path. Disable the extension and reopen: ordinary playback still uses that path.
The [build instructions](README.md#build-and-test) produce the same package.

The clean-user automated walkthrough passes in background Blender 5.2.2:
24 tests pass and one Blender 5.3-only test skips. It includes activation,
save/reopen, moved sequences, ambiguous files, read-only extension files,
completed-render provenance and disabled fallback. This is automated host
evidence; an interactive human usability pass is not claimed.

The OBS → Blender handoff adopts the recording's identity and preserves its
capture activity and technical metadata. Kdenlive → Blender → Manager also
passes adoption, render provenance, moved media, competing writes and staleness.

## Distribution and maintenance

The package contains the GPL-3.0-or-later extension and a matching SDK wheel
with its native library and MIT/Apache-2.0 license texts. Native dependency
versions/licenses accompany the SDK artifact manifest. It installs no packages
at runtime and makes no network requests. Its only manifest permission is
file access for media and the user-selected production/sidecar. Production data
is written beside the project or at the chosen path, never inside the extension.

Use this repository's [issues](https://github.com/postproject-org/postproject-blender/issues)
for experimental pilot support. Installation into the official directory is
a separate moderation outcome; no Blender affiliation or approval is claimed.

## Distribution requirements

Reviewed 2026-10-12: [extension guidelines](https://developer.blender.org/docs/handbook/extensions/addon_guidelines/)
require self-contained dependencies, offline behavior and writable user storage;
the package follows those boundaries. [Moderation guidance](https://developer.blender.org/docs/features/extensions/moderation/guidelines/)
allows bundled wheels. The [Blender core AI policy](https://developer.blender.org/docs/handbook/contributing/ai_contributions/)
explicitly excludes extensions; it does not constitute extension approval.
The official [terms](https://extensions.blender.org/terms-of-service/) were
identified, but the full page could not be retrieved during this review.
Recheck them before requesting an official listing.
