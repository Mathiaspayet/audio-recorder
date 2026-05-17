# Moniteur Audio — enregistreur de son pour caméra RTSP

Application qui enregistre **en continu le son** d'une caméra (ou de tout flux
RTSP), conserve les derniers jours, et fournit une **page web** pour naviguer
dans le passé et repérer d'un coup d'œil **les moments bruyants**.

Elle tourne dans un conteneur Docker sur un NAS Synology. Aucune licence,
aucune limite de caméras.

---

## 1. Comment ce kit fonctionne

Ce dossier est un **kit** : vous le copiez sur votre ordinateur, et Claude Code
s'occupe de le mettre en ligne. La chaîne complète :

```
  Votre ordinateur            GitHub                      NAS Synology
  ┌───────────────┐  envoi   ┌──────────────┐  télécharge ┌───────────────┐
  │   ce dossier  │ ───────► │  construit   │ ──────────► │ audio-recorder│
  │  + Claude Code│          │  l'image     │             │  + Watchtower │
  └───────────────┘          │  → ghcr.io   │             └───────────────┘
                             └──────────────┘   Watchtower surveille GitHub
                                                et met l'application à jour
                                                automatiquement.
```

Concrètement, il y a **trois temps** :

- **Partie A** — une fois : Claude Code envoie le projet sur votre compte
  GitHub, qui fabrique l'image de l'application.
- **Partie B** — une fois : vous installez l'application sur le NAS.
- **Partie C** — quand vous voulez : vous réglez tout depuis l'interface web.

Ensuite, toute amélioration future est automatique : Claude Code renvoie le
code modifié, GitHub reconstruit l'image, et le NAS se met à jour seul.

---

## 2. Partie A — Mettre le projet en ligne (avec Claude Code)

1. Copiez ce dossier complet sur votre ordinateur.
2. Ouvrez-le avec **Claude Code**.
3. Demandez-lui simplement : *« Mets ce projet en place selon CLAUDE.md »*.

Le fichier `CLAUDE.md` contient toutes les instructions : Claude Code va
vérifier votre accès GitHub, créer le dépôt, envoyer le code, et lancer la
construction de l'image. Laissez-vous guider — il vous expliquera chaque étape
et vous demandera confirmation.

À la fin, vous obtiendrez une **adresse d'image** de la forme :

```
ghcr.io/votre-identifiant/audio-recorder:latest
```

> Notez-la : elle apparaît déjà dans `docker-compose.yml`, où Claude Code aura
> remplacé `__GITHUB_USER__` par votre identifiant.

---

## 3. Partie B — Installer sur le NAS Synology

Il vous faut **Container Manager** (Centre de paquets → rechercher
« Container Manager » → Installer). *Sur les anciens DSM, ce paquet s'appelle
« Docker » : les étapes sont quasi identiques.*

### Étape 1 — Déposer le fichier de configuration

Avec **File Station** :

1. Ouvrez (ou créez) un dossier partagé `docker` sur votre volume.
2. À l'intérieur, créez un dossier `audio-recorder`.
3. Déposez-y **uniquement** le fichier `docker-compose.yml` du kit.
   *(Pas besoin du reste : l'application est téléchargée toute prête depuis
   GitHub.)*

### Étape 2 — Créer le projet

1. Ouvrez **Container Manager** → onglet **Projet** → **Créer**.
2. Nom du projet : `audio-recorder`.
3. Chemin : sélectionnez le dossier `docker/audio-recorder`.
4. Container Manager détecte le fichier `docker-compose.yml`. Laissez la
   source sur « Utiliser le fichier existant ».
5. Cliquez sur **Suivant** puis **Terminé**.

Le NAS télécharge l'image depuis GitHub et démarre **deux conteneurs** :
l'application et **Watchtower** (le composant qui assurera les mises à jour
automatiques). L'application redémarre ensuite toute seule, y compris après un
redémarrage du NAS.

### Étape 3 — Ouvrir le tableau de bord

Dans un navigateur, sur n'importe quel appareil du réseau :

```
http://ADRESSE-IP-DU-NAS:8095
```

(par exemple `http://192.168.1.10:8095`)

---

## 4. Partie C — Configurer depuis l'interface

Au premier lancement, aucune caméra n'est encore connue. Cliquez sur l'icône
**engrenage** (en haut à droite) pour ouvrir les **Réglages** :

| Réglage                  | Rôle                                                     |
|--------------------------|----------------------------------------------------------|
| **Adresse RTSP**         | l'adresse du flux de votre caméra (voir ci-dessous)      |
| **Dossier d'enregistrement** | sous-dossier où ranger les fichiers (ex. `recordings/jardin`) |
| **Durée d'un segment**   | longueur d'un fichier, de 1 à 60 minutes                 |
| **Conservation**         | nombre de jours gardés avant suppression automatique     |
| **Qualité audio**        | de 32 à 256 kbps (96 kbps recommandé)                    |
| **Seuils calme / fort**  | réglage des couleurs de la frise                         |

En bas des réglages, un **estimateur d'espace** se met à jour en direct : il
indique la place que l'enregistrement occupera une fois en régime établi, et
la compare à l'espace libre du disque. Une pastille verte / orange / rouge
vous dit si la configuration tient confortablement.

Cliquez sur **Enregistrer** : l'application applique les réglages
immédiatement (l'enregistrement redémarre tout seul).

### Trouver l'adresse RTSP de la caméra

Elle ressemble à :

```
rtsp://utilisateur:motdepasse@192.168.1.50:554/chemin-du-flux
```

La fin du chemin dépend de la marque (voir le manuel de la caméra).
**Testez-la d'abord dans VLC** : Média → Ouvrir un flux réseau → collez
l'adresse. Vous devez voir l'image **et entendre le son** — sans son dans le
flux, rien ne pourra être enregistré.

### Choisir l'emplacement de stockage

- Le **dossier** (dans les réglages) choisit un sous-dossier de rangement.
- Le **disque physique** se choisit dans `docker-compose.yml`, à la ligne
  `volumes:`. Par défaut les fichiers vont dans `docker/audio-recorder/data`.
  Pour les mettre sur un autre volume, remplacez `./data:/data` par, par
  exemple, `/volume2/audio:/data`, puis reconstruisez le projet.

---

## 5. Utiliser le tableau de bord

- **La frise** : un bloc = un segment. Les journées sont empilées, la plus
  récente en haut. La couleur va du sombre (calme) au rouge (bruit fort). Les
  zones hachurées signalent une interruption de l'enregistrement.
- **Repérer le bruit** : cherchez les blocs colorés ou rouges.
- **Écouter** : cliquez sur un bloc. La lecture démarre, et la **mini-courbe**
  en haut montre le niveau sonore *à l'intérieur* du segment — un pic dans la
  courbe indique où écouter. Un trait blanc suit la lecture.
- La page se met à jour toute seule toutes les 45 secondes.

Le premier segment apparaît après la durée d'un segment (≈ 10 min par défaut),
le temps qu'un premier fichier soit complet puis analysé.

---

## 6. Mises à jour automatiques

Vous n'avez rien à faire. Lorsqu'une amélioration est apportée au code (via
Claude Code, puis `git push`), GitHub reconstruit l'image, et **Watchtower**,
sur le NAS, la récupère dans les minutes qui suivent et remplace le conteneur.
Vos réglages et vos enregistrements (dossier `data`) sont conservés.

---

## 7. En cas de problème

**Aucun segment n'apparaît.**
Container Manager → projet `audio-recorder` → conteneur `audio-recorder` →
**Journal**. Les lignes `[recorder]` indiquent ce qui se passe. Une erreur de
connexion = adresse RTSP incorrecte : re-testez-la dans VLC.

**Les segments sont silencieux.**
Le flux RTSP ne contient pas de son. Activez le micro dans les réglages de la
caméra ; certaines caméras ont plusieurs flux et un seul porte l'audio.

**La page web ne s'ouvre pas.**
Vérifiez l'IP du NAS et que le port `8095` est libre. Au besoin, changez-le
dans `docker-compose.yml` (ex. `8096:8080`) et reconstruisez le projet.

**Le NAS ne télécharge pas l'image.**
L'image doit être *publique* sur GitHub. Voir l'étape 5 de `CLAUDE.md`.

---

## 8. Rappel important

Enregistrer le **son** d'un lieu où des personnes peuvent parler est davantage
encadré par la loi que la simple vidéo. Pour un espace strictement privé qui
n'est que le vôtre, pas de souci. Si le micro peut capter des voisins, des
passants ou des visiteurs, renseignez-vous sur ce que la loi autorise avant de
laisser l'enregistrement tourner.
