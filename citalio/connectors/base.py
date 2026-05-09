"""Base classes and shared types for Citalio optional connectors."""

from __future__ import annotations

from typing import Any


class ConnectorError(Exception):
    """Raised when a connector operation fails or a required extra is missing."""

    def __init__(self, message: str, connector: str = "", extra: str = "") -> None:
        self.connector = connector
        self.extra = extra
        hint = f" Install citalio[{extra}] to enable it." if extra else ""
        super().__init__(f"[{connector}] {message}{hint}" if connector else message)


class MetadataConnector:
    """Protocol for connectors that look up bibliographic metadata."""

    name: str = ""

    def capabilities(self) -> list[str]:
        return []

    def lookup_by_doi(self, doi: str) -> dict[str, Any]:
        raise NotImplementedError

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        raise NotImplementedError

    def normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class AcquisitionConnector:
    """Protocol for connectors that download full-text attachments."""

    name: str = ""

    def capabilities(self) -> list[str]:
        return []

    def can_acquire(self, reference: dict[str, Any]) -> bool:
        raise NotImplementedError

    def acquire(self, reference: dict[str, Any], destination_dir: str) -> str:
        raise NotImplementedError


class LibraryImportExportConnector:
    """Protocol for connectors that import or export reference libraries."""

    name: str = ""

    def capabilities(self) -> list[str]:
        return []

    def import_records(self, source: Any) -> list[dict[str, Any]]:
        raise NotImplementedError

    def export_records(self, references: list[dict[str, Any]], destination: Any) -> None:
        raise NotImplementedError
