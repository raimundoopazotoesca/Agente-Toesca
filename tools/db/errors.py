"""Excepciones tipadas para la capa DB."""


class DBError(Exception):
    """Base para errores de la capa DB."""


class NotFoundError(DBError):
    """Entidad solicitada no existe."""


class DuplicateError(DBError):
    """Ya existe un registro con la misma clave única."""


class ValidationError(DBError):
    """Datos de entrada no pasaron validación."""
