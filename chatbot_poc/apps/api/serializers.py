from rest_framework import serializers
from chatbot_poc.apps.core.models import Document


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate_file(self, value):
        # Accept PDFs by content_type or filename suffix as a fallback
        content_type = getattr(value, "content_type", "")
        filename = getattr(value, "name", "")
        if content_type != "application/pdf" and not filename.lower().endswith(".pdf"):
            raise serializers.ValidationError("Uploaded file must be a PDF.")
        return value

    def create(self, validated_data):
        """
        Create and return a Document instance.
        """
        file = validated_data["file"]
        title = getattr(file, "name", "unnamed.pdf")
        doc = Document.objects.create(title=title, file=file)
        return doc
