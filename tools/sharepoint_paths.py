"""Rutas canonicas del SharePoint sincronizado usado por el agente."""
from __future__ import annotations

import os

from config import SHAREPOINT_DIR


def sp_path(*parts: str) -> str:
    """Construye una ruta absoluta dentro de SHAREPOINT_DIR."""
    return os.path.join(SHAREPOINT_DIR, *parts)


RAW_DIR = sp_path("RAW")

CONTROL_GESTION_DIR = sp_path("Control de Gestión")
CDG_MENSUAL_DIR = os.path.join(CONTROL_GESTION_DIR, "CDG Mensual")
BALANCES_CONSOLIDADOS_DIR = os.path.join(CONTROL_GESTION_DIR, "Balances Consolidados")
SALDO_CAJA_DIR = os.path.join(CONTROL_GESTION_DIR, "Saldo Caja")
CALCULO_TIR_DIR = os.path.join(CONTROL_GESTION_DIR, "Cálculo TIR")

RENT_ROLLS_DIR = sp_path("Rent Rolls")
RR_JLL_DIR = os.path.join(RENT_ROLLS_DIR, "JLL")

FONDOS_DIR = sp_path("Fondos")
RENTAS_TRI_DIR = os.path.join(FONDOS_DIR, "Rentas TRI")
RENTAS_PT_DIR = os.path.join(FONDOS_DIR, "Rentas PT")
RENTAS_APOQUINDO_DIR = os.path.join(FONDOS_DIR, "Rentas Apoquindo")
RENTA_RESIDENCIAL_DIR = os.path.join(FONDOS_DIR, "Renta Residencial")

TRI_ACTIVOS_DIR = os.path.join(RENTAS_TRI_DIR, "Activos")
TRI_SOCIEDADES_DIR = os.path.join(RENTAS_TRI_DIR, "Sociedades")
TRI_EEFF_FONDO_DIR = os.path.join(RENTAS_TRI_DIR, "EEFF", "Fondo")
TRI_FACT_SHEETS_DIR = os.path.join(RENTAS_TRI_DIR, "Fact Sheets")

TRI_VINA_DIR = os.path.join(TRI_ACTIVOS_DIR, "Viña Centro")
TRI_CURICO_DIR = os.path.join(TRI_ACTIVOS_DIR, "Curicó")
TRI_INMOSA_DIR = os.path.join(TRI_ACTIVOS_DIR, "INMOSA")

TRI_VINA_EEFF_DIR = os.path.join(TRI_VINA_DIR, "EEFF")
TRI_CURICO_EEFF_DIR = os.path.join(TRI_CURICO_DIR, "EEFF")
TRI_VINA_RENT_ROLL_DIR = os.path.join(TRI_VINA_DIR, "Rent Roll")
TRI_CURICO_RENT_ROLL_DIR = os.path.join(TRI_CURICO_DIR, "Rent Roll")
TRI_INMOSA_FLUJOS_DIR = os.path.join(TRI_INMOSA_DIR, "Flujos")
TRI_INMOSA_EEFF_DIR = os.path.join(TRI_INMOSA_DIR, "EEFF")
TRI_INMOSA_CONTABILIDAD_DIR = os.path.join(TRI_INMOSA_DIR, "Contabilidad")

TRI_BOULEVARD_DIR = os.path.join(TRI_SOCIEDADES_DIR, "Boulevard")
TRI_TORRE_A_DIR = os.path.join(TRI_SOCIEDADES_DIR, "Torre A")
TRI_CHANARCILLO_DIR = os.path.join(TRI_SOCIEDADES_DIR, "Chañarcillo")
TRI_INMOB_APOQUINDO_DIR = os.path.join(TRI_SOCIEDADES_DIR, "Inmobiliaria Apoquindo")
TRI_INMOB_VC_DIR = os.path.join(TRI_SOCIEDADES_DIR, "Inmobiliaria VC")

PT_EEFF_DIR = os.path.join(RENTAS_PT_DIR, "EEFF")
PT_FACT_SHEETS_DIR = os.path.join(RENTAS_PT_DIR, "Fact Sheets")

APO_EEFF_DIR = os.path.join(RENTAS_APOQUINDO_DIR, "EEFF")
APO_FACT_SHEETS_DIR = os.path.join(RENTAS_APOQUINDO_DIR, "Fact Sheets")
