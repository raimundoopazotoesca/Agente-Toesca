# Skill financiera — inventario e internalización

**Fecha:** 2026-07-24 · **Estado:** inventario entregado, **reimplementación no iniciada**
**Corresponde a:** ROADMAP F0.6

---

## 1. Resultado de la búsqueda: no hay copia recuperable

`~/.claude/skills/` **no existe** en esta máquina. No hay copia de
`real-estate-finance-expert` en el repositorio, en `work/`, ni en ningún otro sitio
accesible desde aquí.

**Lo que sí existe y es recuperable:**

1. **El contrato completo de la skill**, deducible de `tools/finance_tools.py`, que es
   el wrapper que la invoca (`from compute_or_fetch import obtener`).
2. **Los resultados ya calculados**, persistidos en `derived_kpi`: 6.246 filas, 15 KPIs,
   con su `formula` (nombre de receta versionada) y sus períodos.
3. **La metodología validada**, en el wiki, con fórmulas y **valores de referencia
   confirmados contra el CDG** — que es exactamente lo que se necesita para
   reimplementar y verificar.

Es decir: la skill como código está perdida en esta máquina, pero **su especificación y
su salida esperada no lo están**. La reimplementación es viable y verificable.

> **Antes de reimplementar: revisar la máquina Windows.** El proyecto vivía en
> `C:\Users\raimundo.opazo\automation_agent` y la skill en
> `C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert`. Si el directorio
> sigue ahí, recuperarlo evita reescribir ~15 KPIs. Aun así, **no se debe incorporar a
> ciegas**: aplicaría el mismo protocolo de §4.

---

## 2. Superficie de la skill

### Punto de entrada único

```python
compute_or_fetch.obtener(kpi, entidad_tipo, entidad_key, periodo, force_recompute=False)
# → {valor, unidad, fuente, recipe, persistido, advertencias, metadata}
```

Con caché: si el KPI ya está en `derived_kpi` lo devuelve; si no, lo calcula y persiste.

### Funciones del wrapper (`tools/finance_tools.py`, 278 líneas)

| Función | Qué hace |
|---|---|
| `calcular_indicador_financiero` | pasa directo a `obtener` |
| `calcular_dy_fondo` | DY bursátil, contable y con amortización para todas las series de un fondo |
| `calcular_tir_fondo` | 6 variantes de TIR por serie (desde inicio, YTD, U12M × contable/bursátil) |
| `listar_indicadores_disponibles` | catálogo estático (no consulta la skill) |
| `invalidar_cache_indicador` | solo devuelve instrucciones; no invalida nada |
| `verificar_skill` | diagnóstico de disponibilidad |

### KPIs efectivamente producidos (en `derived_kpi` hoy)

| KPI | Receta | Filas | Rango | ¿Lo usa el factsheet? |
|---|---|---:|---|---|
| `perfil_vencimiento` | `perfil_vencimiento_v1_v1` | 1.236 | 2017-12 → 2026-06 | **sí** |
| `duration_deuda` | `duration_deuda_v2` | 988 | 2017-12 → 2026-06 | **sí** |
| `ltc` | `ltc_v1` | 750 | 2020-01 → 2026-06 | no |
| `ltv` | `ltv_v1` | 750 | 2020-01 → 2026-06 | **sí** |
| `dscr` | `dscr_v1` | 649 | 2020-01 → 2026-06 | no |
| `dy` | `dy_v2` | 550 | 2018-03 → 2026-06 | **sí** |
| `dy_amort` | 3 recetas (`_v1`, `_contable_v1`, `_capital_v1`) | 550 | 2018-03 → 2026-06 | **sí** |
| `tir_bursatil_desde_inicio` | `tir_bursatil_desde_inicio_v1` | 388 | 2017-12 → 2026-06 | no directo |
| `rent_ytd_bursatil` | `rent_ytd_bursatil_v1` | 384 | 2018-03 → 2026-06 | no directo |
| `tir_bursatil_u12m` | `tir_bursatil_u12m_v1` | 357 | 2018-12 → 2026-06 | no directo |
| `tir_contable_desde_inicio` | `tir_contable_desde_inicio_v1` | 173 | 2017-12 → 2026-03 | no directo |
| `rent_ytd_contable` | `rent_ytd_contable_v1` | 167 | 2018-03 → 2026-03 | no directo |
| `tir_contable_u12m` | `tir_contable_u12m_v1` | 155 | 2018-12 → 2026-03 | no directo |
| `leverage_financiero` | `leverage_financiero_v1` | 105 | 2017-12 → 2026-03 | **sí** |
| `tir_contable_ytd` | `tir_contable_ytd_v1` | 24 | 2020-03 → 2025-12 | no directo |

**Consecuencia operativa:** el factsheet **no invoca la skill**; lee `derived_kpi`. Por eso
sigue funcionando sin ella. Lo que no se puede hacer hoy es **recalcular**: si entra un
período nuevo o se corrige un dato, esos 6 KPIs quedan congelados en su último valor.

### Dependencias externas del wrapper

- `sys.path.insert` a `~/.claude/skills/real-estate-finance-expert/scripts` — ruta absoluta fuera del repo.
- Rutas Windows absolutas hardcodeadas en 4 scripts: `scripts/clear_tir_cache.py:2`,
  `check_tri_vna3.py:2`, `check_tri_vna2.py:29`, `check_tri_flows.py:2`.
- La skill escribe directamente en `derived_kpi` de la DB del proyecto.
- Menciona un módulo interno `tir.py` con `_calcular_rent_ytd` (citado en el wiki).

---

## 3. Metodología disponible para reimplementar

`wiki/kpis_rentabilidad_fondos.md` documenta las fórmulas **con valores de referencia
validados contra el CDG** (corte MAR-2026). Ejemplos:

**TIR desde inicio, TRI series A/C/I** — método `tir_por_cuota`, flujos en UF/cuota:
aportes `-(monto_uf / cuotas_totales_serie)`, disminuciones `+(monto_uf / cuotas_evento)`,
dividendos `+monto_uf_cuota`, terminal `+precio_uf`; XIRR por bisección ACT/365.
Divisores fijos: A=526.079 · C=1.385.310 · I=908.887.
**Valores validados MAR-26 (libro):** A=0,434% · C=0,972% · I=1,072%.

**Rentabilidad YTD anualizada** (corregida y congelada en 2026-07):
`YTD = (1 + XIRR(flujos))^(MES(corte)/12) − 1`.
**Valores validados MAR-26:** A libro 1,209% / bursátil 9,822% · C 1,255% / −0,289% ·
I 1,274% / −0,289% · PT 1,110% / −0,289% · Apo 2,298% (sin bursátil).

El wiki advierte explícitamente el error metodológico ya corregido (exponente por días
vs por meses calendario), lo que evita repetirlo.

Cobertura de la documentación:
- `wiki/kpis_rentabilidad_fondos.md` → TIR, YTD, U12M, DY
- `wiki/tir_contable_desde_inicio.md` → metodología canónica de TIR desde inicio
- `wiki/kpis_noi_cap_rate_apo.md` → NOI/ingresos, caja mínima, tasa de arriendo, cap rate
- **Sin documentar:** `ltv`, `ltc`, `dscr`, `duration_deuda`, `perfil_vencimiento`,
  `leverage_financiero`. De estos hay valores en `derived_kpi` pero no fórmula escrita.

---

## 4. Plan de internalización (propuesto, no ejecutado)

Módulo destino: `tools/finance/`, versionado en el repo, sin rutas absolutas.

| Paso | Alcance | Criterio de aceptación |
|---|---|---|
| 0 | Buscar la copia en Windows | Si aparece: inventariar funciones, dependencias y rutas antes de mover nada. **No incorporar a ciegas.** |
| 1 | **Congelar la salida actual como golden**: exportar `derived_kpi` de los 15 KPIs a un fixture | Existe un baseline reproducible contra el que comparar |
| 2 | Reimplementar los **6 KPIs que usa el factsheet** (`dy`, `dy_amort`, `ltv`, `duration_deuda`, `perfil_vencimiento`, `leverage_financiero`) | Cada uno reproduce el golden dentro de tolerancia, y los valores MAR-26 del wiki al 4º decimal |
| 3 | Reimplementar TIR y rentabilidades (7 KPIs) | Valores validados del wiki reproducidos exactamente |
| 4 | `ltc` y `dscr` | Sin documentación previa: requieren **derivar la fórmula desde los datos y validarla contigo** antes de darlas por buenas |
| 5 | Eliminar `finance_tools.py`, el `sys.path` externo y las 4 rutas Windows | `grep` sin resultados; la suite pasa |

**Regla:** ningún KPI reimplementado reemplaza al valor histórico hasta que reproduzca el
golden. Si diverge, se investiga la diferencia — no se sobrescribe.

**Encaje con F1.1:** la reimplementación debe entrar como recetas versionadas dentro del
orquestador de KPIs, no como scripts sueltos. Es la oportunidad de darles `ingest_run_id`
y trazabilidad, que hoy no tienen (99,8% de `derived_kpi` sin corrida).

---

## 5. Decisiones que requieren tu validación

1. **¿Existe la carpeta en Windows?** Es la diferencia entre recuperar y reescribir.
2. **`ltc` y `dscr`** no tienen metodología escrita. ¿Se reimplementan (habría que
   reconstruir la fórmula y validarla) o se marcan obsoletos? Ningún output los usa.
3. **Orden**: ¿internalizar antes de F1.1 (orquestador) o como parte de él? Recomiendo
   como parte de él: evita hacer el trabajo dos veces.
