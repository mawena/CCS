"""Tests de CCS.

Jamais sur le bureau réel : sans CCS_GUI_TESTS=1 (posé avec `xvfb-run`, voir `make
unit`), l'affichage est retiré de l'environnement avant tout import de GTK, et les tests
graphiques sont sautés. Wayland est toujours retiré : sous Xvfb, GTK ne peut rejoindre
que l'affichage X de Xvfb.

La synchro des comptes Claude ne sort jamais de la machine (`CCS_NO_ACCOUNT_SYNC=1`).

Les chats du bureau ne passent jamais par le vrai pont local de la machine
(`CCS_CHAT_IN_PROCESS=1`) : les tests du pont en lancent un, sur un socket temporaire."""

import os

os.environ.pop("WAYLAND_DISPLAY", None)
if os.environ.get("CCS_GUI_TESTS") != "1":
    os.environ.pop("DISPLAY", None)

# Les dossiers XDG suivent HOME, que chaque test remplace par un dossier temporaire : une
# variable XDG_*_HOME héritée du bureau ferait lire ou écrire les vrais fichiers.
for _var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
    os.environ.pop(_var, None)
os.environ["CCS_CHAT_IN_PROCESS"] = "1"
# Jamais de synchro de comptes vers les vraies machines du réseau maillé.
os.environ["CCS_NO_ACCOUNT_SYNC"] = "1"
