"""Mapa coroplético estático (SVG) de comunas de Santiago para la sección
INMOSA del factsheet TRI.

Geometría base: scripts/data/comunas_santiago_plain.svg — "Comunas de
Santiago (plain).svg" de Wikimedia Commons
(https://commons.wikimedia.org/wiki/File:Comunas_de_Santiago_(plain).svg,
CC BY-SA 2.5). Es el mismo mapa esquemático usado en la referencia visual
que se está replicando (silueta compacta del Gran Santiago, no el límite
administrativo/GIS completo de cada comuna).

Los <path> del SVG original se usan tal cual — mismo `d`, sin recalcular,
reproyectar ni simplificar. Cada comuna ya viene identificada por su propio
`id` (nombre de la comuna, con guion bajo en vez de espacio). Este módulo
solo:
  1. lee cada <path id=... d=...> del archivo original sin tocar `d`;
  2. le asigna fill/stroke gris o verde según si la comuna tiene activos;
  3. calcula un punto interior (anchor) SOLO para ubicar los puntos blancos
     — aproximando cada `d` (que puede traer curvas `C`) como una polilínea
     (los extremos de cada curva se usan como vértice), suficiente para un
     centroide/point-in-polygon visual, no para geometría de precisión.

Ver scripts/_fetch_wikimedia_svg.py para la descarga del archivo original.
"""
import math
import os
import re
import unicodedata

_SVG_PATH = os.path.join(os.path.dirname(__file__), "data", "comunas_santiago_plain.svg")

DOT_RADIUS = 4.5
DOT_SPACING = 11.5


def _norm(s: str) -> str:
    s = s.replace("_", " ")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.strip().lower()


def _load_paths() -> tuple[str, list[tuple[str, str]]]:
    """Devuelve (viewBox, [(id, d), ...]) en el orden original del archivo.

    El viewBox declarado en el SVG original ("0 0 612 792") no cubre toda
    la geometría — Las Condes y Lo Barnechea se extienden más allá de esos
    límites (el archivo original lo resuelve con style="overflow:visible"
    en la raíz, arriesgando desborde del contenedor al embeber). Acá se
    recalcula el viewBox como el bounding box real de todos los `d` — no
    se modifica ni un solo punto de ningún path, solo la ventana de
    coordenadas declarada."""
    content = open(_SVG_PATH, encoding="utf-8").read()
    paths = []
    for m in re.finditer(r"<path\b[^>]*>", content):
        tag = m.group(0)
        id_m = re.search(r'id="([^"]+)"', tag)
        d_m = re.search(r'd="([^"]+)"', tag)
        if id_m and d_m:
            paths.append((id_m.group(1), d_m.group(1)))

    pad = 6
    allx, ally = [], []
    for _, d in paths:
        for ring in _flatten_subpaths(d):
            for x, y in ring:
                allx.append(x)
                ally.append(y)
    minx, maxx, miny, maxy = min(allx), max(allx), min(ally), max(ally)
    view_box = f"{minx - pad:.2f} {miny - pad:.2f} {maxx - minx + 2 * pad:.2f} {maxy - miny + 2 * pad:.2f}"
    return view_box, paths


def _flatten_subpaths(d: str) -> list[list[tuple[float, float]]]:
    """Aproxima un `d` de SVG (M/L/C/Z, absoluto o relativo) como una o más
    polilíneas cerradas. Las curvas C se aproximan usando su punto final
    como vértice (suficiente para centroide / point-in-polygon)."""
    tokens = re.findall(r"[MmLlCcZz]|-?\d+(?:\.\d+)?(?:e-?\d+)?", d)
    subpaths: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    x = y = 0.0
    start_x = start_y = 0.0
    i = 0
    cmd = None
    while i < len(tokens):
        tok = tokens[i]
        if re.match(r"^[MmLlCcZz]$", tok):
            cmd = tok
            i += 1
            if cmd in "Zz":
                if cur:
                    subpaths.append(cur)
                    cur = []
                x, y = start_x, start_y
                continue
        nums_needed = {"M": 2, "m": 2, "L": 2, "l": 2, "C": 6, "c": 6}[cmd]
        vals = [float(tokens[i + k]) for k in range(nums_needed)]
        i += nums_needed
        if cmd in "Mm":
            if cmd == "m":
                x, y = x + vals[0], y + vals[1]
            else:
                x, y = vals[0], vals[1]
            if cur:
                subpaths.append(cur)
            cur = [(x, y)]
            start_x, start_y = x, y
            cmd = "l" if cmd == "m" else "L"  # subsecuentes pares implican lineto
        elif cmd in "Ll":
            if cmd == "l":
                x, y = x + vals[0], y + vals[1]
            else:
                x, y = vals[0], vals[1]
            cur.append((x, y))
        elif cmd in "Cc":
            if cmd == "c":
                ex, ey = x + vals[4], y + vals[5]
            else:
                ex, ey = vals[4], vals[5]
            x, y = ex, ey
            cur.append((x, y))
    if cur:
        subpaths.append(cur)
    return subpaths


def _ring_area_centroid(ring: list[tuple[float, float]]) -> tuple[tuple[float, float], float]:
    if ring[0] != ring[-1]:
        ring = ring + [ring[0]]
    a = cx = cy = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i]
        x1, y1 = ring[i + 1]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    a *= 0.5
    if abs(a) < 1e-9:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return (sum(xs) / len(xs), sum(ys) / len(ys)), 0.0
    return (cx / (6 * a), cy / (6 * a)), abs(a)


def _ray_cast(pt: tuple, ring: list) -> bool:
    x, y = pt
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi:
            inside = not inside
        j = i
    return inside


def _anchor_point(d: str) -> tuple[float, float]:
    """Punto interior visual del path (para ubicar los puntos blancos), sin
    depender de precisión geográfica: centroide del subpath de mayor área;
    si cae fuera (formas cóncavas), barrido en grilla sobre su bbox."""
    subpaths = _flatten_subpaths(d)
    best_area = -1.0
    best_ring = None
    best_centroid = None
    for ring in subpaths:
        if len(ring) < 3:
            continue
        centroid, area = _ring_area_centroid(ring)
        if area > best_area:
            best_area, best_ring, best_centroid = area, ring, centroid
    if best_ring is None:
        return 0.0, 0.0
    if _ray_cast(best_centroid, best_ring):
        return best_centroid
    xs = [p[0] for p in best_ring]
    ys = [p[1] for p in best_ring]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    steps = 24
    best_pt, best_d = None, None
    for i in range(steps + 1):
        for j in range(steps + 1):
            x = minx + (maxx - minx) * i / steps
            y = miny + (maxy - miny) * j / steps
            if _ray_cast((x, y), best_ring):
                dist = (x - best_centroid[0]) ** 2 + (y - best_centroid[1]) ** 2
                if best_d is None or dist < best_d:
                    best_d, best_pt = dist, (x, y)
    return best_pt or best_centroid


def _dot_cluster(cx: float, cy: float, n: int) -> str:
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    circles = []
    for i in range(n):
        row, col = divmod(i, cols)
        x = cx + (col - (cols - 1) / 2) * DOT_SPACING
        y = cy + (row - (rows - 1) / 2) * DOT_SPACING
        circles.append(f'<circle class="comuna-dot" cx="{x:.2f}" cy="{y:.2f}" r="{DOT_RADIUS}"/>')
    return "".join(circles)


def build_mapa_comunas_svg(conteo_por_comuna: list) -> str:
    """conteo_por_comuna: list[(nombre_comuna, n_activos)]. Usa el SVG de
    Wikimedia tal cual (mismo viewBox, mismo `d` por comuna) — no se
    reproyecta ni se reescala nada."""
    view_box, paths = _load_paths()
    conteo = {_norm(k): v for k, v in conteo_por_comuna}

    shapes, dots = [], []
    for comuna_id, d in paths:
        n = conteo.get(_norm(comuna_id), 0)
        cls = "presente" if n else "ausente"
        shapes.append(f'<path class="comuna-shape {cls}" d="{d}"/>')
        if n:
            cx, cy = _anchor_point(d)
            dots.append(_dot_cluster(cx, cy, n))

    return (
        f'<svg viewBox="{view_box}" xmlns="http://www.w3.org/2000/svg">'
        + "".join(shapes) + "".join(dots) + "</svg>"
    )
