import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = 'https://fantasy.premierleague.com/api'
LEAGUE_ID = 1465498
MANAGERS = [
    {'name': 'Ayrton', 'team': 'SpendItLikeBoehly', 'id': 2656684},
    {'name': 'Ciarán', 'team': 'PowerRangersFC', 'id': 8392502},
    {'name': 'Heno', 'team': 'Grovine', 'id': 68523},
    {'name': 'Michael', 'team': 'Backstreet Moyes', 'id': 2182665},
]


def get(path):
    req = urllib.request.Request(
        BASE + path,
        headers={
            'User-Agent': 'Mozilla/5.0 Geoffrey2.0 FPL sync',
            'Accept': 'application/json',
        },
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.load(response)


def choose_event(events):
    finished = [e for e in events if e.get('finished')]
    current = next((e for e in events if e.get('is_current')), None)
    next_event = next((e for e in events if e.get('is_next')), None)
    latest_finished = max(finished, key=lambda e: e['id']) if finished else None
    candidates = [e for e in (latest_finished, current) if e]
    display = max(candidates, key=lambda e: e['id']) if candidates else next_event
    return latest_finished, display


def fixture_status(gameweek):
    try:
        fixtures = get(f'/fixtures/?event={gameweek}')
        fixtures = [f for f in fixtures if f.get('event') == gameweek]
        return bool(fixtures) and all(f.get('finished') for f in fixtures)
    except Exception:
        return False


def event_is_finished(event):
    return bool(event and (event.get('finished') or fixture_status(event['id'])))


def calc_manager(manager, gameweek, live, elements):
    picks = get(f"/entry/{manager['id']}/event/{gameweek}/picks/")
    by_id = {x['id']: x for x in elements}
    live_by_id = {x['id']: x.get('stats', {}) for x in live.get('elements', [])}
    negative, bench10, reds = [], [], []
    captain_points = None

    for pick in picks.get('picks', []):
        player_id = pick['element']
        stats = live_by_id.get(player_id, {})
        points = stats.get('total_points', 0) or 0
        player_name = by_id.get(player_id, {}).get('web_name', str(player_id))
        if points < 0:
            negative.append(player_name)
        if pick.get('position', 0) >= 12 and points >= 10:
            bench10.append(player_name)
        if stats.get('red_cards', 0) > 0:
            reds.append(player_name)
        if pick.get('is_captain'):
            captain_points = points

    entry_history = picks.get('entry_history', {})
    return {
        'manager': manager['name'], 'team': manager['team'], 'id': manager['id'],
        'points': entry_history.get('points', 0) or 0,
        'negative': negative, 'bench10': bench10, 'reds': reds,
        'captain_points': captain_points, 'reasons': [],
    }


def calculate_fines(results, average, finished):
    if not finished:
        for result in results:
            result['fine_total'] = 0
        return

    valid_points = [r['points'] for r in results]
    lowest = min(valid_points) if valid_points else None
    for result in results:
        total = 0
        if average is not None and result['points'] < average:
            result['reasons'].append('Below official FPL average (€2)')
            total += 2
        if result['negative']:
            n = len(result['negative'])
            result['reasons'].append(f'Negative player ×{n} (€{n})')
            total += n
        if result['bench10']:
            n = len(result['bench10'])
            result['reasons'].append(f'Bench ≥10 ×{n} (€{n})')
            total += n
        if result['captain_points'] is not None and result['captain_points'] <= 4:
            result['reasons'].append('Captain ≤4 (€1)')
            total += 1
        if lowest is not None and result['points'] == lowest:
            result['reasons'].append('Lowest of four (€2)')
            total += 2
        if result['reds']:
            n = len(result['reds'])
            result['reasons'].append(f'Player sent off ×{n} (€{2 * n})')
            total += 2 * n
        result['fine_total'] = total


def build_fines(results, gw, average):
    lowest = min(r['points'] for r in results)
    fines = []
    for result in results:
        entries = [
            ('Below official FPL average', 2 if average is not None and result['points'] < average else 0),
            ('Negative player', len(result['negative'])),
            ('Bench player ≥10', len(result['bench10'])),
            ('Captain ≤4', 1 if result['captain_points'] is not None and result['captain_points'] <= 4 else 0),
            ('Lowest of four', 2 if result['points'] == lowest else 0),
            ('Player sent off', 2 * len(result['reds'])),
        ]
        for reason, amount in entries:
            if amount:
                fines.append({
                    'key': f'gw{gw}-{result["id"]}-{reason}',
                    'gw': gw,
                    'manager': result['manager'],
                    'reason': reason,
                    'amount': amount,
                })
    return fines


def main():
    bootstrap = get('/bootstrap-static/')
    events = bootstrap.get('events', [])
    event_by_id = {e['id']: e for e in events}
    latest_finished, display_event = choose_event(events)

    # Determine all completed Gameweeks, not just the latest one, so the app
    # can maintain a complete historical fine ledger.
    finished_ids = []
    for event in events:
        if event['id'] <= (display_event['id'] if display_event else 0) and event_is_finished(event):
            finished_ids.append(event['id'])
    if latest_finished:
        finished_ids.append(latest_finished['id'])
    finished_ids = sorted(set(finished_ids))
    latest_finished_id = max(finished_ids) if finished_ids else None

    display_finished = event_is_finished(display_event) if display_event else False
    if display_finished and display_event and (latest_finished_id is None or display_event['id'] > latest_finished_id):
        latest_finished_id = display_event['id']
        finished_ids.append(display_event['id'])
        finished_ids = sorted(set(finished_ids))

    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'league_id': LEAGUE_ID,
        'season': next((e.get('name') for e in events if e.get('is_current')), None),
        'latest_finished_gw': latest_finished_id,
        'display_gw': display_event['id'] if display_event else None,
        'display_status': 'finished' if display_finished else 'live' if display_event and display_event.get('is_current') else 'upcoming',
        'average': display_event.get('average_entry_score') if display_event else None,
        'managers': [],
        'fines': [],
        'all_fines': [],
        'fine_totals': [],
        'gameweek_detail': None,
        'sync_errors': [],
    }

    if not display_event:
        Path('data').mkdir(exist_ok=True)
        Path('data/fpl.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
        return

    elements = bootstrap.get('elements', [])
    errors = []
    historical_totals = {m['id']: 0 for m in MANAGERS}
    historical_fines = []
    display_results = None

    # Rebuild fines for every finished GW so totals remain correct after each sync.
    for gw in finished_ids:
        try:
            live = get(f'/event/{gw}/live/')
            results = []
            for manager in MANAGERS:
                try:
                    results.append(calc_manager(manager, gw, live, elements))
                except Exception as exc:
                    errors.append({'gameweek': gw, 'manager': manager['name'], 'error': str(exc)})
                    results.append({
                        'manager': manager['name'], 'team': manager['team'], 'id': manager['id'],
                        'points': 0, 'negative': [], 'bench10': [], 'reds': [],
                        'captain_points': None, 'reasons': [], 'fine_total': 0,
                    })
            average = event_by_id.get(gw, {}).get('average_entry_score')
            calculate_fines(results, average, True)
            gw_fines = build_fines(results, gw, average)
            historical_fines.extend(gw_fines)
            for result in results:
                historical_totals[result['id']] += result.get('fine_total', 0)
            if gw == display_event['id']:
                display_results = results
        except Exception as exc:
            errors.append({'gameweek': gw, 'error': str(exc)})

    # If the current display GW is live, calculate it for the dashboard but do
    # not add it to the fine ledger until it has actually finished.
    if display_results is None:
        gw = display_event['id']
        try:
            live = get(f'/event/{gw}/live/')
            display_results = []
            for manager in MANAGERS:
                try:
                    display_results.append(calc_manager(manager, gw, live, elements))
                except Exception as exc:
                    errors.append({'gameweek': gw, 'manager': manager['name'], 'error': str(exc)})
                    display_results.append({
                        'manager': manager['name'], 'team': manager['team'], 'id': manager['id'],
                        'points': 0, 'negative': [], 'bench10': [], 'reds': [],
                        'captain_points': None, 'reasons': [], 'fine_total': 0,
                    })
            calculate_fines(display_results, display_event.get('average_entry_score'), display_finished)
        except Exception as exc:
            errors.append({'gameweek': gw, 'error': str(exc)})
            display_results = []

    out['fines'] = [f for f in historical_fines if f['gw'] == display_event['id']]
    out['all_fines'] = historical_fines
    out['fine_totals'] = [
        {'manager': m['name'], 'team': m['team'], 'id': m['id'], 'total_fines': historical_totals[m['id']]}
        for m in MANAGERS
    ]

    for result in display_results:
        out['managers'].append({
            'id': result['id'], 'manager': result['manager'], 'team': result['team'],
            'gw_points': result['points'], 'fine_total': result.get('fine_total', 0),
            'total_fines': historical_totals[result['id']],
        })

    out['gameweek_detail'] = {
        'gw': display_event['id'],
        'average': display_event.get('average_entry_score'),
        'finished': display_finished,
        'status': out['display_status'],
        'deadline_at': display_event.get('deadline_time'),
        'managers': [
            {
                'manager': r['manager'], 'team': r['team'], 'points': r['points'],
                'captain_points': r['captain_points'], 'negative': r['negative'],
                'bench10': r['bench10'], 'reds': r['reds'], 'reasons': r['reasons'],
                'fine_total': r.get('fine_total', 0),
            }
            for r in display_results
        ],
    }
    out['sync_errors'] = errors

    Path('data').mkdir(exist_ok=True)
    Path('data/fpl.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
