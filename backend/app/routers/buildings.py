from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Building

router = APIRouter()

@router.get("")
def list_buildings(db: Session = Depends(get_db)):
    buildings = db.query(Building).all()

    return [
        {
            "id": b.id,
            "code": b.code,
            "name": b.name,
            "campus": b.campus.name if b.campus else None,
            "delegation": b.campus.delegation.name if b.campus and b.campus.delegation else None,
            "organizational_unit": b.organizational_unit.name if b.organizational_unit else None,
            "unit_type": b.organizational_unit.unit_type if b.organizational_unit else None,
            "is_user_defined": b.is_user_defined,
            "is_placeholder": b.is_placeholder,
            "notes": b.notes,
        }
        for b in buildings
    ]


@router.get("/{building_id}")
def get_building(building_id: int, db: Session = Depends(get_db)):
    building = db.query(Building).filter(Building.id == building_id).first()

    if not building:
        return {"error": "building_not_found"}

    return {
        "id": building.id,
        "code": building.code,
        "name": building.name,
        "campus": building.campus.name if building.campus else None,
        "delegation": building.campus.delegation.name if building.campus and building.campus.delegation else None,
        "organizational_unit": building.organizational_unit.name if building.organizational_unit else None,
        "unit_type": building.organizational_unit.unit_type if building.organizational_unit else None,
        "is_user_defined": building.is_user_defined,
        "is_placeholder": building.is_placeholder,
        "notes": building.notes,
    }
