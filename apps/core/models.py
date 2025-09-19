# After modifying models: run
#   python manage.py makemigrations && python manage.py migrate

from django.db import models

class Document(models.Model):
    STATUS_UPLOADED = 'uploaded'
    STATUS_PROCESSING = 'processing'
    STATUS_INDEXED = 'indexed'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_UPLOADED, 'Uploaded'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_INDEXED, 'Indexed'),
        (STATUS_FAILED, 'Failed'),
    ]

    title = models.CharField(max_length=255)
    file = models.FileField(upload_to='documents/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_UPLOADED)
    text_extracted = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    def get_file_path(self):
        """
        Return absolute filesystem path to the uploaded file.
        """
        return self.file.path

    def __str__(self):
        return self.title