// CCS : boutons « Copier » de la page d'accueil.
(function () {
  'use strict';
  document.querySelectorAll('.copier').forEach(function (bouton) {
    bouton.addEventListener('click', function () {
      var cible = document.getElementById(bouton.dataset.cible);
      var texte = cible.textContent;
      var fini = function () {
        bouton.textContent = 'Copié';
        bouton.classList.add('copie');
        setTimeout(function () { bouton.textContent = 'Copier'; bouton.classList.remove('copie'); }, 2000);
      };
      var selectionner = function () {
        var plage = document.createRange();
        plage.selectNodeContents(cible);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(plage);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(texte).then(fini, selectionner);
      } else {
        selectionner();
      }
    });
  });
})();
