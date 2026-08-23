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
    display = latest_finished or current or next_event
    return latest_finished, display


def calc_manager(manager, gameweek, live, elements):
    picks = get(f"/entry/{manager['id']}/event/{gameweek}/picks/")
    by_id = {x['id']: x for x in elements}
    live_by_id = {x['id']: x.get('stats', {}) for x in live.get('elements', [])}

    negative = []
    bench10 = []
    reds = []
    captain_points = None

    for pick in picks.get('picks', []):
        player_id = pick['element']
        stats = live_by_id.get(player_id, {})
        points = stats.get('total_points', 0) or 0
        player_name = by_id.get(player_id, {}).get('web_name', str(player_id))

        # Positions 12-15 are the four bench slots in FPL picks.
        if points < 0:
            negative.append(player_name)
        if pick.get('position', 0) >= 12 and points >= 10:
            bench10.append(player_name)
        if stats.get('red_cards', 0) > 0:
            reds.append(player_name)
        if pick.get('is_captain'):
            captain_points = points

    entry_history = picks.get('entry_history', {})
    points = entry_history.get('points', 0) or 0
    return {
        'manager': manager['name'],
        'team': manager['team'],
        'id': manager['id'],
        'points': points,
        'negative': negative,
        'bench10': bench10,
        'reds': reds,
        'captain_points': captain_points,
        'reasons': [],
    }


def calculate_fines(results, average, finished):
    if not finished:
        return

    valid_points = [r['points'] for r in results]
    lowest = min(valid_points) if valid_points else None

    for result in results:
        total = 0
        if average is not None and result['points'] < average:
            result['reasons'].append('Below official FPL average (€2)')
            total += 2
        if result['negative']:
            result['reasons'].append(f"Negative player ×{len(result['negative'])} (€{len(result['negative'])})")
            total += len(result['negative'])
        if result['bench10']:
            result['reasons'].append(f"Bench ≥10 ×{len(result['bench10'])} (€{len(result['bench10'])})")
            total += len(result['bench10'])
        if result['captain_points'] is not None and result['captain_points'] <= 4:
            result['reasons'].append('Captain ≤4 (€1)')
            total += 1
        if lowest is not None and result['points'] == lowest:
            result['reasons'].append('Lowest of four (€2)')
            total += 2
        if result['reds']:
            result['reasons'].append(f"Player sent off ×{len(result['reds'])} (€{2 * len(result['reds'])})")
            total += 2 * len(result['reds'])
        result['fine_total'] = total


def main():
    bootstrap = get('/bootstrap-static/')
    events = bootstrap.get('events', [])
    latest_finished, display_event = choose_event(events)

    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'league_id': LEAGUE_ID,
        'season': next((e.get('name') for e in events if e.get('is_current')), None),
        'latest_finished_gw': latest_finished['id'] if latest_finished else None,
        'display_gw': display_event['id'] if display_event else None,
        'display_status': (
            'finished' if display_event and display_event.get('finished')
            else 'live' if display_event and display_event.get('is_current')
            else 'upcoming'
        ),
        'average': display_event.get('average_entry_score') if display_event else None,
        'managers': [],
        'fines': [],
        'gameweek_detail': None,
    }

    if not display_event:
        Path('data').mkdir(exist_ok=True)
        Path('data/fpl.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
        return

    gw = display_event['id']
    live = get(f'/event/{gw}/live/')
    elements = bootstrap.get('elements', [])
    results = []
    errors = []

    for manager in MANAGERS:
        try:
            results.append(calc_manager(manager, gw, live, elements))
        except Exception as exc:
            errors.append({'manager': manager['name'], 'error': str(exc)})
            results.append({
                'manager': manager['name'], 'team': manager['team'], 'id': manager['id'],
                'points': 0, 'negative': [], 'bench10': [], 'reds': [],
                'captain_points': None, 'reasons': [], 'fine_total': 0,
            })

    # Fines are only created after the Gameweek is officially finished.
    calculate_fines(results, out['average'], bool(display_event.get('finished')))

    for result in results:
        out['managers'].append({
            'id': result['id'],
            'manager': result['manager'],
            'team': result['team'],
            'gw_points': result['points'],
            'fine_total': result.get('fine_total', 0),
        })

    detail = []
    for result in results:
        detail.append({
            'manager': result['manager'],
            'team': result['team'],
            'points': result['points'],
            'captain_points': result['captain_points'],
            'negative': result['negative'],
            'bench10': result['bench10'],
            'reds': result['reds'],
            'reasons': result['reasons'],
            'fine_total': result.get('fine_total', 0),
        })

    out['gameweek_detail'] = {
        'gw': gw,
        'average': out['average'],
        'finished': bool(display_event.get('finished')),
        'status': out['display_status'],
        'deadline_at': display_event.get('deadline_time'),
        'managers': detail,
    }
    out['sync_errors'] = errors

    # Only expose fine records when the GW is complete. This prevents fines being
    # issued during an unfinished Gameweek while still showing live scores.
    if display_event.get('finished'):
        for result in results:
            entries = [
                ('Below official FPL average', 2 if out['average'] is not None and result['points'] < out['average'] else 0),
                ('Negative player', len(result['negative'])),
                ('Bench player ≥10', len(result['bench10'])),
                ('Captain ≤4', 1 if result['captain_points'] is not None and result['captain_points'] <= 4 else 0),
                ('Lowest of four', 2 if result['points'] == min(r['points'] for r in results) else 0),
                ('Player sent off', 2 * len(result['reds'])),
            ]
            for reason, amount in entries:
                if amount:
                    key = f"gw{gw}-{result['id']}-{reason}"
                    out['fines'].append({
                        'key': key,
                        'gw': gw,
                        'manager': result['manager'],
                        'reason': reason,
                        'amount': amount,
                    })

    Path('data').mkdir(exist_ok=True)
    Path('data/fpl.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
