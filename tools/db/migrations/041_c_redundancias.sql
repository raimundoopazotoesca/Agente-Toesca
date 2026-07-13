-- C: Limpieza de redundancias verificadas por cross-check.
--
-- C1: raw_tir_fondo_line
--   49 filas, solo TRI. Cross-check exacto vs raw_ar_event_line + raw_dividendo_line:
--     Aportes:      -2,911,048.73 UF ← coincide con SUM(monto_uf) A&R Aporte
--     Disminución:      98,373.97 UF ← coincide exacto
--     Dividendos:      603,216.45 UF ← coincide con Σ(monto_uf_cuota × cuotas)
--   Cero consumidores en el código. Columnas canje_uf y vr_contable_uf siempre NULL.
--   → Tabla huérfana, dropear.

DROP TABLE IF EXISTS raw_tir_fondo_line;

-- C2: dim_credito.sociedad
--   Se mantiene la columna: 3/15 créditos están en sociedades legítimamente distintas
--   al holding del activo (Apo I, Apo II, Inmobiliaria VC SpA).
--   Los otros 11 tenían variaciones tipográficas del mismo ente → normalizados
--   contra dim_activo.sociedad.

UPDATE dim_credito SET sociedad = 'Inmobiliaria Chañarcillo Ltda'                       WHERE credito_key = 'TRI_SUCDEN_BICE';
UPDATE dim_credito SET sociedad = 'Inmobiliaria Chañarcillo Ltda'                       WHERE credito_key = 'TRI_APO3001_SCOTIABANK';
UPDATE dim_credito SET sociedad = 'Inmobiliaria Viña Centro SpA'                        WHERE credito_key = 'TRI_VINA_PRINCIPAL';
UPDATE dim_credito SET sociedad = 'Inmobiliaria e Inversiones Senior Assist Chile S.A.' WHERE credito_key IN
  ('TRI_MEDINA_METLIFE','TRI_CANDIL_METLIFE','TRI_PADREERRA_METLIFE',
   'TRI_COVENTRY_CONFUTURO','TRI_COLOMBIA_PRINCIPAL','TRI_DOMCALDERON_ZURIC');
UPDATE dim_credito SET sociedad = 'Torre A.S.A.'                                         WHERE credito_key = 'PT_TORREA_SECURITY';
UPDATE dim_credito SET sociedad = 'Inmobiliaria Boulevard PT SpA'                        WHERE credito_key = 'PT_BOULEVARD_SECURITY';
