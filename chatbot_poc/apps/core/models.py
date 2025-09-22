from django.db import models

class Document(models.Model):
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to="documents/", blank=True, null=True)  # <--- Add this
    content = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=50, default="pending") 

    def __str__(self):
        return self.title

class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True