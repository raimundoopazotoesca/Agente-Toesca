from __future__ import annotations
import re, sqlite3, unicodedata
from dataclasses import dataclass
from pathlib import Path
from tools.entities.catalog import ENTITY_TYPES
from tools.entities.definitions import load_entity_definitions

_ENTITY_DEFINITIONS_PATH = Path(__file__).resolve().parents[2] / "semantic" / "entities.yaml"

def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"\w+", text))

# Series (A/C/I) are a fund-scoped qualifier, not a registered entity type
# (ENTITY_TYPES has no "serie"). Rather than fail the whole query on a
# compound mention like "TRI serie A" or "serie I de TRI", strip the
# qualifier before matching the fund and carry it separately in the
# candidate's evidence -- the fund resolution itself is unaffected by it.
_SERIE_SUFFIX_RE = re.compile(r"^(?P<fund>.+?)\s+serie\s+(?P<serie>[a-zA-Z]{1,3})$", re.IGNORECASE)
_SERIE_PREFIX_RE = re.compile(r"^serie\s+(?P<serie>[a-zA-Z]{1,3})\s+de\s+(?P<fund>.+)$", re.IGNORECASE)


def _split_serie_qualifier(text: str) -> tuple[str, str | None]:
    stripped = text.strip()
    match = _SERIE_SUFFIX_RE.match(stripped) or _SERIE_PREFIX_RE.match(stripped)
    if match:
        fund = match.group("fund").strip()
        if fund:
            return fund, match.group("serie").upper()
    return text, None

@dataclass(frozen=True)
class EntityCandidate:
    entity_type: str; entity_key: str; canonical_name: str; score: int; match_kind: str; parent_context: dict[str, str]; active: bool; evidence: dict[str, object]
    def as_dict(self): return self.__dict__

@dataclass(frozen=True)
class EntityResolution:
    status: str; query: str; normalized_query: str; candidates: tuple[EntityCandidate, ...]
    def as_dict(self): return {"status": self.status, "query": self.query, "normalized_query": self.normalized_query, "candidates": [c.as_dict() for c in self.candidates]}

class EntityResolver:
    def __init__(self, db_path: Path): self.db_path=Path(db_path)
    def resolve(self, query: str, entity_types: tuple[str, ...], fund: str | None=None) -> EntityResolution:
        q=normalize(query); candidates=[]
        conn=sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro",uri=True); conn.row_factory=sqlite3.Row
        try:
            for typ in entity_types:
                # Only funds carry a serie (A/C/I) qualifier in this domain --
                # stripping it for other entity types risks silently eating
                # real tokens of an asset/company name that happens to
                # contain the word "serie".
                type_query, serie = _split_serie_qualifier(query) if typ == "fund" else (query, None)
                type_q = normalize(type_query)
                serie_evidence = {"serie_qualifier": serie} if serie else {}
                canonical = load_entity_definitions(_ENTITY_DEFINITIONS_PATH).resolve_exact(type_query, typ)
                if canonical is not None:
                    candidates.append(EntityCandidate(typ, canonical.entity_id, canonical.canonical_name, 100,
                        "canonical_alias", {}, True, {"matched_fields": ["canonical_alias"], **serie_evidence}))
                    continue
                fuzzy = load_entity_definitions(_ENTITY_DEFINITIONS_PATH).resolve_fuzzy(type_query, typ)
                if fuzzy is not None:
                    candidates.append(EntityCandidate(typ, fuzzy.entity_id, fuzzy.canonical_name, 80,
                        "fuzzy_alias", {}, True, {"matched_fields": ["fuzzy_alias"], **serie_evidence}))
                    continue
                definition=ENTITY_TYPES[typ]; fields=(definition.key_field,definition.display_field,*definition.parent_context_fields,definition.active_field)
                rows=conn.execute(f"SELECT {','.join(x for x in fields if x)} FROM {definition.source_object}").fetchall()
                for row in rows:
                    if fund and row[definition.parent_context_fields[0]] != fund: continue
                    key,name=str(row[definition.key_field]),str(row[definition.display_field]); nk,nn=normalize(key),normalize(name)
                    # Deliberately no raw-substring tier here: matching any
                    # arbitrary character span (e.g. query "TRI" against
                    # "Strip Machali", which contains "tri" inside "Strip")
                    # produced cross-type noise that made bare, exact fund
                    # aliases look ambiguous against coincidental letter
                    # overlap. token_match already covers real word-level
                    # partial matches; anything looser isn't a safe signal.
                    kind,score=("exact_key",100) if type_q==nk else (("exact_display",95) if type_q==nn else (("token_match",40) if set(type_q.split()) and set(type_q.split()) <= set(nn.split()) else (None,0)))
                    if not score: continue
                    parent={f:str(row[f]) for f in definition.parent_context_fields if row[f] is not None}
                    active=not bool(definition.active_field and row[definition.active_field] is not None)
                    candidates.append(EntityCandidate(typ,key,name,score,kind,parent,active,{"matched_fields":[definition.key_field if kind=='exact_key' else definition.display_field], **serie_evidence}))
        finally: conn.close()
        candidates.sort(key=lambda c:(-c.score,c.entity_type,c.entity_key)); top=tuple(candidates[:5])
        if not top: status="not_found"
        elif len({candidate.entity_type for candidate in top}) > 1: status="ambiguous"
        elif len(top)>1 and top[0].score==top[1].score: status="ambiguous"
        elif top[0].score >= 95: status="resolved"
        else: status="low_confidence"
        return EntityResolution(status,query,q,top)
