"""Limite des essais de connexion : au-delà de `max_failures` échecs dans la fenêtre, la clé
(utilisateur ou adresse IP) est refusée pendant `block` secondes."""


class Limiter:
    def __init__(self, max_failures=5, window=900, block=900, max_keys=10000):
        self.max_failures = max_failures
        self.max_keys = max_keys
        self.window = window
        self.block = block
        self._failures = {}      # clé → [instants]
        self._until = {}         # clé → fin du refus

    def blocked(self, key, now):
        until = self._until.get(key)
        if until is None:
            return False
        if now >= until:
            self._until.pop(key, None)
            self._failures.pop(key, None)
            return False
        return True

    def retry_after(self, key, now):
        until = self._until.get(key)
        return max(0, int(until - now)) if until is not None and now < until else 0

    def failure(self, key, now):
        if self.blocked(key, now):
            return
        recent = [t for t in self._failures.get(key, []) if now - t < self.window]
        recent.append(now)
        self._failures[key] = recent
        if len(self._failures) > self.max_keys:
            self._prune(now)
        if len(recent) >= self.max_failures:
            self._until[key] = now + self.block

    def success(self, key):
        self._failures.pop(key, None)
        self._until.pop(key, None)

    def _prune(self, now):
        """Mémoire bornée : un attaquant qui invente des identifiants ne la fait pas grossir
        sans fin. Les clés les plus anciennes partent d'abord ; un blocage en cours reste."""
        for k in [k for k, until in self._until.items() if until <= now]:
            del self._until[k]
        keep = max(1, int(self.max_keys * 0.9))
        by_age = sorted(self._failures, key=lambda k: self._failures[k][-1])
        for k in by_age[:max(0, len(self._failures) - keep)]:
            del self._failures[k]
