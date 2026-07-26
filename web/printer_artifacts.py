"""Opaque staged upload artifacts for the print-start Compound action.

Staging is the seam that keeps artifact content and caller-supplied paths out
of the Printer-action module and out of the action journal.  Callers hand the
server a stream and receive an opaque reference plus the safe metadata the
server derived itself: a sanitized name, a size, and the resolved preparation
temperatures when a preparation routine is configured.
"""

from dataclasses import dataclass
import logging as log
from pathlib import Path
from secrets import token_urlsafe

from libflagship.ppppapi import FileUploadInfo

import web.util


# Only the G-code preamble is inspected for preparation temperatures, matching
# the pre-print hook's existing behaviour.
_PREAMBLE_BYTES = 256 * 1024
_READ_BLOCK = 64 * 1024

# Staged files carry a suffix so a restart can recognise its own leftovers
# without touching anything else in the configured directory.
_SUFFIX = ".staged"


class ArtifactError(ValueError):
    """Staging refused the upload; nothing was submitted to the printer."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class StagedArtifact:
    """Server-derived, journal-safe description of a staged upload."""

    reference: str
    name: str
    size: int
    user_name: str = "ankerctl"
    origin: str = "pppp_upload"
    bed_celsius: int | None = None
    nozzle_celsius: int | None = None

    def to_dict(self):
        return {
            "reference": self.reference,
            "name": self.name,
            "size": self.size,
            "userName": self.user_name,
            "origin": self.origin,
            "bedCelsius": self.bed_celsius,
            "nozzleCelsius": self.nozzle_celsius,
        }


class ArtifactStore:
    """Local staging area addressed only by opaque references."""

    def __init__(self, root):
        self._root = Path(root)
        self._staged = {}
        self._purge()

    def _purge(self):
        """Drop artifacts this store's own previous process left behind.

        References live only in memory and the server never replays an action
        after restart, so a file we staged is unreachable content that would
        otherwise accumulate.  Only our own suffix is removed: the staging
        directory is operator-configurable, and pointing it somewhere populated
        must not destroy anything we did not write.
        """
        if not self._root.is_dir():
            return
        for path in self._root.glob(f"*{_SUFFIX}"):
            if not path.is_file():
                continue
            try:
                path.unlink()
            except OSError:
                log.warning("Could not remove orphaned staged artifact")

    def _path(self, reference):
        return self._root / f"{reference}{_SUFFIX}"

    def stage(
        self,
        stream,
        *,
        user_name="ankerctl",
        origin="pppp_upload",
        extract_temperatures=False,
    ):
        """Persist one upload and return its opaque reference.

        The reference is unrelated to the file name, so recording it in the
        action journal cannot disclose the artifact or the caller's path.
        ``user_name`` and ``origin`` are the trusted caller identity the server
        adapter derived, never values the request body chose.
        """
        name = _safe_name(getattr(stream, "filename", ""))
        if not name:
            raise ArtifactError("unsupported_artifact_name")

        reference = token_urlsafe(16)
        path = self._path(reference)
        self._root.mkdir(parents=True, exist_ok=True)

        size = 0
        preamble = b""
        with path.open("wb") as handle:
            while chunk := stream.read(_READ_BLOCK):
                if len(preamble) < _PREAMBLE_BYTES:
                    preamble += chunk[:_PREAMBLE_BYTES - len(preamble)]
                handle.write(chunk)
                size += len(chunk)

        if not size:
            path.unlink(missing_ok=True)
            raise ArtifactError("empty_artifact")

        bed_celsius = nozzle_celsius = None
        if extract_temperatures:
            # Parsing only.  Whether the resolved temperatures are supported is
            # the print-start action's policy, applied before it heats anything.
            try:
                bed_celsius, nozzle_celsius = web.util.parse_preprint_temperatures(
                    preamble
                )
            except ValueError as error:
                path.unlink(missing_ok=True)
                # The message names G-code, never the artifact or its path.
                log.info("Rejected staged artifact: %s", error)
                raise ArtifactError("unresolved_preparation_temperatures") from error

        artifact = StagedArtifact(
            reference, name, size, user_name, origin, bed_celsius, nozzle_celsius
        )
        self._staged[reference] = artifact
        return artifact

    def get(self, reference):
        return self._staged.get(reference)

    def open(self, reference):
        """Open staged content for transfer, named as the printer will see it."""
        artifact = self._staged.get(reference)
        if artifact is None:
            raise ArtifactError("unknown_artifact")
        stream = self._path(reference).open("rb")
        stream.filename = artifact.name
        return stream

    def discard(self, reference):
        """Drop a staged artifact.  Safe to repeat, so cleanup can be blind."""
        self._staged.pop(reference, None)
        self._path(reference).unlink(missing_ok=True)


def _safe_name(filename):
    # Slicers and browsers send whole client-side paths in either separator
    # style; only the basename survives staging.
    base = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    return FileUploadInfo.sanitize_filename(base)
