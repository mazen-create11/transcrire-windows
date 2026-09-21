"""Point d'entree : demarre le serveur local et ouvre l'interface."""
import argparse
import os
import sys
import threading
import webbrowser

from . import moteur, reglages, serveur


def main():
    if os.name == "nt":  # la console Windows n'est pas en UTF-8 par defaut
        for flux in (sys.stdout, sys.stderr):
            try:
                flux.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    arguments = argparse.ArgumentParser(
        prog="transcrire", description="Enregistrer, transcrire et résumer en local.")
    arguments.add_argument("--port", type=int, default=None)
    arguments.add_argument("--sans-navigateur", action="store_true")
    arguments.add_argument("--modele", default=None,
                           help="tiny, base, small, medium ou large-v3")
    arguments.add_argument("--dossier", default=None,
                           help="où ranger les notes")
    options = arguments.parse_args()

    modifs = {}
    if options.modele:
        modifs["modele"] = options.modele
    if options.dossier:
        modifs["dossier"] = options.dossier
    if modifs:
        reglages.ecrire(modifs)

    httpd, port = serveur.lancer(options.port)
    adresse = "http://127.0.0.1:%d/" % port
    valeurs = reglages.lire()

    print("")
    print("  Transcrire " + serveur.VERSION)
    print("  Interface : " + adresse)
    print("  Notes     : " + valeurs["dossier"])
    print("  Modèle    : %s (%s)" % (valeurs["modele"], moteur._materiel()[0]))
    print("")
    print("  Laisse cette fenêtre ouverte. Ferme-la pour quitter.")
    print("")

    threading.Thread(target=_prechauffer, daemon=True).start()
    if not options.sans_navigateur:
        threading.Timer(0.6, lambda: webbrowser.open(adresse)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("  Arrêt.")
        httpd.shutdown()


def _prechauffer():
    """Charge le modele des le demarrage : le premier enregistrement part vite."""
    try:
        moteur.charger(journal=lambda m: print("  " + m))
        print("  Modèle prêt.")
    except Exception as erreur:
        print("  Modèle non chargé : %s" % erreur, file=sys.stderr)


if __name__ == "__main__":
    main()
