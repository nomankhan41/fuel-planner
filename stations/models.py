from django.db import models
from django.utils import timezone


class Station(models.Model):
    """A US truck stop with its retail diesel price and resolved coordinates.

    `geo_source` tells where lat/lng came from:
      - "address"       -> US Census batch geocoder matched the street address
      - "city_centroid" -> fell back to the station's city/state coordinates
      - ""              -> not yet geocoded (new station awaiting geocode_stations)
    """

    opis_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2, db_index=True)
    price = models.FloatField(help_text="Retail price, USD per gallon")
    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)

    # Metadata for the incremental importer / geocoder.
    geo_source = models.CharField(max_length=20, blank=True, default="")
    geocoded_at = models.DateTimeField(null=True, blank=True)
    address_hash = models.CharField(max_length=40, blank=True, default="",
                                    help_text="Hash of (address, city, state); changes trigger re-geocode")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["state", "city", "name"]

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state}) ${self.price:.3f}"

    def has_coords(self) -> bool:
        return self.lat is not None and self.lng is not None


class GeocodeCache(models.Model):
    """Permanent DB cache of place-name geocoding results.

    A row per *normalised* user query. Hitting the external geocoder once per
    place ever means the "few API calls" rule is kept even across restarts.
    """

    query_key = models.CharField(max_length=200, unique=True, db_index=True,
                                 help_text="Normalised query, lowercase, single-spaced")
    label = models.CharField(max_length=200, help_text="Display label from the provider")
    lat = models.FloatField()
    lng = models.FloatField()
    source = models.CharField(max_length=20,
                              help_text='"ors" (API), "local" (us_cities.csv fallback), "coords" (user supplied)')
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.query_key} -> {self.label} ({self.source})"
