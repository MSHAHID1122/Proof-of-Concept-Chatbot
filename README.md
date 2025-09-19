
Minimal Django project skeleton for a proof-of-concept (POC) document-centric chatbot using Haystack (deepset) or comparable tooling. The POC ingests PDFs, indexes them into a self-hosted vector store, and answers queries restricted to the uploaded documents.

Quickstart
1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. `python manage.py runserver`