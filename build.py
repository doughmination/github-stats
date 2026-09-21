"""Fetch GitHub stats with the gh CLI and build site/index.html.

    python build.py            # fetch fresh data, then build
    python build.py --no-fetch # rebuild from the JSON already in data/
"""
import base64, datetime, json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(ROOT, 'site', 'index.html')
cfg = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))
exclude = {s.lower() for s in cfg.get('exclude_repos', [])}

def gql(query_file, login, out_file):
    res = subprocess.run(['gh', 'api', 'graphql', '-F', f'login={login}',
                          '-F', f'query=@{os.path.join(ROOT, "queries", query_file)}'],
                         capture_output=True, check=True)
    body = json.loads(res.stdout)
    if body.get('errors'):
        sys.exit(f'GitHub API error for {login}: {body["errors"]}')
    with open(os.path.join(DATA, out_file), 'wb') as f:
        f.write(res.stdout)

def load(name):
    return json.load(open(os.path.join(DATA, name), encoding='utf-8'))['data']

def repos(nodes, owner):
    out = []
    for r in nodes:
        if f'{owner}/{r["name"]}'.lower() in exclude:
            continue
        priv = r['isPrivate']
        # Private repos only contribute counts: no name, description or push time.
        out.append(dict(owner=owner,
            name=None if priv else r['name'], url=None if priv else r['url'],
            desc=None if priv else r['description'], pushed=None if priv else r['pushedAt'],
            private=priv, fork=r['isFork'], archived=r['isArchived'],
            stars=r['stargazerCount'], forks=r['forkCount'],
            lang=(r['primaryLanguage'] or {}).get('name'),
            langs={e['node']['name']: e['size'] for e in r['languages']['edges']}))
    return out

def inline(url):
    b = subprocess.run(['curl', '-sfL', url + ('&' if '?' in url else '?') + 's=160'],
                       capture_output=True, check=True).stdout
    ct = 'image/jpeg' if b[:2] == bytes([255, 216]) else 'image/gif' if b[:3] == b'GIF' else 'image/png'
    return f'data:{ct};base64,' + base64.b64encode(b).decode()

if '--no-fetch' not in sys.argv:
    os.makedirs(DATA, exist_ok=True)
    gql('user.graphql', cfg['user'], 'user.json')
    for o in cfg['orgs']:
        gql('org.graphql', o, f'org_{o}.json')

u = load('user.json')['user']
c = u['contributionsCollection']
kept = [r for r in u['repositories']['nodes'] if f'{u["login"]}/{r["name"]}'.lower() not in exclude]
data = dict(
    user=dict(login=u['login'], name=u['name'], avatar=u['avatarUrl'], bio=u['bio'], created=u['createdAt'], url=u['url'],
        followers=u['followers']['totalCount'], following=u['following']['totalCount'],
        prs=u['pullRequests']['totalCount'], issues=u['issues']['totalCount'],
        contrib=dict(commits=c['totalCommitContributions'], prs=c['totalPullRequestContributions'],
            issues=c['totalIssueContributions'], reviews=c['totalPullRequestReviewContributions'],
            repos=c['totalRepositoryContributions'], private=c['restrictedContributionsCount'],
            total=c['contributionCalendar']['totalContributions']),
        days=[[d['date'], d['contributionCount']] for w in c['contributionCalendar']['weeks'] for d in w['contributionDays']]),
    accounts=[dict(kind='user', login=u['login'], name=u['name'], url=u['url'], avatar=u['avatarUrl'], members=None,
        repoTotal=u['repositories']['totalCount'] - (len(u['repositories']['nodes']) - len(kept)),
        repos=repos(u['repositories']['nodes'], u['login']))])
for o in cfg['orgs']:
    d = load(f'org_{o}.json')['organization']
    kept = [r for r in d['repositories']['nodes'] if f'{d["login"]}/{r["name"]}'.lower() not in exclude]
    data['accounts'].append(dict(kind='org', login=d['login'], name=d['name'] or d['login'], url=d['url'],
        avatar=d['avatarUrl'], desc=d['description'], members=d['membersWithRole']['totalCount'],
        repoTotal=d['repositories']['totalCount'] - (len(d['repositories']['nodes']) - len(kept)),
        repos=repos(d['repositories']['nodes'], d['login'])))

# Artifact previews block external images; a real host doesn't, so only inline on request.
if '--inline-avatars' in sys.argv:
    data['user']['avatar'] = inline(data['user']['avatar'])
    for a in data['accounts']:
        a['avatar'] = inline(a['avatar'])

# Keep the previous "updated" time when nothing else changed, so an idle hour
# produces an identical file and the workflow has nothing to commit.
data['updated'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
if os.path.exists(OUT):
    m = re.search(r'const D=(\{.*?\});\n', open(OUT, encoding='utf-8').read())
    if m:
        prev = json.loads(m.group(1))
        if {**prev, 'updated': None} == {**data, 'updated': None}:
            data['updated'] = prev['updated']

tpl = open(os.path.join(ROOT, 'template.html'), encoding='utf-8').read()
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
    f.write(tpl.replace('/*DATA*/null', json.dumps(data, separators=(',', ':'), ensure_ascii=False)))
print(f'built {OUT} (updated {data["updated"]})')
