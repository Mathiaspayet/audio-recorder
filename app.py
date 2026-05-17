#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enregistreur audio en continu pour un flux RTSP (caméra PoE, etc.).

Quatre tâches tournent en parallele :
  1. ENREGISTRE le son du flux RTSP en petits fichiers MP3 ("segments").
  2. ANALYSE chaque segment terminé pour mesurer son niveau sonore.
  3. NETTOIE automatiquement les fichiers plus vieux que la durée choisie.
  4. SERT une page web (tableau de bord + page de réglages).

Tous les réglages (URL RTSP, dossier d'enregistrement, durée des segments,
conservation, qualité, seuils de couleur) se modifient depuis l'interface web.
Ils sont enregistrés dans /data/settings.json et appliqués immédiatement :
l'enregistrement redémarre tout seul avec les nouveaux réglages.
"""

import os
import re
import json
import time
import shutil
import threading
import subprocess
import datetime as dt
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory, abort
from waitress import serve


# ===========================================================================
# 1. CHEMINS ET CONSTANTES
# ===========================================================================

DATA_DIR      = Path(os.environ.get("DATA_DIR", "/data"))
SETTINGS_FILE = DATA_DIR / "settings.json"
METADATA_FILE = DATA_DIR / "metadata.json"
WEB_PORT      = int(os.environ.get("WEB_PORT", "8080"))

BASE_DIR   = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# Réglages utilisés UNIQUEMENT au tout premier démarrage (ensuite, c'est le
# fichier settings.json, modifiable via l'interface, qui fait foi).
DEFAULT_SETTINGS = {
    "rtsp_url":        os.environ.get("RTSP_URL", "").strip(),
    "folder":          "recordings",
    "segment_minutes": int(float(os.environ.get("SEGMENT_MINUTES", "10"))),
    "retention_days":  float(os.environ.get("RETENTION_DAYS", "3")),
    "bitrate_kbps":    int(float(os.environ.get("AUDIO_BITRATE_KBPS", "96"))),
    "quiet_db":        float(os.environ.get("QUIET_DB", "-50")),
    "loud_db":         float(os.environ.get("LOUD_DB", "-15")),
}

ALLOWED_BITRATES = [32, 64, 96, 128, 192, 256]   # kbps proposés dans l'interface
CURVE_POINTS     = 24       # nombre de points de la mini-courbe d'un segment
LOUDNESS_FLOOR   = -70.0    # niveau plancher : en dessous = silence

# Nom de segment attendu : 2026-05-17_14-30-00.mp3
FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.mp3$")

app = Flask(__name__, static_folder=str(STATIC_DIR))

# Verrous (évitent que deux tâches écrivent un même fichier en même temps).
_settings_lock = threading.Lock()
_meta_lock     = threading.Lock()

_settings    = {}     # réglages courants, en mémoire
_ffmpeg_proc = None   # processus ffmpeg en cours (pour pouvoir le relancer)


def log(section, message):
    """Affiche un message daté dans les journaux du conteneur."""
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} [{section}] {message}",
          flush=True)


def clamp(value, low, high):
    """Garde une valeur dans l'intervalle [low, high]."""
    return max(low, min(high, value))


# ===========================================================================
# 2. RÉGLAGES  (lecture / validation / écriture de settings.json)
# ===========================================================================

def sanitize_folder(raw):
    """Nettoie le nom du dossier d'enregistrement pour qu'il reste sûr :
    pas de '..', pas de chemin absolu, seulement des caractères simples."""
    raw   = (raw or "").strip().strip("/").replace(" ", "-")
    parts = [p for p in raw.split("/") if p and p not in (".", "..")]
    safe  = "/".join(re.sub(r"[^A-Za-z0-9._-]", "", p) for p in parts if p)
    return safe or "recordings"


def validate_settings(raw):
    """Construit un jeu de réglages complet et valide à partir de données
    partielles ou douteuses (venant du fichier ou de l'interface web)."""
    s = dict(DEFAULT_SETTINGS)
    if isinstance(raw, dict):
        s.update({k: raw[k] for k in raw if k in DEFAULT_SETTINGS})

    s["rtsp_url"]        = str(s["rtsp_url"]).strip()
    s["folder"]          = sanitize_folder(s["folder"])
    s["segment_minutes"] = int(clamp(int(float(s["segment_minutes"])), 1, 60))
    s["retention_days"]  = round(clamp(float(s["retention_days"]), 0.5, 60), 2)

    bitrate = int(float(s["bitrate_kbps"]))
    s["bitrate_kbps"]    = min(ALLOWED_BITRATES, key=lambda b: abs(b - bitrate))

    s["quiet_db"]        = round(clamp(float(s["quiet_db"]), -90, -2), 1)
    s["loud_db"]         = round(clamp(float(s["loud_db"]), -89, 0), 1)
    if s["loud_db"] <= s["quiet_db"]:          # le seuil "fort" doit rester
        s["loud_db"] = s["quiet_db"] + 1.0     # au dessus du seuil "calme"
    return s


def load_settings():
    """Lit settings.json (ou renvoie les valeurs par défaut si absent)."""
    if SETTINGS_FILE.exists():
        try:
            with SETTINGS_FILE.open(encoding="utf-8") as f:
                return validate_settings(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return validate_settings({})


def write_settings(s):
    """Écrit settings.json de façon sûre (fichier temporaire puis renommage)."""
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(s, f, indent=1, ensure_ascii=False)
    tmp.replace(SETTINGS_FILE)


def get_settings():
    """Renvoie une copie des réglages courants."""
    with _settings_lock:
        return dict(_settings)


def update_settings(raw):
    """Applique de nouveaux réglages : valide, sauvegarde, met à jour."""
    s = validate_settings(raw)
    with _settings_lock:
        _settings.clear()
        _settings.update(s)
        write_settings(s)
    return s


def recordings_dir():
    """Renvoie le dossier d'enregistrement actif (et le crée si besoin)."""
    d = DATA_DIR / get_settings()["folder"]
    d.mkdir(parents=True, exist_ok=True)
    return d


# ===========================================================================
# 3. MÉTADONNÉES  (catalogue des segments analysés)
# ===========================================================================

def load_metadata():
    if METADATA_FILE.exists():
        try:
            with METADATA_FILE.open(encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_metadata(meta):
    tmp = METADATA_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    tmp.replace(METADATA_FILE)


def filename_to_datetime(name):
    """Déduit la date/heure de début d'un segment à partir de son nom."""
    if not FILENAME_RE.match(name):
        return None
    try:
        return dt.datetime.strptime(name, "%Y-%m-%d_%H-%M-%S.mp3")
    except ValueError:
        return None


# ===========================================================================
# 4. ENREGISTREMENT  (pilotage de ffmpeg, redémarrable à chaud)
# ===========================================================================

def build_ffmpeg_command(s, out_dir):
    """Construit la commande ffmpeg selon les réglages courants."""
    pattern = str(out_dir / "%Y-%m-%d_%H-%M-%S.mp3")
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-rtsp_transport", "tcp",
        "-use_wallclock_as_timestamps", "1",
        "-i", s["rtsp_url"],
        "-vn",  # on ignore l'image : on ne garde QUE le son
        "-c:a", "libmp3lame", "-b:a", f"{s['bitrate_kbps']}k",
        "-ac", "1", "-ar", "44100",
        "-f", "segment",
        "-segment_time", str(s["segment_minutes"] * 60),
        "-segment_format", "mp3",
        "-strftime", "1",
        "-reset_timestamps", "1",
        pattern,
    ]


def stop_recorder():
    """Arrête le ffmpeg en cours : la boucle le relancera avec les nouveaux
    réglages. Appelé après chaque changement de réglages."""
    proc = _ffmpeg_proc
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass


def recorder_loop():
    """Lance ffmpeg et le relance automatiquement (coupure réseau, changement
    de réglages, redémarrage de la caméra...)."""
    global _ffmpeg_proc
    while True:
        s = get_settings()
        if not s["rtsp_url"]:
            time.sleep(5)              # pas encore d'URL : on attend
            continue
        out_dir = recordings_dir()
        log("recorder", f"Enregistrement vers « {s['folder']} » — "
                         f"segments de {s['segment_minutes']} min, "
                         f"{s['bitrate_kbps']} kbps.")
        try:
            _ffmpeg_proc = subprocess.Popen(build_ffmpeg_command(s, out_dir))
            _ffmpeg_proc.wait()
            log("recorder", "ffmpeg s'est arrêté. Reprise dans 3 s.")
        except Exception as exc:
            log("recorder", f"Erreur : {exc}. Reprise dans 3 s.")
        finally:
            _ffmpeg_proc = None
        time.sleep(3)


# ===========================================================================
# 5. ANALYSE DU NIVEAU SONORE  (filtre ebur128 de ffmpeg)
# ===========================================================================

def analyze_file(path):
    """Mesure le niveau sonore d'un fichier audio.
    Renvoie (niveau_max, niveau_moyen, courbe) ou None en cas d'échec."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats",
        "-i", str(path),
        "-af", "ebur128=metadata=1,ametadata=mode=print:key=lavfi.r128.M:file=-",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (subprocess.TimeoutExpired, OSError):
        return None

    samples, current_time = [], 0.0
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("frame:"):
            m = re.search(r"pts_time:([\d.]+)", line)
            if m:
                current_time = float(m.group(1))
        elif line.startswith("lavfi.r128.M="):
            raw = line.split("=", 1)[1].strip()
            try:
                level = float(raw)
            except ValueError:
                level = LOUDNESS_FLOOR
            if level != level or level < LOUDNESS_FLOOR:   # NaN ou silence
                level = LOUDNESS_FLOOR
            samples.append((current_time, level))

    if not samples:
        return None

    levels   = [lvl for _, lvl in samples]
    peak_db  = max(levels)
    mean_db  = sum(levels) / len(levels)
    duration = samples[-1][0] or 1.0

    buckets = [[] for _ in range(CURVE_POINTS)]
    for t, lvl in samples:
        idx = min(int(t / duration * CURVE_POINTS), CURVE_POINTS - 1)
        buckets[idx].append(lvl)
    curve = [round(max(b), 1) if b else round(LOUDNESS_FLOOR, 1) for b in buckets]

    return round(peak_db, 1), round(mean_db, 1), curve


def analyzer_loop():
    """Analyse en continu les nouveaux segments terminés du dossier actif."""
    while True:
        try:
            folder  = get_settings()["folder"]
            out_dir = recordings_dir()
            with _meta_lock:
                meta = load_metadata()
            now = time.time()
            for path in sorted(out_dir.glob("*.mp3")):
                name = path.name
                if name in meta and meta[name].get("folder") == folder:
                    continue
                # On laisse de côté le fichier en cours d'écriture.
                if now - path.stat().st_mtime < 30:
                    continue
                start = filename_to_datetime(name)
                if start is None:
                    continue
                log("analyzer", f"Analyse de {folder}/{name}")
                analysis = analyze_file(path)
                if analysis is None:
                    continue
                peak_db, mean_db, curve = analysis
                with _meta_lock:
                    meta = load_metadata()
                    meta[name] = {
                        "start":   start.isoformat(timespec="seconds"),
                        "folder":  folder,
                        "peak_db": peak_db,
                        "mean_db": mean_db,
                        "curve":   curve,
                        "size":    path.stat().st_size,
                    }
                    save_metadata(meta)
        except Exception as exc:
            log("analyzer", f"Erreur : {exc}")
        time.sleep(20)


# ===========================================================================
# 6. NETTOYAGE  (suppression automatique des vieux fichiers)
# ===========================================================================

def cleanup_loop():
    """Supprime les fichiers et fiches plus vieux que la durée de conservation.
    Balaie TOUS les sous-dossiers (utile si le dossier d'enregistrement a
    changé) pour qu'aucun fichier ne reste oublié indéfiniment."""
    while True:
        try:
            cutoff  = dt.datetime.now() - dt.timedelta(
                          days=get_settings()["retention_days"])
            removed = 0
            for path in DATA_DIR.rglob("*.mp3"):
                start = filename_to_datetime(path.name)
                if start is not None and start < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            with _meta_lock:
                meta    = load_metadata()
                orphans = [n for n, i in meta.items()
                           if not (DATA_DIR / i.get("folder", "") / n).exists()]
                for n in orphans:
                    del meta[n]
                if orphans:
                    save_metadata(meta)
            if removed:
                log("cleanup", f"{removed} segment(s) supprimé(s).")
        except Exception as exc:
            log("cleanup", f"Erreur : {exc}")
        time.sleep(1800)   # toutes les 30 minutes


# ===========================================================================
# 7. ESPACE DISQUE
# ===========================================================================

def folder_usage(path):
    """Taille totale (octets) des MP3 contenus dans un dossier."""
    total = 0
    if path.exists():
        for p in path.rglob("*.mp3"):
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def estimate_bytes(s):
    """Estime la place qu'occupera l'enregistrement en régime établi :
    débit (octets/s) x durée de conservation (secondes)."""
    bytes_per_second = s["bitrate_kbps"] * 1000 / 8
    return int(bytes_per_second * s["retention_days"] * 86400)


def storage_info():
    """Renvoie l'état du disque + l'estimation d'espace nécessaire."""
    s = get_settings()
    try:
        usage = shutil.disk_usage(DATA_DIR)
        total, used, free = usage.total, usage.used, usage.free
    except OSError:
        total = used = free = 0
    return {
        "disk_total":     total,
        "disk_used":      used,
        "disk_free":      free,
        "estimate_bytes": estimate_bytes(s),
        "current_usage":  folder_usage(DATA_DIR / s["folder"]),
    }


# ===========================================================================
# 8. SERVEUR WEB
# ===========================================================================

@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/api/segments")
def api_segments():
    """Liste des segments analysés du dossier actif."""
    s = get_settings()
    with _meta_lock:
        meta = load_metadata()
    segments = [
        {
            "name":    name,
            "start":   info["start"],
            "peak_db": info["peak_db"],
            "mean_db": info["mean_db"],
            "curve":   info.get("curve", []),
            "size":    info.get("size", 0),
        }
        for name, info in meta.items()
        if info.get("folder") == s["folder"]
    ]
    segments.sort(key=lambda x: x["start"])
    return jsonify({
        "segments": segments,
        "config": {
            "segment_minutes": s["segment_minutes"],
            "retention_days":  s["retention_days"],
            "quiet_db":        s["quiet_db"],
            "loud_db":         s["loud_db"],
            "recording":       bool(s["rtsp_url"]),
            "folder":          s["folder"],
        },
    })


@app.get("/api/settings")
def api_get_settings():
    return jsonify({"settings": get_settings(), "storage": storage_info()})


@app.post("/api/settings")
def api_set_settings():
    """Enregistre de nouveaux réglages et redémarre l'enregistrement."""
    payload = request.get_json(force=True, silent=True) or {}
    new = update_settings(payload)
    stop_recorder()    # force ffmpeg à repartir avec les nouveaux réglages
    log("settings", f"Réglages mis à jour (dossier « {new['folder']} »).")
    return jsonify({"settings": new, "storage": storage_info()})


@app.get("/api/storage")
def api_storage():
    return jsonify(storage_info())


@app.get("/api/folders")
def api_folders():
    """Liste les sous-dossiers existants (pour le sélecteur de l'interface)."""
    folders = set()
    if DATA_DIR.exists():
        for p in DATA_DIR.iterdir():
            if p.is_dir():
                folders.add(p.name)
                for sub in p.iterdir():
                    if sub.is_dir():
                        folders.add(f"{p.name}/{sub.name}")
    folders.add(get_settings()["folder"])
    return jsonify(sorted(folders))


@app.get("/audio/<path:name>")
def audio(name):
    """Sert le MP3 d'un segment du dossier actif."""
    if not FILENAME_RE.match(name):
        abort(404)
    path = recordings_dir() / name
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="audio/mpeg", conditional=True)


# ===========================================================================
# 9. DÉMARRAGE
# ===========================================================================

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Chargement (ou création) des réglages.
    with _settings_lock:
        _settings.update(load_settings())
        write_settings(_settings)
    recordings_dir()

    s = get_settings()
    log("start", f"Données : {DATA_DIR}")
    log("start", f"Dossier d'enregistrement : « {s['folder']} »")
    if not s["rtsp_url"]:
        log("start", "Aucune URL RTSP : ouvrez les réglages pour la définir.")

    for task in (recorder_loop, analyzer_loop, cleanup_loop):
        threading.Thread(target=task, daemon=True).start()

    log("start", f"Tableau de bord disponible sur le port {WEB_PORT}.")
    serve(app, host="0.0.0.0", port=WEB_PORT, threads=8)


if __name__ == "__main__":
    main()
