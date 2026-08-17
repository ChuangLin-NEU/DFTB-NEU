from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import structure_mp

router = APIRouter(tags=["structure"])


class MpIn(BaseModel):
    query: str = ""
    material_id: str = ""
    limit: int = 8


@router.get("/structure/status")
def status():
    return structure_mp.mp_status()


@router.post("/structure/search")
def search(body: MpIn):
    try:
        return {"results": structure_mp.search_materials(body.query, limit=body.limit or 8)}
    except structure_mp.StructureError as e:
        raise HTTPException(400, str(e))


@router.post("/structure/fetch")
def fetch(body: MpIn):
    try:
        return structure_mp.fetch_poscar(body.query, material_id=body.material_id)
    except structure_mp.StructureError as e:
        raise HTTPException(400, str(e))
