"""Resolución segura de rutas controladas por usuarios o por el modelo."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


class UnsafePathError(ValueError):
    """La ruta solicitada escapa de una raíz autorizada."""


def _resolved(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def resolve_within(root: str | os.PathLike[str], *parts: object) -> str:
    """Construye una ruta relativa y comprueba que permanezca dentro de ``root``.

    ``Path.resolve`` también resuelve symlinks existentes, por lo que el control
    evita tanto ``..``/rutas absolutas como escapes mediante enlaces simbólicos.
    """
    if not root:
        raise UnsafePathError("La raíz autorizada no está configurada")

    root_path = _resolved(root)
    candidate = root_path
    for raw_part in parts:
        part = str(raw_part or "")
        if "\x00" in part:
            raise UnsafePathError("La ruta contiene un byte nulo")
        part_path = Path(part)
        if part_path.is_absolute():
            raise UnsafePathError("No se permiten rutas absolutas")
        candidate = candidate / part_path

    candidate = candidate.resolve(strict=False)
    try:
        contained = os.path.commonpath((str(root_path), str(candidate))) == str(root_path)
    except ValueError:
        contained = False
    if not contained:
        raise UnsafePathError("La ruta solicitada escapa de la carpeta autorizada")
    return str(candidate)


def resolve_from_allowed_roots(
    path: str | os.PathLike[str], roots: Iterable[str | os.PathLike[str]]
) -> str:
    """Valida una ruta absoluta o relativa contra una lista de raíces permitidas."""
    raw = str(path or "")
    if "\x00" in raw:
        raise UnsafePathError("La ruta contiene un byte nulo")

    candidate = _resolved(raw)
    for root in roots:
        if not root:
            continue
        root_path = _resolved(root)
        try:
            if os.path.commonpath((str(root_path), str(candidate))) == str(root_path):
                return str(candidate)
        except ValueError:
            continue
    raise UnsafePathError("La ruta está fuera de las carpetas autorizadas")
