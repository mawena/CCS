import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';

import 'serveur.dart';
import 'telechargements.dart';

/// Couleurs du manifeste web de CCS (theme_color, background_color) et fond clair du web.
const accent = Color(0xFF3584E4);
const fondSombre = Color(0xFF222226);
const fondClair = Color(0xFFFAFAFB);

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const AppliCcs());
}

class AppliCcs extends StatelessWidget {
  const AppliCcs({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'CCS',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorScheme: ColorScheme.fromSeed(seedColor: accent)),
      darkTheme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: accent, brightness: Brightness.dark),
      ),
      home: const EcranWeb(),
    );
  }
}

/// La version web de CCS en plein écran, façon PWA.
class EcranWeb extends StatefulWidget {
  const EcranWeb({super.key});

  @override
  State<EcranWeb> createState() => _EcranWebState();
}

class _EcranWebState extends State<EcranWeb> {
  final _messager = GlobalKey<ScaffoldMessengerState>();
  late final WebViewController _vue;
  late final Telechargements _telechargements;
  Uri? _serveur;
  int _progression = 0;
  String? _horsLigne; // description de l'erreur de chargement, ou null
  DateTime? _dernierRetour;
  Color? _fond; // fond déjà donné à la vue web

  @override
  void initState() {
    super.initState();
    _telechargements = Telechargements(annoncer: _annoncer);
    _vue = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..addJavaScriptChannel(canalJs, onMessageReceived: (m) => _telechargements.recevoir(m.message))
      ..setNavigationDelegate(NavigationDelegate(
        onNavigationRequest: _navigation,
        onProgress: (p) => setState(() => _progression = p),
        onPageStarted: (_) => setState(() => _progression = 0),
        onPageFinished: (_) {
          setState(() => _progression = 100);
          _vue.runJavaScript(scriptTelechargements);
        },
        onWebResourceError: (e) {
          if (e.isForMainFrame ?? false) setState(() => _horsLigne = e.description);
        },
      ));
    final plateforme = _vue.platform;
    if (plateforme is AndroidWebViewController) {
      // Stockage DOM et cookies persistants sont actifs par défaut dans la vue web d'Android.
      plateforme.setOnShowFileSelector(_choisirFichiers);
      plateforme.setMediaPlaybackRequiresUserGesture(false);
    }
    Serveur.lire().then(_ouvrir);
  }

  void _ouvrir(Uri adresse) {
    setState(() {
      _serveur = adresse;
      _horsLigne = null;
    });
    _vue.loadRequest(adresse);
  }

  void _annoncer(String texte) {
    _messager.currentState
      ?..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(texte)));
  }

  /// Le serveur et les sites du même domaine (portier.mawena.cloud pour la connexion) restent
  /// dans la vue, sinon la connexion finirait dans le navigateur ; tout le reste part dehors.
  bool _memeSite(String hote) {
    final serveur = _serveur?.host;
    if (serveur == null || serveur.isEmpty) return false;
    if (hote == serveur) return true;
    final parties = serveur.split('.');
    if (parties.length < 2 || RegExp(r'^[0-9.]+$').hasMatch(serveur)) return false;
    final base = parties.sublist(parties.length - 2).join('.');
    return hote == base || hote.endsWith('.$base');
  }

  FutureOr<NavigationDecision> _navigation(NavigationRequest requete) async {
    final uri = Uri.tryParse(requete.url);
    if (uri == null) return NavigationDecision.prevent;
    if (const {'about', 'blob', 'data', 'javascript'}.contains(uri.scheme)) return NavigationDecision.navigate;
    final web = uri.scheme == 'http' || uri.scheme == 'https';
    if (web && (!requete.isMainFrame || _memeSite(uri.host))) return NavigationDecision.navigate;
    if (!await launchUrl(uri, mode: LaunchMode.externalApplication)) {
      _annoncer('Aucune application pour ouvrir ce lien.');
    }
    return NavigationDecision.prevent;
  }

  /// `<input type=file>` du web : sélecteur de fichiers d'Android.
  Future<List<String>> _choisirFichiers(FileSelectorParams params) async {
    final types = params.acceptTypes.where((t) => t.trim().isNotEmpty).toList();
    final images = types.isNotEmpty && types.every((t) => t.trim().startsWith('image/'));
    final choix = await FilePicker.platform.pickFiles(
      allowMultiple: params.mode == FileSelectorMode.openMultiple,
      type: images ? FileType.image : FileType.any,
    );
    if (choix == null) return [];
    return [
      for (final f in choix.files)
        if (f.path != null) Uri.file(f.path!).toString(),
    ];
  }

  Future<void> _changerServeur() async {
    final actuel = _serveur ?? Uri.parse(Serveur.parDefaut);
    final nouveau = await Navigator.of(context).push<Uri>(
      MaterialPageRoute(builder: (_) => EcranServeur(actuel: actuel)),
    );
    if (nouveau != null) _ouvrir(nouveau);
  }

  /// Retour : historique de la vue web ; sinon un second appui dans les 2 s quitte.
  Future<void> _retour() async {
    if (_horsLigne == null && await _vue.canGoBack()) {
      await _vue.goBack();
      return;
    }
    final maintenant = DateTime.now();
    if (_dernierRetour != null && maintenant.difference(_dernierRetour!) < const Duration(seconds: 2)) {
      await SystemNavigator.pop();
      return;
    }
    _dernierRetour = maintenant;
    _messager.currentState
      ?..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: const Text('Appuyez encore sur Retour pour quitter.'),
        duration: const Duration(seconds: 2),
        action: SnackBarAction(label: 'Serveur', onPressed: _changerServeur),
      ));
  }

  @override
  Widget build(BuildContext context) {
    final sombre = MediaQuery.platformBrightnessOf(context) == Brightness.dark;
    final fond = sombre ? fondSombre : fondClair;
    if (fond != _fond) {
      _fond = fond;
      _vue.setBackgroundColor(fond);
    }
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle(
        statusBarColor: accent,
        statusBarIconBrightness: Brightness.light,
        statusBarBrightness: Brightness.dark,
        systemNavigationBarColor: fond,
        systemNavigationBarIconBrightness: sombre ? Brightness.light : Brightness.dark,
      ),
      child: ScaffoldMessenger(
        key: _messager,
        child: PopScope(
          canPop: false,
          onPopInvokedWithResult: (aFerme, _) {
            if (!aFerme) _retour();
          },
          child: Scaffold(
            backgroundColor: fond,
            body: Column(
              children: [
                // Barre d'état aux couleurs du thème (l'appli est affichée bord à bord).
                Container(height: MediaQuery.paddingOf(context).top, color: accent),
                Expanded(
                  child: SafeArea(
                    top: false,
                    child: Stack(
                      children: [
                        WebViewWidget(controller: _vue),
                        if (_progression < 100 && _horsLigne == null)
                          LinearProgressIndicator(value: _progression / 100, minHeight: 2),
                        if (_horsLigne != null)
                          Positioned.fill(
                            child: HorsLigne(
                              serveur: _serveur,
                              erreur: _horsLigne!,
                              reessayer: () => _ouvrir(_serveur ?? Uri.parse(Serveur.parDefaut)),
                              changerServeur: _changerServeur,
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Écran affiché quand la page ne se charge pas.
class HorsLigne extends StatelessWidget {
  const HorsLigne({
    super.key,
    required this.serveur,
    required this.erreur,
    required this.reessayer,
    required this.changerServeur,
  });

  final Uri? serveur;
  final String erreur;
  final VoidCallback reessayer;
  final VoidCallback changerServeur;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ColoredBox(
      color: theme.colorScheme.surface,
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.cloud_off, size: 64, color: theme.colorScheme.outline),
              const SizedBox(height: 16),
              Text('Serveur injoignable', style: theme.textTheme.titleLarge),
              const SizedBox(height: 8),
              Text(
                '${serveur ?? ''}\n$erreur',
                textAlign: TextAlign.center,
                style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
              const SizedBox(height: 24),
              FilledButton.icon(onPressed: reessayer, icon: const Icon(Icons.refresh), label: const Text('Réessayer')),
              const SizedBox(height: 8),
              TextButton(onPressed: changerServeur, child: const Text('Changer de serveur')),
            ],
          ),
        ),
      ),
    );
  }
}
