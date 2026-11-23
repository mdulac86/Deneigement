# Relais météo sur le NAS Synology

Remplace la tâche planifiée du portable. Le conteneur lit MétéoMédia avec
la connexion du bureau (ce site refuse les serveurs de GitHub) et publie `data/relay.json`
à 23 h 45, 5 h 45, 11 h 45 et 17 h 45.

Accès à GitHub : une clé de déploiement propre au NAS (`data/ssh/id_ed25519`), limitée à ce dépôt.
Sa clé publique est ajoutée dans GitHub > dépôt > Settings > Deploy keys, avec « Allow write access ».
(Un jeton `GITHUB_TOKEN` dans `.env` fonctionne aussi.)

Démarrer ou mettre à jour (mot de passe administrateur du NAS) :

    sudo env PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin /usr/local/bin/docker-compose -f /volume1/docker/deneigement-relais/docker-compose.yml up -d --build

(Le `PATH` est nécessaire : sudo n'inclut pas `/usr/local/bin`, où se trouve `docker`, et la
construction échoue avec « No such file or directory: 'docker' ».)

Journal du relais : `data/deneigement-relais.log`.
