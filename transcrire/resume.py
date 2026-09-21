"""Resume automatique, gratuit et local, par Ollama s'il est installe.

Aucune cle, aucun compte, aucun envoi sur internet. Si Ollama n'est pas la,
la note est ecrite sans resume.
"""
import json
import urllib.error
import urllib.request

from . import reglages

HOTE = "http://127.0.0.1:11434"

CONSIGNE = {
    "reunion": (
        "Tu resumes la transcription d'une reunion. Rends exactement trois "
        "sections en Markdown : ## Decisions, ## A faire (avec le nom de la "
        "personne quand il est dit), ## Sujets abordes. Des puces courtes, "
        "aucune invention : si une section est vide, ecris 'rien'."
    ),
    "memo": (
        "Tu resumes un memo vocal. Rends ## L'essentiel (3 puces maximum) "
        "puis ## A faire s'il y a des actions. Aucune invention."
    ),
}


def disponible():
    try:
        with urllib.request.urlopen(HOTE + "/api/tags", timeout=1.5) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except Exception:
        return []


def resumer(texte, mode="memo"):
    modeles = disponible()
    if not modeles:
        return ""
    voulu = reglages.lire().get("modele_resume") or ""
    modele = voulu if voulu in modeles else modeles[0]
    consigne = CONSIGNE.get(mode, CONSIGNE["memo"])
    corps = json.dumps({
        "model": modele,
        "stream": False,
        "options": {"temperature": 0.2},
        "messages": [
            {"role": "system", "content": consigne + " Reponds en francais."},
            {"role": "user", "content": texte[:24000]},
        ],
    }).encode("utf-8")
    requete = urllib.request.Request(
        HOTE + "/api/chat", data=corps,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(requete, timeout=300) as r:
            return json.load(r)["message"]["content"].strip()
    except Exception:
        return ""
