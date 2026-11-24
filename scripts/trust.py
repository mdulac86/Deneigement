"""Confiance accordée à chaque source, recalculée automatiquement à chaque passage du robot.

Le tableau de fiabilité (verify.py -> data/verification/scores.json) compare, pour chaque
épisode de neige, ce que chaque source prévoyait la veille avec ce que Climat Québec a mesuré
à Saint-Prosper. On en tire un POIDS par source :

- erreur retenue = écart moyen par épisode (cm) + 2 cm par tempête de 5 cm manquée ou fausse
  alerte, rapportée au nombre d'épisodes;
- les épisodes de l'hiver en cours (suivi en direct) comptent 1,5 fois plus que ceux de la base
  historique : ils reflètent la version actuelle des modèles;
- une source peu mesurée est tirée vers une erreur « par défaut » de 7 cm (6 épisodes fictifs),
  puis s'en détache à mesure que les épisodes réels s'accumulent;
- poids = (meilleure erreur / erreur de la source)², entre 0,15 et 1.

Aucune source n'est jamais exclue : le poids règle son influence sur le plan et les alertes.
Fonctions pures, testées dans tests/test_trust.py.
"""
ALIASES = {'ifs-live': 'ifs', 'aifs-live': 'aifs', 'gfs-live': 'gfs'}
IGNORE = {'consensus', 'wu'}
PRIOR_CM = 7.0
PRIOR_EPISODES = 6
LIVE_FACTOR = 1.5
PENALTY_CM = 2.0
FLOOR = 0.15
FIABLE = 0.6  # poids à partir duquel une source suffit seule à confirmer un risque


def pooled(scores):
    """{id: {'n': épisodes pondérés, 'err': somme des erreurs, 'episodes': réels, 'hist': n, 'live': n}}"""
    out = {}
    for part, factor in (('historique', 1.0), ('en_direct', LIVE_FACTOR)):
        for r in (scores or {}).get(part) or []:
            k = ALIASES.get(r.get('id'), r.get('id'))
            n, e = r.get('episodes') or 0, r.get('ecart_moyen_cm')
            if k in IGNORE or not n or e is None:
                continue
            t = r.get('tempetes') or {}
            err = e + PENALTY_CM * ((t.get('manquees') or 0) + (t.get('fausses_alertes') or 0)) / n
            p = out.setdefault(k, {'n': 0.0, 'err': 0.0, 'episodes': 0, 'hist': 0, 'live': 0, 'nom': r.get('nom')})
            p['n'] += n * factor
            p['err'] += err * n * factor
            p['episodes'] += n
            p['hist' if part == 'historique' else 'live'] += n
    return out


def effective(p):
    n, err = (p['n'], p['err']) if p else (0.0, 0.0)
    return (err + PRIOR_EPISODES * PRIOR_CM) / (n + PRIOR_EPISODES)


def weights(scores, ids=()):
    """Poids de chaque source mesurée, et des `ids` demandés (non mesurés : poids par défaut)."""
    pool = pooled(scores)
    eff = {k: effective(p) for k, p in pool.items()}
    best = min(list(eff.values()) + [PRIOR_CM])
    out = {}
    for k in set(eff) | set(ids):
        e = eff.get(k, PRIOR_CM)
        p = pool.get(k)
        out[k] = {'poids': round(max(FLOOR, min(1.0, (best / e) ** 2)), 2), 'erreur_cm': round(e, 1),
                  'episodes': p['episodes'] if p else 0, 'historique': p['hist'] if p else 0,
                  'cet_hiver': p['live'] if p else 0,
                  'statut': 'mesurée' if p and p['episodes'] >= 5 else 'en rodage' if p else 'non mesurée'}
    return out


def reliable(table, key):
    """Source assez fiable et assez mesurée pour confirmer seule un risque."""
    t = table.get(key) or {}
    return t.get('poids', 0) >= FIABLE and t.get('statut') == 'mesurée'
