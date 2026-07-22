"""Tests para tools.db.ingest_mercado."""
from __future__ import annotations

import pytest

from tools.db import ingest_mercado as mod
from tools.db.connection import apply_migrations, get_conn_for

TEXTO_JLL_Q3_2025 = """Clase
Inventario (m²)
Absorción neta trimestral (m²)
Absorción neta últimos 12 meses (m²)
Vacancia (%)
Renta pedida promedio (UF/m²/mes)
Renta pedida promedio (USD/m²/mes)
Producción trimestral (m²)
Producción últimos 12 meses (m²)
En construcción [2026-2029](m²)
Las Condes (CBD)
Total
1.733.422
9.388
39.913
5,6%
0,57
24,63
7.013
36.704
104.187
Providencia
Total
552.223
8.283
36.890
10,7%
0,49
21,42
0
25.000
17.218
Santiago Centro
Total
373.249
-7.786
8.316
10,6%
0,34
14,82
0
0
0
Vitacura
Total
173.394
4.284
9.313
10,0%
0,50
21,57
0
0
0
Ciudad empresarial
Total
260.433
6.997
10.896
6,8%
0,24
10,39
0
0
0
Estoril
Total
69.242
1.372
2.648
18,5%
0,40
17,37
0
0
0
Santiago
Total
3.161.963
22.538
107.976
7,7%
0,47
20,63
7.013
61.704
121.405
Las Condes (CBD)
A
1.076.580
3.652
27.452
5,4%
0,62
26,85
0
29.691
99.400
Providencia
A
156.895
6.658
28.527
23,6%
0,52
22,78
0
25.000
10.800
Santiago Centro
A
81.180
-4.281
1.752
17,8%
0,34
14,93
0
0
0
Santiago
A
1.314.655
6.028
57.731
8,3%
0,55
23,89
0
54.691
110.200
Las Condes (CBD)
B
656.842
5.737
12.461
6,0%
0,49
21,39
7.013
7.013
4.787
Providencia
B
395.328
1.625
8.363
5,5%
0,44
19,12
0
0
6.418
Santiago Centro
B
292.069
-3.505
6.564
8,6%
0,34
14,76
0
0
0
Vitacura
B
173.394
4.284
9.313
10,0%
0,50
21,57
0
0
0
Ciudad empresarial
B
260.433
6.997
10.896
6,8%
0,24
10,39
0
0
0
Estoril
B
69.242
1.372
2.648
18,5%
0,40
17,37
0
0
0
Santiago
B
1.847.308
16.510
50.245
7,3%
0,41
17,98
7.013
7.013
11.205
"""


TEXTO_JLL_FLAT_Q2_2026 = """Clase
Inventario
(m²)
Absorción neta
trimestral
(m²)
Absorción neta
últimos 12 meses
(m²)
Vacancia
(%)
Renta pedida
promedio
(UF/m²/mes)
Renta pedida
promedio
(USD/m²/mes)
Producción
trimestral
(m²)
Producción
últimos 12 meses
(m²)
En
Construcción
(m²)
Las Condes (CBD) Total 1.726.409 8.445 40.573 5,8% 0,55 24,03 0 29.691 111.200
Providencia Total 561.938 11.011 30.333 11,9% 0,50 21,64 0 47.885 17.218
Santiago Centro Total 373.249 2.696 13.456 8,5% 0,34 14,65 0 0 0
Vitacura Total 173.394 1.671 4.156 12,5% 0,49 21,53 0 0 0
Ciudad Empresarial Total 288.515 1.404 3.636 8,5% 0,24 10,56 0 0 0
Estoril Total 69.242 1.029 905 20,5% 0,39 17,20 0 0 0
Santiago Total 3.192.747 26.256 93.059 8,1% 0,47 20,40 0 77.576 128.418
Las Condes (CBD) A 1.076.580 5.675 30.304 5,7% 0,59 25,97 0 29.691 99.400
Providencia A 166.610 11.785 21.272 26,2% 0,52 22,84 0 47.885 10.800
Santiago Centro A 81.180 2.093 7.609 12,6% 0,31 13,41 0 0 0
Santiago A 1.324.370 19.553 59.186 8,7% 0,54 23,67 0 77.576 110.200
Las Condes (CBD) B 649.829 2.770 10.269 5,9% 0,48 20,92 0 0 11.800
Providencia B 395.328 -774 9.062 5,9% 0,44 19,43 0 0 6.418
Santiago Centro B 292.069 604 5.847 7,4% 0,35 15,24 0 0 0
Vitacura B 173.394 1.671 4.156 12,5% 0,49 21,53 0 0 0
Ciudad Empresarial B 288.515 1.404 3.636 8,5% 0,24 10,56 0 0 0
Estoril B 69.242 1.029 905 20,5% 0,39 17,20 0 0 0
Santiago B 1.868.377 6.703 33.874 7,7% 0,41 17,78 0 0 18.218
"""


def test_parse_tabla_jll_formato_plano_18_filas():
    filas = mod.parse_tabla_jll(TEXTO_JLL_FLAT_Q2_2026)
    assert len(filas) == 18


def test_parse_tabla_jll_formato_plano_pares_coinciden_con_expected():
    filas = mod.parse_tabla_jll(TEXTO_JLL_FLAT_Q2_2026)
    pares = {(f["submercado"], f["clase"]) for f in filas}
    assert pares == mod.EXPECTED_PARES


def test_parse_tabla_jll_formato_plano_normaliza_ciudad_empresarial():
    filas = mod.parse_tabla_jll(TEXTO_JLL_FLAT_Q2_2026)
    f = [f for f in filas if f["clase"] == "Total" and f["submercado"].lower() == "ciudad empresarial"][0]
    assert f["submercado"] == "Ciudad empresarial"
    assert f["inventario_m2"] == 288515.0


def test_parse_tabla_jll_formato_plano_negativo():
    filas = mod.parse_tabla_jll(TEXTO_JLL_FLAT_Q2_2026)
    f = [f for f in filas if f["submercado"] == "Providencia" and f["clase"] == "B"][0]
    assert f["absorcion_trim_m2"] == -774.0


def test_parse_num_cl_miles():
    assert mod._parse_num_cl("1.733.422") == 1733422.0


def test_parse_num_cl_porcentaje():
    assert mod._parse_num_cl("5,6%") == 5.6


def test_parse_num_cl_decimal():
    assert mod._parse_num_cl("0,57") == 0.57


def test_parse_num_cl_negativo():
    assert mod._parse_num_cl("-7.786") == -7786.0


def test_parse_num_cl_cero():
    assert mod._parse_num_cl("0") == 0.0


def test_parse_tabla_jll_18_filas():
    filas = mod.parse_tabla_jll(TEXTO_JLL_Q3_2025)
    assert len(filas) == 18


def test_parse_tabla_jll_primera_fila():
    filas = mod.parse_tabla_jll(TEXTO_JLL_Q3_2025)
    f = filas[0]
    assert f["submercado"] == "Las Condes (CBD)"
    assert f["clase"] == "Total"
    assert f["es_total"] == 0
    assert f["inventario_m2"] == 1733422.0
    assert f["absorcion_trim_m2"] == 9388.0
    assert f["absorcion_u12m_m2"] == 39913.0
    assert f["vacancia_pct"] == 5.6
    assert f["renta_uf_m2"] == 0.57
    assert f["renta_usd_m2"] == 24.63
    assert f["produccion_trim_m2"] == 7013.0
    assert f["produccion_u12m_m2"] == 36704.0
    assert f["construccion_m2"] == 104187.0


def test_parse_tabla_jll_fila_santiago_total_es_total():
    filas = mod.parse_tabla_jll(TEXTO_JLL_Q3_2025)
    santiago_total = [f for f in filas if f["submercado"] == "Santiago" and f["clase"] == "Total"][0]
    assert santiago_total["es_total"] == 1
    assert santiago_total["inventario_m2"] == 3161963.0


def test_parse_tabla_jll_absorcion_negativa():
    filas = mod.parse_tabla_jll(TEXTO_JLL_Q3_2025)
    sc_total = [f for f in filas if f["submercado"] == "Santiago Centro" and f["clase"] == "Total"][0]
    assert sc_total["absorcion_trim_m2"] == -7786.0


def test_parse_tabla_jll_pares_coinciden_con_expected():
    filas = mod.parse_tabla_jll(TEXTO_JLL_Q3_2025)
    pares = {(f["submercado"], f["clase"]) for f in filas}
    assert pares == mod.EXPECTED_PARES


def test_parse_tabla_jll_bloque_incompleto_lanza_error():
    texto_roto = "\n".join(TEXTO_JLL_Q3_2025.strip().splitlines()[:-3])  # corta el último bloque
    with pytest.raises(ValueError, match="bloques de 11"):
        mod.parse_tabla_jll(texto_roto)


def test_validate_ok(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_db_path)
    result = mod.validate(TEXTO_JLL_Q3_2025, "2025-09", "JLL")
    assert result.ok
    assert result.data["n_filas"] == 18
    assert result.data["periodo"] == "2025-09"
    assert result.data["file_hash"]


def test_validate_texto_vacio(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_db_path)
    result = mod.validate("", "2025-09", "JLL")
    assert not result.ok
    assert any("texto" in e.lower() for e in result.errors)


def test_validate_sin_periodo(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_db_path)
    result = mod.validate(TEXTO_JLL_Q3_2025, "", "JLL")
    assert not result.ok


def test_validate_proveedor_invalido(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_db_path)
    result = mod.validate(TEXTO_JLL_Q3_2025, "2025-09", "Colliers")
    assert not result.ok


def test_validate_faltan_filas(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_db_path)
    texto_incompleto = "\n".join(TEXTO_JLL_Q3_2025.strip().splitlines()[:-11])  # quita el último bloque
    result = mod.validate(texto_incompleto, "2025-09", "JLL")
    assert not result.ok
    assert any("faltan" in e.lower() for e in result.errors)


def test_commit_inserta_18_filas(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_db_path)
    summary = mod.commit(TEXTO_JLL_Q3_2025, "2025-09", "JLL")
    assert summary["status"] == "ok"
    assert summary["filas_insertadas"] == 18
    assert summary["filas_superseded"] == 0

    con = get_conn_for(tmp_db_path)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_oficinas WHERE superseded_at IS NULL"
        ).fetchone()[0]
        assert n == 18
    finally:
        con.close()


def test_commit_es_idempotente(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_db_path)
    mod.commit(TEXTO_JLL_Q3_2025, "2025-09", "JLL")
    summary2 = mod.commit(TEXTO_JLL_Q3_2025, "2025-09", "JLL")
    assert summary2["status"] == "skipped_duplicate"

    con = get_conn_for(tmp_db_path)
    try:
        n = con.execute("SELECT COUNT(*) FROM raw_mercado_oficinas").fetchone()[0]
        assert n == 18  # no se duplicó
    finally:
        con.close()


def test_commit_correccion_marca_superseded(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_db_path)
    mod.commit(TEXTO_JLL_Q3_2025, "2025-09", "JLL")

    texto_corregido = TEXTO_JLL_Q3_2025.replace("1.733.422", "1.733.999")
    summary2 = mod.commit(texto_corregido, "2025-09", "JLL")
    assert summary2["status"] == "ok"
    assert summary2["filas_superseded"] == 18
    assert summary2["filas_insertadas"] == 18

    con = get_conn_for(tmp_db_path)
    try:
        vigentes = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_oficinas WHERE superseded_at IS NULL"
        ).fetchone()[0]
        assert vigentes == 18
        total = con.execute("SELECT COUNT(*) FROM raw_mercado_oficinas").fetchone()[0]
        assert total == 36
    finally:
        con.close()
