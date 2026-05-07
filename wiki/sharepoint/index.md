# SharePoint - estructura canonica

**Base:** `C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos`
**Actualizado:** 2026-05-07

Esta es la fuente de verdad para rutas. `RAW/` es solo bandeja de entrada; los archivos que ya tienen funcion conocida deben archivarse en su carpeta canonica.

## Principios

- `Control de Gestión/` contiene planillas transversales del equipo: CDG, balances consolidados, saldo caja y calculo TIR.
- `Fondos/` se ordena por vehiculo/fondo: `Rentas TRI`, `Rentas PT`, `Rentas Apoquindo`, `Renta Residencial`.
- En `Fondos/Rentas TRI/Activos/` van fuentes operativas por activo: rent rolls, EEFF de administradores, flujos y contabilidad operacional.
- En `Fondos/Rentas TRI/Sociedades/` van fuentes legales/contables usadas por balances consolidados: EEFF y analisis de SPVs o sociedades.
- `Rent Rolls/JLL/` queda separado porque el archivo JLL alimenta varios fondos/activos al mismo tiempo.
- `Referencia/` es solo lectura: ejemplos, formatos y materiales historicos no operativos.

## Rutas activas

| Flujo | Ruta canonica | Patron |
|---|---|---|
| CDG mensual | `Control de Gestión/CDG Mensual/{YYYY}/` | `{AAMM} Control De Gestión Renta Comercial*.xlsx` |
| Balances consolidados | `Control de Gestión/Balances Consolidados/{YYYY}/{Q}/` | `{MM.YYYY}- Balance Consolidado Rentas {fondo}*.xlsx` |
| Saldo Caja | `Control de Gestión/Saldo Caja/{YYYY}/` | `{YYMMDD} Saldo Caja + FFMM Inmobiliario.xlsx` |
| Calculo TIR | `Control de Gestión/Cálculo TIR/` | `Cálculo TIR Fondo Rentas*.xlsx` |
| RR JLL | `Rent Rolls/JLL/{YYYY}/` | `{AAMM} Rent Roll y NOI.xlsx` |
| RR Tres A Vina | `Fondos/Rentas TRI/Activos/Viña Centro/Rent Roll/{YYYY}/` | `Excel Tres A Viña {Mes} {YYYY}.xlsx` |
| RR Tres A Curico | `Fondos/Rentas TRI/Activos/Curicó/Rent Roll/{YYYY}/` | `Excel Tres A Curicó {Mes} {YYYY}.xlsx` |
| EEFF Vina | `Fondos/Rentas TRI/Activos/Viña Centro/EEFF/{YYYY}/` | `{MM-YYYY} INFORME EEFF VIÑA CENTRO SPA*.xlsx` |
| EEFF Curico | `Fondos/Rentas TRI/Activos/Curicó/EEFF/{YYYY}/` | `{MM-YYYY} INFORME*CURIC*.xlsx` |
| INMOSA flujos NOI | `Fondos/Rentas TRI/Activos/INMOSA/Flujos/{YYYY}/` | `ER-FC INMOSA*.xlsx` |
| INMOSA contabilidad | `Fondos/Rentas TRI/Activos/INMOSA/Contabilidad/{YYYY}/` | `*Senior Assist*.xlsx`, `Balance General*.xlsx` |
| INMOSA EEFF | `Fondos/Rentas TRI/Activos/INMOSA/EEFF/{YYYY}/` | `*EEFF INMOSA*.pdf` |
| EEFF fondo TRI | `Fondos/Rentas TRI/EEFF/Fondo/{YYYY}/{Q}/` | `*EEFF Toesca Rentas Inmobiliarias*.pdf` |
| Sociedades TRI | `Fondos/Rentas TRI/Sociedades/{sociedad}/{EEFF|Analisis}/{YYYY}/` | PDFs EEFF y analisis xlsx por sociedad |
| EEFF Rentas PT | `Fondos/Rentas PT/EEFF/{YYYY}/{Q}/` | `EEFF {YYYYMM} Toesca FI Rentas PT*.pdf` |
| EEFF Rentas Apoquindo | `Fondos/Rentas Apoquindo/EEFF/{YYYY}/{Q}/` | `Toesca Rentas Inmobiliarias Apoquindo {YYYY} {MM}*.pdf` |
| Fact Sheets TRI | `Fondos/Rentas TRI/Fact Sheets/{YYYY}/` o `{YYYY}/{Mes}/` | `{AAMM} Fact Sheet - Toesca Rentas Inmobiliarias*` |
| Fact Sheets PT | `Fondos/Rentas PT/Fact Sheets/{YYYY}/` | `{AAMM} Fact Sheet - Toesca Rentas Inmobiliarias PT*` |
| Fact Sheets Apoquindo | `Fondos/Rentas Apoquindo/Fact Sheets/{YYYY}/{Mes}/` | `{AAMM} Fact Sheet - Toesca Rentas Inmobiliarias Apoquindo*` |

## Sociedades TRI

Estas carpetas alimentan principalmente balances consolidados:

- `Fondos/Rentas TRI/Sociedades/Boulevard/EEFF/{YYYY}/`
- `Fondos/Rentas TRI/Sociedades/Boulevard/Analisis/{YYYY}/`
- `Fondos/Rentas TRI/Sociedades/Torre A/EEFF/{YYYY}/`
- `Fondos/Rentas TRI/Sociedades/Torre A/Analisis/{YYYY}/`
- `Fondos/Rentas TRI/Sociedades/Chañarcillo/EEFF/{YYYY}/`
- `Fondos/Rentas TRI/Sociedades/Chañarcillo/Analisis/{YYYY}/`
- `Fondos/Rentas TRI/Sociedades/Inmobiliaria VC/EEFF/{YYYY}/`
- `Fondos/Rentas TRI/Sociedades/Inmobiliaria VC/Analisis/{YYYY}/`
- `Fondos/Rentas TRI/Sociedades/Inmobiliaria Apoquindo/EEFF/{YYYY}/`
- `Fondos/Rentas TRI/Sociedades/Inmobiliaria Apoquindo/Analisis/{YYYY}/`

## RAW

`RAW/` debe quedar vacia salvo archivos recien recibidos o bloqueados. `ordenar_archivos_raw()` clasifica automaticamente los patrones conocidos.

Excepcion vigente al 2026-05-07:

- `RAW/Balance General 2025 Senior Assist.xlsx` quedo bloqueado por otro proceso. Hay copia canonica en `Fondos/Rentas TRI/Activos/INMOSA/Contabilidad/2025/`.

## Arbol resumido

```text
Control de Gestión/
  CDG Mensual/{YYYY}/
  Balances Consolidados/{YYYY}/{Q}/
  Saldo Caja/{YYYY}/
  Cálculo TIR/
Fondos/
  Rentas TRI/
    EEFF/Fondo/{YYYY}/{Q}/
    Fact Sheets/{YYYY}/
    Activos/
      Viña Centro/{EEFF,Rent Roll}/{YYYY}/
      Curicó/{EEFF,Rent Roll}/{YYYY}/
      INMOSA/{Flujos,EEFF,Contabilidad}/{YYYY}/
    Sociedades/{sociedad}/{EEFF,Analisis}/{YYYY}/
  Rentas PT/{EEFF,Fact Sheets}/
  Rentas Apoquindo/{EEFF,Fact Sheets}/
  Renta Residencial/
Rent Rolls/JLL/{YYYY}/
Informes de Mercado/
Referencia/
RAW/
```
