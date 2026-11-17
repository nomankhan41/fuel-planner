"""Domain errors. Each carries the HTTP status the API should return."""


class FuelPlannerError(Exception):
    status_code = 400
    code = "error"


class InvalidInput(FuelPlannerError):
    status_code = 400
    code = "invalid_input"


class PlaceNotFound(FuelPlannerError):
    status_code = 404
    code = "place_not_found"


class RouteNotFound(FuelPlannerError):
    status_code = 422
    code = "route_not_found"


class UnreachableRoute(FuelPlannerError):
    """No fuel station within range somewhere along the route."""
    status_code = 422
    code = "unreachable"


class RoutingServiceError(FuelPlannerError):
    status_code = 502
    code = "routing_service_error"


class GeocodingServiceError(FuelPlannerError):
    """Raised only when the API fails AND the local fallback has nothing to offer."""
    status_code = 502
    code = "geocoding_service_error"
