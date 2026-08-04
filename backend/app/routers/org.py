from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Building, Campus, Delegation, ElectricalPanel, OrganizationalUnit

router = APIRouter()


@router.get("/delegations")
def list_delegations(db: Session = Depends(get_db)):
    return db.query(Delegation).all()


@router.get("/campuses")
def list_campuses(db: Session = Depends(get_db)):
    return db.query(Campus).all()


@router.get("/campuses/by-delegation/{delegation_id}")
def campuses_by_delegation(delegation_id: int, db: Session = Depends(get_db)):
    return db.query(Campus).filter(Campus.delegation_id == delegation_id).all()


@router.get("/units")
def list_units(db: Session = Depends(get_db)):
    return db.query(OrganizationalUnit).all()


@router.get("/units/by-campus/{campus_id}")
def units_by_campus(campus_id: int, db: Session = Depends(get_db)):
    return db.query(OrganizationalUnit).filter(OrganizationalUnit.campus_id == campus_id).all()


@router.get("/buildings")
def list_buildings(db: Session = Depends(get_db)):
    buildings = db.query(Building).all()

    return [
        {
            "id": building.id,
            "code": building.code,
            "name": building.name,
            "campus_id": building.campus_id,
            "campus": building.campus.name,
            "delegation": building.campus.delegation.name,
            "organizational_unit_id": building.organizational_unit_id,
            "organizational_unit": building.organizational_unit.name,
            "unit_type": building.organizational_unit.unit_type,
            "is_user_defined": building.is_user_defined,
            "notes": building.notes,
        }
        for building in buildings
    ]


@router.get("/buildings/by-unit/{unit_id}")
def buildings_by_unit(unit_id: int, db: Session = Depends(get_db)):
    buildings = db.query(Building).filter(Building.organizational_unit_id == unit_id).all()

    return [
        {
            "id": building.id,
            "code": building.code,
            "name": building.name,
            "campus_id": building.campus_id,
            "campus": building.campus.name,
            "delegation": building.campus.delegation.name,
            "organizational_unit_id": building.organizational_unit_id,
            "organizational_unit": building.organizational_unit.name,
            "unit_type": building.organizational_unit.unit_type,
            "is_user_defined": building.is_user_defined,
            "notes": building.notes,
        }
        for building in buildings
    ]


@router.get("/panels/by-building/{building_id}")
def panels_by_building(building_id: int, db: Session = Depends(get_db)):
    return db.query(ElectricalPanel).filter(ElectricalPanel.building_id == building_id).all()
