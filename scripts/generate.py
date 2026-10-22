#!/usr/bin/env python3
"""
Pip-Boy styled GitHub profile generator (standard library only).

Everything on the page is read from the GitHub API: name, bio, location,
company, links, repos, stats, languages.  Nothing about you is hardcoded here.

    python3 scripts/generate.py             # live data (GITHUB_TOKEN optional)
    python3 scripts/generate.py --offline   # use data/snapshot.json only

The page is one continuous panel made of stacked image slices that share the
same background, so repo rows stay individually clickable.  A successful live
run refreshes data/snapshot.json, which is the fallback if the API is down.
"""
import base64
import datetime
import json
import math
import re
import os
import sys
import textwrap
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'assets')
SNAPSHOT = os.path.join(ROOT, 'data', 'snapshot.json')

USER = os.environ.get('PROFILE_USER', 'SoftAndoWetto')   # the Action sets this to the repo owner
MAX_REPOS = 4          # top repos shown: most stars first, ties broken by most recent push
MAX_LANGS = 5
# Detail rows under the bio, in order. Reorder / remove / add names from META_CATALOGUE below.
# Rows with no data on your account are skipped automatically.
META_FIELDS = ['SINCE', 'LANG', 'ACTIVE', 'ACTIVITY', 'FOCUS']
MAX_LINKS = 4
# Shown under your name when the bio on your GitHub profile is empty (set a bio on GitHub and it wins).
# Clear this to '' to get an auto-generated summary line instead.
BIO_FALLBACK = ('Penetration tester. Focused on Active Directory, internal infrastructure, '
                'and red team operations. Builds tooling for OSINT, pivoting, and report automation '
                'in Python and Java.')
HIDE_REPOS = {USER}    # never list the profile repo itself

G, GD, GDD, BG = '#1bff80', '#12a857', '#0a5c30', '#020b06'
FONT = "'Courier New','DejaVu Sans Mono','Liberation Mono',Courier,monospace"
CW = 0.6
W = 900


# ======================================================================= DATA
def api(path):
    req = urllib.request.Request('https://api.github.com' + path, headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': 'pipboy-profile-generator'})
    tok = os.environ.get('GITHUB_TOKEN')
    if tok:
        req.add_header('Authorization', f'Bearer {tok}')
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def select_repos(repos):
    """Top repos: stars desc, then most recently pushed (full timestamp) desc."""
    ok = [r for r in repos if not r['fork'] and not r['archived'] and r['name'] not in HIDE_REPOS]
    ok.sort(key=lambda r: (r['stars'], r.get('pushed_at') or r['pushed']), reverse=True)
    return ok


def readme_blurb(name):
    """First real sentence of a repo's README, used when the repo has no description."""
    try:
        raw = base64.b64decode(api(f'/repos/{USER}/{name}/readme')['content']).decode('utf-8', 'replace')
    except Exception:
        return ''
    for line in raw.splitlines():
        line = line.strip()
        if not line or line[0] in '#<>|=-!`' or line.startswith(('[![', '![', '---', '***')):
            continue
        line = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', line)        # [text](url) -> text
        line = re.sub(r'[*_`]', '', line).strip()
        if len(line) >= 12:
            return clip_text(line, 140)
    return ''


def fetch_live():
    u = api(f'/users/{USER}')
    try:
        socials = [{'provider': s.get('provider', ''), 'url': s['url']} for s in api(f'/users/{USER}/social_accounts')]
    except Exception:
        socials = []
    try:
        orgs = [o['login'] for o in api(f'/users/{USER}/orgs')]
    except Exception:
        orgs = []
    try:
        ev = api(f'/users/{USER}/events/public?per_page=1')
        last_event = {'type': ev[0]['type'], 'repo': ev[0]['repo']['name'].split('/')[-1], 'at': ev[0]['created_at']} if ev else None
    except Exception:
        last_event = None
    repos, page = [], 1
    while True:
        batch = api(f'/users/{USER}/repos?per_page=100&type=owner&page={page}')
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    # Per-repo language bytes. Each repo needs one API call, so results are cached in the snapshot
    # (keyed by the repo's last push) to stay well inside the 60 requests/hour anonymous limit.
    try:
        with open(SNAPSHOT) as f:
            cache = json.load(f).get('repo_langs', {})
    except Exception:
        cache = {}
    repo_langs, missing = {}, []
    for r in repos:
        if r['fork']:
            continue
        hit = cache.get(r['name'])
        if hit and hit.get('pushed_at') == r['pushed_at']:
            repo_langs[r['name']] = hit
            continue
        try:
            repo_langs[r['name']] = {'pushed_at': r['pushed_at'], 'langs': api(f'/repos/{USER}/{r["name"]}/languages')}
        except Exception:
            if hit:
                repo_langs[r['name']] = hit          # stale beats missing
            else:
                missing.append(r['name'])
    langs = {}
    if missing:
        msg = ('language lookup failed for %s (probably the 60 requests/hour limit: set GITHUB_TOKEN)' % ', '.join(missing))
        if '--strict' in sys.argv:
            raise RuntimeError(msg)
        print('WARNING: ' + msg + '; falling back to each repo\'s primary language', file=sys.stderr)
        for r in repos:
            if not r['fork'] and r['language']:
                langs[r['language']] = langs.get(r['language'], 0) + 1
    else:
        for entry in repo_langs.values():
            for lang, n in entry['langs'].items():
                langs[lang] = langs.get(lang, 0) + n
    data = {
        'user': {'login': u['login'], 'name': u.get('name') or u['login'], 'bio': u.get('bio') or '',
                 'location': u.get('location') or '', 'company': u.get('company') or '',
                 'created_at': (u.get('created_at') or '')[:10], 'email': u.get('email') or '',
                 'blog': u.get('blog') or '', 'socials': socials, 'orgs': orgs, 'last_event': last_event,
                 'public_repos': u['public_repos'], 'followers': u['followers'], 'following': u['following']},
        'totals': {'stars': sum(r['stargazers_count'] for r in repos), 'forks': sum(r['forks_count'] for r in repos)},
        'repos': [{'name': r['name'], 'description': r['description'] or '', 'language': r['language'] or '',
                   'stars': r['stargazers_count'], 'forks': r['forks_count'], 'pushed': (r['pushed_at'] or '')[:10],
                   'pushed_at': r['pushed_at'] or '', 'created_at': (r.get('created_at') or '')[:10], 'topics': r.get('topics') or [], 'open_issues': r.get('open_issues_count', 0), 'homepage': r.get('homepage') or '',
                   'fork': r['fork'], 'archived': r['archived']} for r in repos],
        'langs': langs,
        'repo_langs': repo_langs,
    }
    for r in select_repos(data['repos'])[:MAX_REPOS]:
        if not r['description']:
            r['readme_blurb'] = readme_blurb(r['name'])
    return data


SOURCE = ['live']      # becomes 'snapshot' if the API could not be reached


def load_data():
    if '--offline' not in sys.argv:
        try:
            d = fetch_live()
            with open(SNAPSHOT, 'w') as f:
                json.dump(d, f, indent=1)
            print('live data fetched for', USER)
            return d
        except Exception as e:
            if '--strict' in sys.argv:       # the Action: fail loudly instead of publishing stale data
                raise SystemExit('ERROR: live fetch failed: %r' % (e,))
            print('WARNING: live fetch failed (%s); using data/snapshot.json' % e, file=sys.stderr)
    SOURCE[0] = 'snapshot'
    with open(SNAPSHOT) as f:
        return json.load(f)


# ======================================================================= SVG HELPERS
def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def clip_text(s, n):
    s = ' '.join(str(s).split())
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


def text(x, y, s, size, fill=G, bold=False, anchor=None, spacing=None, glow='S'):
    a = f' text-anchor="{anchor}"' if anchor else ''
    ls = f' letter-spacing="{spacing}"' if spacing else ''
    fw = ' font-weight="bold"' if bold else ''
    fl = f' filter="url(#glow{glow})"' if glow else ''
    return (f'<text x="{x}" y="{y}" xml:space="preserve" font-family="{FONT}" font-size="{size}"{fw}{a}{ls} '
            f'fill="{fill}"{fl}>{esc(s)}</text>')


def up4(n):
    return int(math.ceil(n / 4.0) * 4)     # slice heights are multiples of the 4px scanline pitch


def shape(w, h, T, B, L, R, r=22):
    """Fill path + stroke path for one slice of the big rounded panel.
    T/B/L/R say which outer edges of the panel this slice touches."""
    tl = r if (T and L) else 0
    tr = r if (T and R) else 0
    bl = r if (B and L) else 0
    br = r if (B and R) else 0
    fill = (f'M{tl},0 H{w - tr} A{tr},{tr} 0 0 1 {w},{tr} V{h - br} A{br},{br} 0 0 1 {w - br},{h} '
            f'H{bl} A{bl},{bl} 0 0 1 0,{h - bl} V{tl} A{tl},{tl} 0 0 1 {tl},0 Z')
    s = []
    if T: s.append(f'M{tl},1 H{w - tr}')
    if tr: s.append(f'M{w - tr},1 A{tr - 1},{tr - 1} 0 0 1 {w - 1},{tr}')
    if R: s.append(f'M{w - 1},{tr} V{h - br}')
    if br: s.append(f'M{w - 1},{h - br} A{br - 1},{br - 1} 0 0 1 {w - br},{h - 1}')
    if B: s.append(f'M{w - br},{h - 1} H{bl}')
    if bl: s.append(f'M{bl},{h - 1} A{bl - 1},{bl - 1} 0 0 1 1,{h - bl}')
    if L: s.append(f'M1,{h - bl} V{tl}')
    if tl: s.append(f'M1,{tl} A{tl - 1},{tl - 1} 0 0 1 {tl},1')
    return fill, ' '.join(s)


def slice_svg(w, h, body, title, T=False, B=False, L=True, R=True, divider=None, vsep=False):
    """One horizontal slice of the single panel. divider: 'full' | 'inset' | None (line along the top)."""
    fill, stroke = shape(w, h, T, B, L, R)
    parts = [f'<defs><clipPath id="c"><path d="{fill}"/></clipPath>'
             f'<filter id="glow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
             f'<filter id="glowS" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="1.1" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
             f'<pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="2" fill="#000" opacity=".30"/></pattern></defs>',
             f'<path d="{fill}" fill="{BG}"/>']
    if divider == 'full':
        parts.append(f'<line x1="1" x2="{w - 1}" y1="1" y2="1" stroke="{GDD}" stroke-width="2"/>')
    elif divider == 'inset':
        parts.append(f'<line x1="40" x2="{w - 40}" y1="1" y2="1" stroke="{GDD}" stroke-width="1.5" opacity=".6"/>')
    if vsep:
        parts.append(f'<line x1="1" x2="1" y1="0" y2="{h}" stroke="{GDD}" stroke-width="2"/>')
    parts.append(body)
    parts.append(f'<g clip-path="url(#c)"><rect width="{w}" height="{h}" fill="url(#scan)"/></g>')
    if stroke:
        parts.append(f'<path d="{stroke}" fill="none" stroke="{GDD}" stroke-width="2"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="{esc(title)}"><title>{esc(title)}</title>{"".join(parts)}</svg>')


# ======================================================================= SLICES
def ago(iso):
    try:
        t = datetime.datetime.fromisoformat(iso.replace('Z', '+00:00'))
    except Exception:
        return ''
    sec = (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds()
    for span, unit in ((86400 * 365, 'y'), (86400 * 30, 'mo'), (86400, 'd'), (3600, 'h'), (60, 'm')):
        if sec >= span:
            return f'{int(sec // span)}{unit} ago'
    return 'just now'


def _since(d):
    c = d['user'].get('created_at')
    if not c:
        return None
    yrs = (datetime.date.today() - datetime.date.fromisoformat(c)).days / 365.25
    return ('MEMBER SINCE', f'{c} \u00b7 {yrs:.1f} years')


def _lang(d):
    langs = sorted(d['langs'].items(), key=lambda kv: kv[1], reverse=True)
    if not langs:
        return None
    tot = sum(n for _, n in langs) or 1
    return ('TOP LANGUAGE', f"{langs[0][0]} \u00b7 {round(100 * langs[0][1] / tot)}% of {len(langs)} language{'s' if len(langs) != 1 else ''}")


def _active(d):
    cutoff = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    own = [r for r in d['repos'] if not r['fork'] and r['name'] not in HIDE_REPOS]
    if not own:
        return None
    n = sum(1 for r in own if r['pushed'] >= cutoff)
    return ('ACTIVE REPOS', f'{n} of {len(own)} pushed in the last 30 days')


def _activity(d):
    e = d['user'].get('last_event')
    if not e:
        return None
    verb = {'PushEvent': 'Pushed to', 'CreateEvent': 'Created', 'WatchEvent': 'Starred', 'ForkEvent': 'Forked',
            'PullRequestEvent': 'Pull request on', 'IssuesEvent': 'Issue on', 'IssueCommentEvent': 'Commented on',
            'DeleteEvent': 'Deleted in', 'ReleaseEvent': 'Released'}.get(e['type'], e['type'].replace('Event', ''))
    return ('LAST ACTIVITY', f"{verb} {e['repo']} \u00b7 {ago(e['at'])}")


def _focus(d):
    counts = {}
    for r in d['repos']:
        if not r['fork']:
            for t in r.get('topics', []):
                counts[t] = counts.get(t, 0) + 1
    if not counts:
        return None
    top = sorted(counts, key=lambda t: (-counts[t], t))[:4]
    return ('FOCUS', ' \u00b7 '.join(top))


def _push(d):
    repos = [r for r in d['repos'] if r['pushed']]
    if not repos:
        return None
    last = max(repos, key=lambda r: r.get('pushed_at') or r['pushed'])
    return ('LAST PUSH', f"{last['name']} \u00b7 {last['pushed']}")


def _starred(d):
    best = max(d['repos'], key=lambda r: r['stars'], default=None)
    return ('MOST STARRED', f"{best['name']} \u00b7 {best['stars']} \u2605") if best and best['stars'] > 0 else None


def _newest(d):
    repos = [r for r in d['repos'] if r.get('created_at') and not r['fork']]
    if not repos:
        return None
    n = max(repos, key=lambda r: r['created_at'])
    return ('NEWEST REPO', f"{n['name']} \u00b7 {n['created_at']}")


def _orgs(d):
    o = d['user'].get('orgs')
    return ('ORGANISATIONS', ' \u00b7 '.join(o[:3])) if o else None


def _issues(d):
    n = sum(r.get('open_issues', 0) for r in d['repos'] if not r['fork'])
    return ('OPEN ISSUES', f'{n} across your repos') if n else None


META_CATALOGUE = {'SINCE': _since, 'LANG': _lang, 'ACTIVE': _active, 'ACTIVITY': _activity, 'FOCUS': _focus,
                  'PUSH': _push, 'STARRED': _starred, 'NEWEST': _newest, 'ORGS': _orgs, 'ISSUES': _issues}


def meta_rows(d):
    rows = []
    for key in META_FIELDS:
        row = META_CATALOGUE[key](d)
        if row:
            rows.append(row)
    return rows


def bio_text(d):
    """Your GitHub bio; if it is empty, a one-line summary built from the account itself."""
    u = d['user']
    if (u.get('bio') or '').strip():
        return u['bio'].strip()
    if BIO_FALLBACK.strip():
        return BIO_FALLBACK.strip()
    langs = sorted(d['langs'].items(), key=lambda kv: kv[1], reverse=True)
    parts = [f"{u['public_repos']} public repositories"]
    if langs:
        parts.append(f"mostly {langs[0][0]}")
    return ', '.join(parts) + '.'


def website(d):
    """Profile website; if unset, your <login>.github.io Pages repo (or its homepage field)."""
    u = d['user']
    if u.get('blog'):
        return u['blog'] if u['blog'].startswith('http') else 'https://' + u['blog']
    pages = f"{u['login'].lower()}.github.io"
    for r in d['repos']:
        if r['name'].lower() == pages:
            return r.get('homepage') or 'https://' + pages
    return ''


def header(d):
    u = d['user']
    name = (u.get('name') or u['login']).upper()
    size = min(54, int(800 / (len(name) * CW)))
    bio = textwrap.wrap(bio_text(d), 74)[:4]
    meta = meta_rows(d)
    y = 32 + size                                    # title baseline
    b = [f'<text x="40" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="bold" fill="{G}" filter="url(#glow)">{esc(name)}'
         f'<animate attributeName="opacity" values="1;1;.86;1;.94;1;1;.9;1" dur="4.7s" repeatCount="indefinite"/></text>']
    y += 30
    b.append(text(43, y, '@' + u['login'], 16, GD, spacing=3, glow=None))
    y += 24
    if bio:
        b.append(f'<line x1="1" x2="{W - 1}" y1="{y}" y2="{y}" stroke="{GDD}" stroke-width="2"/>')
        y += 34
        for line in bio:
            b.append(text(40, y, line, 16))
            y += 24
        y -= 24
    if meta:
        y += 18
        b.append(f'<line x1="1" x2="{W - 1}" y1="{y}" y2="{y}" stroke="{GDD}" stroke-width="2"/>')
        y += 34
        pad = max(len(k) for k, _ in meta) + 3
        vx = 40 + (2 + pad) * 15 * CW
        for k, v in meta:
            b.append(text(40, y, '> ' + (k + ':').ljust(pad), 15, GD, glow=None))
            b.append(text(vx, y, clip_text(v, 48), 15))
            y += 26
        y -= 26
        cx = vx + len(clip_text(meta[-1][1], 48)) * 15 * CW + 6
        b.append(f'<rect x="{cx:.0f}" y="{y - 13}" width="9" height="16" fill="{G}" opacity="0" filter="url(#glowS)">'
                 f'<animate attributeName="opacity" calcMode="discrete" values="1;0" dur="1s" repeatCount="indefinite"/></rect>')
    h = up4(y + 28)
    return slice_svg(W, h, ''.join(b), f"{u['login']} profile", T=True)


def repos_head():
    h = 56
    b = text(40, 34, '> REPOSITORIES', 14, GD, spacing=3, glow=None)
    return slice_svg(W, h, b, 'Repositories', divider='full')


def repo_row(r, first):
    h = 68
    b = text(40, 30, r['name'], 19, G, bold=True, glow='')
    desc = r['description'] or r.get('readme_blurb') or 'no description set on GitHub'
    b += text(40, 54, clip_text(desc, 72), 13, GD, glow=None)
    b += text(W - 40, 30, (r['language'] or '-').upper(), 13, G, anchor='end', spacing=2)
    meta = f"★ {r['stars']}   FORKS {r['forks']}"
    if r['pushed']:
        meta += f"   PUSHED {r['pushed']}"
    b += text(W - 40, 54, meta, 12, GD, anchor='end', glow=None)
    return slice_svg(W, h, b, f"{r['name']}: {r['language'] or 'no language'}, {r['stars']} stars",
                     divider=None if first else 'inset')


def bars(x, title, rows):
    b = text(x, 36, '> ' + title, 13, GD, spacing=3, glow=None)
    for i, (label, val, ratio) in enumerate(rows):
        y = 70 + i * 26
        b += text(x, y, label, 13, GD, glow=None)
        b += f'<rect x="{x + 112}" y="{y - 10}" width="190" height="11" fill="none" stroke="{GDD}" stroke-width="1"/>'
        fw = 190 * max(0.0, min(1.0, ratio))
        if fw >= 1:
            b += (f'<rect x="{x + 112}" y="{y - 10}" width="{fw:.0f}" height="11" fill="{G}" opacity=".85" filter="url(#glowS)">'
                  f'<animate attributeName="opacity" values=".85;.55;.85" dur="{2.0 + i * 0.3:.1f}s" repeatCount="indefinite"/></rect>')
        b += text(x + 318, y, val, 13, G, bold=True)
    return b


def stats_slice(d):
    u, t = d['user'], d['totals']
    stat_rows = [('REPOS', u['public_repos'], 20), ('STARS', t['stars'], 5), ('FORKS', t['forks'], 5),
                 ('FOLLOWERS', u['followers'], 10), ('FOLLOWING', u['following'], 10)]
    langs = sorted(d['langs'].items(), key=lambda kv: kv[1], reverse=True)[:MAX_LANGS]
    tot = sum(n for _, n in langs) or 1
    left = bars(40, 'GITHUB STATS', [(k, str(v), v / max(cap, v, 1)) for k, v, cap in stat_rows])
    right = bars(480, 'TOP LANGUAGES', [(k.upper(), f'{round(100 * n / tot)}%', n / tot) for k, n in langs])
    h = up4(70 + (max(len(stat_rows), len(langs)) - 1) * 26 + 32)
    sep = f'<line x1="450" x2="450" y1="18" y2="{h - 18}" stroke="{GDD}" stroke-width="2"/>'
    return slice_svg(W, h, left + sep + right, 'GitHub stats and top languages', divider='full')


def link_items(d):
    """Buttons: website, public email and other social accounts from your GitHub profile
    (no GitHub button: you're already on it; LinkedIn is deliberately left out)."""
    u = d['user']
    glyphs = {'twitter': 'X', 'mastodon': 'M', 'youtube': 'YT', 'bluesky': 'BS', 'generic': 'LNK'}
    short = lambda url: re.sub(r'^www\.', '', url.split('://', 1)[-1]).rstrip('/')
    items = []
    site = website(d)
    if site:
        items.append(('WEBSITE', short(site), 'WWW', site))
    if u.get('email'):
        items.append(('EMAIL', u['email'], '@', 'mailto:' + u['email']))
    for sa in u.get('socials', []):
        prov = (sa.get('provider') or 'generic').lower()
        if prov == 'linkedin':
            continue
        label = {'twitter': 'X', 'generic': 'LINK'}.get(prov, prov.upper())
        items.append((label, short(sa['url']), glyphs.get(prov, prov[:2].upper()), sa['url']))
    return items[:MAX_LINKS]


def link_cell(item, i, n):
    label, sub, glyph, _ = item
    w, h = W // n, 84
    chars = int((w - 100) / 7.2)
    b = f'<rect x="{w // 2 - w // 2 + 20}" y="14" width="56" height="56" fill="none" stroke="{GD}" stroke-width="1"/>'
    b += (f'<text x="{w // 2 - w // 2 + 48}" y="52" text-anchor="middle" font-family="{FONT}" font-size="24" font-weight="bold" fill="{G}" filter="url(#glow)">{esc(glyph)}'
          f'<animate attributeName="opacity" values="1;.7;1" dur="{2.2 + (i % 7) * 0.4:.1f}s" repeatCount="indefinite"/></text>')
    b += text(90, 38, label, 19, G, bold=True, spacing=3)
    b += text(90, 60, clip_text(sub, chars), 12, GD, glow=None)
    return slice_svg(w, h, b, f'{label}: {sub}', B=True, L=(i == 0), R=(i == n - 1), divider='full', vsep=(i > 0))


# ======================================================================= BUILD
def main():
    d = load_data()
    repos = select_repos(d['repos'])
    shown = repos[:MAX_REPOS]
    user = d['user']['login']

    files = {'header.svg': header(d)}
    order = [('header.svg', None, user)]
    if shown:
        files['repos_head.svg'] = repos_head()
        order.append(('repos_head.svg', None, 'Repositories'))
        for i, r in enumerate(shown):
            files[f'repo_{i}.svg'] = repo_row(r, first=(i == 0))
            order.append((f'repo_{i}.svg', f"https://github.com/{user}/{r['name']}", r['name']))
    files['stats.svg'] = stats_slice(d)
    order.append(('stats.svg', None, 'GitHub stats and top languages'))
    items = link_items(d)

    for i, it in enumerate(items):
        files[f'link_{i}.svg'] = link_cell(it, i, len(items))

    os.makedirs(OUT, exist_ok=True)
    for name in os.listdir(OUT):
        if name not in files:
            os.remove(os.path.join(OUT, name))
    for name, content in files.items():
        with open(os.path.join(OUT, name), 'w', encoding='utf-8') as f:
            f.write(content)

    # No blank lines inside the div: blank lines create <p> margins that would split the panel.
    # align="top" removes the baseline gap under inline images so the slices butt together.
    md = [f'<!-- generated {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%MZ} from {SOURCE[0]} data -->', '<div align="center">']
    for fn, href, alt in order:
        img = f'<img src="./assets/{fn}" alt="{esc(alt)}" width="100%" align="top" />'
        md.append(f'<a href="{esc(href)}">{img}</a>' if href else img)
    pct = 100 if len(items) == 1 else math.floor(998 / len(items)) / 10   # a lone button must be exactly full width
    md.append(''.join(f'<a href="{esc(it[3])}"><img src="./assets/link_{i}.svg" alt="{esc(it[0])}: {esc(it[1])}" width="{pct}%" align="top" /></a>'
                      for i, it in enumerate(items)))
    md += ['</div>', '']
    with open(os.path.join(ROOT, 'README.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))
    u = d['user']
    print(f"  bio:      {'from GitHub profile' if (u.get('bio') or '').strip() else 'EMPTY on GitHub -> using BIO_FALLBACK' if BIO_FALLBACK.strip() else 'EMPTY on GitHub -> auto summary'}")
    print(f"  website:  {website(d) or 'none (set one on GitHub, or add a <login>.github.io repo)'}")
    print(f"  details:  {', '.join(k for k, _ in meta_rows(d)) or 'none'}")
    print(f'wrote {len(files)} svgs + README.md ({len(shown)} repos shown of {len(repos)}, {len(items)} links)')


if __name__ == '__main__':
    main()
