"""Relais du bureau dans un conteneur (NAS Synology) : remplace la tâche planifiée Windows.

Au démarrage : clone le dépôt dans /data/depot (volume du NAS), puis lance scripts/pc_relay.py
à 23 h 45, 5 h 45, 11 h 45 et 17 h 45 (heure de Saint-Prosper), plus une fois au démarrage.

Variables :
  GITHUB_TOKEN  jeton GitHub limité au dépôt (droit « Contents : Read and write »). Obligatoire.
  DEPOT         dépôt GitHub (défaut : mdulac86/deneigement)
  HEURES        heures de lancement (défaut : 23:45,05:45,11:45,17:45)
"""
import datetime as dt
import os
from pathlib import Path
import subprocess
import sys
import time

DATA = Path('/data')
REPO = DATA / 'depot'
DEPOT = os.environ.get('DEPOT', 'mdulac86/deneigement')
HEURES = [h.strip() for h in os.environ.get('HEURES', '23:45,05:45,11:45,17:45').split(',') if h.strip()]


def log(msg):
    print(f'{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}', flush=True)


def prepare():
    token = os.environ.get('GITHUB_TOKEN', '').strip()
    if not token:
        log('GITHUB_TOKEN manquant : ajoute-le dans les variables d’environnement du conteneur.')
        sys.exit(1)
    url = f'https://x-access-token:{token}@github.com/{DEPOT}.git'
    if not (REPO / '.git').exists():
        log(f'Clonage de {DEPOT}…')
        r = subprocess.run(['git', 'clone', '-q', '--depth', '50', url, str(REPO)], capture_output=True, text=True)
        if r.returncode:
            log('Clonage refusé : ' + r.stderr.replace(token, '***').strip()[:300])
            sys.exit(1)
    else:  # le jeton peut avoir changé
        subprocess.run(['git', '-C', str(REPO), 'remote', 'set-url', 'origin', url], check=True)


def run_once():
    log('Relais : lecture de MétéoMédia et Weather Underground…')
    r = subprocess.run([sys.executable, str(REPO / 'scripts' / 'pc_relay.py')], capture_output=True, text=True)
    for line in (r.stdout + r.stderr).strip().splitlines()[-6:]:
        log('  ' + line.replace(os.environ.get('GITHUB_TOKEN', '') or '\0', '***'))


def next_run(now):
    cands = []
    for h in HEURES:
        hh, mm = map(int, h.split(':'))
        t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        cands.append(t if t > now else t + dt.timedelta(days=1))
    return min(cands)


def main():
    prepare()
    run_once()
    while True:
        when = next_run(dt.datetime.now())
        log(f'Prochain relais : {when:%Y-%m-%d %H:%M}')
        while dt.datetime.now() < when:
            time.sleep(min(300, max(1, (when - dt.datetime.now()).total_seconds())))
        try:
            run_once()
        except Exception as e:  # on ne s'arrête jamais pour une erreur passagère
            log(f'Erreur : {e}')


if __name__ == '__main__':
    main()
