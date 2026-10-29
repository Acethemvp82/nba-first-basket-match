"""Scheduled pregame capture and settlement. Public sports forecasts only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import gzip
import json
import os
from hashlib import sha256
from model import fetch, utc, competitors, team_id, prior_events, parse_game, forecast, source_starters, select_shortlist
from archive import snapshot, keep_pregame, settle

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'
ET=ZoneInfo('America/New_York')

class Client:
    def __init__(self):
        self.cache=Path(os.environ.get('FIRST_BASKET_CACHE',str(Path.home()/'.cache'/'first-basket')))
        self.cache.mkdir(parents=True,exist_ok=True)
    def get(self,path):
        key=self.cache/(sha256(path.encode()).hexdigest()+'.json.gz')
        if path.startswith('summary?') and key.exists():
            try:
                with gzip.open(key,'rt') as f:return json.load(f)
            except (OSError,ValueError):pass
        d=fetch(path)
        if path.startswith('summary?') and d.get('header',{}).get('competitions',[{}])[0].get('status',{}).get('type',{}).get('completed'):
            with gzip.open(key,'wt') as f:json.dump(d,f)
        return d

def game_rows(e,year,client):
    hist={};meta={};selected={};flags=[]
    current=client.get('summary?event='+e['id'])
    for c in competitors(e):
        tid=team_id(c)
        schedule=client.get(f'teams/{tid}/schedule?season={year}&seasontype=2')
        events=[x for x in schedule.get('events',[]) if int(x.get('season',{}).get('year',year))==year and int(x.get('seasonType',{}).get('type',2))==2]
        games=[]
        for old in prior_events(events,utc(e['date']),20):
            try:games.append(parse_game(client.get('summary?event='+old['id'])))
            except Exception:continue
        if not games:raise ValueError('Missing historical PBP')
        hist[tid]=games
        rd=client.get(f'teams/{tid}/roster')
        meta[tid]={str(a['id']):{'name':a['displayName'],'position':a.get('position',{}).get('abbreviation','?')} for a in rd.get('athletes',[])}
        confirmed=source_starters(current,e['id'],tid,meta[tid],e['date'])
        selected[tid]=confirmed or sorted(p for p in games[0]['starters'][tid] if p in meta[tid])
        if len(selected[tid])!=5:raise ValueError('Incomplete projected lineup')
        flags.append(bool(confirmed))
    rows,_=forecast(hist,selected,meta)
    abbr={team_id(c):c['team']['abbreviation'] for c in competitors(e)}
    for r in rows:
        r.update({'Game ID':str(e['id']),'Matchup':e['shortName'],'Team':abbr[r['Team ID']],
                  'Tip UTC':e['date'],'Basis':'Field goal','Lineup':'Source confirmed' if all(flags) else 'Projected',
                  'Lineup source':'ESPN current-game flags' if all(flags) else 'Latest historical starters; awaiting ESPN',
                  'Listed American odds':None})
    return rows

def write(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,indent=2,allow_nan=False)+'\n')

def run():
    now=datetime.now(timezone.utc);client=Client();DATA.mkdir(exist_ok=True)
    index_path=DATA/'index.json'
    index=json.loads(index_path.read_text()) if index_path.exists() else {'records':[]}
    entries={x['path']:x for x in index.get('records',[])};errors=[];rows=[];seen=set()
    # Date labels follow Eastern time; include tomorrow for midnight boundaries.
    for date in [now.astimezone(ET).date(),(now.astimezone(ET)+timedelta(days=1)).date()]:
        try:board=client.get('scoreboard?dates='+date.strftime('%Y%m%d')+'&limit=100')
        except Exception as ex:errors.append(f'Scoreboard: {type(ex).__name__}');continue
        year=int(board.get('season',{}).get('year',date.year+(date.month>=7)))
        events=[]
        for e in board.get('events',[]):
            if e['id'] in seen:continue
            if e['status']['type']['state']=='pre' and now<utc(e['date'])<=now+timedelta(hours=2):
                seen.add(e['id']);events.append(e)
        def load(e):
            try:return game_rows(e,year,client),None
            except Exception as ex:return [],f"{e['id']}: {type(ex).__name__}: {ex}"
        with ThreadPoolExecutor(max_workers=2) as pool:
            for got,error in pool.map(load,events):
                rows.extend(got)
                if error:errors.append(error)
    captured=datetime.now(timezone.utc)
    rows.sort(key=lambda r:(-r['Game first %'],r['Game ID'],r['Player ID']))
    chosen={(r['Game ID'],r['Player ID']) for r in select_shortlist(rows,captured)}
    team_counts={}
    for i,r in enumerate(rows,1):
        k=(r['Game ID'],r['Team ID']);team_counts[k]=team_counts.get(k,0)+1
        r.update({'Overall Rank':i,'Team Rank':team_counts[k],'Shortlisted':(r['Game ID'],r['Player ID']) in chosen,'Lineup checked at':captured.isoformat()})
    for gid in sorted({r['Game ID'] for r in rows}):
        subset=[r for r in rows if r['Game ID']==gid]
        date=utc(subset[0]['Tip UTC']).astimezone(ET).date().isoformat()
        relative=f'pregame/{date}-{gid}.json';path=DATA/relative
        previous=json.loads(path.read_text()) if path.exists() else None
        candidate=snapshot(subset,'Field goal',captured,'Automatic archive: games within two hours of tip; 20 current-season games maximum')
        candidate['settings']={'games':20,'previous_season':False}
        kept=keep_pregame(previous,candidate,captured)
        if kept is not None and kept!=previous:write(path,kept)
        if kept is not None:entries[relative]={'path':relative,'date':date,'game_id':gid,'matchup':subset[0]['Matchup'],'created_at':kept['created_at'],'settled':bool(kept.get('settled_at'))}
    for relative,entry in entries.items():
        if entry.get('settled'):continue
        path=DATA/relative
        if not path.exists():continue
        record=json.loads(path.read_text())
        if now<=utc(record['rows'][0]['Tip UTC']):continue
        try:
            d=client.get('summary?event='+entry['game_id'])
            if not d['header']['competitions'][0]['status']['type'].get('completed'):continue
            write(path,settle(record,d,datetime.now(timezone.utc)));entry['settled']=True
        except Exception as ex:errors.append(f"Settlement {entry['game_id']}: {type(ex).__name__}")
    # Heartbeat is hourly, avoiding a repository commit on every idle poll.
    write(index_path,{'checked_hour_utc':now.replace(minute=0,second=0,microsecond=0).isoformat(),
                      'records':sorted(entries.values(),key=lambda r:(r['date'],r['game_id']),reverse=True),'errors':errors})
    print(f'Archive: {len(rows)} current rows, {len(entries)} saved game records, {len(errors)} source errors')
    if errors:print('\n'.join(errors))

if __name__=='__main__':run()
