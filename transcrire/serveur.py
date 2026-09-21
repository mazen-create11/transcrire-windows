"""Serveur local : sert l'interface et transcrit ce que le navigateur envoie.

Il n'ecoute que sur 127.0.0.1 et exige un jeton sur toutes les routes /api,
avec controle de l'en-tete Host (anti rebind DNS) et de l'Origin.
"""
import base64
import http.server
import json
import mimetypes
import os
import pathlib
import socketserver
import threading
import time
import traceback
import urllib.parse
import uuid

from . import moteur, reglages, resume

WEB = pathlib.Path(__file__).parent / "web"
TACHES = {}
VERROU = threading.Lock()
EXTENSIONS = {".webm", ".m4a", ".mp3", ".wav", ".ogg", ".opus", ".mp4",
              ".mov", ".mkv", ".aac", ".flac", ".caf", ".avi", ".m4v", ".wma"}


def _nouvelle_tache(mode, titre):
    tid = uuid.uuid4().hex[:12]
    with VERROU:
        TACHES[tid] = {"id": tid, "etat": "attente", "message": "En file d'attente",
                       "mode": mode, "titre": titre, "debut": time.time()}
    return tid


def _maj(tid, **champs):
    with VERROU:
        if tid in TACHES:
            TACHES[tid].update(champs)


def _travailler(tid, chemin, mode, titre, langue):
    try:
        _maj(tid, etat="travail", message="Préparation…")
        resultat = moteur.transcrire(
            chemin, mode=mode, titre=titre, langue=langue,
            progression=lambda m: _maj(tid, message=m))
        if resultat["vide"]:
            _maj(tid, etat="vide", message="Rien d'exploitable (%d mots), aucune note écrite"
                 % resultat["mots"], **resultat)
        else:
            _maj(tid, etat="fini", message="Note écrite", **resultat)
    except Exception as erreur:
        traceback.print_exc()
        _maj(tid, etat="erreur", message=str(erreur) or erreur.__class__.__name__)
    finally:
        try:
            if os.path.exists(chemin) and mode == "dictee":
                os.remove(chemin)
        except Exception:
            pass


class Gestionnaire(http.server.BaseHTTPRequestHandler):
    server_version = "Transcrire"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    # --- garde-fous -------------------------------------------------
    def _hote_sain(self):
        hote = (self.headers.get("Host") or "").split(":")[0]
        return hote in ("127.0.0.1", "localhost", "[::1]", "::1")

    def _origine_saine(self):
        origine = self.headers.get("Origin")
        if not origine:
            return True
        return urllib.parse.urlparse(origine).hostname in ("127.0.0.1", "localhost")

    def _autorise(self, params):
        fourni = self.headers.get("X-Transcrire") or params.get("jeton", [""])[0]
        return fourni == reglages.jeton()

    # --- reponses ---------------------------------------------------
    def _envoyer(self, corps, type_mime="application/json; charset=utf-8", code=200):
        if isinstance(corps, (dict, list)):
            corps = json.dumps(corps, ensure_ascii=False).encode("utf-8")
        elif isinstance(corps, str):
            corps = corps.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", type_mime)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(corps)

    def _erreur(self, code, message):
        self._envoyer({"erreur": message}, code=code)

    # --- GET --------------------------------------------------------
    def do_GET(self):
        if not self._hote_sain():
            return self._erreur(403, "hôte refusé")
        url = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(url.query)
        route = url.path

        if route in ("/", "/index.html"):
            page = (WEB / "index.html").read_text(encoding="utf-8")
            page = page.replace("__JETON__", reglages.jeton())
            return self._envoyer(page, "text/html; charset=utf-8")

        if route.startswith("/api/"):
            if not self._autorise(params):
                return self._erreur(403, "jeton absent ou invalide")
            return self._api_get(route, params)

        fichier = (WEB / route.lstrip("/")).resolve()
        if fichier.is_file() and str(fichier).startswith(str(WEB.resolve())):
            type_mime = mimetypes.guess_type(str(fichier))[0] or "application/octet-stream"
            return self._envoyer(fichier.read_bytes(), type_mime)
        return self._erreur(404, "introuvable")

    def _api_get(self, route, params):
        if route == "/api/sante":
            r = reglages.lire()
            return self._envoyer({
                "dossier": r["dossier"], "modele": r["modele"], "langue": r["langue"],
                "resume": r["resume"], "modeles_resume": resume.disponible(),
                "modele_resume": r.get("modele_resume", ""),
                "materiel": moteur._materiel()[0], "pret": moteur._modele is not None,
                "version": VERSION,
            })
        if route == "/api/etat":
            tid = params.get("id", [""])[0]
            with VERROU:
                tache = TACHES.get(tid)
            return self._envoyer(tache or {"etat": "inconnu"})
        if route == "/api/notes":
            return self._envoyer({"notes": _dernieres_notes()})
        if route == "/api/note":
            note = pathlib.Path(params.get("f", [""])[0])
            if not _dans_le_dossier(note) or not note.is_file():
                return self._erreur(404, "note introuvable")
            return self._envoyer({"texte": note.read_text(encoding="utf-8"),
                                  "nom": note.name})
        if route == "/api/ouvrir":
            cible = pathlib.Path(params.get("f", [""])[0] or reglages.lire()["dossier"])
            if not _dans_le_dossier(cible):
                return self._erreur(403, "hors du dossier")
            _ouvrir(cible)
            return self._envoyer({"ok": True})
        return self._erreur(404, "route inconnue")

    # --- POST -------------------------------------------------------
    def do_POST(self):
        if not self._hote_sain() or not self._origine_saine():
            return self._erreur(403, "requête refusée")
        url = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(url.query)
        if not self._autorise(params):
            return self._erreur(403, "jeton absent ou invalide")

        if url.path == "/api/reglages":
            corps = self._lire_json()
            nouveaux = reglages.ecrire(corps)
            if "modele" in corps:
                moteur._modele = None
            return self._envoyer(nouveaux)

        if url.path in ("/api/depot", "/api/dictee"):
            return self._recevoir_audio(url.path == "/api/dictee")

        return self._erreur(404, "route inconnue")

    def _lire_json(self):
        taille = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(taille) or b"{}")
        except Exception:
            return {}

    def _entete_texte(self, nom):
        brut = self.headers.get(nom) or ""
        if not brut:
            return ""
        try:
            return base64.b64decode(brut).decode("utf-8")
        except Exception:
            return brut

    def _recevoir_audio(self, dictee):
        taille = int(self.headers.get("Content-Length") or 0)
        if taille <= 0:
            return self._erreur(400, "corps vide")
        if taille > 2 * 1024 ** 3:
            return self._erreur(413, "fichier trop gros (2 Go maximum)")

        mode = "dictee" if dictee else (self.headers.get("X-Mode") or "memo")
        titre = self._entete_texte("X-Titre")
        langue = self.headers.get("X-Langue") or reglages.lire()["langue"]
        ext = (self.headers.get("X-Ext") or ".webm").lower()
        if not ext.startswith("."):
            ext = "." + ext
        if ext not in EXTENSIONS:
            ext = ".webm"

        cible = reglages.dossier_travail() / ("%s%s" % (uuid.uuid4().hex[:10], ext))
        recu = 0
        with cible.open("wb") as f:
            while recu < taille:
                bloc = self.rfile.read(min(1 << 20, taille - recu))
                if not bloc:
                    break
                f.write(bloc)
                recu += len(bloc)

        tid = _nouvelle_tache(mode, titre)
        threading.Thread(target=_travailler,
                         args=(tid, str(cible), mode, titre, langue),
                         daemon=True).start()
        return self._envoyer({"id": tid})


def _dans_le_dossier(chemin):
    try:
        racine = pathlib.Path(reglages.lire()["dossier"]).resolve()
        return str(pathlib.Path(chemin).resolve()).startswith(str(racine))
    except Exception:
        return False


def _dernieres_notes(combien=25):
    racine = pathlib.Path(reglages.lire()["dossier"])
    if not racine.exists():
        return []
    notes = [p for p in racine.rglob("*.md") if p.name != "index.md"]
    notes.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    sortie = []
    for p in notes[:combien]:
        entete = _entete(p)
        sortie.append({
            "chemin": str(p), "nom": p.stem,
            "titre": entete.get("titre", p.stem),
            "date": entete.get("date", ""), "duree": entete.get("duree", ""),
            "mode": entete.get("mode", ""), "mots": entete.get("mots", ""),
        })
    return sortie


def _entete(note):
    valeurs = {}
    try:
        with note.open(encoding="utf-8") as f:
            if f.readline().strip() != "---":
                return valeurs
            for ligne in f:
                if ligne.strip() == "---":
                    break
                if ":" in ligne:
                    cle, _, valeur = ligne.partition(":")
                    valeurs[cle.strip()] = valeur.strip().strip('"')
    except Exception:
        pass
    return valeurs


def _ouvrir(chemin):
    chemin = str(chemin)
    try:
        if os.name == "nt":
            os.startfile(chemin)  # noqa: S606
        elif sys_darwin():
            import subprocess
            subprocess.Popen(["open", chemin])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", chemin])
    except Exception:
        pass


def sys_darwin():
    import sys
    return sys.platform == "darwin"


class Serveur(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


VERSION = "1.0.0"


def lancer(port=None):
    port = port or reglages.lire()["port"]
    for essai in range(20):
        try:
            httpd = Serveur(("127.0.0.1", port + essai), Gestionnaire)
            return httpd, port + essai
        except OSError:
            continue
    raise SystemExit("Aucun port libre entre %d et %d." % (port, port + 19))
