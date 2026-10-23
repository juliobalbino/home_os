from django.db import connections
from django.db.utils import DatabaseError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        try:
            connections["default"].ensure_connection()
        except DatabaseError:
            return Response(
                {"status": "unhealthy", "database": "unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"status": "ok", "database": "connected"})
