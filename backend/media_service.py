from typing import Any, Dict, Optional

# Hand-picked photos that show the destination itself (matched on the destination NAME only: a region match
# would give every Rajasthan trip the Hawa Mahal). Unsplash's license needs no credit; we show one anyway.
_UNSPLASH = {"credit": "Unsplash", "creditUrl": "https://unsplash.com/"}
CATALOG = [
    ("goa", "https://images.unsplash.com/photo-1512343879784-a960bf40e7f2?auto=format&fit=crop&w=800&q=80",
     "Goa coastline and palm trees"),
    ("kolkata", "https://images.unsplash.com/photo-1558431382-27e303142255?auto=format&fit=crop&w=800&q=80",
     "Howrah Bridge Landmark in Kolkata"),
    ("kathmandu", "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=800&q=80",
     "Kathmandu Valley & Historic Temples"),
    ("kerala", "https://images.unsplash.com/photo-1602216056096-3b40cc0c9944?auto=format&fit=crop&w=800&q=80",
     "Kerala Backwaters & Houseboats"),
    ("manali", "https://images.unsplash.com/photo-1626621341517-bbf3d9990a23?auto=format&fit=crop&w=800&q=80",
     "Manali Snow Mountains"),
    ("jaipur", "https://images.unsplash.com/photo-1477587458883-47145ed94245?auto=format&fit=crop&w=800&q=80",
     "Jaipur Hawa Mahal Palace"),
]


class MediaService:
    """
    Destination cover resolver (server-side). Order: the catalog above (name match), then image_service
    (Wikipedia page of the destination, then Pexels), then NO picture: {"url": "", "provider": "none"} and the app
    shows its placeholder. Never a random photo.
    Result: {url, alt, provider, credit?, creditUrl?}. provider: catalog | wikipedia | pexels | none.
    """
    def resolve_cover_media(self, destination: Dict[str, Any]) -> Dict[str, Any]:
        raw_name = (destination.get("name") or "").strip()
        dest_name = raw_name.lower()

        for key, url, alt in CATALOG:
            if key in dest_name:
                return {"url": url, "alt": alt, "provider": "catalog", **_UNSPLASH}

        found: Optional[Dict[str, Any]] = None
        if raw_name:
            try:
                import image_service
                found = image_service.resolve_cover_image(
                    raw_name, destination.get("region") or "",
                    destination.get("latitude", destination.get("lat")),
                    destination.get("longitude", destination.get("lng")))
            except Exception as e:
                print(f"[COVER MEDIA] lookup skipped: {type(e).__name__}", flush=True)
        if found:
            return {"url": found["url"], "alt": raw_name, "provider": found["source"],
                    "credit": found.get("credit"), "creditUrl": found.get("credit_url")}

        return {"url": "", "alt": raw_name or "Trip destination", "provider": "none"}


media_service = MediaService()
