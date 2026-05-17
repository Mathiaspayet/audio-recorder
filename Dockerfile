# Image de base : Python 3.12, version "slim" (légère).
FROM python:3.12-slim

# ffmpeg sert à la fois à enregistrer le flux RTSP et à analyser le son.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# On installe d'abord les dépendances Python (mises en cache par Docker).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Puis on copie le code de l'application.
COPY app.py .
COPY static/ static/

# Port du serveur web à l'intérieur du conteneur.
EXPOSE 8080

CMD ["python", "app.py"]
