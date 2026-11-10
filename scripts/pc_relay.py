"""Relais du poste du bureau : lit MétéoMédia et Weather Underground avec la connexion
du bureau, puis publie data/relay.json sur GitHub. Le robot GitHub l'utilise pendant 7 h.

Lancé par une tâche planifiée Windows (23 h 45, 5 h 45, 11 h 45, 17 h 45).
Si le PC est éteint, rien n'est publié : l'appli garde les dernières données, marquées anciennes.
"""
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT.parent / 'deneigement-relais.log'


def log(msg):
    line = f'{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}'
    print(line)
    with LOG.open('a', encoding='utf-8') as f:
        f.write(line + '\n')


def git(*args, check=True):
    r = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if check and r.returncode:
        raise RuntimeError(f'git {" ".join(args)} : {r.stderr.strip()[:300]}')
    return r


def main():
    # Copie dédiée au relais : on repart toujours de la dernière version publiée.
    git('fetch', '-q', 'origin')
    git('checkout', '-q', '-B', 'main', 'origin/main')
    try:
        import truststore  # certificats Windows
        truststore.inject_into_ssl()
    except ImportError:
        pass
    sys.path.insert(0, str(ROOT / 'scripts'))
    import collect
    out = {'fetched_at': collect.stamp(), 'host': 'poste du bureau', 'sources': {}}
    for key, fn in (('mm', collect.mm), ('wu', collect.wu)):
        try:
            out['sources'][key] = {'status': 'ok', 'fetched_at': collect.stamp(), 'result': fn()}
            log(f'{key} : ok')
        except Exception as e:
            out['sources'][key] = {'status': 'error', 'fetched_at': collect.stamp(), 'error': str(e)[:200]}
            log(f'{key} : erreur {e}')
    collect.write(collect.DATA / 'relay.json', out)
    git('add', 'data/relay.json')
    if not git('diff', '--cached', '--quiet', check=False).returncode:
        log('rien de nouveau')
        return
    git('-c', 'user.name=Relais bureau', '-c', 'user.email=actions@users.noreply.github.com',
        'commit', '-q', '-m', 'Relais bureau : MétéoMédia et Weather Underground')
    for _ in range(3):
        if not git('push', '-q', 'origin', 'main', check=False).returncode:
            log('publié')
            return
        git('pull', '-q', '--rebase', 'origin', 'main')
    raise RuntimeError('push refusé trois fois')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log('ÉCHEC ' + traceback.format_exc().strip().splitlines()[-1])
        sys.exit(1)
