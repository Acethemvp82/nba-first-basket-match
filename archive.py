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
    result['settled_rows']=[{**r,'Game first hit':game['global_first']==(str(r['Team ID']),str(r['Player ID'])),
                            'Team first hit':game['first'].get(str(r['Team ID']))==str(r['Player ID'])} for r in rows]
    return result
