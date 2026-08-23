import json, urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE='https://fantasy.premierleague.com/api'
LEAGUE_ID=1465498
MANAGERS=[
    {'name':'Ayrton','team':'SpendItLikeBoehly','id':2656684},
    {'name':'Ciarán','team':'PowerRangersFC','id':8392502},
    {'name':'Heno','team':'Grovine','id':68523},
    {'name':'Michael','team':'Backstreet Moyes','id':2182665},
]

def get(path):
    req=urllib.request.Request(BASE+path,headers={'User-Agent':'Geoffrey2.0/1.0'})
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.load(r)

def latest_finished(events):
    finished=[e for e in events if e.get('finished')]
    return max(finished,key=lambda e:e['id']) if finished else None

def calc_manager(m, gw, live, elements):
    picks=get(f"/entry/{m['id']}/event/{gw}/picks/")
    by_id={x['id']:x for x in elements}
    live_by_id={x['id']:x['stats'] for x in live['elements']}
    reasons=[]; negative=[]; bench10=[]; reds=[]
    captain_points=None
    for p in picks.get('picks',[]):
        pid=p['element']; stats=live_by_id.get(pid,{})
        pts=stats.get('total_points',0)
        name=by_id.get(pid,{}).get('web_name',str(pid))
        if pts<0: negative.append(name)
        if p.get('position',0)>=12 and pts>=10: bench10.append(name)
        if stats.get('red_cards',0)>0: reds.append(name)
        if p.get('is_captain'):
            captain_points=pts
    entry_points=picks.get('entry_history',{}).get('points')
    if captain_points is not None and captain_points<=4: reasons.append('Captain ≤4 (€1)')
    if negative: reasons.append(f"Negative player ×{len(negative)} (€{len(negative)})")
    if bench10: reasons.append(f"Bench ≥10 ×{len(bench10)} (€{len(bench10)})")
    if reds: reasons.append(f"Sent off ×{len(reds)} (€{2*len(reds)})")
    return {'manager':m['name'],'team':m['team'],'id':m['id'],'points':entry_points or 0,'negative':negative,'bench10':bench10,'reds':reds,'captain_points':captain_points,'reasons':reasons}

def h2h_lookup():
    # The H2H endpoint has changed shape over time. Try the current public endpoint first,
    # then the older documented form. If unavailable, the app still has manager scores.
    for path in [f'/leagues-h2h-matches/league/{LEAGUE_ID}/?page=1', f'/leagues-h2h/{LEAGUE_ID}/standings/']:
        try:
            return get(path)
        except Exception:
            pass
    return {}

def main():
    bootstrap=get('/bootstrap-static/')
    event=latest_finished(bootstrap.get('events',[]))
    out={'generated_at':datetime.now(timezone.utc).isoformat(),'league_id':LEAGUE_ID,'managers':[],'fines':[],'latest_finished_gw':event['id'] if event else None,'average':event.get('average_entry_score') if event else None,'gameweek_detail':None}
    if not event:
        Path('data').mkdir(exist_ok=True); Path('data/fpl.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)); return
    gw=event['id']; live=get(f'/event/{gw}/live/'); elements=bootstrap.get('elements',[])
    results=[calc_manager(m,gw,live,elements) for m in MANAGERS]
    min_points=min(x['points'] for x in results)
    avg=event.get('average_entry_score')
    for r in results:
        total=0
        if avg is not None and r['points']<avg:
            r['reasons'].insert(0,'Below official FPL average (€2)'); total+=2
        total+=len(r['negative'])
        total+=len(r['bench10'])
        total+=2*len(r['reds'])
        if r['captain_points'] is not None and r['captain_points']<=4: total+=1
        if r['points']==min_points: r['reasons'].append('Lowest of four (€2)'); total+=2
        r['fine_total']=total
        out['managers'].append({'id':r['id'],'manager':r['manager'],'team':r['team'],'gw_points':r['points'],'wins':0,'draws':0,'losses':0,'fine_total':total})
    # H2H standings: if the response contains standings, use them for W/D/L.
    h2h=h2h_lookup()
    candidates=[]
    if isinstance(h2h,dict):
        candidates=h2h.get('standings') or h2h.get('results') or []
    if isinstance(candidates,list):
        for r in out['managers']:
            hit=next((x for x in candidates if x.get('entry')==r['id'] or x.get('id')==r['id']),None)
            if hit:
                r['wins']=hit.get('won',hit.get('wins',0)) or 0; r['draws']=hit.get('drawn',hit.get('draws',0)) or 0; r['losses']=hit.get('lost',hit.get('losses',0)) or 0
    detail=[]
    for r in results:
        detail.append({'manager':r['manager'],'team':r['team'],'points':r['points'],'captain_points':r['captain_points'],'negative':r['negative'],'bench10':r['bench10'],'reds':r['reds'],'reasons':r['reasons'],'fine_total':next(x['fine_total'] for x in out['managers'] if x['id']==r['id'])})
    out['gameweek_detail']={'gw':gw,'average':avg,'finished':bool(event.get('finished')),'managers':detail}
    # Generate a deterministic fine ledger for the latest completed GW.
    for r in detail:
        for reason,amount in [
            ('Below official FPL average',2 if avg is not None and r['points']<avg else 0),
            ('Negative player',len(r['negative'])),
            ('Bench player ≥10',len(r['bench10'])),
            ('Captain ≤4',1 if r['captain_points'] is not None and r['captain_points']<=4 else 0),
            ('Lowest of four',2 if r['points']==min_points else 0),
            ('Player sent off',2*len(r['reds']))]:
            if amount:
                out['fines'].append({'key':f"gw{gw}-{r['id']}-{reason}",'gw':gw,'manager':r['manager'],'reason':reason,'amount':amount})
    Path('data').mkdir(exist_ok=True); Path('data/fpl.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
