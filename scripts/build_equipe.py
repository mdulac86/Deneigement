"""Version équipe de l'app : equipe.html, copie d'index.html en mode « equipe ».

Le mode équipe (app.js, constante EQ, et la classe .owner-only de style.css) garde la météo et les
statistiques, et retire : heures de départ (sortie et épandage : le jour seulement), plan détaillé,
routes et caméras, pavage, excavation, dégel et travaux, notifications, érablière et motoneige.

Le workflow meteo.yml lance : python scripts/build_equipe.py dist
(écrit dist/equipe.html et dist/equipe.webmanifest; installable à part sur les téléphones).
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def build(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    reps = [('<html lang="fr-CA">', '<html lang="fr-CA" data-mode="equipe">'),
            ('href="manifest.webmanifest"', 'href="equipe.webmanifest"')]
    for a, b in reps:
        if html.count(a) != 1:
            raise SystemExit(f'index.html : « {a} » introuvable ou en double')
        html = html.replace(a, b)
    title_start = html.index('<title>')
    title_end = html.index('</title>', title_start)
    html = html[:title_start] + '<title>Météo · Équipe Dulac' + html[title_end:]
    (out / 'equipe.html').write_text(html, encoding='utf-8')
    man = json.loads((ROOT / 'manifest.webmanifest').read_text(encoding='utf-8'))
    man.update({'id': 'equipe', 'name': 'Météo · Équipe Dulac', 'short_name': 'Météo équipe',
                'start_url': './equipe.html', 'scope': './'})
    (out / 'equipe.webmanifest').write_text(json.dumps(man, ensure_ascii=False), encoding='utf-8')
    print('version équipe :', out / 'equipe.html')


if __name__ == '__main__':
    build(sys.argv[1] if len(sys.argv) > 1 else ROOT)
