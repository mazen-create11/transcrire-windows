"""Test d'integration : depot d'un audio -> note ecrite, sur la vraie pile.

Tourne tel quel sur Windows, macOS et Linux. Le modele 'tiny' est telecharge
au premier appel (~75 Mo) ; la CI le met en cache.
"""
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import urllib.request

RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

if os.name == "nt":  # sinon les accents sortent en mojibake dans le journal CI
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

BAC = pathlib.Path(tempfile.mkdtemp(prefix="transcrire-test-"))
os.environ["APPDATA"] = str(BAC)
os.environ["XDG_CONFIG_HOME"] = str(BAC)

from transcrire import moteur, reglages, serveur  # noqa: E402

reglages.ecrire({"modele": "tiny", "langue": "fr", "resume": False,
                 "dossier": str(BAC / "notes")})
ECHANTILLON = RACINE / "tests" / "echantillon.wav"


def _demarrer():
    httpd, port = serveur.lancer(7899)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def _appel(url, donnees=None, entetes=None):
    requete = urllib.request.Request(url, data=donnees, headers=entetes or {})
    requete.add_header("X-Transcrire", reglages.jeton())
    with urllib.request.urlopen(requete, timeout=600) as r:
        return json.load(r)


def principal():
    httpd, port = _demarrer()
    base = "http://127.0.0.1:%d" % port
    echecs = []

    def verifier(nom, condition, detail=""):
        print(("  OK   " if condition else "  RATE ") + nom + ("  " + detail if detail else ""))
        if not condition:
            echecs.append(nom)

    # 1. la page se sert et porte le jeton
    with urllib.request.urlopen(base + "/", timeout=20) as r:
        page = r.read().decode("utf-8")
    verifier("interface servie", "<title>Transcrire</title>" in page)
    verifier("jeton injecte", "__JETON__" not in page and reglages.jeton() in page)

    # 2. sans jeton, l'API refuse
    try:
        urllib.request.urlopen(base + "/api/sante", timeout=10)
        verifier("api protegee", False, "403 attendu")
    except urllib.error.HTTPError as e:
        verifier("api protegee", e.code == 403, "code %d" % e.code)

    # 3. sante
    sante = _appel(base + "/api/sante")
    verifier("sante lisible", sante["modele"] == "tiny" and "dossier" in sante)

    # 4. depot d'un vrai audio
    debut = time.time()
    reponse = _appel(base + "/api/depot", ECHANTILLON.read_bytes(),
                     {"X-Mode": "memo", "X-Ext": ".wav", "X-Langue": "fr",
                      "X-Titre": "dGVzdCBhdXRvbWF0aXF1ZQ=="})
    tache = {}
    for _ in range(600):
        tache = _appel(base + "/api/etat?id=" + reponse["id"])
        if tache.get("etat") in ("fini", "vide", "erreur"):
            break
        time.sleep(1)
    verifier("transcription terminee", tache.get("etat") == "fini",
             "%s - %s (%.0f s)" % (tache.get("etat"), tache.get("message"), time.time() - debut))

    texte = (tache.get("texte") or "").lower()
    verifier("contenu reconnu", "transcription" in texte or "reunion" in texte or "réunion" in texte,
             texte[:90])

    # 5. la note existe, avec son frontmatter et son .srt
    if tache.get("note"):
        note = pathlib.Path(tache["note"])
        contenu = note.read_text(encoding="utf-8")
        verifier("note ecrite", note.exists() and contenu.startswith("---"))
        verifier("titre repris", "test automatique" in contenu)
        verifier("sous-titres ecrits", note.with_suffix(".srt").exists())
        verifier("index mis a jour", (note.parent.parent / "index.md").exists())

    # 6. la liste des notes la voit
    notes = _appel(base + "/api/notes")["notes"]
    verifier("note listee", len(notes) == 1 and notes[0]["mots"])

    # 7. garde-fou du vide
    verifier("silence ignore", moteur.rien_d_exploitable("Merci."))
    verifier("artefact ignore", moteur.rien_d_exploitable("Sous-titres realises par la communaute d'Amara.org"))
    verifier("vrai contenu garde", not moteur.rien_d_exploitable(
        "On se voit lundi pour parler du budget et du planning de la semaine"))

    # 8. hors du dossier, la lecture est refusee
    try:
        _appel(base + "/api/note?f=" + str(RACINE / "README.md"))
        verifier("lecture hors dossier bloquee", False)
    except urllib.error.HTTPError as e:
        verifier("lecture hors dossier bloquee", e.code in (403, 404))

    httpd.shutdown()
    print("")
    if echecs:
        print("  %d controle(s) en echec : %s" % (len(echecs), ", ".join(echecs)))
        return 1
    print("  Tout est vert.")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
