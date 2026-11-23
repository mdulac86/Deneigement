# Relais météo sur le NAS Synology

Remplace la tâche planifiée du portable. Le conteneur lit MétéoMédia et Weather Underground avec
la connexion du bureau (ces sites refusent les serveurs de GitHub) et publie `data/relay.json`
à 23 h 45, 5 h 45, 11 h 45 et 17 h 45.

1. **Jeton GitHub** : github.com > Settings > Developer settings > Fine-grained tokens > Generate.
   Dépôt : seulement `deneigement`. Permission : *Contents : Read and write*. Expiration : 1 an.
2. **Sur le NAS** : copier ce dossier `relais` dans `docker/deneigement-relais` (File Station),
   renommer `.env.exemple` en `.env` et coller le jeton après `GITHUB_TOKEN=`.
3. **Container Manager** > Projet > Créer : nom `deneigement-relais`, chemin = ce dossier,
   source = docker-compose.yml existant > Suivant > Terminé (il construit et démarre).
4. **Vérifier** : Conteneur > deneigement-relais > Journal : « mm : ok », « wu : ok », « publié ».
5. Une fois que ça fonctionne, désactiver la tâche Windows « Deneigement - relais meteo ».
