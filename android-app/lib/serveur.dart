import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Adresse du serveur CCS, gardée dans les préférences.
class Serveur {
  static const parDefaut = 'https://ccs.mawena.cloud';
  static const _cle = 'serveur';

  static Future<Uri> lire() async {
    final prefs = await SharedPreferences.getInstance();
    return normaliser(prefs.getString(_cle) ?? '') ?? Uri.parse(parDefaut);
  }

  static Future<void> ecrire(Uri adresse) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_cle, adresse.toString());
  }

  /// `ccs.exemple.fr` -> `https://ccs.exemple.fr` ; null si l'adresse n'est pas utilisable.
  static Uri? normaliser(String texte) {
    var t = texte.trim();
    if (t.isEmpty) return null;
    if (!t.contains('://')) t = 'https://$t';
    final uri = Uri.tryParse(t);
    if (uri == null || uri.host.isEmpty || !(uri.scheme == 'https' || uri.scheme == 'http')) return null;
    return uri.path.isEmpty ? uri.replace(path: '/') : uri;
  }
}

/// Écran « Serveur » : changer l'adresse ouverte par l'appli. Rend la nouvelle adresse (ou null).
class EcranServeur extends StatefulWidget {
  const EcranServeur({super.key, required this.actuel});

  final Uri actuel;

  @override
  State<EcranServeur> createState() => _EcranServeurState();
}

class _EcranServeurState extends State<EcranServeur> {
  late final _champ = TextEditingController(text: widget.actuel.toString());
  String? _erreur;

  @override
  void dispose() {
    _champ.dispose();
    super.dispose();
  }

  Future<void> _enregistrer() async {
    final uri = Serveur.normaliser(_champ.text);
    if (uri == null) {
      setState(() => _erreur = 'Adresse invalide (exemple : https://ccs.mawena.cloud)');
      return;
    }
    await Serveur.ecrire(uri);
    if (mounted) Navigator.of(context).pop(uri);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Serveur')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('Adresse de la version web de CCS ouverte par l\'appli.'),
          const SizedBox(height: 16),
          TextField(
            controller: _champ,
            keyboardType: TextInputType.url,
            autocorrect: false,
            decoration: InputDecoration(
              labelText: 'Adresse',
              border: const OutlineInputBorder(),
              errorText: _erreur,
            ),
            onSubmitted: (_) => _enregistrer(),
          ),
          const SizedBox(height: 16),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              TextButton(
                onPressed: () => setState(() {
                  _champ.text = Serveur.parDefaut;
                  _erreur = null;
                }),
                child: const Text('Par défaut'),
              ),
              const SizedBox(width: 8),
              FilledButton(onPressed: _enregistrer, child: const Text('Enregistrer')),
            ],
          ),
        ],
      ),
    );
  }
}
