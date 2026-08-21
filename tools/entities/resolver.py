from __future__ import annotations
import re, sqlite3, unicodedata
from dataclasses import dataclass
from pathlib import Path
from tools.entities.catalog import ENTITY_TYPES

def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"\w+", text))

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
                definition=ENTITY_TYPES[typ]; fields=(definition.key_field,definition.display_field,*definition.parent_context_fields,definition.active_field)
                rows=conn.execute(f"SELECT {','.join(x for x in fields if x)} FROM {definition.source_object}").fetchall()
                for row in rows:
                    if fund and row[definition.parent_context_fields[0]] != fund: continue
                    key,name=str(row[definition.key_field]),str(row[definition.display_field]); nk,nn=normalize(key),normalize(name)
                    kind,score=("exact_key",100) if q==nk else (("exact_display",95) if q==nn else (("token_match",40) if set(q.split()) and set(q.split()) <= set(nn.split()) else (("substring",15) if q and q in nn else (None,0))))
                    if not score: continue
                    parent={f:str(row[f]) for f in definition.parent_context_fields if row[f] is not None}
                    active=not bool(definition.active_field and row[definition.active_field] is not None)
                    candidates.append(EntityCandidate(typ,key,name,score,kind,parent,active,{"matched_fields":[definition.key_field if kind=='exact_key' else definition.display_field]}))
        finally: conn.close()
        candidates.sort(key=lambda c:(-c.score,c.entity_type,c.entity_key)); top=tuple(candidates[:5])
        if not top: status="not_found"
        elif len(top)>1 and top[0].score==top[1].score: status="ambiguous"
        elif top[0].score >= 95: status="resolved"
        else: status="low_confidence"
        return EntityResolution(status,query,q,top)
