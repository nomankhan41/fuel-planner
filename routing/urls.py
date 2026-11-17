from django.urls import path

from . import views

urlpatterns = [
    path("route/", views.TripView.as_view(), name="trip"),
    path("route/<str:trip_id>/map/", views.trip_map, name="trip-map"),
]
