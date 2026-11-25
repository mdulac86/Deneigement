"""Confiance accordée à chaque source, recalculée automatiquement à chaque passage du robot.

Le tableau de fiabilité (verify.py -> data/verification/scores.json) compare, pour chaque
épisode de neige, ce que chaque source prévoyait la veille avec ce que Climat Québec a mesuré
à Saint-Prosper. On en tire un POIDS par source :

- erreur retenue = écart moyen par épisode (cm) + 2 cm par tempête de 5 cm manquée ou fausse
  alerte, rapportée au nombre d'épisodes;
- les épisodes de l'hiver en cours (suivi en direct) comptent 1,5 fois plus que ceux de la base
  historique : ils reflètent la version actuelle des modèles;
- une source peu mesurée est tirée vers une erreur « par défaut » de 7 cm (6 épisodes fictifs),
  puis s'en détache à mesure que les épisodes réels s'accumulent; une source dérivée d'un modèle
  mesuré (PARENTS : MET Norway <- ECMWF IFS) part plutôt de l'erreur de ce modèle (« à confirmer »);
- poids = (meilleure erreur / erreur de la source)², entre 0,15 et 1.

Aucune source n'est jamais exclue : le poids règle son influence sur le plan et les alertes.
Fonctions pures, testées dans tests/test_trust.py.
"""
ALIASES = {'ifs-live': 'ifs', 'aifs-live': 'aifs', 'gfs-live': 'gfs'}
IGNORE = {'consensus', 'wu'}
# Source sans archive publique, dérivée d'un modèle mesuré : elle part de l'erreur de ce modèle au lieu
# des 7 cm par défaut, puis s'en détache avec ses propres épisodes. MET Norway, hors Scandinavie,
# reprend essentiellement ECMWF IFS (même modèle, interpolé et corrigé à 2 m).
PARENTS = {'met': 'ifs'}
PRIOR_CM = 7.0
PRIOR_EPISODES = 6
LIVE_FACTOR = 1.5
PENALTY_CM = 2.0
FLOOR = 0.15
FIABLE = 0.6  # poids à partir duquel une source suffit seule à confirmer un risque


# Pluie (saison des chantiers) : erreur quotidienne en mm d'eau, sur les jours de précipitations.
KINDS = {
    'neige': {'n': 'episodes', 'err': 'ecart_moyen_cm', 'prior': PRIOR_CM, 'pseudo': PRIOR_EPISODES, 'mesuree': 5},
    'pluie': {'n': 'jours_precip', 'err': 'ecart_precip_mm', 'prior': 4.0, 'pseudo': 15, 'mesuree': 15},
}


def pooled(scores, kind='neige'):
    """{id: {'n': épisodes pondérés, 'err': somme des erreurs, 'episodes': réels, 'hist': n, 'live': n}}"""
    K = KINDS[kind]
    out = {}
    for part, factor in (('historique', 1.0), ('en_direct', LIVE_FACTOR)):
        for r in (scores or {}).get(part) or []:
            k = ALIASES.get(r.get('id'), r.get('id'))
            n, e = r.get(K['n']) or 0, r.get(K['err'])
            if k in IGNORE or not n or e is None:
                continue
            t = (r.get('tempetes') or {}) if kind == 'neige' else {}  # pénalité de tempête : neige seulement
            err = e + PENALTY_CM * ((t.get('manquees') or 0) + (t.get('fausses_alertes') or 0)) / n
            p = out.setdefault(k, {'n': 0.0, 'err': 0.0, 'episodes': 0, 'hist': 0, 'live': 0, 'nom': r.get('nom')})
            p['n'] += n * factor
            p['err'] += err * n * factor
            p['episodes'] += n
            p['hist' if part == 'historique' else 'live'] += n
    return out


def effective(p, kind='neige', prior=None):
    K = KINDS[kind]
    n, err = (p['n'], p['err']) if p else (0.0, 0.0)
    return (err + K['pseudo'] * (K['prior'] if prior is None else prior)) / (n + K['pseudo'])


def weights(scores, ids=(), kind='neige'):
    """Poids de chaque source mesurée, et des `ids` demandés (non mesurés : poids par défaut).
    kind='neige' : écart par épisode de neige (cm); kind='pluie' : écart quotidien de précipitations (mm d'eau)."""
    K = KINDS[kind]
    pool = pooled(scores, kind)
    eff = {k: effective(p, kind) for k, p in pool.items()}
    base = {}  # source dérivée : départ = erreur mesurée du modèle parent
    for k, parent in PARENTS.items():
        own = pool.get(k)
        if parent in pool and pool[parent]['episodes'] >= K['mesuree'] and not (own and own['episodes'] >= K['mesuree']):
            base[k] = parent
            eff[k] = effective(own, kind, eff[parent])
    best = min(list(eff.values()) + [K['prior']])
    out = {}
    for k in set(eff) | set(ids):
        e = eff.get(k, K['prior'])
        p = pool.get(k)
        out[k] = {'poids': round(max(FLOOR, min(1.0, (best / e) ** 2)), 2), ('erreur_cm' if kind == 'neige' else 'erreur_mm'): round(e, 1),
                  'episodes': p['episodes'] if p else 0, 'historique': p['hist'] if p else 0,
                  'cet_hiver': p['live'] if p else 0, 'a_mesurer': K['mesuree'],
                  'statut': 'mesurée' if p and p['episodes'] >= K['mesuree'] else 'à confirmer' if k in base
                  else 'en rodage' if p else 'non mesurée'}
        if k in base:
            out[k]['base'] = base[k]
    return out


TEMP_PRIOR_C, TEMP_PSEUDO = 2.0, 10


def temp_weights(scores, ids=()):
    """Poids des sites pour les températures (max/min du jour) : écart moyen en °C, mesuré chaque jour."""
    rows = {r['id']: r for r in (scores or {}).get('temperatures') or []}
    eff = {k: (r['ecart_c'] * r['jours'] + TEMP_PSEUDO * TEMP_PRIOR_C) / (r['jours'] + TEMP_PSEUDO) for k, r in rows.items()}
    best = min(list(eff.values()) + [TEMP_PRIOR_C])
    return {k: {'poids': round(max(FLOOR, min(1.0, (best / eff.get(k, TEMP_PRIOR_C)) ** 2)), 2),
                'erreur_c': round(eff.get(k, TEMP_PRIOR_C), 1), 'jours': (rows.get(k) or {}).get('jours', 0)}
            for k in set(eff) | set(ids)}


def reliable(table, key):
    """Source assez fiable et assez mesurée pour confirmer seule un risque."""
    t = table.get(key) or {}
    return t.get('poids', 0) >= FIABLE and t.get('statut') == 'mesurée'
