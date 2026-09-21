"""Transcription locale : audio -> texte, note Markdown + sous-titres SRT.

Rien ne quitte la machine : faster-whisper tourne sur le processeur (ou la carte
NVIDIA si elle est presente). Le decodage passe par PyAV, embarque par
faster-whisper : aucun ffmpeg a installer.
"""
import datetime
import json
import os
import re
import threading
import unicodedata

from . import reglages

_modele = None
_modele_nom = None
_verrou = threading.Lock()

# Artefacts que Whisper invente sur du silence (paye sur la version macOS).
ARTEFACTS = (
    "amara org", "sous titres realises par", "soustitreur", "radio canada",
    "thanks for watching", "merci d avoir regarde", "abonnez vous",
    "sous titrage societe radio canada", "merci", "thank you",
)
MOTS_MINIMUM = 5


def _sans_accent(texte):
    plat = unicodedata.normalize("NFD", texte.lower())
    plat = "".join(c for c in plat if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", plat).strip()


def rien_d_exploitable(texte):
    """Vrai si la note ne merite pas d'etre ecrite (silence, faux depart)."""
    plat = _sans_accent(texte)
    mots = plat.split()
    if len(mots) < MOTS_MINIMUM:
        return True
    return any(plat == a or plat.startswith(a) for a in ARTEFACTS)


def charger(nom=None, journal=None):
    """Charge le modele en memoire (une fois) et le renvoie."""
    global _modele, _modele_nom
    from faster_whisper import WhisperModel

    nom = nom or reglages.lire()["modele"]
    with _verrou:
        if _modele is not None and _modele_nom == nom:
            return _modele
        appareil, calcul = _materiel()
        if journal:
            journal("Chargement du modèle %s (%s)…" % (nom, appareil))
        _modele = WhisperModel(nom, device=appareil, compute_type=calcul,
                               download_root=str(reglages.dossier_modeles()))
        _modele_nom = nom
        return _modele


def _materiel():
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def _horodatage(secondes):
    h = int(secondes // 3600)
    m = int(secondes % 3600 // 60)
    s = secondes % 60
    return ("%02d:%02d:%06.3f" % (h, m, s)).replace(".", ",")


def _slug(texte):
    plat = _sans_accent(texte)
    return re.sub(r"\s+", "-", plat)[:60].strip("-")


def transcrire(chemin, mode="memo", titre="", langue="auto", progression=None):
    """Transcrit un fichier. Renvoie un dictionnaire de resultat."""
    modele = charger(journal=progression)
    if progression:
        progression("Transcription en cours…")
    options = {"vad_filter": True, "beam_size": 5,
               "condition_on_previous_text": False}
    if langue and langue != "auto":
        options["language"] = langue
    segments, info = modele.transcribe(chemin, **options)

    lignes, srt, total = [], [], 0.0
    for i, seg in enumerate(segments, 1):
        texte = seg.text.strip()
        if not texte or texte == "...":
            continue
        lignes.append(texte)
        srt.append("%d\n%s --> %s\n%s\n" % (
            i, _horodatage(seg.start), _horodatage(seg.end), texte))
        total = max(total, seg.end)
        if progression and i % 8 == 0:
            progression("Transcription : %s écoutées" % _duree_lisible(total))

    texte = " ".join(lignes).strip()
    duree = info.duration or total
    if rien_d_exploitable(texte):
        return {"vide": True, "mots": len(texte.split()), "texte": texte,
                "duree": duree, "langue": info.language}

    resume = ""
    if reglages.lire()["resume"]:
        if progression:
            progression("Résumé en cours…")
        from .resume import resumer
        resume = resumer(texte, mode)

    note = _ecrire(texte, "\n".join(srt), duree, info.language, mode, titre,
                   resume, chemin)
    return {"vide": False, "mots": len(texte.split()), "texte": texte,
            "duree": duree, "langue": info.language, "note": str(note),
            "resume": resume, "titre": note.stem}


def _duree_lisible(secondes):
    m, s = divmod(int(secondes), 60)
    h, m = divmod(m, 60)
    if h:
        return "%d h %02d" % (h, m)
    return "%d min %02d s" % (m, s) if m else "%d s" % s


def _ecrire(texte, srt, duree, langue, mode, titre, resume, source):
    import pathlib
    quand = datetime.datetime.fromtimestamp(os.path.getmtime(source))
    jour = quand.strftime("%Y-%m-%d")
    base = quand.strftime("%Y-%m-%d_%Hh%M")
    if titre.strip():
        base += "_" + _slug(titre)

    dossier = pathlib.Path(reglages.lire()["dossier"]) / jour
    dossier.mkdir(parents=True, exist_ok=True)
    note = dossier / (base + ".md")
    n = 2
    while note.exists():
        note = dossier / ("%s-%d.md" % (base, n))
        n += 1

    entete = {
        "titre": titre.strip() or base,
        "date": quand.strftime("%Y-%m-%d %H:%M"),
        "duree": _duree_lisible(duree),
        "mode": {"memo": "Mémo", "reunion": "Réunion", "dictee": "Dictée"}.get(mode, mode),
        "langue": langue,
        "mots": len(texte.split()),
    }
    corps = ["---"]
    corps += ["%s: %s" % (k, json.dumps(v, ensure_ascii=False) if isinstance(v, str) and ":" in v else v)
              for k, v in entete.items()]
    corps += ["---", ""]
    corps.append("# " + entete["titre"])
    corps.append("")
    if resume:
        # Le modele met souvent ses propres titres de niveau 2 : on les descend
        # d'un cran pour qu'ils vivent sous « Résumé ».
        propre = re.sub(r"^## ", "### ", resume.strip(), flags=re.M)
        corps += ["## Résumé", "", propre, ""]
    corps += ["## Transcription", "", _paragraphes(texte), ""]
    note.write_text("\n".join(corps), encoding="utf-8")
    if srt:
        note.with_suffix(".srt").write_text(srt, encoding="utf-8")
    _indexer(note, entete)
    return note


def _paragraphes(texte, phrases_par_bloc=4):
    morceaux = re.split(r"(?<=[.!?])\s+", texte)
    blocs = [" ".join(morceaux[i:i + phrases_par_bloc])
             for i in range(0, len(morceaux), phrases_par_bloc)]
    return "\n\n".join(b for b in blocs if b.strip())


def _indexer(note, entete):
    import pathlib
    index = pathlib.Path(reglages.lire()["dossier"]) / "index.md"
    ligne = "- %s - [%s](%s) - %s - %s mots\n" % (
        entete["date"], entete["titre"],
        note.relative_to(index.parent).as_posix(), entete["duree"], entete["mots"])
    if not index.exists():
        index.write_text("# Transcriptions\n\n", encoding="utf-8")
    with index.open("a", encoding="utf-8") as f:
        f.write(ligne)
