from rest_framework import serializers


class RoomCodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=8)


class CreateRoomSerializer(serializers.Serializer):
    visibility = serializers.ChoiceField(choices=["open", "private"])
    password = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        visibility = attrs.get("visibility", "open")
        password = (attrs.get("password") or "").strip()
        if visibility == "private" and not password:
            raise serializers.ValidationError("Password is required for private rooms.")
        return attrs


class JoinRoomSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=8)
    password = serializers.CharField(required=False, allow_blank=True)
