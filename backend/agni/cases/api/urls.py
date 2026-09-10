from django.urls import path

from . import views

urlpatterns = [
    path("premises", views.PremisesListView.as_view(), name="premises"),
    path("premises/<uuid:premises_id>", views.PremisesDetailView.as_view(), name="premises-detail"),
]
