# Stage 5.4 — Dynamic Coverage: diseño v3 (cierra bypass B.3/raw_text, no implementado)

Mantiene de [v2](toesca-analyst-stage5.4-dynamic-coverage-design-v2.md): `governed_dataset`, `complete|partial|unknown`, `run_sql` sin `ToolEvidence`, `governed_dataset_ref`, `governed_dataset_claims`, coverage guard separado del canonical scalar guard. Corrige: dónde ocurre la validación (no en B.3), cómo se cierra `text/raw_text`, y la condición de scope certainty. Agrega hallazgo de preflight temporal.

## 1. Por qué B.3 no puede cerrar el raw-only bypass

`OpenAIResponsesFinalPresenter.present(user_message, draft_answer)` (presentation.py:41-63) recibe solo dos strings. `_integrity_status` (presentation.py:66-79) compara el draft contra sí mismo/contra el texto presentado — no tiene acceso a `SynthesisEnvelope`, `governed_dataset_claims`, `ToolEvidence` ni `coverage`. Para el caso:

```
run_sql → draft libre "A, B, C" → presenter conserva "A, B, C"
```

no existe ningún dato de comparación: no hay claim, no hay evidencia gobernada, no hay número o identificador "correcto" contra el cual el draft pueda fallar la comparación estructural. B.3 solo puede detectar que el draft *cambió* entre etapas, no que sus entidades carecen de respaldo — esa prueba solo existe mientras `governed_dataset_claims`/`ToolEvidence.coverage` siguen en memoria, es decir, **antes** de que el texto se colapse a `(user_message, draft_answer)`. Ampliar el contrato de B.3 para pasarle evidencia sería exactamente el rediseño de B.3 que sigue prohibido. Conclusión: la validación de provenance de entidades debe ocurrir en un guard nuevo, pre-B.3, con el envelope completo disponible; B.3 solo recibe el draft ya validado (o ya degradado a fallback), sin cambios a su firma.

## 2. Guard pre-B.3 definitivo — Option A elegida

**Option B** (que structured finalization "obligue" a introducir entidades de dataset gobernado solo vía `governed_dataset_ref`) es una disciplina de construcción del envelope, no un mecanismo de bloqueo: nada impide que el modelo igual escriba los mismos identificadores en un fragment `text/raw_text` — seguiría siendo una instrucción de esquema sin enforcement, equivalente en la práctica a "pedirle" al modelo que no bypassee. No cierra el caso raw-only por sí sola.

**Option A — pre-B.3 entity provenance guard — es la elegida** y sí cierra el caso, con esta regla exacta:

- Compilar de `dim_activo`/`dim_fondo` (Entity Catalog) el conjunto cerrado de claves canónicas de entidad tipo `asset` (activo_key) por fondo — **exact match**, no fuzzy, no NLP.
- Para cada fragment `text`/`raw_text` del envelope: contar apariciones literales de claves canónicas de `asset` pertenecientes al mismo scope de fondo.
- **Si aparecen 2 o más claves canónicas distintas del mismo fondo dentro de un fragment `text/raw_text`**, esas claves deben estar todas presentes en el `entity_ids` de algún `governed_dataset_claims` de ese envelope cuya evidencia (`governed_dataset`) haya sido validada por el coverage guard. Si falta respaldo para alguna, la validación falla → fallback pre-B.3 (mismo tipo de degradación que hoy usa `_fallback`, pero disparado antes, no dentro de B.3).
- **Si aparece 0 o 1 clave canónica** en el fragment, el guard no se activa — protege explícitamente el análisis de un solo activo (no requiere respaldo de universo, consistente con la regla de sufficiency ya establecida en v1 §4).

Esto es determinístico (lookup en un vocabulario cerrado y ya existente, mismo tipo de operación que hace `canonical_guard.py` al bindear `claim_id`↔`evidence_id`), no usa NLP, no usa regex de intención, no usa keywords como "todos", no usa intent router. Cierra el caso raw-only: SQL devuelve filas con `activo_key` de PT (p.ej. "Torre A", "Boulevard", "Parking PT"), el modelo las escribe en `raw_text` sin `governed_dataset_ref` → 3 claves canónicas del mismo fondo sin respaldo → guard falla → fallback. Un query legítimo de un solo activo ("Apoquindo 3001 tuvo vacancia alta") con 1 clave canónica no se toca.

Option B se conserva como disciplina complementaria de diseño de prompt/esquema (preferir `governed_dataset_ref` cuando el resultado proviene de un `governed_dataset`), pero el cierre real del bypass es Option A.

## 3. Scope certainty — condición corregida

Reemplaza v2 §3 condición 1. Scope demostrado se cumple si **cualquiera** de:
- **Canonical key validada directamente**: el identificador de scope (p.ej. `fondo_key="TRI"`) es un match literal exacto contra el catálogo maestro (`dim_fondo`/`dim_activo`) sin ambigüedad posible — no existe hoy una clase `CanonicalScopeValidator` en el runtime; se propone como una función determinística mínima (lookup exacto contra `dim_fondo`/`dim_activo`, sin fuzzy matching), distinta de la lógica de desambiguación de `EntityResolver`. Aplica cuando el scope ya llega como clave canónica inequívoca (p.ej. tomada directamente de un query/parámetro estructurado) y no requiere resolución de lenguaje natural.
- **EntityResolver con `resolution_status == "resolved"`** (como en v2).

`ambiguous` / `low_confidence` / `not_found` siguen sin poder producir `complete` bajo ninguna vía.

## 4. Temporal preflight — hallazgo real (read-only, sin migraciones)

Consulta sobre `memory/agente_toesca_v2.db`, `dim_activo` (17 filas totales):

| fondo_key | activos | vigente_hasta NULL |
|---|---|---|
| Apo | 2 | 2 |
| PT | 3 | 3 |
| TRI | 12 | 11 |

Único activo con `vigente_hasta` no NULL: `Strip Machalí` (TRI) = `2025-08` — el activo ya divestido y documentado como excluido del portfolio.

**Hallazgo crítico**: `vigente_hasta = NULL` es, por convención ya establecida en el schema, "vigente indefinidamente / sin fecha de término" (activo activo, no dato faltante) — NO es un valor "desconocido". Solo se rellena cuando el activo deja de estar vigente. Si la regla de v2 §3 ("NULL → temporal applicability indecidible → unknown") se aplica literalmente sin distinguir esto, **16 de 17 activos (94%)** forzarían `unknown` en casi cualquier consulta de universo completo, dejando coverage v1 prácticamente inútil (todo cae en `unknown`, nunca en `complete`).

No se cambia la regla (instrucción explícita del usuario). Se reporta el hallazgo para que la siguiente iteración de diseño decida si `vigente_hasta IS NULL` debe tratarse como "decidible = vigente" (dato ausente por convención, no por vacío) en vez de "indecidible", reservando `unknown` para casos donde el dato realmente falta por un problema de ingesta (no aplica a ningún registro actual — la distribución observada no tiene NULLs "sucios", todos son NULLs-por-convención).

## 5. Flujos (actualizados)

**Raw-only exhaustive attempt**: `run_sql` sin evidencia (v2 §4, sin cambios) → modelo escribe ≥2 claves canónicas de activo del mismo fondo en `raw_text` sin `governed_dataset_ref` → guard pre-B.3 (§2) detecta ausencia de respaldo → fallback antes de B.3 → B.3 recibe ya el draft degradado, sin cambio de contrato.

**Governed complete**: capability produce `governed_dataset` con universo determinístico (scope vía §3), todos los miembros con `vigente_hasta` decidible bajo la interpretación pendiente de §4, `observed_count==eligible_count` → `coverage.status="complete"` → `governed_dataset_ref` renderiza → guard pre-B.3 encuentra respaldo completo para todas las claves → sin caveat → B.3 presenta normal.

**Governed partial**: mismo camino, `observed_count<eligible_count` → `coverage.status="partial"` → coverage guard exige que el draft declare la limitación antes de llegar a B.3 → guard de provenance pasa (las entidades sí están respaldadas, solo que el conjunto es parcial y así se declara) → B.3 presenta el draft ya limitado.

**Unknown**: scope no cumple §3 (ni canonical key ni resolved) o universo no decidible bajo la regla vigente de §4 → `coverage.status="unknown"` → draft debe declarar incertidumbre explícita antes de B.3 → B.3 presenta ese draft tal cual, sin agregar ni quitar certeza.

## 6. GO / NO-GO definitivo

**GO** para pasar a implementación, con dos condiciones explícitas que deben resolverse en la fase de implementación (no bloquean el diseño en sí):
1. Confirmar en implementación la interpretación de `vigente_hasta IS NULL` (§4) antes de habilitar `complete` en producción — bajo la lectura literal actual, v1 sería casi siempre `unknown`, lo cual es seguro pero de bajo valor; bajo la lectura "NULL=vigente por convención", el preflight muestra que es viable declarar `complete` en la mayoría de los fondos.
2. Implementar `CanonicalScopeValidator` como función nueva y mínima (no existe hoy) — lookup exacto contra `dim_fondo`/`dim_activo`, sin lógica de desambiguación, claramente separada de `EntityResolver`.

El resto del diseño (v2 + guard pre-B.3 de Option A) queda cerrado y no requiere más iteraciones de bypass conocidas.
