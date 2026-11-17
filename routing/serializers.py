from rest_framework import serializers


class TripRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=120, help_text="'City, ST' or 'lat,lng' inside the USA")
    finish = serializers.CharField(max_length=120, help_text="'City, ST' or 'lat,lng' inside the USA")
    start_tank_full = serializers.BooleanField(
        default=False,
        help_text="false (default): tank starts empty, so every gallon of the trip is bought and costed. "
                  "true: tank starts full and only fuel bought en route is costed.",
    )

    def validate(self, attrs):
        if attrs["start"].strip().lower() == attrs["finish"].strip().lower():
            raise serializers.ValidationError("start and finish must be different.")
        return attrs
