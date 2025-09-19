from django.urls import path
from . import views

urlpatterns = [
    path("upload/", views.UploadPDFView.as_view(), name="upload_pdf"),
    path("index/", views.TriggerIndexView.as_view(), name="trigger_index"),
    path("query/", views.QueryView.as_view(), name="query"),
    path("docs/<int:id>/status/", views.DocumentStatusView.as_view(), name="document_status"),
]
