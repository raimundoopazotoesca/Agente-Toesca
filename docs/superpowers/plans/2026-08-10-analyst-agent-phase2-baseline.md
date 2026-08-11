# Phase 2 Baseline (frozen at commit 1c93aef)

## Test suite

Pre-existing full suite (unrelated to analyst work):
```
python -m pytest tests/ -q
→ 10 failed, 486 passed, 1 xfailed, 3 errors in 237.97s
```

Analyst-scoped baseline:
```
python -m pytest tests/analyst tests/test_db_chat.py -q
→ 66 passed in 2.15s
```

## Eval (extract_intent only, tests/eval/questions.yaml, 18 questions)

```
[MISS] ¿cómo ha evolucionado la vacancia de Parque Titanium este año?
    esperado: metric=vacancia_pct entities={'fondo': 'PT'}
    obtenido: metric=None entities={} confidence=0.0
[MISS] vacancia de bodegas en Apoquindo
    esperado: metric=vacancia_pct entities={'fondo': 'Apo'}
    obtenido: metric=None entities={} confidence=0.0
[OK] ¿y el mes anterior?
    esperado: metric=None entities=None
    obtenido: metric=None entities={} confidence=0.0
    nota: requiere conversation_state previo -- correr despues de una pregunta de vacancia en la misma sesion
[MISS] NOI de Viña Centro en los últimos 12 meses
    esperado: metric=noi entities={'activo': 'Viña Centro'}
    obtenido: metric=None entities={} confidence=0.0
[MISS] compara el NOI de Apo y PT este año
    esperado: metric=noi entities=None
    obtenido: metric=None entities={} confidence=0.0
[MISS] dividend yield con amortización de la serie A de TRI
    esperado: metric=dividend_yield entities={'fondo': 'TRI'}
    obtenido: metric=None entities={} confidence=0.0
[MISS] ¿cuál es la TIR desde inicio bursátil de la serie C?
    esperado: metric=tir_desde_inicio entities={'fondo': 'TRI'}
    obtenido: metric=tir_desde_inicio entities={'fondo': 'serie C'} confidence=1.0
[MISS] tasa de arriendo ajustada contable de Apo3001
    esperado: metric=tasa_arriendo entities={'activo': 'Apo3001'}
    obtenido: metric=None entities={} confidence=0.0
    nota: Apo3001 pertenece a TRI, no a Apo -- valida entity_resolver/relationships.yaml
[OK] ¿cómo viene Parque Titanium?
    esperado: metric=None entities=None
    obtenido: metric=None entities={} confidence=0.0
    nota: ambiguo -- debe pedir aclaracion o cubrir mas de una metrica, no elegir una sola sin avisar
[MISS] vacancia del fondo TRI por tipo de activo
    esperado: metric=vacancia_pct entities={'fondo': 'TRI'}
    obtenido: metric=None entities={} confidence=0.0
[OK] NOI de enero 2024 de PT
    esperado: metric=noi entities={'fondo': 'PT'}
    obtenido: metric=noi entities={'fondo': 'PT'} confidence=1.0
[MISS] ¿la vacancia de Curicó está sobre 100%?
    esperado: metric=vacancia_pct entities={'activo': 'Mall Curicó'}
    obtenido: metric=None entities={} confidence=0.0
    nota: result_checks debe marcar violado si el dato ejecutado supera 100
[MISS] dividend yield de las tres series de TRI, sin amortización
    esperado: metric=dividend_yield entities={'fondo': 'TRI'}
    obtenido: metric=None entities={} confidence=0.0
[MISS] ¿qué fondo tiene menor vacancia hoy?
    esperado: metric=vacancia_pct entities=None
    obtenido: metric=None entities={} confidence=0.0
[MISS] TIR contable desde inicio de Apo
    esperado: metric=tir_desde_inicio entities={'fondo': 'Apo'}
    obtenido: metric=None entities={} confidence=0.0
[MISS] renta promedio UF/m2 en oficinas de Parque Titanium
    esperado: metric=tasa_arriendo entities=None
    obtenido: metric=None entities={} confidence=0.0
    nota: no hay formula UF/m2 de rent roll confirmada -- debe decir que esta pendiente de validar
[OK] capex de Viña Centro este año
    esperado: metric=None entities=None
    obtenido: metric=None entities={} confidence=0.0
    nota: capex no tiene YAML en esta fase -- debe decir explicitamente que no puede responder
[OK] muéstrame lo mismo para Viña Centro
    esperado: metric=None entities=None
    obtenido: metric=None entities={} confidence=0.0
    nota: sigue a una pregunta de NOI de PT en la misma sesion -- debe heredar metrica/periodo, cambiar solo entidad

Metric accuracy: 6/18
Entity accuracy: 8/18
```

## Known Phase 1 gaps (from repo inspection)

- intent.py / entity_resolver.py NOT called from tools/db_chat.py or scripts/ingesta_server.py.
- conversation_state only ever writes last_metric from db_chat.answer(); last_entities/last_period/last_analysis_type are never populated in the real flow.
- scripts/ingesta_server.py:336 uses request.remote_addr as session_id.
- Only 5 metrics have semantic/metrics/*.yaml (vacancia_pct, noi, dividend_yield, tir_desde_inicio, tasa_arriendo); _BUSINESS_CONTEXT in db_chat.py still hardcodes entity/synonym data that duplicates semantic/entities.yaml + synonyms.yaml.
