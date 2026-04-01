from sqlalchemy.orm import Session

from app.models import CollisionAlert, SpaceObject


def seed_space_objects(db: Session) -> None:
    if db.query(SpaceObject).count() > 0:
        return

    samples = [
        (25544, "STARLINK-25544", "payload", 550.0, 53.0),
        (39444, "ONEWEB-39444", "payload", 1200.0, 87.9),
        (44713, "IRIDIUM-NEXT-44713", "payload", 780.0, 86.4),
        (44714, "IRIDIUM-NEXT-44714", "payload", 781.0, 86.4),
        (43013, "IRIDIUM-NEXT-43013", "payload", 782.0, 86.4),
        (44238, "IRIDIUM-NEXT-44238", "payload", 783.0, 86.4),
        (50123, "CZ-5B DEBRIS-50123", "debris", 560.0, 41.0),
        (50211, "FALCON-9 UPPER-50211", "rocket", 540.0, 51.5),
    ]

    db.add_all(
        [
            SpaceObject(
                norad_id=norad_id,
                name=name,
                object_type=obj_type,
                altitude_km=altitude,
                inclination_deg=inc,
            )
            for norad_id, name, obj_type, altitude, inc in samples
        ]
    )
    db.flush()

    objects = {obj.name: obj for obj in db.query(SpaceObject).all()}
    starter_alerts = [
        ("ONEWEB-39444", "STARLINK-25544", 0.3, 2.0, 97.0),
        ("STARLINK-25544", "IRIDIUM-NEXT-44713", 0.8, 4.0, 93.0),
        ("IRIDIUM-NEXT-44714", "IRIDIUM-NEXT-43013", 1.5, 8.0, 86.0),
        ("IRIDIUM-NEXT-43013", "IRIDIUM-NEXT-44238", 2.1, 12.0, 80.0),
    ]
    for primary, secondary, miss, tca, risk in starter_alerts:
        db.add(
            CollisionAlert(
                primary_object_id=objects[primary].id,
                secondary_object_id=objects[secondary].id,
                miss_distance_km=miss,
                tca_hours=tca,
                risk_score=risk,
                impact_summary="Broadband connectivity",
                is_urgent=True,
            )
        )
    db.commit()
