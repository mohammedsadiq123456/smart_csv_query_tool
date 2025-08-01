from django.urls import path
from . import views

urlpatterns = [
    path('generate-code/', views.generate_code, name='generate_code'),
]
