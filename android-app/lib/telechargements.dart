import 'dart:async';
import 'dart:convert';

import 'package:flutter/services.dart';

/// Nom du canal JavaScript par lequel la page remet ses fichiers à l'appli.
const canalJs = 'CcsAndroid';

/// Injecté à chaque chargement de page. Le web télécharge en remettant un lien `blob:` (ou `data:`)
/// avec l'attribut `download` au navigateur ; la vue web d'Android l'ignore. On intercepte le clic,
/// on lit le contenu et on l'envoie à l'appli par morceaux (base64), qui l'enregistre dans
/// Téléchargements.
const scriptTelechargements = r'''
(function () {
  if (window.__ccsAndroid) return;
  window.__ccsAndroid = true;
  var MORCEAU = 786432, suivant = 0;
  function poster(o) { CcsAndroid.postMessage(JSON.stringify(o)); }
  function lire(b) {
    return new Promise(function (ok, ko) {
      var r = new FileReader();
      r.onload = function () { var s = r.result; ok(s.slice(s.indexOf(',') + 1)); };
      r.onerror = function () { ko(r.error); };
      r.readAsDataURL(b);
    });
  }
  async function envoyer(url, nom) {
    var id = ++suivant;
    try {
      var blob = await (await fetch(url)).blob();
      poster({ t: 'debut', id: id, nom: nom, type: blob.type || '' });
      for (var o = 0; o < blob.size; o += MORCEAU) {
        poster({ t: 'morceau', id: id, d: await lire(blob.slice(o, o + MORCEAU)) });
      }
      poster({ t: 'fin', id: id });
    } catch (e) {
      poster({ t: 'erreur', id: id, m: String(e) });
    }
  }
  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest ? e.target.closest('a[download]') : null;
    if (!a) return;
    var h = a.href || '';
    if (h.indexOf('blob:') !== 0 && h.indexOf('data:') !== 0) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    envoyer(h, a.getAttribute('download') || h.split('/').pop() || 'fichier');
  }, true);
})();
''';

/// Reçoit les messages du canal JavaScript et écrit les fichiers par le canal natif
/// (MainActivity.kt). Les messages sont traités un par un, dans l'ordre.
class Telechargements {
  Telechargements({required this.annoncer});

  /// Message court pour l'utilisateur (fichier enregistré, échec).
  final void Function(String) annoncer;

  static const _natif = MethodChannel('com.mawena.ccs/telechargements');
  final _ouverts = <int, ({int natif, String nom})>{};
  final _rates = <int>{};
  Future<void> _file = Future.value();

  void recevoir(String message) {
    _file = _file.then((_) => _traiter(message));
  }

  Future<void> _traiter(String message) async {
    final Map<String, dynamic> m;
    try {
      m = jsonDecode(message) as Map<String, dynamic>;
    } catch (_) {
      return;
    }
    final id = m['id'] as int;
    // Les numéros repartent de 1 à chaque chargement de page.
    if (m['t'] == 'debut') _rates.remove(id);
    if (_rates.contains(id)) return;
    try {
      switch (m['t']) {
        case 'debut':
          final nom = (m['nom'] as String?) ?? 'fichier';
          final natif = await _natif.invokeMethod<int>('ouvrir', {'nom': nom, 'type': m['type'] ?? ''});
          _ouverts[id] = (natif: natif!, nom: nom);
        case 'morceau':
          final o = _ouverts[id];
          if (o == null) return;
          await _natif.invokeMethod('ecrire', {'id': o.natif, 'donnees': base64Decode(m['d'] as String)});
        case 'fin':
          final o = _ouverts.remove(id);
          if (o == null) return;
          final nom = await _natif.invokeMethod<String>('fermer', {'id': o.natif});
          annoncer('« ${nom ?? o.nom} » enregistré dans Téléchargements.');
        case 'erreur':
          await _abandonner(id, 'Téléchargement impossible : ${m['m']}');
      }
    } catch (e) {
      await _abandonner(id, 'Téléchargement impossible : ${e is PlatformException ? e.message : e}');
    }
  }

  Future<void> _abandonner(int id, String raison) async {
    _rates.add(id);
    final o = _ouverts.remove(id);
    if (o != null) {
      try {
        await _natif.invokeMethod('annuler', {'id': o.natif});
      } catch (_) {}
    }
    annoncer(raison);
  }
}
