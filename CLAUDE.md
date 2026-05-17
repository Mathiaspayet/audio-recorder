# Instructions projet — pour Claude Code

Ce fichier est lu automatiquement par Claude Code. Il décrit le projet et la
mission de mise en place. **L'utilisateur est débutant : explique chaque étape
simplement, en français, et demande confirmation avant toute action
irréversible (création de dépôt, envoi de code).**

---

## 1. Présentation du projet

`audio-recorder` est une petite application qui enregistre en continu le son
d'une caméra (flux RTSP), conserve quelques jours d'historique, et fournit un
tableau de bord web pour naviguer dans les enregistrements et repérer les
moments bruyants.

Elle tourne dans un conteneur Docker sur un NAS Synology.

### Chaîne de fonctionnement visée

```
  PC de l'utilisateur          GitHub                     NAS Synology
  ┌───────────────┐    push    ┌──────────────┐  pull   ┌──────────────┐
  │  ce dossier   │ ─────────► │ Actions      │ ──────► │ audio-recorder│
  │ (+ Claude Code)│           │ build image  │         │  + Watchtower │
  └───────────────┘            │ → ghcr.io    │         └──────────────┘
                               └──────────────┘   Watchtower surveille
                                                  ghcr.io et met à jour
                                                  le conteneur tout seul.
```

À chaque envoi de code sur `main`, GitHub Actions reconstruit l'image et la
publie sur `ghcr.io`. Sur le NAS, Watchtower détecte la nouvelle image et
remplace le conteneur automatiquement. L'utilisateur n'a rien à refaire.

---

## 2. Structure du dépôt

```
audio-recorder/
├── CLAUDE.md                 ← ce fichier
├── README.md                 ← guide pour l'utilisateur (NAS + usage)
├── .gitignore
├── .github/workflows/
│   └── build.yml             ← CI : construit et publie l'image
├── Dockerfile                ← recette de l'image
├── docker-compose.yml        ← déploiement NAS (image ghcr + Watchtower)
├── requirements.txt          ← dépendances Python
├── app.py                    ← application (enregistrement, analyse, web)
└── static/                   ← interface web
    ├── index.html
    ├── style.css
    └── app.js
```

---

## 3. MISSION DE MISE EN PLACE INITIALE

À effectuer une seule fois, avec l'utilisateur, dans cet ordre :

### Étape 1 — Identifier le compte GitHub

- Vérifie que l'outil `gh` (GitHub CLI) est installé et connecté :
  `gh auth status`. S'il ne l'est pas, guide l'utilisateur :
  `gh auth login`.
- Récupère son identifiant GitHub (`gh api user --jq .login`).
  Note-le **en minuscules** : on l'appellera `IDENTIFIANT`.

### Étape 2 — Adapter docker-compose.yml

- Dans `docker-compose.yml`, remplace `__GITHUB_USER__` par `IDENTIFIANT`
  (en minuscules). C'est la seule modification de fichier nécessaire.

### Étape 3 — Créer le dépôt et envoyer le code

- Initialise git si besoin : `git init`, branche `main`.
- `git add .` puis `git commit -m "Version initiale"`.
- Crée le dépôt GitHub et pousse le code :
  `gh repo create audio-recorder --private --source=. --remote=origin --push`
  (le dépôt peut être privé : le code ne contient aucun secret — l'URL RTSP
  et le mot de passe de la caméra restent uniquement sur le NAS).

### Étape 4 — Vérifier la construction de l'image

- Le workflow se lance tout seul après le push. Suis-le :
  `gh run watch` (ou `gh run list`).
- En cas d'échec, lis les journaux (`gh run view --log-failed`) et corrige.

### Étape 5 — Rendre l'image accessible au NAS

L'image publiée hérite de la visibilité du dépôt. Pour que le NAS puisse la
télécharger **sans identifiants**, le plus simple est de rendre le *package*
public (le code ne contient aucun secret, c'est sans risque) :

- Explique à l'utilisateur d'aller sur la page du package sur GitHub
  (`https://github.com/users/IDENTIFIANT/packages/container/audio-recorder/settings`),
  rubrique « Danger Zone » → « Change visibility » → **Public**.
- Alternative : laisser le package privé et configurer des identifiants de
  registre sur le NAS — plus complexe, à éviter pour un débutant.

### Étape 6 — Passer la main

- Indique l'adresse de l'image :
  `ghcr.io/IDENTIFIANT/audio-recorder:latest`.
- Renvoie l'utilisateur vers le `README.md` pour l'installation sur le NAS
  (copier `docker-compose.yml`, créer le projet dans Container Manager).

---

## 4. Développement et test en local

L'application est en Python 3.12 + Flask, avec `ffmpeg` pour l'audio.

Pour la tester localement (sans NAS) :

```bash
# avec Docker
docker build -t audio-recorder .
docker run --rm -p 8095:8080 -v "$PWD/data:/data" audio-recorder
# puis ouvrir http://localhost:8095

# ou directement en Python (ffmpeg doit être installé sur la machine)
pip install -r requirements.txt
DATA_DIR=./data WEB_PORT=8095 python app.py
```

L'URL RTSP et les autres réglages se saisissent ensuite dans l'interface web
(icône d'engrenage). Ils sont stockés dans `data/settings.json`.

---

## 5. Conventions à respecter

- **Langue** : commentaires de code et interface en français ; l'utilisateur
  est néophyte, privilégier la clarté à la concision.
- **Aucun secret dans le dépôt** : ni URL RTSP, ni mot de passe. Le dossier
  `data/` (réglages, enregistrements) est ignoré par git (voir `.gitignore`).
- **Modifier le projet** : après toute modification du code, un simple
  `git push` sur `main` suffit — l'image se reconstruit et le NAS se met à
  jour seul via Watchtower (compter ~5 à 10 minutes).
- Ne pas committer le dossier `data/` ni les fichiers `*.mp3`.

---

## 6. Détail technique rapide

- `app.py` lance 4 tâches : enregistrement (`ffmpeg`), analyse du niveau
  sonore (`ebur128`), nettoyage des vieux fichiers, et le serveur web.
- Les réglages modifiables à chaud sont dans `/data/settings.json`. Changer un
  réglage via l'interface relance automatiquement l'enregistrement `ffmpeg`.
- Le catalogue des segments analysés est dans `/data/metadata.json`.
- Le port web interne est `8080` (exposé en `8095` côté NAS).
