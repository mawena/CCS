"""Tests de CCS.

Jamais sur le bureau réel : sans CCS_GUI_TESTS=1 (posé avec `xvfb-run`, voir `make
unit`), l'affichage est retiré de l'environnement avant tout import de GTK, et les tests
graphiques sont sautés. Wayland est toujours retiré : sous Xvfb, GTK ne peut rejoindre
que l'affichage X de Xvfb."""

import os

os.environ.pop("WAYLAND_DISPLAY", None)
if os.environ.get("CCS_GUI_TESTS") != "1":
    os.environ.pop("DISPLAY", None)
