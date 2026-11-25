# Déneigement · Saint-Prosper

Application statique pour l'équipe : prévisions comparées, bulletin officiel,
radar animé et cumul de l'hiver à partir des relevés publiés de Saint-Prosper.
Seuil opérationnel affiché : **5 cm de nouvelle neige au sol**.

## Mise en ligne sur GitHub

1. Créer `mdulac86/Deneigement`, **public**, avec un README pour initialiser `main`.
2. Publier le contenu de ce projet à la racine du dépôt, y compris `.github/workflows/meteo.yml`.
3. Dans **Settings → Pages → Build and deployment**, sélectionner **GitHub Actions**.
4. Dans **Actions → Robot météo et publication**, lancer **Run workflow**.
5. Partager `https://mdulac86.github.io/Deneigement/` une fois le déploiement vert.

Le dépôt public et le site ne contiennent que des données météo publiques. Ne pas
y ajouter de clients, adresses de contrats, horaires de personnel ou mots de passe.
Un site GitHub Pages public est accessible à toute personne qui connaît le lien.
Pour un accès strictement réservé aux employés, choisir un hébergement avec
authentification réelle; un mot de passe dans le JavaScript ne protège pas le site.

Le robot utilise GitHub Actions, collecte quatre fois par jour (0 h, 6 h, 12 h et 18 h, heure du Québec) et archive
les états dans Git. Les tâches planifiées peuvent être retardées par GitHub.
Sur un dépôt public inactif, GitHub peut désactiver les planifications après 60
jours : consulter Actions si le bandeau de fraîcheur indique des données anciennes.
L'actualisation MET Norway respecte son intervalle minimal de 3 heures hors pays
nordiques. Les pages publiques des autres fournisseurs peuvent changer ou refuser
la lecture automatisée; le robot indique alors « non disponible » sans contourner
la restriction et sans compter une ancienne donnée dans le consensus.

## Sources réellement branchées

- Environnement Canada, API GeoMet `citypageweather-realtime/qc-b6` : secteur de
  Saint-Georges incluant Saint-Prosper; bulletin 7 jours, horaire et quantités
  explicitement publiées par période. Alertes via `weather-alerts` et boîte
  géographique autour de Saint-Prosper.
- meteoblue : cartes quotidiennes datées, conditions et températures.
- MET Norway : API Locationforecast, licence CC BY 4.0; températures, conditions,
  vent et précipitations liquides par échéance. Pas de conversion arbitraire en neige.
- MétéoMédia : tableau de données structurées (schema.org / CSVW) publié dans la
  page 7 jours : conditions, températures, pluie en mm et **neige en cm** par période
  (nuit, matin, après-midi, soir). Les 4 périodes donnent un total 00-24 h comparable;
  les cm entrent aussi dans le plan de sortie (répartis sur chaque heure de la période).
- AccuWeather et Weather Underground refusent toute lecture automatisée (403, même depuis
  le bureau) : retirés des sources. MétéoMédia (page de vérification) refuse les serveurs
  de GitHub : il est lu par le relais du bureau.
- L'interface n'affiche que les sources qui fonctionnent (à jour, ou lues dans les 24 h).
- **Relais du bureau** (`scripts/pc_relay.py`) : le conteneur du NAS Synology (`relais/`)
  ou une tâche planifiée Windows lit MétéoMédia à 23 h 45, 5 h 45, 11 h 45 et
  17 h 45, puis publie `data/relay.json`, ce qui relance le robot. Le robot utilise
  ces lectures pendant 7 h. PC éteint = pas de nouvelle lecture : l'appli affiche
  les données comme anciennes. Journal : `deneigement-relais.log` à côté du dossier.
- Climat Québec / MELCCFP : sommaire de la station automatique **7027660**,
  relevés quotidiens depuis le 1er octobre; relecture quotidienne de tous les mois
  de la saison afin de récupérer les corrections tardives. Saison jusqu'au 31 mai.
  Les mois/jours manquants restent manquants. Les valeurs marquées `I` sont exclues.
- Radar ECCC GeoMet : pluie, neige ou type de précipitations; temps réellement
  disponibles lus dans GetCapabilities, animation sur environ 2 heures. Rafraîchi
  lorsque l'onglet est ouvert. Fond Esri World Topographic Map, bibliothèque Leaflet.

## Modèle européen et probabilité de 5 cm

`scripts/ecmwf.py` lit les données ouvertes ECMWF (CC BY 4.0) : le modèle IFS (neige
tombée aux 3 h, 72 h) et le modèle AIFS à intelligence artificielle (aux 6 h) entrent dans le
plan de sortie, et l'ensemble de 51 versions donne,
pour chaque jour, la probabilité d'avoir 5 cm ou plus et la fourchette 10-90 %.

## Modèles américains NBM et HRRR

`scripts/noaa.py` lit deux produits NOAA (domaine public) sur Amazon Open Data, par plages
d'octets comme GFS et ECMWF. Saint-Prosper est dans leur grille (point le plus proche à ≈ 1 km).

- **NBM** (National Blend of Models, 2,5 km) : synthèse corrigée d'une trentaine de modèles.
  Neige tombée par tranche de 6 h jusqu'à 72 h, et **probabilité de dépasser 2,5 cm et 5 cm**
  par tranche de 6 h jusqu'à 48 h (panneau « Chances de neige par tranche de 6 h »). Les tranches
  se terminent à 00, 06, 12 et 18 UTC, quel que soit le cycle lu.
- **HRRR** (3 km) : neige tombée heure par heure jusqu'à 24 h, puis par 3 h jusqu'à 48 h
  (runs de 00, 06, 12 et 18 UTC), température et **pluie verglaçante** prévue. Deux heures et
  plus de pluie verglaçante dans la journée ajoutent le risque « Verglas / grésil ».

Les deux entrent dans le plan de sortie et dans le tableau de fiabilité.

## Routes autour de Saint-Prosper

`scripts/routes.py` lit le service WFS du ministère des Transports (Québec 511, CC BY 4.0)
dans un rayon de 45 km : état des routes en hiver (chaussée, visibilité, lames de neige, noté par
les patrouilleurs), avertissements routiers en cours et caméras de circulation (courte vidéo
chargée depuis Québec 511 quand on touche « Voir »). La station météoroutière de Saint-Georges
ne publie que la profondeur de gel (déjà lue par `frost.py`).

Écartés : CoCoRaHS (un seul observateur à moins de 120 km, à Sainte-Foy), Open-Meteo (gratuit
seulement pour un usage non commercial), MyRadar (API payante, couverture surtout américaine).

## Confiance automatique dans les sources

`scripts/trust.py` transforme le tableau de fiabilité en **poids**, recalculés à chaque passage
du robot (aucune intervention) :

1. `verify.py` compare, pour chaque épisode de neige mesuré par Climat Québec, ce que chaque
   source prévoyait la veille (base historique + archives du robot cet hiver).
2. Erreur retenue = écart moyen par épisode + 2 cm par tempête de 5 cm manquée ou fausse alerte.
   Les épisodes de cet hiver comptent 1,5 fois plus. Une source peu mesurée part d'une erreur
   par défaut de 7 cm (6 épisodes fictifs) et s'en détache à mesure que les épisodes s'accumulent.
   MET Norway (dérivé d'ECMWF IFS hors Scandinavie) part plutôt de l'erreur mesurée d'IFS, « à confirmer ».
   HRDPS, RDPS, MétéoMédia et MET Norway n'ont pas d'archive publique : le robot garde leurs prévisions
   depuis le 11 novembre 2026; elles deviennent « mesurées » après 5 épisodes de neige.
3. Poids = (meilleure erreur / erreur de la source)², entre 0,15 et 1.

Utilisation :
- **Plan de sortie** : médiane pondérée des modèles; la fourchette ne retient que les modèles de
  poids 0,4 et plus. Les alertes de sortie citent les modèles mesurés les plus fiables.
- **Alertes de risque** (verglas, pluie sur la neige) : envoyées seulement si le risque vient
  d'Environnement Canada, d'au moins 2 sources, ou d'une source « mesurée » (5 épisodes et plus)
  de poids 0,6 et plus. Sinon il est affiché « à confirmer », sans alerte. La pluie verglaçante
  HRRR suit la même règle.
- Onglet Sources : tableau « Poids accordé à chaque source en ce moment ».

## Modèle ou source isolé

Si une seule source prévoit beaucoup plus que les autres (plus du double de la médiane des autres,
au moins 8 cm de plus, et aucune autre source à moins de 30 % d'elle), elle est **mise de côté** :
elle ne compte ni dans la fourchette, ni dans « sortie possible », ni dans les alertes, et le plan
la nomme (« HRRR prévoit ≈ 30 cm, très au-dessus des autres modèles : mis de côté »). Deux sources
d'accord sur un gros total ne sont jamais mises de côté. Heure par heure, la fourchette est le
20 % – 80 % pondéré des modèles (dès 3 modèles) au lieu du minimum – maximum.

**Probabilité de sortie** (`plan.probability`) : moyenne de la part des modèles (pondérés par leur fiabilité)
qui atteignent le seuil sur l'épisode, de l'ensemble européen (part des 51 versions à 2 cm et plus) et
du NBM (probabilité de 2,5 cm et plus en 6 h). Une « sortie possible » sous 30 % (`possible_min_pct`
dans config/plan.json) redevient « sous le seuil » : un seul modèle enneigé ne suffit plus.

## Fréquence du robot (adaptative)

Le workflow est lancé toutes les heures et décide :
- **passage complet** à 0 h, 6 h, 12 h et 18 h (heure du Québec), et à chaque publication du relais;
- **passage rapide** les autres heures **seulement si une tempête est en vue** : une sortie prévue ou
  possible qui commence dans les 36 h (ou en cours), ou une alerte d'Environnement Canada
  (`tempete` dans `data/weather.json`). Le passage rapide relit Environnement Canada, MET Norway,
  meteoblue, NBM, le dernier run horaire HRRR (18 h, complété par le dernier run de 48 h), les
  routes et la neige au sol; HRDPS, RDPS et GFS sont repris du dernier passage complet; ECMWF est
  déjà mis en cache. Pas d'archive ni de recalcul de fiabilité en passage rapide;
- **rien** par temps calme.

Anti-va-et-vient : un changement d'heure de départ (1 h et plus) ou une annulation n'est annoncé
que si deux passages de suite sont d'accord, sauf si le départ est dans moins de 3 h.

## Été et saison des sucres

- **Orages** : d'avril à novembre, une forte pluie, un orage ou une menace de foudre (champ LTNG de
  HRRR, lu d'avril à octobre) prévus de jour dans les 36 h font passer le robot toutes les heures.
  La foudre HRRR seule est affichée (« Foudre possible ») sans alerte.
- **Pluie** : poids « pluie » par modèle (`confiance_pluie`, écart quotidien en mm d'eau vs Climat
  Québec), utilisés pour la pluie des chantiers et la détection de forte pluie. Climat Québec est
  maintenant lu d'octobre à **septembre** (la neige reste comptée d'octobre à mai).
- **Heures sèches et forte pluie** : NBM et MétéoMédia (tranches de 6 h réparties sur chaque heure)
  ne comptent pas heure par heure.
- **Dégel et travaux (MTQ)** : période de dégel de la zone de Saint-Prosper (alerte 3 jours avant, au
  début et à la fin) et chantiers routiers à 45 km, ceux qui limitent la charge en premier (onglet Chantier).
- **Températures** : max et min des sites pondérés par leur fiabilité mesurée (`confiance_temperatures`;
  le minimum d'Environnement Canada, celui de la nuit qui suit, est comparé au minimum du lendemain).
- **Érablière** : heures de dégel (8 h – 20 h) et écart entre modèles, heure par heure; date de première
  coulée recalculée chaque automne sur les 10 derniers printemps (`scripts/erable.py`,
  `data/erable-estimation.json`); `config/erable.json` → `manuelle` la remplace pour une seule saison.

## Motoneige hors-piste (onglet Motoneige)

`scripts/motoneige.py`, endroits dans `config/motoneige.json` (coordonnées OpenStreetMap, temps de
route OSRM depuis Saint-Prosper, vitesses d'été). Du 15 novembre au 30 avril, à chaque passage complet :
- neige au sol : HRDPS (GeoMet, SD) et HRRR (SNOD), moyenne; historique 14 jours dans
  `data/motoneige.json` (variation sur 72 h);
- 7 jours de NBM par tranche de 6 h (neige, précipitations, température, rafales), lus pour tous les
  endroits d'un seul téléchargement par champ (`grib.field_points`; NBM range une rangée sur deux à
  l'envers : corrigé);
- projection de la base (neige fraîche tassée, fonte, pluie), surface du jour (poudreuse, neige fraîche,
  bonne base, ventée, lourde, croûte), note de 0 à 10, et « vaut la route » = note − 1 point par heure
  de route au-delà de la première. Moins de 15 cm de base : 2/10 au plus.
Valeurs au point de grille de 2,5 km : pas sous le couvert forestier ni au sommet; à confirmer sur place.

## Fiabilité : qui voit juste ?

`scripts/history.py` compare la prévision de la veille des modèles archivés
publiquement (ECMWF IFS, AIFS, NOAA GFS) à la neige mesurée par Climat Québec pour
l'hiver 2025-2026 (workflow « Base historique », relancé en modifiant
`config/historique.json`). `scripts/verify.py` produit `data/verification/scores.json`
et ajoute, jour après jour, toutes les sources archivées par le robot. Résultat dans
l'onglet Sources.

## Plan de sortie (modèles horaires)

Le robot interroge aussi des modèles numériques gratuits, libres pour un usage
commercial : **HRDPS 2,5 km** et **RDPS 10 km** d'Environnement Canada (MSC GeoMet,
GetFeatureInfo au point), **GFS 0,25°** de la NOAA (THREDDS UCAR) et **MET Norway**
(déjà collecté). Chaque modèle donne des mm d'eau et une température heure par
heure; les cm de neige sont **estimés** (10:1 près de 0 °C, plus léger au froid,
mélange entre 0,5 et 2 °C) et affichés comme tels. Un modèle indisponible est
exclu, jamais compté comme zéro. Open-Meteo n'est pas utilisé : sa version
gratuite est réservée à un usage non commercial.

La médiane horaire des modèles donne l'heure où le seuil de 5 cm est atteint,
la fin de la tempête et un plan (`scripts/plan.py`, règles dans `config/plan.json`) :

- 4 h par machine jusqu'à 10 cm, +1,5 h par tranche de 10 cm de plus;
- semaine et fin de semaine : commercial propre pour 7 h 45 → départ = 7 h 45 − durée,
  jamais avant l'atteinte des 5 cm; résidentiel et locatif en acte de présence;
- nettoyage final à 9 h 00 si la neige a cessé, sinon à la fin de la tempête;
  2e tournée si 5 cm de plus tombent après le départ.

Le plan est une aide à la décision; il ne remplace pas une vérification au sol.

## Consensus : ce qui est calculé

Les températures sont moyennées par date avec une fourchette entre fournisseurs.
Les fenêtres exactes de maximum/minimum peuvent varier légèrement selon le site.
Ce consensus est une tendance; il ne prouve pas une meilleure précision.

Pour la neige, la moyenne, la médiane et la fourchette sont calculées seulement
si au moins deux sources donnent des cm **avec une période explicitement
compatible** (`snow_period: "00-24-local"`). Les données absentes restent nulles,
jamais zéro. Les sources publiques branchées ne fournissent actuellement pas
deux séries de cm alignées : l'interface indique donc **moyenne indisponible**.
Les quantités ECCC restent visibles dans le bulletin original par période.
Une intégration numérique supplémentaire avec des données autorisées et leurs
périodes explicites est nécessaire pour une moyenne de neige intersources.

Le niveau de confiance est un indicateur qualitatif d'accord et d'horizon, pas
une probabilité calibrée. Le robot ne garantit pas l'accumulation réelle au sol,
ne calcule pas la fonte ou le tassement et n'invente pas de quantité de verglas.

Les relevés de Climat Québec ont un délai de publication. La source indique que
la répartition pluie/neige de cette station automatique est indicative, calculée
selon la température moyenne horaire. Le cumul publié n'est ni l'épaisseur de
neige au sol ni une mesure de la cour. Aucun relevé de l'équipe n'est demandé.

## Alertes et partage

Les alertes arrivent comme notifications du site (Web Push), sans application à installer
(`scripts/alerts.py` et `scripts/webpush_channel.py`, appelés à chaque collecte) : sortie
prévue, déplacée d'une heure et plus ou annulée; alerte officielle d'Environnement Canada;
probabilité de 5 cm et plus de 50 % et plus pour aujourd'hui ou demain; risque de verglas ou
pluie sur la neige au sol. Chaque alerte n'est envoyée qu'une fois (`data/alerts-state.json`).

- iPhone (iOS 16.4+) : Safari → Partager → « Sur l'écran d'accueil », ouvrir le site depuis
  l'icône, onglet Sources → « Activer les notifications ». Android : directement dans Chrome.
- Le téléphone dépose son abonnement dans une boîte d'inscription (un canal ntfy.sh utilisé
  comme simple boîte aux lettres, invisible pour l'équipe); le robot le récupère à la
  collecte suivante et le garde dans `data/push-subscriptions.json`.
- Envoyer une notification exige la clé privée VAPID (secret `VAPID_PRIVATE_KEY`). La clé
  publique est dans `app.js`. Un téléphone désabonné est retiré automatiquement.

## Développement et validation

Python 3.12+, Node.js pour vérifier la syntaxe JavaScript :

```sh
pip install -r requirements.txt
python -m unittest discover -s tests
python scripts/collect.py
node --check app.js
```

Pour ouvrir localement : `python -m http.server 8000` depuis ce dossier, puis
`http://localhost:8000`. Le radar nécessite une connexion aux services externes.
Les polices et Leaflet sont chargés depuis leurs fournisseurs publics.

## Attribution

Données : © Environnement et Changement climatique Canada; © Gouvernement du
Québec; MET Norway, CC BY 4.0, https://www.met.no/en/free-meteorological-data;
prévisions publiques des fournisseurs cités avec lien original dans l'interface.
Carte : © Esri, HERE, Garmin, USGS et contributeurs. Leaflet : BSD-2-Clause.
