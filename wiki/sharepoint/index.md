# SharePoint — Índice de Archivos

**Base:** `C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos`
**Actualizado:** 2026-05-07 | **Total:** ~240 archivos | **Reorganizado:** 2026-05-07

---

## Carpetas activas usadas por el agente

| Carpeta (relativa a SHAREPOINT_DIR) | Tool que la usa | Patrón de nombre de archivo |
|---|---|---|
| `Control de Gestión\CDG Mensual\{YYYY}\` | `gestion_renta_tools` | `{AAMM} Control De Gestión Renta Comercial*.xlsx` |
| `Control de Gestión\Balances Consolidados\{YYYY}\{Q}\` | `balance_consolidado_tools` | `{MM.YYYY}- Balance Consolidado Rentas {fondo}*.xlsx` |
| `Control de Gestión\Saldo Caja\{YYYY}\` | `caja_tools` | `{YYMMDD} Saldo Caja + FFMM Inmobiliario.xlsx` |
| `Control de Gestión\Cálculo TIR\` | `gestion_renta_tools` | `Cálculo TIR Fondo Rentas*.xlsx` |
| `Rent Rolls\JLL\{YYYY}\` | `noi_tools`, `rentroll_tools` | `{AAMM} Rent Roll y NOI.xlsx` |
| `Fondos\Rentas TRI\Activos\Viña Centro\Rent Roll\{YYYY}\` | `rentroll_tools` | `Excel Tres A Viña {Mes} {YYYY}.xlsx` |
| `Fondos\Rentas TRI\Activos\Curicó\Rent Roll\{YYYY}\` | `rentroll_tools` | `Excel Tres A Curicó {Mes} {YYYY}.xlsx` |
| `Fondos\Rentas TRI\Activos\Viña Centro\EEFF\{YYYY}\` | `noi_tools` | `{MM-YYYY} INFORME EEFF VIÑA CENTRO SPA*.xlsx` |
| `Fondos\Rentas TRI\Activos\Curicó\EEFF\{YYYY}\` | `noi_tools` | `{MM-YYYY} INFORME EEFF POWER CENTER CURICO SPA.xlsx` |
| `Fondos\Rentas TRI\Activos\INMOSA\Flujos\{YYYY}\` | `noi_tools` | `ER-FC INMOSA {YYYY} Ene a {mes}.xlsx` |
| `Fondos\Apoquindo\EEFF\{YYYY}\{Q}\` | `eeff_tools` | `Toesca Rentas Inmobiliarias Apoquindo {YYYY} {MM}*.pdf` |
| `Fondos\Parque Titanium\EEFF\{YYYY}\{Q}\` | `eeff_tools`, `balance_consolidado_tools` | `EEFF {YYYYMM} Toesca FI Rentas PT Final.pdf` |
| `Fondos\Rentas TRI\EEFF\Fondo\{YYYY}\{Q}\` | `eeff_tools` | `{YYYY} EEFF Toesca Rentas Inmobiliarias*.pdf` |
| `Fondos\Rentas TRI\EEFF\Activos\Boulevard\` | `balance_consolidado_tools` | `{MM-YYYY} - Análisis Inmobiliaria Boulevard PT.xlsx` |
| `Fondos\Rentas TRI\EEFF\Activos\Torre A\` | `balance_consolidado_tools` | `{MM-YYYY} - Análisis Torre A.xlsx` |
| `Fondos\Apoquindo\Fact Sheets\{YYYY}\{Mes}\` | `factsheet_tools` | `{AAMM} Fact Sheet - Toesca Rentas Inmobiliarias Apoquindo*.pptx` |
| `Fondos\Parque Titanium\Fact Sheets\{YYYY}\` | `factsheet_tools` | `{AAMM} Fact Sheet - Toesca Rentas Inmobiliarias PT*.pptx` |
| `Fondos\Rentas TRI\Fact Sheets\{YYYY}\{Mes}\` | `factsheet_tools` | `{AAMM} Fact Sheet - Toesca Rentas Inmobiliarias*.pptx` |
| `RAW\` | `raw_tools` | (cualquier archivo — el agente lo reclasifica) |

> **Nota:** `{AAMM}` = año+mes 2 dígitos (ej. `2603`). `{Q}` = trimestre (`1T`, `2T`, `3T`, `4T`).

---

## Carpeta RAW — flujo de entrada

```
Usuario sube archivo a RAW/ → llama al agente → ordenar_archivos_raw() → mueve al destino correcto
```

Patrones reconocidos automáticamente:
- `{AAMM} Rent Roll y NOI.xlsx` → `Rent Rolls/JLL/{YYYY}/`
- `Excel Tres A Viña*.xlsx` → `Fondos/Rentas TRI/Activos/Viña Centro/Rent Roll/{YYYY}/`
- `Excel Tres A Curicó*.xlsx` → `Fondos/Rentas TRI/Activos/Curicó/Rent Roll/{YYYY}/`
- `*INFORME EEFF POWER CENTER CURICO*.xlsx` → `Fondos/Rentas TRI/Activos/Curicó/EEFF/{YYYY}/`
- `*INFORME EEFF VIÑA CENTRO*.xlsx` → `Fondos/Rentas TRI/Activos/Viña Centro/EEFF/{YYYY}/`
- `ER-FC INMOSA*.xlsx` → `Fondos/Rentas TRI/Activos/INMOSA/Flujos/{YYYY}/`
- `{AAMM} Control De Gestión Renta Comercial*.xlsx` → `Control de Gestión/CDG Mensual/{YYYY}/`
- `*Saldo Caja*.xlsx` → `Control de Gestión/Saldo Caja/{YYYY}/`
- `*Toesca Rentas Inmobiliarias Apoquindo*.pdf` → `Fondos/Apoquindo/EEFF/{YYYY}/{Qt}/`
- `*Toesca FI Rentas PT*.pdf` → `Fondos/Parque Titanium/EEFF/{YYYY}/{Qt}/`
- `*EEFF Toesca Rentas Inmobiliarias*.pdf` → `Fondos/Rentas TRI/EEFF/Fondo/{YYYY}/{Qt}/`
- `*Fact Sheet*Apoquindo*.pptx` → `Fondos/Apoquindo/Fact Sheets/{YYYY}/{Mes}/`
- `*Fact Sheet*PT*.pptx` → `Fondos/Parque Titanium/Fact Sheets/{YYYY}/`
- `*Fact Sheet*Toesca Rentas Inmobiliarias*.pptx` → `Fondos/Rentas TRI/Fact Sheets/{YYYY}/{Mes}/`

---

## Árbol completo (2026-05-07, post-reorganización)

### RAW/
```
(vacía — carpeta de entrada para archivos nuevos)
```

### Fondos/
```
Apoquindo/                                     ← Toesca Rentas Inmobiliarias Apoquindo
  EEFF/
    2025/4T/
      Toesca Rentas Inmobiliarias Apoquindo 2025 12 con Opinión.pdf
  Fact Sheets/
    2025/ [4 PDFs: 2502, 2504, 2507, 2510]
    2026/
      Enero/
        2601 Fact Sheet - Toesca Rentas Inmobiliarias Apoquindo vActualizar.pptx
        2601 Fact Sheet - Toesca Rentas Inmobiliarias Apoquindo.pdf

Parque Titanium/                               ← Toesca Rentas Inmobiliarias PT
  EEFF/
    2025/4T/
      EEFF 202512 Toesca FI Rentas PT Final.pdf
  Fact Sheets/
    2025/ [4 PDFs: 2502, 2504, 2507, 2510]
    2026/
      2601 Fact Sheet - Toesca Rentas Inmobiliarias PT vRevisar.pptx
      2601 Fact Sheet - Toesca Rentas Inmobiliarias PT.pdf

Rentas TRI/                                    ← Toesca Rentas Inmobiliarias (TRI)
  EEFF/
    Fondo/                                     ← EEFF consolidado del fondo
      2025/4T/
        2025 EEFF Toesca Rentas Inmobiliarias - final.pdf
    Activos/                                   ← EEFF de SPVs y filiales
      Boulevard/
        12-2025 - Análisis Inmobiliaria Boulevard PT.xlsx
        EEFF 31-12-2025 Boulevard.pdf
      Torre A/
        12-2025 - Análisis Torre A.xlsx
        EEFF 31-12-2025 Torre A.pdf
      Chañarcillo/
        EEFF 31-12-2025 Chañancillo.pdf
      Inmobiliaria Apoquindo/
        EEFF Inmobiliaria Apoquindo 12-2025 con Opinión.pdf
      Inmobiliaria VC/
        EEFF 31-12-2025 Inmobiliaria VC.pdf
  Fact Sheets/
    2017..2025/ [histórico: ~107 archivos]
    2026/
      Enero/
        2601 Fact Sheet - Toesca Rentas Inmobiliarias vRevisar.pptx
        2601 Fact Sheet - Toesca Rentas Inmobiliarias.pdf
  Activos/
    Viña Centro/
      EEFF/
        2026/
          01-2026 INFORME EEFF VIÑA CENTRO SPA V3.xlsx
          02-2026 INFORME EEFF VIÑA CENTRO SPA.xlsx
          (archivo adicional)
      Rent Roll/
        2025/
          Excel Tres A Viña Diciembre 2025.xlsx
          Excel Tres A Viña Octubre 2025.xlsx
        2026/
          Excel Tres A Viña Enero 2026.xlsx
          Excel Tres A Viña Febrero 2026.xlsx
          Excel Tres A Viña Marzo 2026.xlsx
    Curicó/
      EEFF/
        2026/
          01-2026 INFORME EEFF POWER CENTER CURICO SPA.xlsx
          (archivo adicional)
      Rent Roll/
        2026/
          Excel Tres A Curicó Febrero 2026.xlsx
          Excel Tres A Curicó Marzo 2026.xlsx
    INMOSA/
      Flujos/
        2026/
          ER-FC INMOSA 2026 Ene a Feb.xlsx

Residencial/                                   ← Fondo Renta Residencial (no automatizado)
  3Q25 Comité de Vigilancia Toesca Renta Residencial.pptx
  2601 Control De Gestión Renta Residencial vNuevo.xlsx
  2601 Fact Sheet - Toesca Renta Residencial.pptx
  Recaudación mensual 2025 - Diciembre 26 2025.xlsx
  Recaudacion mensual diciembre 262025.xlsx
```

### Control de Gestión/
```
CDG Mensual/                                   ← Archivos mensuales CDG Renta Comercial
  2021/ [9 archivos CDG + 2 RR]
  2022/ [12 archivos CDG]
  2023/ [12 archivos CDG]
  2024/ [11 archivos CDG — falta 2407]
  2025/
    2501..2512 Control De Gestión Renta Comercial.xlsx  [12 archivos]
    ⚠ 2508 tiene doble espacio en nombre: "2508  Control De Gestión..."
    ⚠ 2510 tiene sufijo: "2510 Control De Gestión Renta Comercial - corregido.xlsx"
  2026/
    2601 Control De Gestión Renta Comercial vF.xlsx
    2602 Control De Gestión Renta Comercial vF.xlsx
    2603 Control De Gestión Renta Comercial vActualizar.xlsx

Balances Consolidados/
  2025/4Q/
    12.2025- Balance Consolidado Rentas Apoquindo vF.xlsx
    12.2025- Balance Consolidado Rentas Apoquindo vRevisar.xlsx
    12.2025- Balance Consolidado Rentas Nuevo vF.xlsx
    12.2025- Balance Consolidado Rentas Nuevo vRevisar.xlsx
    12.2025- Balance Consolidado Rentas PT vAgente.xlsx
    12.2025- Balance Consolidado Rentas PT vF.xlsx
    12.2025- Balance Consolidado Rentas PT vRevisar.xlsx

Saldo Caja/
  2025/
    250310 Saldo Caja + FFMM Inmobiliario.xlsx
    250317 Saldo Caja + FFMM Inmobiliario.xlsx
    250331 Saldo Caja + FFMM Inmobiliario.xlsx
    250414 Saldo Caja + FFMM Inmobiliario.xlsx
    250428 Saldo Caja + FFMM Inmobiliario.xlsx
    250505 Saldo Caja + FFMM Inmobiliario.xlsx
    250526 Saldo Caja + FFMM Inmobiliario.xlsx
    250528 Saldo Caja + FFMM Inmobiliario.xlsx
    250602 Saldo Caja + FFMM Inmobiliario.xlsx
  2026/
    260413 Saldo Caja + FFMM Inmobiliario.xlsx

Cálculo TIR/
  Cálculo TIR Fondo Rentas (act. sept-25).xlsx
```

### Rent Rolls/
```
JLL/
  2025/
    2509 Rent Roll y NOI.xlsx
    2510 Rent Roll y NOI.xlsx
    2511 Rent Roll y NOI.xlsx
    2512 Rent Roll y NOI.xlsx
  2026/
    2601 Rent Roll y NOI.xlsx
```

### Informes de Mercado/
```
Bodegas/
  2025/
    1S 2025/ Reporte Bodegas_1S_2025.pdf
    2S 2025/ Reporte Bodegas_2S_2025.pdf
Oficinas/
  4T 2025/ JLL Chile - Informe de oficinas 4T 2025.pdf
```

### Referencia/
```
Residencial/ [4 PDFs: 2502, 2504, 2507, 2510]
TRI/         [4 PDFs: 2502, 2504, 2507, 2510]
```

---

## Anomalías conocidas

| Archivo | Anomalía |
|---|---|
| `2508  Control De Gestión Renta Comercial.xlsx` | Doble espacio en nombre |
| `2510 Control De Gestión Renta Comercial - corregido.xlsx` | Sufijo " - corregido" inesperado |

---

## Carpetas sin automatización

- `Fondos/Residencial/` — renta residencial, no automatizada
- `Informes de Mercado/` — PDFs de mercado externos
- `Referencia/` — ejemplos de cierres trimestrales (solo lectura)
