"""
Real places that trips point to (for now: a trip's starting city).

A city is stored once and reused: get_or_create_city looks it up by
normalized name + region and creates it only if it isn't there yet.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import Column, Float, String, UniqueConstraint
from sqlalchemy.orm import Session

from database import Base


class CityModel(Base):
    __tablename__ = "cities"

    id = Column(String, primary_key=True, index=True)
    lookup_key = Column(String, nullable=False)  # lower(name)|lower(region)
    name = Column(String, nullable=False)
    region = Column(String, nullable=True)
    country = Column(String, nullable=False, default="India")
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    created_at = Column(String, nullable=False)

    __table_args__ = (UniqueConstraint("lookup_key", name="uq_city_lookup_key"),)


def _lookup_key(name: str, region: Optional[str]) -> str:
    return f"{name.strip().lower()}|{(region or '').strip().lower()}"


def city_to_dict(city: Optional[CityModel]) -> Optional[Dict[str, Any]]:
    if not city:
        return None
    return {
        "id": city.id,
        "name": city.name,
        "region": city.region,
        "country": city.country,
        "latitude": city.latitude,
        "longitude": city.longitude,
        "displayName": ", ".join(p for p in [city.name, city.region, city.country] if p),
    }


def get_or_create_city(db: Session, place: Dict[str, Any]) -> CityModel:
    """
    `place` is a validated place dict (name, latitude, longitude, optional region/country).
    Returns the existing city with the same name + region, or creates it.
    Does not commit; the caller's transaction does.
    """
    name = place["name"].strip()
    region = (place.get("region") or "").strip() or None
    key = _lookup_key(name, region)

    city = db.query(CityModel).filter(CityModel.lookup_key == key).first()
    if city:
        return city

    city = CityModel(
        id=f"city_{uuid.uuid4().hex[:12]}",
        lookup_key=key,
        name=name,
        region=region,
        country=(place.get("country") or "India").strip() or "India",
        latitude=float(place["latitude"]),
        longitude=float(place["longitude"]),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(city)
    db.flush()
    return city
