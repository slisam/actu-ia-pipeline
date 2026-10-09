# Actu IA Pipeline — module 1 : collecte

## Installation

Python 3.11+ est recommandé. Créez un environnement virtuel puis installez les versions verrouillées :

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Aucune clé API n'est nécessaire pour RSS, Hacker News ou arXiv. Les secrets optionnels vont dans `.env` (voir `.env.example`).

## Exécution

```bash
python -m src.collect.cli
python -m src.collect.cli --dry-run --output /tmp/collect-test
```

La collecte écrit `collect.json` avec `articles`, `failed_sources` et `summary`. Les erreurs sont journalisées par source et n'empêchent pas les autres sources de fonctionner.

## Configuration

`config.yaml` définit les sources, `max_age_hours` (48 par défaut), `minimum_score` (10), les mots-clés et les limites. Les articles datés de plus de 48 heures sont ignorés. Un article sans date est conservé prudemment, car son ancienneté ne peut pas être démontrée.

Chaque article retenu est dédupliqué par URL dans `data/pipeline.db`, y compris entre deux exécutions. `--dry-run` n'appelle pas le réseau et n'écrit pas dans SQLite.

## Tests

```bash
pytest
```
