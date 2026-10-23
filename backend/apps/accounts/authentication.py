from rest_framework.authentication import SessionAuthentication


class CookieSessionAuthentication(SessionAuthentication):
    def authenticate_header(self, request):
        return "Session"
