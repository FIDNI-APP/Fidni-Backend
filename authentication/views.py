from rest_framework import status, views
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from users.serializers import (
    UserSerializer,
)


import logging
logger = logging.getLogger('django')


#----------------------------LOGIN-------------------------------
class LoginView(views.APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # Skip authentication


    def post(self, request):
        identifier = request.data.get('identifier')
        password = request.data.get('password')

        if not all([identifier, password]):
            return Response(
                {'error': 'Please provide email/username and password'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Try to find user by email or username
        try:
            if '@' in identifier:
                user = User.objects.get(email=identifier)
            else:
                user = User.objects.get(username=identifier)
        except User.DoesNotExist:
            return Response(
                {'error': 'Invalid credentials'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Authenticate with username
        user = authenticate(username=user.username, password=password)
        if user is None:
            return Response(
                {'error': 'Invalid credentials'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        login(request, user)
        return Response(UserSerializer(user).data)


#----------------------------REGISTER-------------------------------

class RegisterView(views.APIView):
    permission_classes = [AllowAny]
    queryset = User.objects.all()
    serializer_class = UserSerializer
    authentication_classes = []  # Skip authentication


    def post(self, request):
        username = request.data.get('username')
        email = request.data.get('email')
        password = request.data.get('password')

        if not all([username, email, password]):
            return Response(
                {'error': 'Please provide all required fields'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if User.objects.filter(username=username).exists():
            return Response(
                {'error': 'Username already exists'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if User.objects.filter(email=email).exists():
            return Response(
                {'error': 'Email already exists'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )

        login(request, user)
        return Response(UserSerializer(user).data)
    

#----------------------------LOGOUT-------------------------------

class LogoutView(views.APIView):
    authentication_classes = []  # Skip authentication

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_200_OK)