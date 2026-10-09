"""Déduplication d'articles par URL et similarité de titre."""
from rapidfuzz.fuzz import ratio
def deduplicate_articles(articles,threshold=88.0):
 result=[]; urls=set()
 for article in articles:
  normalized=article.url.rstrip('/').lower(); title=' '.join(article.title.lower().split())
  if normalized in urls or any(ratio(title,' '.join(old.title.lower().split()))>=threshold for old in result): continue
  urls.add(normalized); result.append(article)
 return result
