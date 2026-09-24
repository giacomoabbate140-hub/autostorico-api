import ast
import pathlib
import threading
import urllib.parse
from datetime import datetime, timezone
from typing import Any

source = pathlib.Path(__file__).with_name('server_core.py').read_text()
names = {'_defect_source_key', '_defect_review_candidate', '_defect_review_rows', '_safe_defect_review_item', '_defect_review_status', 'admin_defect_review'}
module = ast.parse(source)
ns = dict(Any=Any, urllib=urllib, datetime=datetime, timezone=timezone,
          SUPABASE_URL='configured', SUPABASE_SECRET_KEY='configured',
          DEFECT_REVIEW_CACHE_LOCK=threading.Lock(),
          safe_public_source_url=lambda v: str(v or '') if str(v or '').startswith('https://') else '',
          defect_source_relevant_to_vehicle=lambda candidate, make='', model='': True,
          catalog_year_value=lambda v: int(v or 0))
exec(compile(ast.Module(body=[n for n in module.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[]), '<review functions>', 'exec'), ns)
url = 'https://example.com/topic?id=1'
candidate = dict(sourceUrl=url, make='BMW', model='Serie 1', year=2005, title='Test', sourceName='Forum', sourceType='community_candidate')
queue = [candidate, dict(candidate, sourceUrl=url+'&utm_source=test#post')]
db = {}
def request(method, path, payload=None, **kwargs):
    if method == 'GET': return list(db.values())
    db[payload['source_url']] = payload
    return [payload]
ns['_supabase_json_request'] = request
ns['_load_defect_research_candidates'] = lambda: queue
review = ns['admin_defect_review']
assert review({})['pendingCount'] == 1
assert review({'action':'publish', 'sourceUrl':url})['status'] == 'published'
review({'action':'publish', 'sourceUrl':url+'&utm_source=again#post'})
assert len(db) == 1
assert review({'includeResolved':True})['publishedCount'] == 1
queue.clear()
assert review({'includeResolved':True})['publishedCount'] == 1
# A rejected source must remain publishable after it leaves the research queue.
review({'action':'reject', 'sourceUrl':url})
assert db[url]['status'] == 'rejected'
review({'action':'publish', 'sourceUrl':url})
assert db[url]['status'] == 'published'
assert len(db) == 1
try: review({'action':'publish', 'sourceUrl':'https://example.com/unknown'})
except ValueError: pass
else: raise AssertionError('Unknown source accepted')
queue.append(candidate)
ns['_supabase_json_request'] = lambda method, *args, **kwargs: []
try: review({'action':'publish', 'sourceUrl':url})
except RuntimeError: pass
else: raise AssertionError('Unconfirmed save accepted')
def failed(*args, **kwargs): raise RuntimeError('database unavailable')
ns['_supabase_json_request'] = failed
try: review({})
except RuntimeError: pass
else: raise AssertionError('Database read failure hidden')
assert ns['_defect_source_key'](url) != ns['_defect_source_key'](url.replace('id=1','id=2'))
print('PASS: dedupe, repeated publish, retained published list, unconfirmed save, DB failure, distinct URLs, rejected source recovery, unknown source rejection')
