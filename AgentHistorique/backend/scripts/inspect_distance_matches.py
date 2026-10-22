from app.database import SessionLocal
from sqlalchemy import text
from app.services.distance_service import build_distance_lookup

with SessionLocal() as session:
    rows = session.execute(text("SELECT id, name_fr FROM monuments ORDER BY id")).mappings().all()
    ids = [str(row["id"]) for row in rows if row.get("id") is not None]
    _, unresolved = build_distance_lookup(session, monument_ids=ids)
    print(f"monuments={len(ids)}")
    print(f"unresolved_pairs={len(unresolved)}")
    for pair in unresolved[:50]:
        print(pair)
