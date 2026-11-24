# Chat riche

Les réponses de Claude dans le chat de CCS peuvent contenir des images, des sons, des vidéos et
de petits composants interactifs. Claude en est averti à chaque lancement par une consigne
courte (`RICH_HINT`, dans `ccs_app/chat_engine.py`) ; le chat Market les utilise pour ses
annonces (`CLAUDE_MD`, dans `ccs_app/market.py`).

## Images et médias

- Image Markdown `![texte](adresse)` :
  - adresse https ;
  - ou chemin local, absolu ou relatif au dossier de la session.
- Sur le web, l'image reste en taille limitée et s'ouvre en grand d'un clic.
- Un lien ou un `chemin` vers un son ou une vidéo reçoit un lecteur :
  - sons : mp3, ogg, wav, m4a, opus ;
  - vidéos : mp4, webm, mov.
- Adresses refusées : `javascript:`, `data:`, http sans s, `//hôte`.

## Blocs `ccs`

Un bloc de code de langue `ccs` contenant un objet JSON devient un composant. Un JSON invalide,
un type inconnu ou une liste vide laisse le bloc de code tel quel.

### choix

```json
{"type": "choix", "titre": "Que faire ?", "options": ["Oui", {"label": "Voir", "message": "Montre les détails"}]}
```

- Le titre peut aussi s'écrire `question`.
- Un clic envoie `message` (à défaut, `label`) comme si Charles l'avait tapé.
- Après ce clic, tous les boutons du bloc sont désactivés.

### carte et cartes

```json
{"type": "cartes", "items": [
  {"titre": "Vélo", "image": "https://…/v.jpg", "prix": "45 000 FCFA", "sous_titre": "Lomé",
   "description": "Bon état", "lien": "https://…",
   "actions": [{"label": "Plus", "message": "Plus sur le vélo"}, {"label": "Site", "lien": "https://…"}]}
]}
```

- Pour une seule fiche : `{"type": "carte", "titre": …}`.
- Le `titre` est obligatoire ; dans `cartes`, les items sans titre sont ignorés.
- `lien` : http(s) seulement, ouvert dans un nouvel onglet ; tout autre schéma est retiré.
- Une action avec `message` envoie ce texte ; une action avec `lien` ouvre l'adresse.
- Les cartes défilent à l'horizontale.

### formulaire

```json
{"type": "formulaire", "titre": "Recherche", "envoyer": "Chercher", "champs": [
  {"nom": "prix", "label": "Prix max", "type": "nombre"},
  {"nom": "ville", "label": "Ville", "type": "liste", "options": ["Lomé", "Kara"]},
  {"nom": "note", "label": "Note", "type": "texte", "valeur": "", "aide": "facultatif"}]}
```

Le message envoyé contient le titre, puis une ligne `- Libellé : valeur` par champ rempli.

## Où c'est rendu

| | Web | Bureau (GTK) | iOS, Android |
|---|---|---|---|
| choix, carte, cartes | oui | oui | pas encore |
| formulaire | oui | oui | pas encore |
| images https | oui | oui (chargées en arrière-plan) | pas encore |
| images et médias locaux | oui (lus par l'explorateur, 60 Mo au plus) | oui (Gtk.Video) | pas encore |
| sons et vidéos distants | oui | oui (lecteur créé au clic sur « Lire ») | pas encore |

- Web :
  - code dans `ccs_app/web/chat-rich.js`, appelé après chaque rendu de réponse ;
  - la CSP autorise `img-src 'self' data: blob: https:` et `media-src 'self' blob: https:`.
- Bureau :
  - partie commune dans `ccs_app/chat_rich.py` ;
  - rendu dans `ccs_app/gui/markdown_view.py`.
  - Formulaire : le message envoyé est le même que sur le web (titre, puis `- Libellé : valeur`
    par champ rempli) ; bouton ou Entrée dans un champ, une seule fois.
  - Images https : téléchargées dans un fil (8 Mo au plus, 30 gardées en cache), affichées
    dans 600 × 400 au plus ; en cas d'échec, le lien reste. `http:` et `data:` sont refusés.
  - Sons et vidéos https : rien n'est chargé à l'affichage ; le bouton « Lire » crée le lecteur
    (Gtk.Video, lu en continu par GStreamer).
  - Dans les vues des sous-agents, les boutons et champs restent inactifs.

## Android

- Partie commune dans `android-app/.../logique/ChatRiche.kt` (comme `web/chat-rich.js`) ; rendu
  dans `ui/chat/RicheVue.kt`, branché par `MarkdownVue.kt` et fourni par `EcranChat.kt`
  (`LocalRiche`). Hors du chat (aperçu d'un fichier `.md`), le Markdown reste simple.
- Images : 360 dp de large au plus, agrandies d'un toucher. Fichiers du serveur lus par
  `files.download`, adresses https par OkHttp ; 60 Mo au plus, gardés 24 h dans le cache de l'appli.
- Sons : `MediaPlayer` (lecture, pause, position). Vidéos : `VideoView` et ses commandes.
  Rien ne se charge avant le premier toucher.
- Blocs `ccs` : boutons, menus déroulants et champs Material ; un bouton n'envoie qu'une fois.
  Dans la vue d'un sous-agent, les boutons restent inactifs.
