"""CLI du module de collecte, avec déduplication persistante SQLite."""
from __future__ import annotations
import argparse,json,logging
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from src.common.config import charger_config,dossier_episode
from src.common.db import DB_PATH,ajouter_article,article_existe,connexion
from src.common.logging_setup import configurer_logging
from .deduplicator import deduplicate_articles
from .fetchers import Article,fetch_source
from .selector import select_articles
LOGGER=logging.getLogger(__name__)
def _args():
 p=argparse.ArgumentParser(description="Collecte les actualités IA"); p.add_argument('--dry-run',action='store_true'); p.add_argument('--limit',type=int,default=15); p.add_argument('--config',type=Path,default=None); p.add_argument('--output',type=Path,default=None); return p.parse_args()
def _published_datetime(value):
 if not value:return None
 try: dt=datetime.fromisoformat(value.replace('Z','+00:00'))
 except ValueError:
  try: dt=parsedate_to_datetime(value)
  except (TypeError,ValueError): return None
 return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
def _within_max_age(article,max_age_hours):
 published=_published_datetime(article.published_at)
 return published is None or (datetime.now(timezone.utc)-published).total_seconds()<=max_age_hours*3600
def run(config,dry_run=False,limit=15,output_dir=None,db_path=None):
 collect=config.get('collect',{}); sources=collect.get('sources',[]); keywords=collect.get('keywords',[]); max_age=float(collect.get('max_age_hours',48)); minimum=float(collect.get('minimum_score',10)); all_articles=[]; failed_sources=[]
 if dry_run: all_articles=[Article('Démo : actualité IA','https://example.com/demo-ia','dry-run','Article de démonstration IA',datetime.now(timezone.utc).isoformat())]
 else:
  for source in sources:
   name=source.get('name','?')
   try: all_articles.extend(fetch_source(source,min(limit,int(collect.get('max_articles_per_source',limit)))))
   except Exception as exc: failed_sources.append({'name':name,'error':str(exc)}); LOGGER.error('Source %s échouée: %s',name,exc)
 fresh=[a for a in all_articles if _within_max_age(a,max_age)]; selected=select_articles(deduplicate_articles(fresh),keywords,limit,minimum)
 if not dry_run:
  with connexion(db_path or DB_PATH) as conn:
   before=len(selected); selected=[a for a in selected if not article_existe(conn,a.url)]
   for a in selected: ajouter_article(conn,a.url,a.title,a.source,a.summary,a.published_at or '')
   LOGGER.info('%d doublon(s) SQLite ignoré(s)',before-len(selected))
 target=output_dir or dossier_episode(datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')); target.mkdir(parents=True,exist_ok=True)
 payload={'articles':[a.to_dict() for a in selected],'failed_sources':failed_sources,'summary':{'collected':len(all_articles),'selected':len(selected),'failed_sources':len(failed_sources),'dry_run':dry_run}}
 (target/'collect.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8'); LOGGER.info('Collecte: %d article(s), %d source(s) en échec; sortie %s',len(selected),len(failed_sources),target/'collect.json'); return selected
def main():
 args=_args(); configurer_logging('collect'); run(charger_config(args.config),args.dry_run,max(1,args.limit),args.output)
if __name__=='__main__': main()
