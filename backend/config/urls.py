from django.http import HttpResponse
from django.urls import path

from routing import views


def health(request):
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("api/health", health),
    path("api/geocode", views.geocode),
    path("api/reverse-geocode", views.reverse_geocode),
    path("api/plan", views.plan),
    path("api/plans/<str:plan_id>/heatmap", views.plan_heatmap),
]
