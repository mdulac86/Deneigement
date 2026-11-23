# Relais météo sur le NAS Synology

Remplace la tâche planifiée du portable. Le conteneur lit MétéoMédia et Weather Underground avec
la connexion du bureau (ces sites refusent les serveurs de GitHub) et publie `data/relay.json`
à 23 h 45, 5 h 45, 11 h 45 et 17 h 45.

Accès à GitHub : une clé de déploiement propre au NAS (`data/ssh/id_ed25519`), limitée à ce dépôt.
Sa clé publique est ajoutée dans GitHub > dépôt > Settings > Deploy keys, avec « Allow write access ».
(Un jeton `GITHUB_TOKEN` dans `.env` fonctionne aussi.)

Démarrer ou mettre à jour (mot de passe administrateur du NAS) :

    sudo /usr/local/bin/docker-compose -f /volume1/docker/deneigement-relais/docker-compose.yml up -d --build

Journal du relais : `data/deneigement-relais.log`.
