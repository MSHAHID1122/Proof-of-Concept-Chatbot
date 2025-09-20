from django.shortcuts import render

def frontend(request):
    return render(request, "index.html")  # Django will find it in frontend/