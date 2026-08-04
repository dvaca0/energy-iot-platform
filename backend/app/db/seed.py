from datetime import datetime, UTC

from app.db.database import SessionLocal, Base, engine
from app.db.models import (
    Delegation,
    Campus,
    OrganizationalUnit,
    Building,
    ElectricalPanel,
    Node,
    Deployment,
    TariffPeriod,
)


def get_or_create(db, model, defaults=None, **kwargs):
    item = db.query(model).filter_by(**kwargs).first()
    if item:
        return item

    data = dict(kwargs)
    if defaults:
        data.update(defaults)

    item = model(**data)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def seed():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    delegations_data = {
        "Manzanillo": ["El Naranjo", "San Pedrito", "Valle de las Garzas", "Santiago", "El Colomo"],
        "Tecomán": ["Campus Tecomán"],
        "Colima": ["Campus Central", "Campus Norte"],
        "Coquimatlán": ["Campus Coquimatlán"],
        "Villa de Álvarez": ["Campus Villa de Álvarez"],
    }

    campuses = {}

    for delegation_name, campus_names in delegations_data.items():
        delegation = get_or_create(
            db,
            Delegation,
            name=delegation_name,
            defaults={"municipality": delegation_name},
        )

        for campus_name in campus_names:
            campus = get_or_create(
                db,
                Campus,
                name=campus_name,
                defaults={
                    "location": f"{campus_name}, Colima, México",
                    "delegation_id": delegation.id,
                },
            )
            campuses[campus_name] = campus

    units = [
        ("Escuela de Mercadotecnia", "school", "Campus Central"),
        ("Facultad de Ciencias", "faculty", "Campus Central"),
        ("Facultad de Ciencias de la Educación", "faculty", "Campus Central"),
        ("Facultad de Telemática", "faculty", "Campus Norte"),
        ("Facultad de Trabajo Social", "faculty", "Campus Central"),
        ("Facultad de Ciencias Políticas y Sociales", "faculty", "Campus Central"),
        ("Facultad de Contabilidad y Administración Colima", "faculty", "Campus Central"),
        ("Facultad de Derecho", "faculty", "Campus Central"),
        ("Facultad de Enfermería", "faculty", "Campus Central"),
        ("Facultad de Psicología", "faculty", "Campus Central"),
        ("Facultad de Letras y Comunicación", "faculty", "Campus Central"),
        ("Facultad de Medicina", "faculty", "Campus Central"),
        ("Instituto Universitario de Bellas Artes", "institute", "Campus Central"),

        ("Facultad de Arquitectura y Diseño", "faculty", "Campus Coquimatlán"),
        ("Facultad de Ciencias Químicas", "faculty", "Campus Coquimatlán"),
        ("Facultad de Ingeniería Civil", "faculty", "Campus Coquimatlán"),
        ("Facultad de Ingeniería Mecánica y Eléctrica", "faculty", "Campus Coquimatlán"),

        ("Escuela de Filosofía", "school", "Campus Villa de Álvarez"),
        ("Facultad de Pedagogía", "faculty", "Campus Villa de Álvarez"),
        ("Facultad de Economía", "faculty", "Campus Villa de Álvarez"),
        ("Facultad de Turismo", "faculty", "Campus Villa de Álvarez"),
        ("Facultad de Lenguas Extranjeras", "faculty", "Campus Villa de Álvarez"),

        ("Facultad de Contabilidad y Administración Tecomán", "faculty", "Campus Tecomán"),
        ("Facultad de Ciencias Biológicas y Agropecuarias", "faculty", "Campus Tecomán"),
        ("Facultad de Medicina Veterinaria y Zootecnia", "faculty", "Campus Tecomán"),

        ("Facultad de Turismo y Gastronomía", "faculty", "Valle de las Garzas"),
        ("Facultad de Ciencias Marinas", "faculty", "El Naranjo"),
        ("Facultad de Contabilidad y Administración Manzanillo", "faculty", "Valle de las Garzas"),
        ("Facultad de Ingeniería Electromecánica", "faculty", "El Naranjo"),
        ("Facultad de Comercio Exterior", "faculty", "Valle de las Garzas"),

        ("Rectoría", "administrative", "Campus Central"),
        ("Biblioteca Central", "library", "Campus Central"),
        ("Centro de Cómputo", "technical", "Campus Central"),
        ("Data Center", "technical", "Campus Central"),
        ("Servicios Universitarios Central", "services", "Campus Central"),
        ("Servicios Universitarios Norte", "services", "Campus Norte"),
        ("Servicios Universitarios Coquimatlán", "services", "Campus Coquimatlán"),
        ("Servicios Universitarios Villa de Álvarez", "services", "Campus Villa de Álvarez"),
        ("Servicios Universitarios Tecomán", "services", "Campus Tecomán"),
        ("Servicios Universitarios Manzanillo", "services", "Valle de las Garzas"),
    ]


    extra_dependencies = [
        ("Centro de Periodismo Universitario", "center", "Campus Central"),
        ("Centro de Tecnología Educativa", "center", "Campus Central"),
        ("Centro Universitario de Análisis Estadísticos y de Opinión Pública", "center", "Campus Central"),
        ("Centro Universitario de Estudios e Investigaciones sobre la Cuenca del Pacífico-Centro de Estudios APEC", "center", "Campus Central"),
        ("Centro Universitario de Estudios Vulcanológicos", "center", "Campus Central"),
        ("Centro Universitario de Gestión Ambiental", "center", "Campus Central"),
        ("Centro Universitario de Investigaciones Biomédicas", "center", "Campus Central"),
        ("Centro Universitario de Investigaciones Jurídicas", "center", "Campus Central"),
        ("Centro Universitario de Investigaciones Oceanológicas", "center", "El Naranjo"),
        ("Centro Universitario de Investigaciones Sociales", "center", "Campus Central"),
        ("Centro Universitario para la Igualdad y los Estudios de Género", "center", "Campus Central"),
        ("Centros Especializados de Idiomas", "center", "Campus Central"),
        ("Contraloría General", "administrative", "Campus Central"),
        ("Secretaría General", "administrative", "Campus Central"),
        ("Tesorería General", "administrative", "Campus Central"),
        ("Dirección General de Administración Escolar", "administrative", "Campus Central"),
        ("Dirección General de Educación Superior", "administrative", "Campus Central"),
        ("Dirección General de Educación Media Superior", "administrative", "Campus Central"),
        ("Dirección General de Servicios Universitarios", "services", "Campus Central"),
        ("Dirección General de Servicios Telemáticos", "technical", "Campus Central"),
        ("Dirección General de Recursos Humanos", "administrative", "Campus Central"),
        ("Dirección General de Obras Materiales", "administrative", "Campus Central"),
        ("Dirección General de Planeación y Desarrollo Institucional", "administrative", "Campus Central"),
        ("Dirección General de Prensa", "administrative", "Campus Central"),
        ("Coordinación General Administrativa y Financiera", "administrative", "Campus Central"),
        ("Coordinación General de Docencia", "administrative", "Campus Central"),
        ("Coordinación General de Investigación", "administrative", "Campus Central"),
        ("Coordinación General de Extensión", "administrative", "Campus Central"),
        ("Coordinación General de Vinculación", "administrative", "Campus Central"),
        ("CEGAF", "administrative", "Campus Central"),
        ("DIGESET", "technical", "Campus Central"),
    ]

    for item in extra_dependencies:
        if item not in units:
            units.append(item)


    org_units = {}

    for name, unit_type, campus_name in units:
        campus = campuses[campus_name]
        unit = get_or_create(
            db,
            OrganizationalUnit,
            name=name,
            defaults={
                "unit_type": unit_type,
                "campus_id": campus.id,
            },
        )
        org_units[name] = unit

    starter_buildings = [
        ("B-FIME-001", "Edificio Principal FIME", "Facultad de Ingeniería Mecánica y Eléctrica", "Campus Coquimatlán"),
        ("B-FIME-002", "Laboratorio de Redes", "Facultad de Ingeniería Mecánica y Eléctrica", "Campus Coquimatlán"),
        ("B-SERV-COQ-001", "Servicios Universitarios Coquimatlán", "Servicios Universitarios Coquimatlán", "Campus Coquimatlán"),
        ("B-DC-001", "Data Center", "Data Center", "Campus Central"),
        ("B-RECT-001", "Rectoría", "Rectoría", "Campus Central"),
        ("B-BIB-001", "Biblioteca Central", "Biblioteca Central", "Campus Central"),
    ]

    buildings = {}

    for code, building_name, unit_name, campus_name in starter_buildings:
        building = get_or_create(
            db,
            Building,
            code=code,
            defaults={
                "name": building_name,
                "campus_id": campuses[campus_name].id,
                "organizational_unit_id": org_units[unit_name].id,
                "is_user_defined": False,
                "notes": "Registro inicial del sistema.",
            },
        )
        buildings[code] = building

        get_or_create(
            db,
            ElectricalPanel,
            name="Tablero Principal",
            building_id=building.id,
            defaults={
                "notes": "Panel creado como punto inicial. El técnico puede renombrarlo o crear más paneles.",
            },
        )

    node_1 = get_or_create(
        db,
        Node,
        code="N001",
        defaults={
            "name": "Edge Node 001",
            "ip_address": "100.64.1.10",
            "status": "online",
            "last_sync": datetime.now(UTC),
            "samples": 8640,
        },
    )

    node_2 = get_or_create(
        db,
        Node,
        code="N002",
        defaults={
            "name": "Edge Node 002",
            "ip_address": "100.64.1.11",
            "status": "online",
            "last_sync": datetime.now(UTC),
            "buffer_pending": 3,
            "samples": 6210,
        },
    )

    fime_building = buildings["B-FIME-001"]
    lab_building = buildings["B-FIME-002"]

    fime_panel = db.query(ElectricalPanel).filter_by(building_id=fime_building.id, name="Tablero Principal").first()
    lab_panel = db.query(ElectricalPanel).filter_by(building_id=lab_building.id, name="Tablero Principal").first()

    db.add_all([
        Deployment(
            node_id=node_1.id,
            building_id=fime_building.id,
            electrical_panel_id=fime_panel.id,
            start_date="2025-01-06",
            end_date="2025-01-13",
            status="active",
            notes="Despliegue inicial de prueba.",
        ),
        Deployment(
            node_id=node_2.id,
            building_id=lab_building.id,
            electrical_panel_id=lab_panel.id,
            start_date="2025-01-06",
            end_date="2025-01-13",
            status="active",
            notes="Monitoreo de laboratorio.",
        ),
    ])
    db.commit()

    tariff_periods = [
        ("base", 0, 6, 1.0375),
        ("intermediate", 6, 9, 1.8463),
        ("peak", 9, 13, 2.0789),
        ("intermediate", 13, 16, 1.8463),
        ("peak", 16, 18, 2.0789),
        ("intermediate", 18, 22, 1.8463),
        ("base", 22, 24, 1.0375),
    ]

    for period_name, start_hour, end_hour, price in tariff_periods:
        db.add(
            TariffPeriod(
                tariff_name="GDMTH",
                period_name=period_name,
                start_hour=start_hour,
                end_hour=end_hour,
                price_per_kwh_mxn=price,
                is_active=True,
            )
        )

    db.commit()
    db.close()

    print("UdeC hierarchy seeded successfully.")


if __name__ == "__main__":
    seed()
