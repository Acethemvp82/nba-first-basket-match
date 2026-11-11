from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json
from pathlib import Path
import pandas as pd
import streamlit as st
import importlib
import model as _model
# Streamlit can retain an already-imported module during a source update.
if getattr(_model, 'VERSION', None) != '1.6.0':
    importlib.reload(_model)
from model import fetch, competitors, team_id, utc, prior_events, parse_game, forecast, implied, VERSION, opening_context, select_shortlist, SHORTLIST_RULES, source_starters, tip_conversion, jumper_records, shot_style, position_summary, simulate_first_basket
import archive as _archive
if not hasattr(_archive, 'live_first_basket'):
    importlib.reload(_archive)
from archive import snapshot as make_snapshot, keep_pregame, settle, tracking_summary, live_first_basket

ET = ZoneInfo('America/New_York')
st.set_page_config(page_title='First Basket Match', page_icon='🏀', layout='wide')
st.markdown('''<style>.block-container{padding-top:2rem}h1{letter-spacing:-1px}
[data-testid="stMetric"]{background:#172236;padding:16px;border-radius:12px}
div[data-testid="stCaptionContainer"]{color:#a9b8cc}
.stTabs [role="tab"][aria-selected="true"]{color:#bfdbfe}
</style>''', unsafe_allow_html=True)
st.caption('ACE THE MVP  /  NBA RESEARCH')
st.title('First Basket Match')
st.write('Opening opportunity. First scoring touch. One board.')
st.caption('Experimental model • rankings and model estimates are not validated betting edges.')

def priority_colors(row):
    background={'Top game candidate':'#174c3c','Limited data':'#4a391f',
                'Awaiting starters':'#303946'}.get(row['Research tier'],'#172236')
    return [f'background-color:{background};color:#f3f6fb' for _ in row]

@st.cache_data(ttl=300, show_spinner=False)
def live(path): return fetch(path)

@st.cache_data(ttl=45, show_spinner=False)
def game_lineups(gid):
    return fetch('summary?event='+gid), datetime.now(ET).isoformat()

@st.cache_data(ttl=60, show_spinner=False)
def background_records():
    data=Path(__file__).resolve().parent/'data'
    index_path=data/'index.json'
    if not index_path.exists():return {},{}
    index=json.loads(index_path.read_text());records={}
    for entry in index.get('records',[])[:100]:
        path=(data/entry['path']).resolve()
        if not path.is_relative_to(data.resolve()) or not path.is_file():continue
        records[entry['path']]=json.loads(path.read_text())
    return records,index

@st.cache_data(ttl=86400, show_spinner=False)
def historic(gid):
    d = fetch('summary?event='+gid)
    if not d.get('header',{}).get('competitions',[{}])[0].get('status',{}).get('type',{}).get('completed'):
        raise ValueError('Game is not final')
    return d

@st.cache_data(ttl=1800, show_spinner=False)
def history(tid, year, cutoff_string, n, prior, basis, model_version):
    events = {}
    for season in ([year,year-1] if prior else [year]):
        d = live(f'teams/{tid}/schedule?season={season}&seasontype=2')
        for e in d.get('events',[]):
            if int(e.get('season',{}).get('year', season)) == season and int(e.get('seasonType',{}).get('type',2)) == 2:
                events[e['id']] = e
    chosen = prior_events(list(events.values()), utc(cutoff_string), n)
    output, errors = list(), list()
    # Each team loads serially; teams share at most four workers in the UI.
    for e in chosen:
        try:
            d = historic(e['id'])
            parsed = parse_game(d, basis)
            if tid not in parsed['first']: raise ValueError('Team missing from PBP')
            output.append(parsed)
        except Exception as ex: errors.append(f"{e['id']}: {type(ex).__name__}: {ex}")
    return output, errors

def load_matchup_history(events,year,n,prior,market):
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(history,team_id(c),year,e['date'],n,prior,market,VERSION):
                (e['id'],team_id(c)) for e in events for c in competitors(e)}
        loaded={}
        for future in as_completed(jobs):
            try:loaded[jobs[future]]=future.result()
            except Exception as ex:loaded[jobs[future]]=([],[str(ex)])
    return loaded

def resolve_lineup(event,tid,games,summary):
    data=live(f'teams/{tid}/roster')
    roster={str(a['id']):{'name':a['displayName'],'position':a.get('position',{}).get('abbreviation','?')}
            for a in data.get('athletes',[])}
    if not roster:raise ValueError('Current roster unavailable')
    confirmed=source_starters(summary,event['id'],tid,roster,event['date'])
    projected=sorted((p for p in games[0]['starters'][tid] if p in roster),key=lambda p:roster[p]['name'])
    return roster,confirmed,confirmed or projected

def add_matchup_labels(rows,event,market,confirmed,checked_at):
    teams={team_id(c):c['team']['abbreviation'] for c in competitors(event)}
    for row in rows:
        row.update({'Game ID':event['id'],'Matchup':event['shortName'],'Team':teams[row['Team ID']],
                    'Lineup':'Source confirmed' if confirmed else 'Projected',
                    'Lineup source':'ESPN current-game starter flags' if confirmed else 'Latest historical starters; awaiting ESPN',
                    'Lineup checked at':checked_at,'Basis':market,'Tip UTC':event['date']})

def label_priority(df):
    leaders=set()
    now=datetime.now(ET)
    for gid,group in df.groupby('Game ID',sort=False):
        eligible=select_shortlist(group.to_dict('records'),now)
        if eligible:leaders.add((str(gid),str(eligible[0]['Player ID'])))
    def tier(r):
        if r['Lineup']!='Source confirmed':return 'Awaiting starters'
        if min(r['Sample'],r['Opponent sample'])<15 or r['Starts']<8:return 'Limited data'
        return 'Top game candidate' if (str(r['Game ID']),str(r['Player ID'])) in leaders else 'Research'
    df['Research tier']=df.apply(tier,axis=1)

def render_simulator(pregame,date,year,n,prior,market):
    st.subheader('First basket simulator')
    st.caption('Add one or more games directly from this slate. Each matchup uses the history setting in the sidebar and gets its own results.')
    now=datetime.now(ET)
    available={str(e['id']):e for e in pregame if utc(e['date'])>now}
    if not available:
        st.info('No pregame matchups are available to simulate.')
        return
    chosen=st.multiselect('Simulator matchups',list(available),format_func=lambda gid:available[gid]['shortName'],
                          key=f'sim-matchups-{date}',placeholder='Add matchups')
    trials=st.selectbox('Simulated games per matchup',[10000,50000,100000],format_func=lambda v:f'{v:,}',key='sim-trials')
    selected_games=[available[gid] for gid in chosen if gid in available]
    if not selected_games:
        st.info('Select at least one matchup to see simulation results.')
        return
    with st.spinner('Loading data for the selected matchups…'):
        loaded=load_matchup_history(selected_games,year,n,prior,market)
    simulations=[]
    for e in selected_games:
        gid=e['id']
        st.markdown(f"**{e['shortName']}**")
        hist={team_id(c):loaded[(gid,team_id(c))][0] for c in competitors(e)}
        if any(not games for games in hist.values()):
            st.warning('This matchup needs valid completed games for both teams.')
            continue
        try:current,checked_at=game_lineups(gid)
        except Exception:current,checked_at={},None
        try:
            metadata,starters,flags={},{},[]
            for tid,games in hist.items():
                metadata[tid],confirmed,starters[tid]=resolve_lineup(e,tid,games,current)
                flags.append(bool(confirmed))
            if any(len(players)!=5 for players in starters.values()):
                st.warning('Five starters are not yet available for both teams.')
                continue
            rows,_=forecast(hist,starters,metadata)
        except Exception:
            st.warning('Current data is incomplete; simulation unavailable for this matchup.')
            continue
        if datetime.now(ET)>=utc(e['date']):
            st.info('Scheduled tip reached. Check Results tracker for this game.')
            continue
        add_matchup_labels(rows,e,market,all(flags),checked_at)
        frame=pd.DataFrame(rows)
        label_priority(frame)
        seed=f'first-basket:{gid}'
        sim=pd.DataFrame(simulate_first_basket(frame.to_dict('records'),trials=trials,seed=seed))
        lineup=rows[0]['Lineup']
        st.caption(f'{market} • {trials:,} simulated games • {lineup} starters')
        st.dataframe(sim.style.apply(priority_colors,axis=1).format({'Model %':'{:.1f}','Simulated %':'{:.1f}'}),hide_index=True,width='stretch')
        simulations.append(sim.assign(**{'Game ID':gid,'Matchup':e['shortName'],'Basis':market,'Simulations':trials,'Seed':seed,'Lineup':lineup}))
    if simulations:
        st.caption('Each matchup keeps its own unlisted-player chance. More runs reduce sampling noise; they do not change model estimates.')
        export=pd.concat(simulations,ignore_index=True)
        st.download_button('Download simulation CSV',export.to_csv(index=False),file_name=f'first-basket-simulation-{date}.csv',mime='text/csv')

with st.sidebar:
    st.header('Board settings')
    date = st.date_input('Slate date (Eastern)', datetime.now(ET).date())
    market = 'First points'
    st.caption('First Basket: first points scored, including free throws.')
    n = st.select_slider('Recent regular-season games / team', options=[5, 10, 15], value=15, format_func=lambda games: f'Last {games}')
    prior = st.checkbox('Include previous season', value=False, help='Can add sample size early in the season, but includes old roles and rosters. No preseason or playoff games are used.')
    st.caption('Free ESPN feed. Five-minute slate cache; final play-by-play cached for one day.')
    if st.button('Refresh data', width='stretch'):
        st.cache_data.clear(); st.rerun()
    st.caption('While open, starters recheck every 60 seconds. The automatic pregame archive runs separately.')

@st.fragment(run_every=60)
def render_model():
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

    board_tab, sim_tab, tracking_tab, method_tab = st.tabs(['Prediction board','Simulator','Results tracker','How it works'])
    with board_tab:
        st.caption('Game first = first scorer in the entire game. Team first = first scorer for that team. Both include free throws (First points).')
        if not pregame:
            st.info('All games have started or finished. Pregame rankings are closed. Use Results tracker to settle a saved board.')
        else:
            shortlist_slot=st.container()
            game_options = {e['id']: e['shortName'] for e in pregame}
            chosen_ids = st.multiselect('Matchups to load', list(game_options), default=list(game_options)[:1], format_func=game_options.get)
            st.caption('Load one game for a faster view, or select the full slate for overall ranks.')
            if st.button('Load / update prediction board', type='primary'):
                st.session_state['loaded'] = (str(date),market,n,prior,chosen_ids)
            signature = (str(date),market,n,prior,chosen_ids)
            if st.session_state.get('loaded') == signature and chosen_ids:
                active = [e for e in pregame if e['id'] in chosen_ids]
                with st.spinner('Loading real opening possessions and historical starters…'):
                    loaded = load_matchup_history(active,year,n,prior,market)
                all_rows, residuals, issues = [], [], []
                for e in active:
                    gid = e['id']; hist = {}; selected = {}; metadata = {}; confirms=[]
                    try: current_summary, checked_at=game_lineups(gid)
                    except Exception as ex:
                        current_summary={};checked_at=None
                        issues.append(f'Starter source {gid}: {ex}')
                    st.subheader(e['shortName'])
                    cs = competitors(e)
                    if any(not loaded[(gid,team_id(c))][0] for c in cs):
                        st.warning('Both teams need valid completed regular-season games. This matchup is withheld. Try the previous-season option if appropriate.')
                        for c in cs: issues.extend(loaded[(gid,team_id(c))][1])
                        continue
                    with st.expander('Starting lineups — automatic source check', expanded=True):
                        columns=st.columns(2)
                        for col,c in zip(columns,cs):
                            tid=team_id(c); games, errs=loaded[(gid,tid)]; hist[tid]=games; issues.extend(errs)
                            latest = games[0]
                            try:
                                roster,confirmed,players=resolve_lineup(e,tid,games,current_summary)
                            except Exception as ex:
                                issues.append(f'Roster {tid}: {ex}')
                                col.error('Current roster unavailable; matchup withheld.'); continue
                            metadata[tid]=roster
                            selected[tid]=players
                            confirms.append(bool(confirmed))
                            with col:
                                st.write(c['team']['displayName'])
                                st.caption(f"{len(games)} valid games • latest {utc(latest['date']).astimezone(ET):%b %d, %Y}.")
                                if confirmed: st.success('Source confirmed — ESPN game feed')
                                else: st.info('Projected — awaiting source confirmation')
                                st.write(' · '.join(roster[p]['name'] for p in selected[tid]) or 'No projected lineup available')
                                if checked_at: st.caption(f"ESPN checked {utc(checked_at).astimezone(ET):%I:%M:%S %p ET}")
                                st.caption('Starter status updates automatically while this page is open. Projected names come from the latest sampled game, not a confirmed lineup.')
                    if len(metadata)!=2 or any(len(selected.get(team_id(c),[]))!=5 for c in cs):
                        st.warning('Five starters are not yet available for both teams. Waiting for lineup data.');continue
                    # Cached input can be open across tip: never export a prediction after tip.
                    if datetime.now(ET) >= utc(e['date']):
                        st.info('Scheduled tip reached; pregame board withheld.'); continue
                    rows,res=forecast(hist,selected,metadata)
                    abbreviations={team_id(c):c['team']['abbreviation'] for c in cs}
                    with st.expander('Opening matchup — tip-off, first shots and first baskets'):
                        context=opening_context(hist)
                        detail=[]
                        for tid,ctx in context.items():
                            chance=ctx['tip_chance']
                            tip_text=f"{chance:.1%}" if chance is not None else 'Insufficient tip data'
                            st.caption(f"{abbreviations[tid]} tip-win estimate: {tip_text} • identified tips: {ctx['tip_n']} own / {ctx['opp_tip_n']} opponent. Team-history estimate, not a confirmed jumper matchup. Tip estimate does not change the scoring ranks.")
                            conversion=tip_conversion(hist[tid],tid)
                            fg_text=f"{conversion['fg_hits']}/{conversion['fg_n']}" if conversion['fg_n'] else 'Unavailable'
                            pts_text=f"{conversion['points_hits']}/{conversion['points_n']}" if conversion['points_n'] else 'Unavailable'
                            st.write(f"{abbreviations[tid]} scored the game’s first FG after winning the tip: **{fg_text}**; first points: **{pts_text}**.")
                            st.caption('These denominators count identified tip wins, not all sampled games. Descriptive history only; small samples do not raise the score.')
                            jumpers=jumper_records(hist[tid],tid)
                            if jumpers:
                                st.dataframe(pd.DataFrame(jumpers).drop(columns='Player ID').style.format({'Tip win %':'{:.1f}'}),hide_index=True,width='stretch')
                                st.caption('Historical jumpers only. Today’s jumper has not been confirmed; these percentages are not a head-to-head prediction.')
                            st.caption(f"{abbreviations[tid]} matchup position summary: {position_summary(ctx['basket_allowed'])}")
                            for pos in ['G','F','C']:
                                detail.append({'Team':abbreviations[tid],'Position group':pos,
                                               'Team first-shot share %':100*ctx['own']['rates'][pos] if ctx['own']['rates'][pos] is not None else None,
                                               'Opponent allows first-shot share %':100*ctx['allowed']['rates'][pos] if ctx['allowed']['rates'][pos] is not None else None,
                                               'Team games':ctx['own']['n'],'Opponent shot games':ctx['allowed']['n'],
                                               'Opponent first FG allowed count':ctx['basket_allowed']['counts'].get(pos,0) if ctx['basket_allowed']['n'] else None,
                                               'Opponent first FG allowed %':100*ctx['basket_allowed']['counts'].get(pos,0)/ctx['basket_allowed']['n'] if ctx['basket_allowed']['n'] else None,
                                               'Opponent first FG games':ctx['basket_allowed']['n']})
                        st.dataframe(pd.DataFrame(detail).style.format({'Team first-shot share %':'{:.1f}','Opponent allows first-shot share %':'{:.1f}','Opponent first FG allowed %':'{:.1f}'},na_rep='—'),hide_index=True,width='stretch')
                        st.caption('First-shot shares are smoothed. First FG allowed counts and percentages are observed: the first made field goal by the opposing team in each sampled game, excluding free throws. This is separate from its first shot attempt. G = guards, F = forwards, C = centers. Each position signal needs at least five usable games before adjustment. Unknown or hybrid positions stay neutral.')
                    with st.expander('Opening shot styles — descriptive context'):
                        style_rows=[]
                        for row in rows:
                            tid=row['Team ID'];opp=next(t for t in hist if t!=tid)
                            style=shot_style(hist[tid],hist[opp],tid,opp,row['Player ID'])
                            style_rows.append({'Player':row['Player'],'Team':abbreviations[tid],
                                               'Opening style':style['style'] or 'Mixed / unavailable',
                                               'Player opening attempts':f"{style['player_count']}/{style['player_n']}" if style['style'] else '—',
                                               'Opponent first FG of that type':f"{style['allowed_count']}/{style['allowed_n']}" if style['style'] else '—',
                                               'Context':style['note']})
                        st.dataframe(pd.DataFrame(style_rows),hide_index=True,width='stretch')
                        st.caption('Layups, dunks, hooks, 2PT jumpers and 3PT shots remain separate. Unknown types are excluded. Ties show Mixed rather than inventing a preferred style. No new weight is applied.')
                    add_matchup_labels(rows,e,market,all(confirms),checked_at)
                    all_rows.extend(rows)
                    residuals.append({'Matchup':e['shortName'],'Other players / unlisted first scorer %':round(100*sum(res.values()),1)})
                if issues:
                    with st.expander(f'Data coverage / skipped fetches ({len(issues)})'):
                        st.write(issues)
                if all_rows:
                    df=pd.DataFrame(all_rows).sort_values('Game first %',ascending=False).reset_index(drop=True)
                    df.insert(0,'Overall Rank',range(1,len(df)+1))
                    df.insert(1,'Team Rank',df.groupby(['Game ID','Team ID'])['Game first %'].rank(method='first',ascending=False).astype(int))
                    label_priority(df)
                    picks=select_shortlist(df.to_dict('records'),datetime.now(ET))
                    shortlisted={(str(r['Game ID']),str(r['Player ID'])) for r in picks}
                    listed_odds={}
                    with shortlist_slot:
                        st.subheader('Slate shortlist')
                        st.caption(f'Up to four candidates from different games • {len(active)} of {len(pregame)} pregame matchups loaded • {market} settlement. Highest model game-first estimates among eligible players; prices do not affect selection.')
                        if picks:
                            preview=pd.DataFrame(picks)
                            preview.insert(0,'Pick',range(1,len(preview)+1))
                            short_table=st.empty()
                            with st.expander('Add current sportsbook odds (optional)'):
                                for r in picks:
                                    k=(str(r['Game ID']),str(r['Player ID']))
                                    price=st.number_input(f"American odds — {r['Player']} ({r['Team']})",value=None,step=25,
                                                          placeholder='Enter your current price',key=f"short-price-{date}-{market}-{k[0]}-{k[1]}")
                                    if price is not None:
                                        if abs(price)<100: st.warning(f"Enter +100 or greater, or -100 or lower for {r['Player']}.")
                                        else: listed_odds[k]=int(price)
                                st.caption('Enter live prices from your sportsbook. No odds feed is connected. Missing or invalid prices are saved as blank; no price is invented.')
                            preview['Your odds']=[f'{listed_odds[(str(r["Game ID"]),str(r["Player ID"]))]:+d}' if (str(r['Game ID']),str(r['Player ID'])) in listed_odds else '—' for r in picks]
                            short_table.dataframe(preview[['Pick','Player','Team','Matchup','Research tier','Game first %','Your odds','Why ranked','Sample','Starts']].style.apply(priority_colors,axis=1).format({'Game first %':'{:.1f}'}),hide_index=True,width='stretch')
                            if len(picks)<4: st.info(f'{len(picks)} eligible game(s). The model has not filled the remaining slots with weaker candidates.')
                        else:
                            st.info('No eligible shortlist yet. Starter status updates automatically; both teams need source-confirmed starters. Candidates also need five sampled games per team, three player starts, three early shot attempts, an opening-shot attempt and a team-first scoring hit in the sample.')
                        st.caption('Green: top eligible player in a game, source-confirmed starters, ≥15 sampled games per team and ≥8 player starts. Amber: limited history. Gray: awaiting starters. Color means research priority, not a guaranteed first basket.')
                    df['Shortlisted']=[(str(r['Game ID']),str(r['Player ID'])) in shortlisted for r in df.to_dict('records')]
                    df['Listed American odds']=[listed_odds.get((str(r['Game ID']),str(r['Player ID']))) for r in df.to_dict('records')]
                    a,b,c=st.columns(3)
                    a.metric('Players ranked',len(df));b.metric('Games loaded',df['Game ID'].nunique());c.metric('Lineups', 'Source confirmed' if (df['Lineup']=='Source confirmed').all() else 'Awaiting source')
                    filt=st.multiselect('Team filter',sorted(df['Team'].unique()))
                    shown=df[df['Team'].isin(filt)] if filt else df
                    columns=['Overall Rank','Team Rank','Player','Team','Position','Game first %','Team first %','Research tier','Why ranked','Shot matchup','Opening shot %','Early FG %','Early FGA','Team scores first %','Team first hits','Starts','Sample','Lineup']
                    st.dataframe(shown[columns].style.apply(priority_colors,axis=1).format({x:'{:.1f}' for x in ['Game first %','Team first %','Opening shot %','Early FG %','Team scores first %']},na_rep='—'),hide_index=True,width='stretch')
                    st.caption('Green = top eligible game candidate with adequate history. Amber = limited history. Gray = awaiting source-confirmed starters. Other rows stay navy. Labels explain each color; overall ranks cover loaded matchups only.')
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
                    snap={'version':VERSION,'created_at':now,'basis':market,'settings':{'games':n,'previous_season':prior},'shortlist_rules':SHORTLIST_RULES,'rows':clean_rows}
                    session_records=st.session_state.setdefault('automatic_pregame_records',{})
                    for game_id in df['Game ID'].unique():
                        subset=[r for r in clean_rows if r['Game ID']==game_id]
                        key=f'{market}:{game_id}'
                        candidate=make_snapshot(subset,market,utc(now),'This session: loaded matchups and current settings')
                        candidate['settings']=snap['settings']
                        kept=keep_pregame(session_records.get(key),candidate,datetime.now(ET))
                        if kept is not None:session_records[key]=kept
                    st.caption('Pregame board saved automatically for this open session. Background records use the default settings and are saved separately; downloads remain useful as your own copy.')
                    can_save=all(datetime.now(ET)<utc(t) for t in df['Tip UTC'])
                    st.download_button('Save pregame snapshot for tracking',json.dumps(snap,indent=2,allow_nan=False,default=str),file_name=f'first-basket-{date}.json',mime='application/json',disabled=not can_save)
                    st.download_button('Download board CSV',df.to_csv(index=False),file_name=f'first-basket-{date}.csv',mime='text/csv',disabled=not can_save)
                    st.caption('Save before tip. Snapshots remain on your device; Streamlit disk storage is not treated as permanent tracking.')

    with sim_tab:
        render_simulator(pregame,date,year,n,prior,market)

    with tracking_tab:
        st.subheader('Who scored first — live results')
        st.caption('First Basket includes free throws. This section shows the scorer as soon as ESPN supplies the opening scoring play; it does not wait for the final buzzer. Refreshes every 60 seconds while open, with up to 45 seconds of source cache.')
        started=[e for e in events if e.get('status',e.get('competitions',[{}])[0].get('status',{})).get('type',{}).get('state') in ['in','post']]
        def opening_result(e):
            try:
                summary,_=game_lineups(str(e['id']))
                return str(e['id']),live_first_basket(summary,str(e['id']))
            except Exception:return str(e['id']),None
        with ThreadPoolExecutor(max_workers=4) as pool:
            first_results=dict(pool.map(opening_result,started))
        actual_rows=[]
        for event in events:
            gid=str(event['id']);actual=first_results.get(gid)
            teams={team_id(c):c['team'].get('abbreviation','') for c in competitors(event)}
            actual_rows.append({'Matchup':event.get('shortName',gid),
                                'First Basket scorer':actual['Player'] if actual else 'Awaiting scoring feed' if gid in first_results else 'Not started',
                                'Team':teams.get(actual['Team ID'],'') if actual else '—',
                                'Method':actual['Method'] if actual else '—',
                                'Q1 clock':actual['Clock'] if actual else '—'})
        if actual_rows:st.dataframe(pd.DataFrame(actual_rows),hide_index=True,width='stretch')
        st.caption('Live names can be corrected by the source. Saved pregame ranks and official completed-game comparisons are shown below. A game can have a live scorer here even if no pregame forecast was saved.')
        st.subheader('Automatic pregame records')
        try: archived,archive_index=background_records()
        except Exception as ex:
            archived,archive_index={},{}
            st.warning(f'Background archive unavailable: {type(ex).__name__}')
        automatic={f'Background archive · {k}':r for k,r in archived.items()}
        automatic.update({f'This session · {k}':r for k,r in st.session_state.get('automatic_pregame_records',{}).items()})
        st.caption('Open-session records save your loaded board automatically. New background records use default settings, first-points settlement including free throws, and a scheduled capture within two hours of tip. Older records keep their original settlement basis. Session records may disappear when disconnected; the background archive is committed to the repository. Scheduling and data delays can cause missed captures.')
        if archive_index.get('checked_hour_utc'):
            st.caption(f"Background archive heartbeat: {utc(archive_index['checked_hour_utc']).astimezone(ET):%b %d, %I:%M %p ET} (hourly timestamp).")
        if archive_index.get('errors'):
            with st.expander('Background source coverage'):st.write(archive_index['errors'])
        st.subheader('First Basket results tracker')
        source=st.selectbox('Tracker records',['Background archive','This session'],index=0 if archived else 1)
        pool=archived if source=='Background archive' else st.session_state.get('automatic_pregame_records',{})
        tracker_basis=st.selectbox('Saved record type',['First points','Field goal'],format_func=lambda b:'First Basket (includes free throws)' if b=='First points' else 'Older field-goal records')
        summary=tracking_summary(list(pool.values()),tracker_basis)
        if summary:
            for r in summary:r['Date (ET)']=utc(r['Tip UTC']).astimezone(ET).date().isoformat()
            dates=sorted({r['Date (ET)'] for r in summary},reverse=True)
            chosen_date=st.selectbox('Results date',['All saved dates']+dates,index=1)
            shown=[r for r in summary if chosen_date=='All saved dates' or r['Date (ET)']==chosen_date]
            finals=[r for r in shown if r['Status']=='Final']
            short=[r for r in finals if r['Shortlist hit'] is not None]
            a,b,c,d=st.columns(4)
            a.metric('Games settled',len(finals))
            b.metric('Top-pick hits',f"{sum(r['Top pick hit'] for r in finals)} / {len(finals)}")
            c.metric('Top-3 coverage',f"{sum(r['Top 3 hit'] for r in finals)} / {len(finals)}")
            d.metric('Shortlist hits',f"{sum(r['Shortlist hit'] for r in short)} / {len(short)}")
            view=pd.DataFrame(shown)
            cols=['Date (ET)','Matchup','Status','First scorer','Pregame game rank','Pregame team rank','Pregame overall rank','Scorer model %','Top pick','Top pick hit','Top 3 hit','Shortlist pick','Shortlist hit','Lineup','History window']
            st.dataframe(view[cols].style.format({'Scorer model %':'{:.1f}','Pregame game rank':'{:.0f}','Pregame team rank':'{:.0f}','Pregame overall rank':'{:.0f}','History window':'{:.0f}'},na_rep='—'),hide_index=True,width='stretch')
            st.caption(f"{len(shown)-len(finals)} pending game(s). Top-3 coverage means the scorer was among three candidates, not three winning bets. Ranks and estimates come only from saved pregame records. Overall rank applies to that record’s captured slate. Projected lineups remain labeled. Games without an eligible shortlist pick are excluded from the shortlist denominator. Sources and settlement types are kept separate; latest pregame record per game is counted once.")
            st.download_button('Download results tracker CSV',view.to_csv(index=False),file_name='first-basket-tracker.csv',mime='text/csv')
        else:
            st.info('No saved records for this source and settlement yet. New First Basket forecasts save automatically near tip; completed games are settled by the background job. Older field-goal records can be viewed separately.')
        st.caption('Future background captures use Last 15 and include free throws. Your open-session records preserve your chosen Last 5 / 10 / 15 setting. Missed pregame captures cannot be reconstructed after the game. Pending results refresh while the page is open and the archive is available.')
        if automatic:
            def label(k):
                r=automatic[k];first=r['rows'][0]
                return f"{first.get('Matchup',first['Game ID'])} · {r['basis']} · {utc(r['created_at']).astimezone(ET):%b %d %I:%M %p} · {k.split(' · ')[0]}"
            record_key=st.selectbox('Saved pregame record',list(automatic),format_func=label)
            record=automatic[record_key]
            displayed=record
            if not record.get('settled_rows') and datetime.now(ET)>utc(record['rows'][0]['Tip UTC']):
                try:displayed=settle(record,live('summary?event='+str(record['rows'][0]['Game ID'])),datetime.now(ET))
                except Exception:st.info('Final result data is not available yet. The saved pregame ranks are preserved.')
            st.caption(f"Scope: {record.get('scope','Saved board')}. Lineups: {record['rows'][0].get('Lineup','Unknown')}. This is a prospective record; older results are never used to reconstruct its pregame ranks.")
            rd=pd.DataFrame(displayed.get('settled_rows',record['rows']))
            cols=[c for c in ['Overall Rank','Team Rank','Player','Team','Game first %','Shortlisted','Game first hit','Team first hit'] if c in rd.columns]
            st.dataframe(rd[cols],hide_index=True,width='stretch')
            if 'Game first hit' in rd.columns:
                st.metric('Saved game top-pick hit','Yes' if bool(rd.sort_values('Game first %',ascending=False).iloc[0]['Game first hit']) else 'No')
            st.download_button('Download automatic record',json.dumps(displayed,indent=2,allow_nan=False,default=str),file_name=f"first-basket-auto-{record['rows'][0]['Game ID']}.json",mime='application/json')
        else:st.info('No automatic records yet. Load games to save this session’s board; scheduled background captures begin prospectively near tip, when data is available.')
        st.subheader('Upload an earlier snapshot (optional)')
        st.write('Earlier downloaded files remain supported.')
        upload=st.file_uploader('Pregame snapshot',type='json')
        if upload and st.button('Check final results'):
            try:
                snap=json.load(upload)
                if snap.get('version') not in ['1.0.0','1.1.0','1.2.0','1.3.0','1.4.0','1.5.0',VERSION] or snap.get('basis') not in ['Field goal','First points']: raise ValueError('Unsupported snapshot')
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
                    if 'Shortlisted' in settled.columns:
                        short=settled[settled['Shortlisted'].eq(True)]
                        total_short=sum(r.get('Shortlisted') is True for r in saved)
                        if total_short:
                            st.subheader('Saved shortlist results')
                            st.metric('Shortlist hits — settled games',f"{int(short['Game first hit'].sum())} / {len(short)}")
                            st.caption(f'{total_short} saved picks; {total_short-len(short)} awaiting final data. Results refer to the chosen settlement basis.')
                            st.dataframe(short[['Player','Team','Matchup','Game first %','Listed American odds','Game first hit']],hide_index=True,width='stretch')
                    st.dataframe(settled[['Overall Rank','Team Rank','Player','Team','Game first %','Team first %','Game first hit','Team first hit']],hide_index=True,width='stretch')
                    top=settled.sort_values('Game first %',ascending=False).drop_duplicates('Game ID')
                    st.metric('Game top-pick hits',f"{int(top['Game first hit'].sum())} / {len(top)}")
                    st.caption('Only this uploaded snapshot. No historical accuracy or ROI claim is made. Uploaded snapshots are editable and not an audited record.')
                    st.download_button('Download settled results',settled.to_csv(index=False),'first-basket-results.csv','text/csv')
            except Exception as ex: st.error(f'Cannot settle this snapshot: {ex}')

    with method_tab:
        st.markdown('''### Reading the board
**Slate shortlist** chooses up to four players from different loaded games using the highest game-first estimates. Both lineups must be source-confirmed automatically, tip must be in the future, both teams need at least five sampled games, and the player needs three starts, three early shot attempts, at least one opening shot and one team-first scoring hit. These are initial research rules, not trained or validated selection thresholds. A team filter does not change the shortlist. Load all desired games to compare the slate; absent or skipped games cannot contribute candidates. No four-pick minimum is imposed. While the page is open, this section and starting lineups refresh every 60 seconds; current-game summaries are cached for 45 seconds. Live-page refresh stops when closed. A separate background archive job can still capture default-setting forecasts, subject to scheduling and source availability.

Optional American odds are entered by you and are stored with the shortlist in the pregame snapshot. They do not affect rank and are not checked for freshness. Missing prices remain blank. The tracker identifies saved shortlist picks and displays settled hits and pending games; neither a shortlist nor displayed model estimates establish profitability.

**Game first %** estimates a player scoring first in the entire game. **Team first %** estimates that player scoring first for his own team. The board and simulator use First points, including free throws. Field-goal statistics remain inputs to the model. Older saved records retain their original settlement basis.

**Opening shot %** is the share of sampled team games in which the player took that team's first field-goal attempt. **Early FG %** is actual shooting in the opening three minutes of the first quarter. **Starts** counts starts within that team's sample, not career starts.

### Simulator
In the Simulator tab, select any upcoming matchups directly from the slate. The prediction board can be loaded separately. The simulator draws one game-first scorer per simulated game from each matchup’s own board probabilities and keeps its unlisted-player probability. The run count applies to each selected matchup. The CSV includes all selected games. It uses First points, including free throws, and the displayed starter status. It does not simulate individual possessions, foul rates, jump balls or changing lineups. A fixed seed for each matchup makes repeated runs stable; the displayed percentages are frequencies under the model, not measured accuracy or confidence intervals. It does not change rankings or shortlist eligibility.

### Forecast formula and context
The team's game-first rate is shrunk toward 50% with ten prior games. Its matchup chance averages that rate and the opponent's failure-to-score-first rate.

Within each team, the model uses six buckets: the five selected players plus all other players. Each bucket receives one prior first-scoring event and one prior opening attempt. A player's team-first estimate is **60% smoothed first-scoring share + 40% normalized opening-shot share × smoothed early FG conversion**. Conversion uses a 45% prior with ten attempts. Game-first estimate = team-first estimate × team game-first chance.

**Shot matchup** combines the team's first-shot position tendency and its opponent's first-shot position allowance. Positions are grouped as G/F/C. Each profile is smoothed with ten prior games toward its historical starter position mix. The geometric mean of the two position lifts adjusts only the 40% opening-shot component, capped between 0.85 and 1.15 before normalization. Both profiles need at least five usable games; otherwise the multiplier is exactly 1.0. Favorable means a multiplier of at least 1.05; Tougher means at most 0.95. This position adjustment is experimental, not a measured improvement in accuracy.

**First basket allowed by position** uses the first made field goal by the opposing team in each sampled game, even when a free throw came first. It does not use the first missed attempt or require that the opponent scored first in the entire game. The detail table shows observed counts, percentages and sample size. For ranking, the opponent allowance profile is smoothed toward its historical starter position mix with ten prior games. The position lift adjusts only the 60% first-scoring component, capped between 0.85 and 1.15; that component is then normalized including the unlisted-player bucket. Fewer than five usable opponent games or an unknown player position means no adjustment. First-points mode still includes free throws in its base scoring history; this added matchup signal always uses made field goals.

**Why ranked** summarizes the player's observed opening-shot count, basket-position matchup label, any favorable/tougher shot-position signal, and a limited-history flag when appropriate. It explains signals rather than promising a result. The two position adjustments are heuristic and may be correlated; saved pregame results are needed to assess their value.

**Tip-off estimate** uses only identifiable opening jump balls at 12:00 in quarter one, matching the possession recipient to the historical roster. Missing or ambiguous events are skipped. Team tip rates shrink toward 50% with ten prior games; the matchup averages a team's win rate with the opponent's loss rate. At least five identifiable tips on each side are required. This is team history, not an individual-jumper probability, and is displayed as context only without changing the scoring estimates.

These are starting assumptions, not fitted or calibrated coefficients. First-points mode uses first-points history in its 60% component; its shot component still models field goals and does not separately model early foul rates.

### Data and limitations
Only completed regular-season games strictly before the target tip are sampled. No preseason or playoff games are mixed in. Previous-season data is optional and can contain stale roles. Skipped or incomplete PBP is reported; it is never replaced with made-up stats. Missing teams withhold the matchup.

Current rosters and current-game starter flags come from ESPN. The app checks that starter flags belong to this exact pregame event and scheduled tip, with five distinct players matching the current roster and none marked did-not-play. There is no manual verification step. Until those records are published, the full board uses latest-game starters as clearly marked projections; projected matchups cannot enter the shortlist. Automatic starter confirmation is not a separate injury-model adjustment. ESPN may report grouped G/F positions; this app does not invent PG/SG/SF/PF labels.

No confirmed jumper lineup, automatic injury adjustment, sportsbook odds feed, general defense-versus-position score, or backtested profitability is included. First-shot and first-basket allowance are opening tendencies, not general defensive ratings. Repeated saved pregame forecasts and settled results are needed before assessing calibration. A high rank is a relative research signal and does not mean a likely winning bet. Version 1.0–1.3 pregame snapshots remain supported by the tracker.

### Sources
[ESPN NBA](https://www.espn.com/nba/) supplies the public scoreboard, team schedule, roster, boxscore and play-by-play endpoints. These endpoints are unofficial, can change, and carry no uptime guarantee. This model is independent of ESPN and the NBA.
    ''')


render_model()





