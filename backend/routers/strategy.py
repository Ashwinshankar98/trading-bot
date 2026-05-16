from fastapi import APIRouter
from database import get_connection

router = APIRouter(prefix="/strategy", tags=["strategy"])

@router.get("/")
def list_versions():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM strategy_versions ORDER BY version DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@router.get("/active")
def get_active():
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM strategy_versions WHERE is_active = 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else {}

@router.post("/{version}/activate")
def activate_version(version: int):
    conn = get_connection()
    conn.execute("UPDATE strategy_versions SET is_active = 0")
    conn.execute(
        "UPDATE strategy_versions SET is_active = 1 WHERE version = ?", (version,)
    )
    conn.commit()
    conn.close()
    return {"activated": version}
