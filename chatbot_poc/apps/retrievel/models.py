from django.db import models

class QueryLog(models.Model):
    query = models.TextField()
    response = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=True)
    
    def __str__(self):
        return f"Query at {self.created_at}"