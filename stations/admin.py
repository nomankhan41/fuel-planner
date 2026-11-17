from django.contrib import admin

from .models import GeocodeCache, Station


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "price", "geo_source", "geocoded_at")
    list_filter = ("state", "geo_source")
    search_fields = ("name", "city", "address")


@admin.register(GeocodeCache)
class GeocodeCacheAdmin(admin.ModelAdmin):
    list_display = ("query_key", "label", "source", "created_at")
    list_filter = ("source",)
    search_fields = ("query_key", "label")
