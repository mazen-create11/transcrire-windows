"""Reglages et emplacements de fichiers, valables sur Windows, macOS et Linux."""
import json
import os
import pathlib
import secrets

APP = "Transcrire"
_cache = None


def dossier_config():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or pathlib.Path.home() / "AppData/Roaming"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or pathlib.Path.home() / ".config"
    d = pathlib.Path(base) / APP
    d.mkdir(parents=True, exist_ok=True)
    return d


def dossier_modeles():
    d = dossier_config() / "modeles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def dossier_travail():
    d = dossier_config() / "enregistrements"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _documents():
    if os.name == "nt":
        try:
            import ctypes.wintypes
            tampon = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            # CSIDL_PERSONAL = 5 : suit le dossier Documents meme redirige vers OneDrive
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, tampon)
            if tampon.value:
                return pathlib.Path(tampon.value)
        except Exception:
            pass
    maison = pathlib.Path.home()
    for nom in ("Documents", "Documenti", "Dokumente"):
        if (maison / nom).is_dir():
            return maison / nom
    return maison


DEFAUTS = {
    "modele": "small",          # tiny | base | small | medium | large-v3
    "langue": "auto",           # auto | fr | en | ar ...
    "resume": False,            # necessite Ollama installe (gratuit, local)
    "modele_resume": "",        # vide = premier modele Ollama trouve
    "dossier": "",              # vide = Documents/Transcrire
    "port": 7791,
}


def chemin():
    return dossier_config() / "reglages.json"


def lire():
    global _cache
    if _cache is None:
        valeurs = dict(DEFAUTS)
        try:
            valeurs.update(json.loads(chemin().read_text(encoding="utf-8")))
        except Exception:
            pass
        if not valeurs.get("dossier"):
            valeurs["dossier"] = str(_documents() / APP)
        _cache = valeurs
    return _cache


def ecrire(nouveaux):
    valeurs = lire()
    for cle, valeur in nouveaux.items():
        if cle in DEFAUTS:
            valeurs[cle] = valeur
    chemin().write_text(json.dumps(valeurs, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return valeurs


def jeton():
    """Jeton local exige sur toutes les routes /api : sans lui, n'importe quelle
    page ouverte dans le navigateur pourrait piloter le micro (paye sur macOS)."""
    f = dossier_config() / "jeton"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        try:
            os.chmod(f, 0o600)
        except Exception:
            pass
    return f.read_text(encoding="utf-8").strip()
