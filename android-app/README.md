# CCS pour Android

Application Android (Flutter) qui ouvre la version web de CCS — par défaut
https://ccs.mawena.cloud — en plein écran, comme la PWA, avec ce que la vue web d'Android
ne fait pas seule :

- connexion gardée entre deux lancements (cookies et stockage du navigateur persistants) ;
- envoi de fichiers (`<input type=file>`) par le sélecteur de fichiers d'Android ;
- téléchargements du gestionnaire de fichiers enregistrés dans **Téléchargements** ;
- liens vers un autre domaine (et `mailto:`, `tel:`…) ouverts dans le navigateur ;
- bouton Retour : historique de la page, puis un second appui quitte ;
- écran « Serveur injoignable » avec **Réessayer** si la page ne se charge pas.

**Changer de serveur** : appuyer sur Retour à la page d'accueil, puis sur **Serveur** dans le
bandeau (ou **Changer de serveur** sur l'écran hors ligne). L'adresse est gardée.

## Construire

Le VPS n'a pas Flutter : la construction se fait sur `pc-bureau`, depuis ce dossier, après commit
(l'envoi ignore ce que git ignore) :

```sh
ccs distant lancer --machine pc-bureau -- flutter pub get
ccs distant lancer --machine pc-bureau -- flutter analyze
ccs distant lancer --machine pc-bureau --rapatrier build/app/outputs/flutter-apk -- flutter build apk --release
```

L'APK arrive dans `build/app/outputs/flutter-apk/app-release.apk`.

## Signature

Comme Portail, la version de publication est signée avec la **clé de débogage** de la machine qui
construit (`~/.android/debug.keystore` de `pc-bureau`) : il faut donc toujours construire sur
`pc-bureau` pour pouvoir installer une mise à jour par-dessus l'appli déjà installée. Pour une vraie
clé, créer un `android/key.properties` (ignoré par git) et un `signingConfig` dans
`android/app/build.gradle.kts`.

## Structure

- `lib/main.dart` : vue web, navigation, retour, envoi de fichiers, écran hors ligne.
- `lib/serveur.dart` : adresse du serveur (préférences) et écran « Serveur ».
- `lib/telechargements.dart` : interception des liens `blob:` du web, envoi par morceaux.
- `android/app/src/main/kotlin/com/mawena/ccs/MainActivity.kt` : écriture dans Téléchargements.

Paquet Android : `com.mawena.ccs`. Version : celle de CCS (`pubspec.yaml`).
