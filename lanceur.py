"""Point d'entree du paquet Windows (PyInstaller n'aime pas `python -m`)."""
import multiprocessing

from transcrire.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
