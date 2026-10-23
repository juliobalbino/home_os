from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import User


def csrf_response(request):
    failure = CsrfViewMiddleware(lambda req: None).process_view(
        request, lambda req: None, (), {}
    )
    if failure is not None:
        return Response({"detail": "CSRF token ausente ou inválido."}, status=403)
    return None


@api_view(["GET"])
@permission_classes([AllowAny])
def csrf(request):
    return Response({"csrfToken": get_token(request)})


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    rejected = csrf_response(request)
    if rejected:
        return rejected
    email = str(request.data.get("email", "")).strip().lower()
    name = str(request.data.get("name", "")).strip()
    password = str(request.data.get("password", ""))
    if not email or "@" not in email or not name or len(password) < 12:
        return Response(
            {
                "detail": "Informe email válido, nome e senha com ao menos 12 caracteres."
            },
            status=400,
        )
    if User.objects.filter(email=email).exists():
        return Response({"email": ["Este email já está cadastrado."]}, status=400)
    user = User.objects.create_user(email=email, name=name, password=password)
    login(request, user)
    return Response(
        {"id": user.pk, "email": user.email, "name": user.name},
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    rejected = csrf_response(request)
    if rejected:
        return rejected
    user = authenticate(
        request,
        username=str(request.data.get("email", "")).strip().lower(),
        password=request.data.get("password", ""),
    )
    if user is None:
        return Response({"detail": "Email ou senha incorretos."}, status=400)
    login(request, user)
    return Response({"id": user.pk, "email": user.email, "name": user.name})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    logout(request)
    return Response({"detail": "Sessão encerrada."})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(
        {"id": request.user.pk, "email": request.user.email, "name": request.user.name}
    )
