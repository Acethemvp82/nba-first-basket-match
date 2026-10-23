from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json
import pandas as pd
import streamlit as st
from model import fetch, competitors, team_id, utc, prior_events, parse_game, forecast, implied, VERSION

ET = ZoneInfo('America/New_York')
st.set_page_config(page_title='First Basket Match', page_icon='🏀', layout='wide')
st.markdown('''<style>.block-container{padding-top:2rem}h1{letter-spacing:-1px}
[data-testid="stMetric"]{background:#172236;padding:16px;border-radius:12px}
div[data-testid="stCaptionContainer"]{color:#a9b8cc}</style>''', unsafe_allow_html=True)
st.caption('ACE THE MVP  /  NBA RESEARCH')
st.title('First Basket Match')
st.write('Opening opportunity. First scoring touch. One board.')
st.caption('Experimental model • rankings and model estimates are not validated betting edges.')

@st.cache_data(ttl=300, show_spinner=False)
def live(path): return fetch(path)

@st.cache_data(ttl=86400, show_spinner=False)
def historic(gid):
    d = fetch('summary?event='+gid)
    if not d.get('header',{}).get('competitions',[{}])[0].get('status',{}).get('type',{}).get('completed'):
        raise ValueError('Game is not final')
    return d

@st.cache_data(ttl=1800, show_spinner=False)
def history(tid, year, cutoff_string, n, prior, basis):
    events = {}
    for season in ([year,year-1] if prior else [year]):
        d = live(f'teams/{tid}/schedule?season={season}&seasontype=2')
        for e in d.get('events',[]):
            if int(e.get('season',{}).get('year', season)) == season and int(e.get('seasonType',{}).get('type',2)) == 2:
                events[e['id']] = e
    chosen = prior_events(list(events.values()), utc(cutoff_string), n)
    output, errors = [], []
    # Each team loads serially; teams share at most four workers in the UI.
    for e in chosen:
        try:
            d = historic(e['id'])
            parsed = parse_game(d, basis)
            if tid not in parsed['first']: raise ValueError('Team missing from PBP')
            output.append(parsed)
        except Exception as ex: errors.append(f"{e['id']}: {type(ex).__name__}: {ex}")
    return output, errors

with st.sidebar:
    st.header('Board settings')
    date = st.date_input('Slate date (Eastern)', datetime.now(ET).date())
    market = st.radio('Settlement basis', ['Field goal', 'First points'], help='Field goal excludes free throws. First points includes them. Match your sportsbook rules.')
    n = st.slider('Recent regular-season games / team', 5, 30, 20)
    prior = st.checkbox('Include previous season', value=False, help='Can add sample size early in the season, but includes old roles and rosters. No preseason or playoff games are used.')
    st.caption('Free ESPN feed. Five-minute slate cache; final play-by-play cached for one day.')
    if st.button('Refresh data', width='stretch'):
        st.cache_data.clear(); st.rerun()
    st.caption('Refresh is manual. This version does not run in the background.')

try:
    slate = live('scoreboard?dates='+date.strftime('%Y%m%d')+'&limit=100')
except Exception as ex:
    st.error(f'Slate unavailable: {ex}. No rankings have been fabricated.'); st.stop()
events = slate.get('events', [])
if not events:
    st.info('No NBA games returned for this date. Choose another date.'); st.stop()

st.subheader('Game schedule')
schedule = []
for e in events:
    status = e['status']['type']
    schedule.append({'Matchup':e['shortName'], 'Tip (ET)':utc(e['date']).astimezone(ET).strftime('%I:%M %p'),
                     'Status':status.get('detail',status.get('description'))})
st.dataframe(pd.DataFrame(schedule), hide_index=True, width='stretch')
pregame = [e for e in events if e['status']['type']['state'] == 'pre']
year = int(slate.get('season',{}).get('year', date.year+(date.month>=7)))

board_tab, tracking_tab, method_tab = st.tabs(['Prediction board','Results tracker','How it works'])
with board_tab:
    st.caption('Game first = first scorer in the entire game. Team first = first scorer for that team. Both follow your selected settlement basis.')
    if not pregame:
        st.info('All games have started or finished. Pregame rankings are closed. Use Results tracker to settle a saved board.')
    else:
        game_options = {e['id']: e['shortName'] for e in pregame}
        chosen_ids = st.multiselect('Matchups to load', list(game_options), default=list(game_options)[:1], format_func=game_options.get)
        st.caption('Load one game for a faster view, or select the full slate for overall ranks.')
        if st.button('Load / update prediction board', type='primary'):
            st.session_state['loaded'] = (str(date),market,n,prior,chosen_ids)
        signature = (str(date),market,n,prior,chosen_ids)
        if st.session_state.get('loaded') == signature and chosen_ids:
            active = [e for e in pregame if e['id'] in chosen_ids]
            jobs = {}
            with st.spinner('Loading real opening possessions and historical starters…'):
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for e in active:
                        for c in competitors(e):
                            tid = team_id(c)
                            jobs[pool.submit(history,tid,year,e['date'],n,prior,market)] = (e['id'],tid)
                    loaded = {}
                    for future in as_completed(jobs):
                        key=jobs[future]
                        try: loaded[key]=future.result()
                        except Exception as ex: loaded[key]=([], [str(ex)])
            all_rows, residuals, issues = [], [], []
            for e in active:
                gid = e['id']; hist = {}; selected = {}; metadata = {}; confirms=[]
                st.subheader(e['shortName'])
                cs = competitors(e)
                if any(not loaded[(gid,team_id(c))][0] for c in cs):
                    st.warning('Both teams need valid completed regular-season games. This matchup is withheld. Try the previous-season option if appropriate.')
                    for c in cs: issues.extend(loaded[(gid,team_id(c))][1])
                    continue
                with st.expander('Review projected starters — confirm before using', expanded=True):
                    columns=st.columns(2)
                    for col,c in zip(columns,cs):
                        tid=team_id(c); games, errs=loaded[(gid,tid)]; hist[tid]=games; issues.extend(errs)
                        latest = games[0]
                        # Current roster is the candidate pool; historical boxscore only provides projection.
                        try:
                            rd=live(f'teams/{tid}/roster')
                            roster={str(a['id']):{'name':a['displayName'],'position':a.get('position',{}).get('abbreviation','?')} for a in rd.get('athletes',[])}
                        except Exception as ex:
                            issues.append(f'Roster {tid}: {ex}'); roster={}
                        if not roster:
                            col.error('Current roster unavailable; matchup withheld.'); continue
                        metadata[tid]=roster
                        default=[p for p in latest['starters'][tid] if p in roster]
                        default.sort(key=lambda p:roster[p]['name'])
                        with col:
                            st.write(c['team']['displayName'])
                            st.caption(f"{len(games)} valid games • latest {utc(latest['date']).astimezone(ET):%b %d, %Y}. No automatic lineup/injury verification.")
                            selected[tid]=st.multiselect('Select five starters', sorted(roster,key=lambda p:roster[p]['name']), default=default, max_selections=5,
                                                       format_func=lambda p,r=roster:r[p]['name'], key=f'lineup-{date}-{gid}-{tid}')
                            confirms.append(st.checkbox('I verified these five starters and availability',key=f'confirm-{date}-{gid}-{tid}'))
                if len(metadata)!=2 or any(len(selected.get(team_id(c),[]))!=5 for c in cs):
                    st.warning('Select five players for both teams to calculate.');continue
                # Cached input can be open across tip: never export a prediction after tip.
                if datetime.now(ET) >= utc(e['date']):
                    st.info('Scheduled tip reached; pregame board withheld.'); continue
                rows,res=forecast(hist,selected,metadata)
                abbreviations={team_id(c):c['team']['abbreviation'] for c in cs}
                for row in rows:
                    row.update({'Game ID':gid,'Matchup':e['shortName'],'Team':abbreviations[row['Team ID']],
                                'Lineup':'User confirmed' if all(confirms) else 'Projected',
                                'Basis':market,'Tip UTC':e['date']})
                all_rows.extend(rows)
                residuals.append({'Matchup':e['shortName'],'Other players / unlisted first scorer %':round(100*sum(res.values()),1)})
            if issues:
                with st.expander(f'Data coverage / skipped fetches ({len(issues)})'):
                    st.write(issues)
            if all_rows:
                df=pd.DataFrame(all_rows).sort_values('Game first %',ascending=False).reset_index(drop=True)
                df.insert(0,'Overall Rank',range(1,len(df)+1))
                df.insert(1,'Team Rank',df.groupby(['Game ID','Team ID'])['Game first %'].rank(method='first',ascending=False).astype(int))
                df['Research tier']=df.apply(lambda r:'Limited data' if r['Sample status']=='Limited' else ('Top team candidate' if r['Team Rank']<=2 else 'Watch'),axis=1)
                a,b,c=st.columns(3)
                a.metric('Players ranked',len(df));b.metric('Games loaded',df['Game ID'].nunique());c.metric('Lineups', 'Confirmed by you' if (df['Lineup']=='User confirmed').all() else 'Check starters')
                filt=st.multiselect('Team filter',sorted(df['Team'].unique()))
                shown=df[df['Team'].isin(filt)] if filt else df
                columns=['Overall Rank','Team Rank','Player','Team','Position','Game first %','Team first %','Research tier','Opening shot %','Early FG %','Early FGA','Team scores first %','Team first hits','Starts','Sample','Lineup']
                def colors(r):
                    bg='#153e34' if r['Research tier']=='Top team candidate' else '#493b19' if r['Research tier']=='Limited data' else '#172236'
                    return [f'background-color:{bg};color:#eef4fa' for _ in r]
                st.dataframe(shown[columns].style.apply(colors,axis=1).format({x:'{:.1f}' for x in ['Game first %','Team first %','Opening shot %','Early FG %','Team scores first %']},na_rep='—'),hide_index=True,width='stretch')
                st.caption('Green = top two on a team with ≥15 team games and ≥8 player starts. Amber = limited sample. Colors show research priority, not proven profit. Overall ranks cover loaded matchups only.')
                st.dataframe(pd.DataFrame(residuals),hide_index=True,width='stretch')
                st.caption('Unlisted-player probability is retained, so the ten listed players are not forced to total 100%.')
                st.subheader('Compare a sportsbook price')
                lookup={i:f"{r['Player']} · {r['Team']}" for i,r in df.iterrows()}
                idx=st.selectbox('Player',list(lookup),format_func=lookup.get)
                odds_market=st.selectbox('Odds market',['Game first','Team first'])
                price=st.number_input('American odds',value=600,step=25)
                if abs(price)>=100:
                    r=df.loc[idx];p=float(r[odds_market+' %'])/100;ip=implied(price)
                    decimal=1+price/100 if price>0 else 1+100/abs(price)
                    a,b,c=st.columns(3);a.metric('Model estimate',f'{p:.1%}');b.metric('Price break-even',f'{ip:.1%}');c.metric('Model EV per $1',f'${p*decimal-1:+.2f}')
                    st.caption('Uncalibrated model comparison; includes bookmaker margin in the price. A positive estimate alone is not a verified edge.')
                else: st.warning('Enter valid American odds: +100 or greater, or -100 or lower.')
                now=datetime.now(ET).isoformat()
                clean_rows=df.astype(object).where(pd.notna(df),None).to_dict('records')
                snap={'version':VERSION,'created_at':now,'basis':market,'settings':{'games':n,'previous_season':prior},'rows':clean_rows}
                can_save=all(datetime.now(ET)<utc(t) for t in df['Tip UTC'])
                st.download_button('Save pregame snapshot for tracking',json.dumps(snap,indent=2,allow_nan=False,default=str),file_name=f'first-basket-{date}.json',mime='application/json',disabled=not can_save)
                st.download_button('Download board CSV',df.to_csv(index=False),file_name=f'first-basket-{date}.csv',mime='text/csv',disabled=not can_save)
                st.caption('Save before tip. Snapshots remain on your device; Streamlit disk storage is not treated as permanent tracking.')

with tracking_tab:
    st.subheader('Settle a saved pregame board')
    st.write('Upload your saved JSON snapshot after games finish. The tracker preserves the pregame ranks and estimates.')
    upload=st.file_uploader('Pregame snapshot',type='json')
    if upload and st.button('Check final results'):
        try:
            snap=json.load(upload)
            if snap.get('version')!=VERSION or snap.get('basis') not in ['Field goal','First points']: raise ValueError('Unsupported snapshot')
            saved_at=utc(snap['created_at']); saved=snap['rows']; result=[]
            if not saved: raise ValueError('Empty snapshot')
            for gid in dict.fromkeys(str(r['Game ID']) for r in saved):
                subset=[r for r in saved if str(r['Game ID'])==gid]
                if any(saved_at>=utc(r['Tip UTC']) for r in subset): raise ValueError('Snapshot was not created before scheduled tip')
                try: outcome=parse_game(historic(gid),snap['basis'])
                except Exception as ex:
                    st.info(f'{subset[0]["Matchup"]}: unavailable or not final ({ex})');continue
                for r in subset:
                    tid=str(r['Team ID']);pid=str(r['Player ID'])
                    result.append({**r,'Game first hit':outcome['global_first']==(tid,pid), 'Team first hit':outcome['first'].get(tid)==pid})
            if result:
                settled=pd.DataFrame(result)
                st.dataframe(settled[['Overall Rank','Team Rank','Player','Team','Game first %','Team first %','Game first hit','Team first hit']],hide_index=True,width='stretch')
                top=settled.sort_values('Game first %',ascending=False).drop_duplicates('Game ID')
                st.metric('Game top-pick hits',f"{int(top['Game first hit'].sum())} / {len(top)}")
                st.caption('Only this uploaded snapshot. No historical accuracy or ROI claim is made. Uploaded snapshots are editable and not an audited record.')
                st.download_button('Download settled results',settled.to_csv(index=False),'first-basket-results.csv','text/csv')
        except Exception as ex: st.error(f'Cannot settle this snapshot: {ex}')

with method_tab:
    st.markdown('''### Reading the board
**Game first %** estimates a player scoring first in the entire game. **Team first %** estimates that player scoring first for his own team. Choose field-goal or first-points settlement to match your book; first points includes free throws.

**Opening shot %** is the share of sampled team games in which the player took that team's first field-goal attempt. **Early FG %** is actual shooting in the opening three minutes of the first quarter. **Starts** counts starts within that team's sample, not career starts.

### Transparent v1 formula
The team's game-first rate is shrunk toward 50% with ten prior games. Its matchup chance averages that rate and the opponent's failure-to-score-first rate.

Within each team, the model uses six buckets: the five selected players plus all other players. Each bucket receives one prior first-scoring event and one prior opening attempt. A player's team-first estimate is **60% smoothed first-scoring share + 40% normalized opening-shot share × smoothed early FG conversion**. Conversion uses a 45% prior with ten attempts. Game-first estimate = team-first estimate × team game-first chance.

These are starting assumptions, not fitted or calibrated coefficients. First-points mode uses first-points history in its 60% component; its shot component still models field goals and does not separately model early foul rates.

### Data and limitations
Only completed regular-season games strictly before the target tip are sampled. No preseason or playoff games are mixed in. Previous-season data is optional and can contain stale roles. Skipped or incomplete PBP is reported; it is never replaced with made-up stats. Missing teams withhold the matchup.

Current rosters come from ESPN. Starter defaults are copied from the latest sampled game and intersected with that roster. Confirm all five starters and injuries yourself. ESPN may report grouped G/F positions; this app does not invent PG/SG/SF/PF labels.

No verified jump-ball win feed, automatic injury adjustment, sportsbook odds feed, defense-versus-position score, or backtested profitability is included. Repeated saved pregame forecasts and settled results are needed before assessing calibration. A high rank is a relative research signal and does not mean a likely winning bet.

### Sources
[ESPN NBA](https://www.espn.com/nba/) supplies the public scoreboard, team schedule, roster, boxscore and play-by-play endpoints. These endpoints are unofficial, can change, and carry no uptime guarantee. This model is independent of ESPN and the NBA.
''')
