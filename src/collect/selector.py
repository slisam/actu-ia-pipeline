"""Classement des articles selon les mots-clés de config.yaml."""
from __future__ import annotations
from .fetchers import Article
def score_article(article,keywords):
 text=f"{article.title} {article.summary}".lower(); title=article.title.lower(); hits=sum(1 for word in keywords if word.lower() in text); title_hits=sum(1 for word in keywords if word.lower() in title); return min(100.0,round(hits*12.0+title_hits*18.0,2))
def select_articles(articles,keywords,limit=15,minimum_score=0.0):
 selected=[]
 for article in articles:
  article.score=score_article(article,keywords)
  if article.score>=minimum_score:selected.append(article)
 return sorted(selected,key=lambda a:(-a.score,a.published_at or ""))[:limit]
