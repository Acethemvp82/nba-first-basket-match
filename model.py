"""First Basket Match v1: transparent, uncalibrated empirical ranking model."""
import json
from collections import Counter
from datetime import datetime, timezone
from urllib.request import Request, urlopen

BASE = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/'
VERSION = '1.5.0'

def shot_type(play):
    if not is_fg(play): return None
    if play.get('pointsAttempted')==3:return '3PT'
    label=(play.get('type',{}).get('text','')+' '+play.get('text','')).lower()
    for word,name in [('dunk','Dunk'),('layup','Layup'),('hook','Hook')]:
        if word in label:return name
    if any(w in label for w in ['jump','fadeaway','fade away','pullup','pull-up']):return '2PT jumper'
    return None

def tip_conversion(games,tid):
    wins=[g for g in games if g.get('tip_winner')==tid]
    valid_fg=[g for g in wins if g.get('global_first_fg')]
    valid_pts=[g for g in wins if g.get('global_first_points')]
    return {'tip_wins':len(wins),
            'fg_hits':sum(g['global_first_fg'][0]==tid for g in valid_fg),'fg_n':len(valid_fg),
            'points_hits':sum(g['global_first_points'][0]==tid for g in valid_pts),'points_n':len(valid_pts)}

def jumper_records(games,tid):
    counts=Counter();wins=Counter();names={}
    for g in games:
        pid=g.get('jumpers',{}).get(tid)
        if not pid or g.get('tip_winner') not in g['first']:continue
        counts[pid]+=1;wins[pid]+=int(g['tip_winner']==tid)
        names[pid]=g['rosters'].get(tid,{}).get(pid,{}).get('name',pid)
    return [{'Player ID':p,'Jumper':names[p],'Tip wins':wins[p],'Tip attempts':counts[p],
             'Tip win %':100*wins[p]/counts[p]} for p in sorted(counts,key=lambda p:(-counts[p],p))]

def shot_style(games, opponent_games, tid, opp, pid):
    own=Counter(g.get('opening_types',{}).get(tid,{}).get('type') for g in games
                if g.get('opening_types',{}).get(tid,{}).get('player')==pid)
    allowed=Counter(v.get('type') for g in opponent_games for t,v in g.get('first_fg_types',{}).items() if t!=opp)
    own.pop(None,None);allowed.pop(None,None)
    n=sum(own.values());an=sum(allowed.values())
    leaders=[k for k,v in own.items() if v==max(own.values())] if own else []
    style=leaders[0] if len(leaders)==1 else None
    note='Shot type: limited data'
    if n>=3 and an>=5:
        note=(f'{style} openings {own[style]}/{n}; opponent first FG {allowed[style]}/{an}'
              if style else 'Shot type: no clear opening style')
    return {'style':style,'player_count':own.get(style,0),'player_n':n,
            'allowed_count':allowed.get(style,0),'allowed_n':an,'note':note,
            'own_counts':dict(own),'allowed_counts':dict(allowed)}

def position_summary(profile):
    counts=profile.get('counts',{})
    if not profile.get('n') or not counts:return 'Insufficient position data'
    best=max(counts.values());leaders=[p for p,c in counts.items() if c==best]
    if len(leaders)!=1:return 'No clear position advantage — tied counts'
    return f"Most observed: {leaders[0]} ({best}/{profile['n']}); descriptive, not a proven edge"

def source_starters(summary, event_id, tid, roster, tip):
    """Accept five explicit starter flags for this exact pregame event only."""
    comps=summary.get('header',{}).get('competitions',[])
    if len(comps)!=1: return []
    comp=comps[0]
    try:
        if (str(comp.get('id'))!=str(event_id) or utc(comp['date'])!=utc(tip)
                or comp.get('status',{}).get('type',{}).get('state')!='pre'):
            return []
    except (KeyError,TypeError,ValueError): return []
    blocks=[b for b in summary.get('boxscore',{}).get('players',[]) if str(b.get('team',{}).get('id'))==str(tid)]
    if len(blocks)!=1:return []
    records=[a for s in blocks[0].get('statistics',[]) for a in s.get('athletes',[]) if a.get('starter') is True]
    ids=[str(a.get('athlete',{}).get('id','')) for a in records]
    if len(ids)!=5 or len(set(ids))!=5 or any(p not in roster for p in ids):return []
    if any(a.get('didNotPlay') is True for a in records):return []
    return ids

SHORTLIST_RULES = {'min_team_games':5,'min_starts':3,'min_early_attempts':3,'max_picks':4}

def select_shortlist(rows, now):
    """Research screen, not a fitted edge threshold. One candidate per game."""
    eligible=[]
    for r in rows:
        try:
            if (r.get('Lineup')=='Source confirmed' and utc(r['Tip UTC'])>now
                    and min(r['Sample'],r['Opponent sample'])>=SHORTLIST_RULES['min_team_games']
                    and r['Starts']>=SHORTLIST_RULES['min_starts']
                    and r['Early FGA']>=SHORTLIST_RULES['min_early_attempts']
                    and r['Opening shot %']>0 and r['Team first hits']>0
                    and 0<r['Game first %']<100):
                eligible.append(r)
        except (KeyError,TypeError,ValueError):
            continue
    eligible.sort(key=lambda r:(-r['Game first %'],str(r['Game ID']),str(r['Player ID'])))
    selected=[]; used_games=set()
    for r in eligible:
        gid=str(r['Game ID'])
        if gid in used_games: continue
        used_games.add(gid);selected.append(dict(r))
        if len(selected)==SHORTLIST_RULES['max_picks']: break
    return selected

def position_group(position):
    return {'PG':'G','SG':'G','G':'G','SF':'F','PF':'F','F':'F','C':'C'}.get(position)

def position_profile(games, tid, allowed=False, event='attempts'):
    counts, baseline, valid = Counter(), Counter(), 0
    for g in games:
        events = g.get(event, {})
        shooting_team = next((t for t in events if t != tid), None) if allowed else tid
        roster = g['rosters'].get(shooting_team, {})
        group = position_group(roster.get(events.get(shooting_team), {}).get('position'))
        lineup = [position_group(roster.get(p, {}).get('position')) for p in g['starters'].get(shooting_team, [])]
        if group is None or len(lineup)!=5 or any(p is None for p in lineup):
            continue
        counts[group] += 1; baseline.update(lineup); valid += 1
    # Compare position frequency with the number of starters in that position.
    rates = {p: (counts[p]+10*baseline[p]/(5*valid))/(valid+10) if valid else None for p in ['G','F','C']}
    lifts = {p: rates[p]/(baseline[p]/(5*valid)) if valid and baseline[p] else 1.0 for p in rates}
    return {'n':valid,'rates':rates,'lifts':lifts,'counts':dict(counts)}

def opening_context(histories):
    result={}; tids=list(histories)
    for tid in tids:
        opp=next(t for t in tids if t!=tid)
        own=position_profile(histories[tid],tid)
        allowed=position_profile(histories[opp],opp,allowed=True)
        baskets=position_profile(histories[opp],opp,allowed=True,event='first_fg')
        tips=[g['tip_winner'] for g in histories[tid] if g.get('tip_winner') in g['first']]
        opp_tips=[g['tip_winner'] for g in histories[opp] if g.get('tip_winner') in g['first']]
        chance=((sum(t==tid for t in tips)+5)/(len(tips)+10)+1-(sum(t==opp for t in opp_tips)+5)/(len(opp_tips)+10))/2 if min(len(tips),len(opp_tips))>=5 else None
        result[tid]={'own':own,'allowed':allowed,'basket_allowed':baskets,'tip_n':len(tips),'opp_tip_n':len(opp_tips),'tip_chance':chance}
    return result

def shot_adjustment(context, position):
    group=position_group(position)
    if group is None or min(context['own']['n'],context['allowed']['n'])<5:
        return 1.0,'Limited data'
    lift=(context['own']['lifts'][group]*context['allowed']['lifts'][group])**.5
    factor=max(.85,min(1.15,lift))
    return factor, 'Favorable' if factor>=1.05 else 'Tougher' if factor<=.95 else 'Neutral'

def basket_adjustment(context, position):
    group=position_group(position)
    profile=context['basket_allowed']
    if group is None or profile['n']<5:
        return 1.0,'Limited data'
    factor=max(.85,min(1.15,profile['lifts'][group]))
    return factor, 'Favorable' if factor>=1.05 else 'Tougher' if factor<=.95 else 'Neutral'

def rank_reason(opening_attempts, sample, starts, shot_label, basket_label):
    parts=[f'Opening shots {opening_attempts}/{sample}']
    if basket_label=='Limited data': parts.append('Basket matchup: insufficient data')
    else: parts.append(f'Basket matchup: {basket_label.lower()}')
    if shot_label in ['Favorable','Tougher']: parts.append(f'Shot matchup: {shot_label.lower()}')
    if sample<15 or starts<8: parts.append('Limited history')
    return ' • '.join(parts)

def fetch(path):
    with urlopen(Request(BASE + path, headers={'Accept': 'application/json'}), timeout=20) as r:
        return json.load(r)

def utc(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))

def competitors(event):
    return event['competitions'][0]['competitors']

def team_id(c):
    return str(c['team']['id'])

def is_complete(event):
    return event.get('status', event['competitions'][0].get('status', {})).get('type', {}).get('completed', False)

def prior_events(events, cutoff, n):
    # Strict date cutoff prevents target-game results entering pregame features.
    return sorted([e for e in events if is_complete(e) and utc(e['date']) < cutoff],
                  key=lambda e: e['date'], reverse=True)[:n]

def actor(p):
    participants = p.get('participants', [])
    return str(participants[0]['athlete']['id']) if participants else None

def is_fg(p):
    return p.get('shootingPlay', False) and p.get('pointsAttempted') in (2, 3)

def parse_game(data, market='Field goal'):
    """FTs excluded in FG mode. Chronological sequence, never response array order."""
    comp = data['header']['competitions'][0]
    if not comp['status']['type'].get('completed'):
        raise ValueError('Incomplete historical game')
    plays = sorted(data.get('plays', []), key=lambda p: int(p.get('sequenceNumber', 0)))
    first, first_fg, attempts, early, global_first = {}, {}, {}, {}, None
    opening_types,first_fg_types={},{}
    global_first_fg=global_first_points=None
    teams = [str(c['team']['id']) for c in comp['competitors']]
    for p in plays:
        tid = str(p.get('team', {}).get('id', ''))
        pid = actor(p)
        if tid not in teams or not pid:
            continue
        if is_fg(p):
            if tid not in attempts:
                attempts[tid]=pid;opening_types[tid]={'player':pid,'type':shot_type(p)}
            if p.get('scoringPlay'):
                if tid not in first_fg:
                    first_fg[tid]=pid;first_fg_types[tid]={'player':pid,'type':shot_type(p)}
                if global_first_fg is None:global_first_fg=(tid,pid)
            clock = p.get('clock', {}).get('displayValue', '0:00').split(':')
            remaining = float(clock[0])*60 + float(clock[1]) if len(clock)==2 else float(clock[0])
            if p.get('period', {}).get('number') == 1 and remaining >= 540:
                v = early.setdefault((tid, pid), [0, 0])
                v[1] += 1
                v[0] += int(bool(p.get('scoringPlay')))
        if p.get('scoringPlay') and p.get('scoreValue',0)>0 and global_first_points is None:
            global_first_points=(tid,pid)
        scoring = p.get('scoringPlay') and (is_fg(p) if market == 'Field goal' else p.get('scoreValue', 0) > 0)
        if scoring:
            first.setdefault(tid, pid)
            if global_first is None:
                global_first = (tid, pid)
    # Missing either team's opening event means the PBP is not reliable enough.
    if len(first) != 2 or len(first_fg) != 2 or len(attempts) != 2 or global_first is None:
        raise ValueError('Missing opening play-by-play')
    rosters, starters = {}, {}
    for block in data.get('boxscore', {}).get('players', []):
        tid = str(block['team']['id'])
        rosters[tid], starters[tid] = {}, set()
        for group in block.get('statistics', []):
            for a in group.get('athletes', []):
                athlete = a['athlete']; pid = str(athlete['id'])
                rosters[tid][pid] = {'name': athlete['displayName'], 'position': athlete.get('position', {}).get('abbreviation', '?')}
                if a.get('starter') and not a.get('didNotPlay'):
                    starters[tid].add(pid)
    if any(len(starters.get(t, [])) != 5 for t in teams):
        raise ValueError('Missing five historical starters')
    tip_winner=None;jumpers={}
    for p in plays:
        if p.get('period',{}).get('number')!=1 or p.get('clock',{}).get('displayValue')!='12:00': continue
        if p.get('type',{}).get('text','').lower().replace(' ','')!='jumpball': continue
        # Never infer tip winner from first shot, first score, or jump-ball team ID.
        receivers=p.get('participants',[])
        if len(receivers)>=3:
            receiver=str(receivers[-1]['athlete']['id'])
            matches=[t for t in teams if receiver in rosters.get(t,{}) and
                     rosters[t][receiver]['name']+' gains possession' in p.get('text','')]
            if len(matches)==1: tip_winner=matches[0]
            first_two=[str(x.get('athlete',{}).get('id','')) for x in receivers[:2]]
            for player in first_two:
                ts=[t for t in teams if player in rosters.get(t,{}) and rosters[t][player]['name'] in p.get('text','').split('(')[0]]
                if len(ts)==1:jumpers[ts[0]]=player
            if len(jumpers)!=2 or len(set(jumpers.values()))!=2:jumpers={}
        break
    return {'id': str(comp['id']), 'date': comp['date'], 'first': first, 'tip_winner':tip_winner,
            'first_fg':first_fg, 'attempts': attempts, 'early': early, 'global_first': global_first,
            'global_first_fg':global_first_fg,'global_first_points':global_first_points,
            'opening_types':opening_types,'first_fg_types':first_fg_types,'jumpers':jumpers,
            'rosters': rosters, 'starters': starters}

def forecast(histories, selected, metadata):
    """One game: mixture over player + residual buckets; mass sums exactly to one."""
    tids = list(histories)
    if len(tids) != 2 or any(not histories[t] for t in tids):
        raise ValueError('Both teams need valid historical games')
    if any(len(selected[t]) != 5 or len(set(selected[t])) != 5 for t in tids):
        raise ValueError('Select exactly five distinct starters per team')
    rates = {t: (sum(g['global_first'][0] == t for g in histories[t])+5)/(len(histories[t])+10) for t in tids}
    team_chance = (rates[tids[0]] + 1-rates[tids[1]])/2
    rows, residual = [], {}
    context=opening_context(histories)
    for idx, tid in enumerate(tids):
        games = histories[tid]; ids = list(selected[tid]); n = len(games)
        # Six outcomes: each selected starter and everybody else. All have prior 1.
        def bucket(pid): return pid if pid in ids else 'OTHER'
        first = Counter(bucket(g['first'][tid]) for g in games)
        attempts = Counter(bucket(g['attempts'][tid]) for g in games)
        buckets = ids + ['OTHER']; raw = {}
        for pid in buckets:
            made = att = 0
            for g in games:
                for (team, player), (m, a) in g['early'].items():
                    if team == tid and bucket(player) == pid:
                        made += m; att += a
            conversion = (made+4.5)/(att+10)
            factor=shot_adjustment(context[tid],metadata[tid][pid]['position'])[0] if pid!='OTHER' else 1.0
            raw[pid] = (attempts[pid]+1)/(n+6)*conversion*factor
        total = sum(raw.values())
        # Made-basket matchup modifies only the first-scoring component; keep
        # the unlisted-player bucket and normalize each component separately.
        first_raw={p:(first[p]+1)/(n+6)*(basket_adjustment(context[tid],metadata[tid][p]['position'])[0] if p!='OTHER' else 1.0) for p in buckets}
        first_total=sum(first_raw.values())
        shares = {p: .6*first_raw[p]/first_total + .4*raw[p]/total for p in buckets}
        game_share = team_chance if idx == 0 else 1-team_chance
        residual[tid] = game_share*shares['OTHER']
        for pid in ids:
            starts = sum(pid in g['starters'][tid] for g in games)
            early_made = sum(g['early'].get((tid,pid), [0,0])[0] for g in games)
            early_att = sum(g['early'].get((tid,pid), [0,0])[1] for g in games)
            shot_label=shot_adjustment(context[tid],metadata[tid][pid]['position'])[1]
            basket_label=basket_adjustment(context[tid],metadata[tid][pid]['position'])[1]
            group=position_group(metadata[tid][pid]['position'])
            profile=context[tid]['basket_allowed']
            opponent=next(t for t in tids if t!=tid)
            style=shot_style(games,histories[opponent],tid,opponent,pid)
            rows.append({'Player ID': pid, 'Player': metadata[tid][pid]['name'], 'Team ID': tid,
                         'Position': metadata[tid][pid]['position'], 'Sample': n,
                         'Opponent sample':len(histories[next(t for t in tids if t!=tid)]),
                         'Shot matchup':shot_label, 'Basket matchup':basket_label,
                         'Why ranked':rank_reason(attempts[pid],n,starts,shot_label,basket_label),
                         'Opening style context':style['note'],
                         'Opponent first FG position hits':profile['counts'].get(group,0) if group and profile['n'] else None,
                         'Opponent first FG position sample':profile['n'],
                         'Opponent first FG position %':100*profile['counts'].get(group,0)/profile['n'] if group and profile['n'] else None,
                         'Team tip estimate %':100*context[tid]['tip_chance'] if context[tid]['tip_chance'] is not None else None,
                         'Position sample':context[tid]['own']['n'], 'Opponent position sample':context[tid]['allowed']['n'],
                         'Starts': starts, 'Team first hits': first[pid],
                         'Opening shot %': 100*attempts[pid]/n,
                         'Early FG %': 100*early_made/early_att if early_att else None,
                         'Early FGA': early_att, 'Team scores first %': 100*game_share,
                         'Team first %': 100*shares[pid], 'Game first %': 100*game_share*shares[pid],
                         'Model fair decimal': 1/(game_share*shares[pid]),
                         'Sample status': 'Limited' if n < 15 or starts < 8 else 'Developing'})
    return sorted(rows, key=lambda r:r['Game first %'], reverse=True), residual

def implied(american):
    if abs(american) < 100:
        raise ValueError('American odds must be at least +100 or at most -100')
    return 100/(american+100) if american > 0 else -american/(-american+100)
