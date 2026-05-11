---
tipo: activo
nombre: "INMOSA"
fondo: "A&R Rentas"
administrador: "INMOSA"
filas_noi: "287–295"
fuentes: 0
actualizado: 2026-05-11
---

# INMOSA

## Datos básicos

- **Fondo**: [[fondos/ar-rentas]]
- **Administrador**: INMOSA
- **Filas NOI-RCSD**: 287–295

## Fuente de datos

**Archivo (ER-FC, para CDG/NOI)**: dos naming patterns para el mismo archivo:
- `ER-FC INMOSA {año} {meses}.xlsx` (naming antiguo)
- `EEFF y FC Senior Assist {Mes}.{AA}.xlsx` (naming nuevo desde 2026)

**Ubicación**: SharePoint → `Fondos/Rentas TRI/Activos/INMOSA/Flujos/{año}/`
**Función**: `actualizar_noi_inmosa`, búsqueda con `buscar_er_inmosa`

## Distinguir archivos INMOSA (importante)

Existen DOS tipos de archivos para INMOSA / Senior Assist que NO deben confundirse:

| Archivo | Naming | Carpeta SP | Uso |
|---|---|---|---|
| **ER-FC** (estado de resultado + flujo de caja) | `ER-FC INMOSA ...` o `EEFF y FC Senior Assist ...` | `INMOSA/Flujos/{año}/` | CDG, NOI-RCSD |
| **Balance General** | `Balance ... Senior Assist ...` o `Balance General ... Senior Assist` | `INMOSA/Contabilidad/{año}/` | Balance consolidado |

**Regla de ruteo automático** (`tools/raw_tools.py`):
- Nombre contiene "Balance" + "Senior Assist" → Contabilidad
- Nombre contiene "EEFF/FC" + "Senior Assist", o "ER-FC INMOSA" → Flujos

**`buscar_er_inmosa`** reconoce ambos naming patterns ER-FC y excluye archivos de Balance.

## Vínculos

- [[fondos/ar-rentas]]
- [[procesos/noi-rcsd]]
