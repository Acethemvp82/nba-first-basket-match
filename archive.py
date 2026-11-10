"""Pregame records: never reconstruct forecasts after tip."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from model import utc, parse_game, VERSION, SHORTLIST_RULES

def snapshot(rows,basis,created_at,scope='Loaded games'):
    return {'version':VERSION,'created_at':created_at.isoformat(),'basis':basis,
            'scope':scope,'shortlist_rules':SHORTLIST_RULES,'rows':deepcopy(rows)}

def keep_pregame(previous, candidate, now):
    """Retain latest pretip record. Refuse late, mixed-game, or older records."""
    rows=candidate.get('rows',[])
    if not rows or len({str(r.get('Game ID')) for r in rows})!=1:return previous
    try:
        created=utc(candidate['created_at'])
        if created>now or any(created>=utc(r['Tip UTC']) or now>=utc(r['Tip UTC']) for r in rows):return previous
        if previous and ('settled_rows' in previous or created<=utc(previous['created_at'])):return previous
    except (KeyError,TypeError,ValueError):return previous
    return deepcopy(candidate)

def settle(record, summary, now):
    rows=record.get('rows',[])
    if not rows:raise ValueError('Empty pregame record')
    game=parse_game(summary,record['basis'])
    if any(str(r['Game ID'])!=game['id'] for r in rows):raise ValueError('Wrong settlement game')
    if any(utc(record['created_at'])>=utc(r['Tip UTC']) for r in rows):raise ValueError('Late forecast')
    result=deepcopy(record)
    result['pregame_sha256']=sha256(json.dumps(record['rows'],sort_keys=True,allow_nan=False).encode()).hexdigest()
    result['settled_at']=now.isoformat()
    tid,pid=game['global_first']
    result['first_scorer']={'Player ID':pid,'Team ID':tid,
                           'Player':game['rosters'].get(tid,{}).get(pid,{}).get('name',pid)}
    result['settled_rows']=[{**r,'Game first hit':game['global_first']==(str(r['Team ID']),str(r['Player ID'])),
                            'Team first hit':game['first'].get(str(r['Team ID']))==str(r['Player ID'])} for r in rows]
    return result


def tracking_summary(records, basis='First points'):
    """One latest prospective record per game, within a single selected source."""
    chosen={}
    for record in records:
        rows=record.get('rows',[])
        if record.get('basis')!=basis or not rows:continue
        try:
            gid=str(rows[0]['Game ID']);created=utc(record['created_at'])
            if any(str(r['Game ID'])!=gid or created>=utc(r['Tip UTC']) for r in rows):continue
            if gid not in chosen or created>utc(chosen[gid]['created_at']):chosen[gid]=record
        except (KeyError,TypeError,ValueError):continue
    result=[]
    for gid,record in chosen.items():
        original=record['rows']
        ranked=sorted(original,key=lambda r:(-r['Game first %'],str(r['Player ID'])))
        settled=record.get('settled_rows',[])
        hits={(str(r['Team ID']),str(r['Player ID'])) for r in settled if r.get('Game first hit') is True}
        identity=lambda r:(str(r['Team ID']),str(r['Player ID']))
        winner=next((r for r in ranked if identity(r) in hits),None)
        final=bool(settled)
        shortlisted=[r for r in ranked if r.get('Shortlisted') is True]
        result.append({'Game ID':gid,'Tip UTC':ranked[0]['Tip UTC'],
                       'Matchup':ranked[0].get('Matchup',gid),'Status':'Final' if final else 'Pending',
                       'First scorer':winner['Player'] if winner else record.get('first_scorer',{}).get('Player','Unlisted player' if final else 'Pending'),
                       'Pregame game rank':next((i for i,r in enumerate(ranked,1) if identity(r) in hits),None),
                       'Pregame team rank':winner.get('Team Rank') if winner else None,
                       'Pregame overall rank':winner.get('Overall Rank') if winner else None,
                       'Scorer model %':winner['Game first %'] if winner else None,
                       'Top pick':ranked[0]['Player'],
                       'Top pick hit':identity(ranked[0]) in hits if final else None,
                       'Top 3 hit':any(identity(r) in hits for r in ranked[:3]) if final else None,
                       'Shortlist pick':', '.join(r['Player'] for r in shortlisted) or 'None eligible',
                       'Shortlist hit':any(identity(r) in hits for r in shortlisted) if final and shortlisted else None,
                       'Lineup':ranked[0].get('Lineup','Unknown'),
                       'History window':record.get('settings',{}).get('games'),
                       'Saved at':record['created_at']})
    return sorted(result,key=lambda r:(r['Tip UTC'],r['Game ID']),reverse=True)


def live_first_basket(summary, event_id):
    """Identify first points without requiring a final game or rebuilding ranks."""
    comp=summary.get('header',{}).get('competitions',[{}])[0]
    if str(comp.get('id'))!=str(event_id):return None
    plays=sorted(summary.get('plays',[]),key=lambda p:int(p.get('sequenceNumber',0)))
    first=next((p for p in plays if p.get('scoringPlay') and p.get('scoreValue',0)>0),None)
    if not first or first.get('period',{}).get('number')!=1:return None
    # Cumulative score must prove no earlier points are missing from the feed.
    try:
        if int(first['homeScore'])+int(first['awayScore'])!=int(first['scoreValue']):return None
    except (KeyError,ValueError,TypeError):return None
    participants=first.get('participants',[])
    if not participants:return None
    pid=str(participants[0].get('athlete',{}).get('id',''))
    tid=str(first.get('team',{}).get('id',''))
    for block in summary.get('boxscore',{}).get('players',[]):
        if str(block.get('team',{}).get('id'))!=tid:continue
        for group in block.get('statistics',[]):
            for player in group.get('athletes',[]):
                athlete=player.get('athlete',{})
                if str(athlete.get('id'))==pid and athlete.get('displayName'):
                    return {'Player':athlete['displayName'],'Player ID':pid,'Team ID':tid,
                            'Clock':first.get('clock',{}).get('displayValue',''),
                            'Method':'Free throw' if first['scoreValue']==1 else f"{first['scoreValue']}-pointer"}
    return None
