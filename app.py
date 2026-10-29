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
if getattr(_model, 'VERSION', None) != '1.5.0':
    importlib.reload(_model)
from model import fetch, competitors, team_id, utc, prior_events, parse_game, forecast, implied, VERSION, opening_context, select_shortlist, SHORTLIST_RULES, source_starters, tip_conversion, jumper_records, shot_style, position_summary
from archive import snapshot as make_snapshot, keep_pregame, settle

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

with st.sidebar:
    st.header('Board settings')
    date = st.date_input('Slate date (Eastern)', datetime.now(ET).date())
    market = st.radio('Settlement basis', ['Field goal', 'First points'], help='Field goal excludes free throws. First points includes them. Match your sportsbook rules.')
    n = st.slider('Recent regular-season games / team', 5, 30, 20)
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

    board_tab, tracking_tab, method_tab = st.tabs(['Prediction board','Results tracker','How it works'])
    with board_tab:
        st.caption('Game first = first scorer in the entire game. Team first = first scorer for that team. Both follow your selected settlement basis.')
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
                jobs = {}
                with st.spinner('Loading real opening possessions and historical starters…'):
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        for e in active:
                            for c in competitors(e):
                                tid = team_id(c)
                                jobs[pool.submit(history,tid,year,e['date'],n,prior,market,VERSION)] = (e['id'],tid)
                        loaded = {}
                        for future in as_completed(jobs):
                            key=jobs[future]
                            try: loaded[key]=future.result()
                            except Exception as ex: loaded[key]=([], [str(ex)])
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
                            # Current roster is the candidate pool; historical boxscore only provides projection.
                            try:
                                rd=live(f'teams/{tid}/roster')
                                roster={str(a['id']):{'name':a['displayName'],'position':a.get('position',{}).get('abbreviation','?')} for a in rd.get('athletes',[])}
                            except Exception as ex:
                                issues.append(f'Roster {tid}: {ex}'); roster={}
                            if not roster:
                                col.error('Current roster unavailable; matchup withheld.'); continue
                            metadata[tid]=roster
                            confirmed=source_starters(current_summary,gid,tid,roster,e['date'])
                            default=[p for p in latest['starters'][tid] if p in roster]
                            default.sort(key=lambda p:roster[p]['name'])
                            selected[tid]=confirmed or default
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
                    for row in rows:
                        row.update({'Game ID':gid,'Matchup':e['shortName'],'Team':abbreviations[row['Team ID']],
                                    'Lineup':'Source confirmed' if all(confirms) else 'Projected',
                                    'Lineup source':'ESPN current-game starter flags' if all(confirms) else 'Latest historical starters; awaiting ESPN',
                                    'Lineup checked at':checked_at,
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
                    # Color priority is per game and uses the existing eligibility rules.
                    # It does not alter estimates, ranks, or shortlist selection.
                    now_for_priority=datetime.now(ET)
                    leaders=set()
                    for game_id in df['Game ID'].unique():
                        eligible=select_shortlist(df[df['Game ID']==game_id].to_dict('records'),now_for_priority)
                        if eligible:leaders.add((str(eligible[0]['Game ID']),str(eligible[0]['Player ID'])))
                    def tier(r):
                        if r['Lineup']!='Source confirmed':return 'Awaiting starters'
                        if min(r['Sample'],r['Opponent sample'])<15 or r['Starts']<8:return 'Limited data'
                        return 'Top game candidate' if (str(r['Game ID']),str(r['Player ID'])) in leaders else 'Research'
                    df['Research tier']=df.apply(tier,axis=1)
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

    with tracking_tab:
        st.subheader('Automatic pregame records')
        try: archived,archive_index=background_records()
        except Exception as ex:
            archived,archive_index={},{}
            st.warning(f'Background archive unavailable: {type(ex).__name__}')
        automatic={f'Background archive · {k}':r for k,r in archived.items()}
        automatic.update({f'This session · {k}':r for k,r in st.session_state.get('automatic_pregame_records',{}).items()})
        st.caption('Open-session records save your loaded board automatically. Background records use default settings, field-goal settlement and a scheduled capture within two hours of tip. Session records may disappear when disconnected; the background archive is committed to the repository. Scheduling and data delays can cause missed captures.')
        if archive_index.get('checked_hour_utc'):
            st.caption(f"Background archive heartbeat: {utc(archive_index['checked_hour_utc']).astimezone(ET):%b %d, %I:%M %p ET} (hourly timestamp).")
        if archive_index.get('errors'):
            with st.expander('Background source coverage'):st.write(archive_index['errors'])
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
                if snap.get('version') not in ['1.0.0','1.1.0','1.2.0','1.3.0','1.4.0',VERSION] or snap.get('basis') not in ['Field goal','First points']: raise ValueError('Unsupported snapshot')
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

**Game first %** estimates a player scoring first in the entire game. **Team first %** estimates that player scoring first for his own team. Choose field-goal or first-points settlement to match your book; first points includes free throws.

**Opening shot %** is the share of sampled team games in which the player took that team's first field-goal attempt. **Early FG %** is actual shooting in the opening three minutes of the first quarter. **Starts** counts starts within that team's sample, not career starts.

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
