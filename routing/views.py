from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from services.exceptions import FuelPlannerError
from services.planner import get_cached_trip, plan_trip

from .serializers import TripRequestSerializer


class TripView(APIView):
    """Plan a trip: route + cheapest fuel stops + total fuel cost."""

    def post(self, request):
        return self._handle(request, request.data)

    def get(self, request):
        if "start" not in request.query_params:
            return Response({"usage": "POST {'start': 'City, ST', 'finish': 'City, ST'} "
                                      "or GET ?start=...&finish=..."})
        return self._handle(request, request.query_params)

    def _handle(self, request, data):
        ser = TripRequestSerializer(data=data)
        if not ser.is_valid():
            return Response({"error": "invalid_input", "details": ser.errors}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = plan_trip(**ser.validated_data)
        except FuelPlannerError as exc:
            return Response({"error": exc.code, "detail": str(exc)}, status=exc.status_code)
        result["map_url"] = request.build_absolute_uri(reverse("trip-map", args=[result["trip_id"]]))
        return Response(result)


def trip_map(request, trip_id):
    trip = get_cached_trip(trip_id)
    if trip is None:
        raise Http404("Trip not found or expired - request the route again.")
    return render(request, "routing/map.html", {"trip": trip})
