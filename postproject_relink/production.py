# SPDX-License-Identifier: GPL-3.0-or-later
"""The extension's PostProject calls.

This module never imports Blender. It receives strip media as plain values,
records them in a production, and answers where missing media went.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import postproject as pp

APPLICATION_SCHEME = "https://postproject.org/id/application"
STRIP_QUALIFIER = "org.blender:strip_uuid"
PROJECT_PRODUCTION_NAME = "postproject.pproj"


@dataclass(frozen=True)
class Sequence:
    """A numbered image sequence: every frame from start to end by step."""

    directory: Path
    prefix: str
    suffix: str
    padding: int
    start: int
    end: int
    step: int

    def filename(self, frame: int) -> str:
        return self.naming.filename(frame)

    @property
    def naming(self) -> pp.SequenceNaming:
        return pp.SequenceNaming(self.prefix, self.suffix, self.padding)

    def frames(self) -> range:
        return range(self.start, self.end + 1, self.step)


@dataclass(frozen=True)
class StripMedia:
    """The files one strip uses, identified by the strip's UUID property."""

    uuid: str
    name: str
    paths: tuple[Path, ...]
    #: Set for an image strip whose frames form a numbered sequence.
    sequence: Sequence | None = None
    #: Frame rate as an exact fraction, used for image sequences.
    rate: tuple[int, int] = (24, 1)

    def exists(self) -> bool:
        return all(path.is_file() for path in self.paths)


@dataclass
class RecordReport:
    recorded: int = 0
    adopted: int = 0
    #: Strip indexes that matched several logical assets. They are left
    #: unrecorded so Blender never chooses an asset implicitly.
    ambiguous: tuple[int, ...] = ()
    #: Index into the recorded strips of each strip whose files are no longer
    #: the media its UUID names, with the new UUID it was recorded under.
    new_uuids: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Relink:
    """What happened to one missing strip media."""

    uuid: str
    name: str
    #: One of "relinked", "ambiguous", "missing", "unrecorded", or "error".
    outcome: str
    #: Old absolute path to new absolute path, for every file of the strip.
    paths: dict[Path, Path] = field(default_factory=dict)
    detail: str | None = None


@dataclass(frozen=True)
class RenderFacts:
    """Observable Blender render settings retained as historical context."""

    scene: str
    engine: str
    frame_start: int
    frame_end: int
    output_format: str


def production_path(
    blend_path: Path,
    project_root: Path | None,
    selected: Path | None = None,
) -> Path:
    """Return an explicit production, otherwise the project or sidecar default."""

    if selected is not None:
        return selected
    if project_root is not None:
        return project_root / PROJECT_PRODUCTION_NAME
    return blend_path.with_suffix(".pproj")


def record(
    production: Path,
    strips: list[StripMedia],
    *,
    new_uuid,
    blender_version: str,
) -> RecordReport:
    """Record every strip whose files exist, creating the production if needed.

    ``new_uuid`` returns a fresh UUID string for a strip whose files differ
    from the media its UUID names.
    """

    report = RecordReport()
    if not any(strip.paths and strip.exists() for strip in strips):
        return report
    if production.exists():
        prod = pp.Production.open(production)
    else:
        prod = pp.Production.create(production, production.stem)
    try:
        # Strips sharing a UUID are duplicates or cut pieces of one strip.
        groups: dict[str, dict[tuple[Path, ...], list[int]]] = defaultdict(dict)
        for index, strip in enumerate(strips):
            if strip.paths and strip.exists():
                groups[strip.uuid].setdefault(strip.paths, []).append(index)
        with prod.transaction() as tx:
            tx.set_revision_context(
                pp.RevisionContext(
                    pp.OriginIdentity("Blender", blender_version),
                    "Record sequencer media on save",
                )
            )
            for uuid, by_paths in groups.items():
                asset = _asset_for(prod, uuid)
                claimed = False
                for indices in by_paths.values():
                    strip = strips[indices[0]]
                    report.recorded += len(indices)
                    if asset is None and not claimed:
                        candidates = _known_assets(prod, strip)
                        if len(candidates) > 1:
                            report.ambiguous += tuple(indices)
                            continue
                        if candidates:
                            asset = candidates[0]
                            tx.add_external_identifier(
                                asset,
                                pp.ExternalIdentifier(
                                    APPLICATION_SCHEME, uuid, STRIP_QUALIFIER
                                ),
                            )
                            report.adopted += len(indices)
                    if not claimed and (
                        asset is None or _matches(prod, tx, asset, strip)
                    ):
                        claimed = True
                        if asset is None:
                            _import(tx, strip, uuid)
                        continue
                    # A strip whose files were changed since is new media.
                    fresh = new_uuid()
                    _import(tx, strip, fresh)
                    report.new_uuids.update(dict.fromkeys(indices, fresh))
    finally:
        prod.close()
    return report


def _known_assets(prod: pp.Production, strip: StripMedia) -> tuple[pp.AssetId, ...]:
    """Return exact current-locator candidates for explicit host adoption."""

    if strip.sequence is None:
        locator = pp.LocatorIdentity(pp.file_locator(strip.paths[0]))
    else:
        locator = pp.LocatorIdentity(
            pp.file_locator(strip.sequence.directory), strip.sequence.naming
        )
    matches = prod.find_known_media_by_locator(locator, limit=100).items
    return tuple(dict.fromkeys(match.asset_id for match in matches))


def find(
    production: Path,
    strips: list[StripMedia],
    search_directories: list[Path],
) -> list[Relink]:
    """Resolve the recorded media of missing strips in one call.

    Never mutates the production. A strip is relinked only when its media has
    exactly one candidate that PostProject matched by content.
    """

    prod = pp.Production.open(production)
    try:
        results: list[Relink] = []
        wanted: dict[pp.AssetId, list[StripMedia]] = defaultdict(list)
        directories = set(search_directories)
        for strip in strips:
            asset = _asset_for(prod, strip.uuid)
            if asset is None:
                results.append(Relink(strip.uuid, strip.name, "unrecorded"))
                continue
            wanted[asset].append(strip)
            for resource in _original(prod, asset).resources:
                for locator in resource.locators:
                    directories.update(_former_directories(locator.uri))
        if not wanted:
            return results
        resolutions = prod.resolve(
            list(wanted),
            search_directories=sorted(d for d in directories if d.is_dir()),
        )
        originals = {asset: _original(prod, asset).id for asset in wanted}
        for resolution in resolutions:
            if resolution.representation_id != originals[resolution.asset_id]:
                continue
            for strip in wanted[resolution.asset_id]:
                results.append(_relink(strip, resolution))
        return results
    finally:
        prod.close()


def record_render(
    production: Path,
    source_uuids: tuple[str, ...],
    output: Path,
    *,
    blender_version: str,
    facts: RenderFacts,
) -> pp.RepresentationId | None:
    """Record one completed render when its sources name one logical asset.

    Blender exposes completion, but not a complete worker lifecycle. This is
    observed provenance rather than a claimed PostProject job or recipe.
    """

    if not production.is_file() or not output.is_file():
        return None
    with pp.Production.open(production) as prod:
        assets = tuple(
            dict.fromkeys(
                asset
                for uuid in source_uuids
                if (asset := _asset_for(prod, uuid)) is not None
            )
        )
        if len(assets) != 1:
            return None
        source_ids = tuple(
            representation.id
            for representation in prod.representations[assets[0]]
            if representation.kind is pp.RepresentationKind.ORIGINAL
        )
        if not source_ids:
            return None
        with prod.transaction() as transaction:
            transaction.set_revision_context(
                pp.RevisionContext(
                    pp.OriginIdentity("Blender", blender_version),
                    "Record completed render",
                )
            )
            render_id = transaction.add_representation(
                assets[0], pp.RepresentationKind.DERIVED, output
            )
            activity_id = transaction.create_activity(
                pp.ActivitySpec(
                    "org.blender:render",
                    inputs=tuple(pp.ActivityEdge(item) for item in source_ids),
                    outputs=(pp.ActivityEdge(render_id),),
                )
            )
            vocabulary = "https://postproject.org/ns/blender/1"
            values = {
                "scene": facts.scene,
                "engine": facts.engine,
                "frame-range": f"{facts.frame_start}-{facts.frame_end}",
                "output-format": facts.output_format,
            }
            for name, value in values.items():
                transaction.add_metadata(
                    activity_id,
                    pp.MetadataProperty(vocabulary, name),
                    pp.MetadataString(value),
                )
        return render_id


def _asset_for(prod: pp.Production, uuid: str) -> pp.AssetId | None:
    key = (APPLICATION_SCHEME, uuid, STRIP_QUALIFIER)
    for target in prod.objects_by_external_identifier[key]:
        if isinstance(target, pp.AssetId):
            return target
    return None


def _original(prod: pp.Production, asset: pp.AssetId) -> pp.Representation:
    return next(
        representation
        for representation in prod.representations[asset]
        if representation.kind is pp.RepresentationKind.ORIGINAL
    )


def _matches(
    prod: pp.Production,
    tx: pp.Transaction,
    asset: pp.AssetId,
    strip: StripMedia,
) -> bool:
    """Confirm that the strip still uses the asset's media, recording its location.

    A new location of the same content is confirmed, and locators whose files
    are gone are retired. Returns False when the strip uses different content.
    """

    original = _original(prod, asset)
    resource = original.resources[0]
    if strip.sequence is not None:
        sequence = strip.sequence
        descriptor = original.image_sequence
        if descriptor is None or (descriptor.start, descriptor.end) != (
            sequence.start,
            sequence.end,
        ):
            return False
        uri = pp.file_locator(sequence.directory)
        known = {
            (locator.uri, locator.sequence_naming) for locator in resource.locators
        }
        if (uri, sequence.naming) not in known:
            # A sequence found under new names is recorded with them, beside
            # its former locators, once its content is the recorded content.
            verification = prod.verify_resource(
                resource.id, sequence.directory, sequence_naming=sequence.naming
            )
            if verification is not pp.ContentVerification.MATCHES:
                return False
            tx.confirm_locator(resource.id, uri, sequence_naming=sequence.naming)
        _retire_vanished(tx, resource, uri, sequence.naming, sequence.start)
        return True
    if len(strip.paths) != 1 or original.image_sequence is not None:
        return False
    path = strip.paths[0]
    uri = pp.file_locator(path)
    known = {locator.uri for locator in resource.locators}
    if uri in known:
        stat = path.stat()
        if (stat.st_size, stat.st_mtime_ns // 1000) != (
            resource.file_size,
            resource.modified_at_unix_micros,
        ):
            outcome = tx.observe_resource_content(resource.id, path)
            if outcome is pp.ContentObservationOutcome.CHANGED:
                return False
    elif prod.verify_resource(resource.id, path) is pp.ContentVerification.MATCHES:
        tx.confirm_locator(resource.id, uri)
    else:
        return False
    _retire_vanished(tx, resource, uri)
    return True


def _retire_vanished(
    tx: pp.Transaction,
    resource: pp.Resource,
    current: str,
    naming: pp.SequenceNaming | None = None,
    first_frame: int = 0,
) -> None:
    """Retire every other locator whose files are gone."""

    for locator in resource.locators:
        if (locator.uri, locator.sequence_naming) == (current, naming):
            continue
        path = pp.locator_file_path(locator.uri)
        if locator.sequence_naming is not None:
            path = path / locator.sequence_naming.filename(first_frame)
        if not path.exists():
            tx.retire_locator(locator.id)


def _import(tx: pp.Transaction, strip: StripMedia, uuid: str) -> pp.AssetId:
    source: pp.MediaSource = pp.FileSource(strip.paths[0])
    if strip.sequence is not None:
        sequence = strip.sequence
        source = pp.ImageSequenceSource(
            directory=sequence.directory,
            naming=sequence.naming,
            start=sequence.start,
            end=sequence.end,
            step=sequence.step,
            rate_numerator=strip.rate[0],
            rate_denominator=strip.rate[1],
        )
    asset = tx.import_media(source, strip.name)
    tx.add_external_identifier(
        asset, pp.ExternalIdentifier(APPLICATION_SCHEME, uuid, STRIP_QUALIFIER)
    )
    return asset


def _former_directories(uri: str) -> list[Path]:
    """Return the folders a locator's file was in, to search them again."""

    try:
        path = pp.locator_file_path(uri)
    except pp.PostProjectError:
        return []
    return [path.parent, path] if path.suffix == "" else [path.parent]


_CONTENT_EVIDENCE = {
    pp.EvidenceKind.EXACT_FINGERPRINT_MATCH,
    pp.EvidenceKind.FULL_HASH_MATCH,
}
#: A sequence's content evidence samples its first, middle, and last frames.
_SEQUENCE_EVIDENCE = _CONTENT_EVIDENCE | {pp.EvidenceKind.PARTIAL_FINGERPRINT_MATCH}


def _relink(strip: StripMedia, resolution: pp.RepresentationResolution) -> Relink:
    resource = resolution.resources[0]
    state = resource.state
    if state is pp.ResourceResolutionState.ONLINE_AT_KNOWN_LOCATOR:
        candidate = resource.candidates[0]
    elif state is pp.ResourceResolutionState.AMBIGUOUS:
        return _unresolved(strip, "ambiguous", resource)
    elif state in (
        pp.ResourceResolutionState.RESOLVED_EXACT,
        pp.ResourceResolutionState.RESOLVED_PROBABLE,
    ):
        if len(resource.candidates) != 1:
            return _unresolved(strip, "ambiguous", resource)
        candidate = resource.candidates[0]
        kinds = {evidence.kind for evidence in candidate.evidence}
        accepted = _CONTENT_EVIDENCE if strip.sequence is None else _SEQUENCE_EVIDENCE
        if not kinds & accepted:
            return _unresolved(strip, "missing", resource)
    elif state is pp.ResourceResolutionState.OFFLINE:
        return Relink(strip.uuid, strip.name, "missing")
    else:
        return _unresolved(strip, "error", resource)
    found = pp.locator_file_path(candidate.uri)
    if strip.sequence is None:
        paths = {strip.paths[0]: found}
    else:
        # A renamed sequence is found under the names of its new location.
        naming = candidate.sequence_naming or strip.sequence.naming
        paths = {
            path: found / naming.filename(frame)
            for path, frame in zip(strip.paths, strip.sequence.frames(), strict=True)
        }
    if not all(new.is_file() for new in paths.values()):
        return Relink(strip.uuid, strip.name, "missing", detail="incomplete sequence")
    return Relink(strip.uuid, strip.name, "relinked", paths)


def _unresolved(
    strip: StripMedia, outcome: str, resource: pp.ResourceResolution
) -> Relink:
    details = [candidate.uri for candidate in resource.candidates[:3]]
    details += [evidence.detail for evidence in resource.evidence if evidence.detail]
    return Relink(strip.uuid, strip.name, outcome, detail="; ".join(details) or None)
