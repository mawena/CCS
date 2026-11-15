"""Calculs des graphiques, sans GTK (testables sans écran)."""

WEEK_S = 7 * 86400


def series_to_points(series, t0, t1, width, height):
    """(ts, %) → coordonnées écran ; % borné à 0–100, points hors [t0, t1] ignorés."""
    if t1 <= t0:
        return []
    out = []
    for ts, value in series:
        if ts < t0 or ts > t1:
            continue
        v = min(100.0, max(0.0, float(value)))
        out.append(((ts - t0) / (t1 - t0) * width, height - v / 100 * height))
    return out


def ideal_weekly_series(samples):
    """Rythme idéal (%) aux instants des relevés hebdo (ts, %, reset_ts)."""
    out = []
    for ts, _, reset in samples:
        if reset is None:
            continue
        frac = 1 - (reset - ts) / WEEK_S
        out.append((ts, 100.0 * min(1.0, max(0.0, frac))))
    return out


def span_to_x(t, t0, t1, width):
    """Position horizontale de l'instant t sur [t0, t1], bornée à la largeur."""
    if t1 <= t0:
        return 0.0
    return min(float(width), max(0.0, (t - t0) / (t1 - t0) * width))
