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
- Weather Underground : cartes publiques demandées aux coordonnées exactes,
  dates et coordonnées des liens horaires vérifiées. Conditions et températures.
  Les valeurs neige sans unité explicite ne sont pas interprétées.
- meteoblue : cartes quotidiennes datées, conditions et températures.
- MET Norway : API Locationforecast, licence CC BY 4.0; températures, conditions,
  vent et précipitations liquides par échéance. Pas de conversion arbitraire en neige.
- MétéoMédia : tableau de données structurées (schema.org / CSVW) publié dans la
  page 7 jours : conditions, températures, pluie en mm et **neige en cm** par période
  (nuit, matin, après-midi, soir). Les 4 périodes donnent un total 00-24 h comparable;
  les cm entrent aussi dans le plan de sortie (répartis sur chaque heure de la période).
- AccuWeather refuse toute lecture automatisée (serveurs de GitHub et PC du bureau) : retiré
  des sources. Weather Underground (403) et MétéoMédia (page de vérification) refusent les
  serveurs de GitHub : ils sont lus par le relais du bureau.
- L'interface n'affiche que les sources qui fonctionnent (à jour, ou lues dans les 24 h).
- **Relais du bureau** (`scripts/pc_relay.py`) : une tâche planifiée Windows sur le
  PC du bureau lit MétéoMédia et Weather Underground à 23 h 45, 5 h 45, 11 h 45 et
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
