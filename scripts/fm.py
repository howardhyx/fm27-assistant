"""FM27 read-only data gateway. JSON on stdout; no analysis or game mutations."""
from __future__ import annotations
import argparse,collections,dataclasses,datetime,enum,hashlib,json,os,pathlib,struct,sys,warnings
ROOT=pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'vendor'))
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf8')
BUILD='27.0.0+2493426'
DLL_HASH='252ff8fb5b7a4a5a5464db6ba632e309eef9b6e65ffa992ae20575a189e66c6a'
HIDDEN={'dirtiness','consistency','important_matches','injury_proneness','versatility'}
POSITIONS={'gk','dc','dr','dl','dm','mc','ml','mr','aml','amc','amr','stc','wbl','wbr'}
from local_paths import DEFAULT_CONFIG,load_config,resolve_dll,resolve_save,remember_paths

def encode(value):
    if dataclasses.is_dataclass(value):return {f.name:encode(getattr(value,f.name))for f in dataclasses.fields(value)}
    if isinstance(value,enum.Enum):return value.name.lower()
    if isinstance(value,dict)or hasattr(value,'items'):return {str(k):encode(v)for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [encode(v)for v in value]
    if isinstance(value,(datetime.date,datetime.datetime,pathlib.Path)):return str(value)
    return value

def project(row,fields):
    if not fields:return row
    result={}
    for field in fields.split(','):
        field=field.strip();value=row
        for key in field.split('.'):
            if value is None:break
            if not isinstance(value,dict)or key not in value:raise ValueError(f'Unknown or unavailable field: {field}')
            value=value[key]
        result[field]=value
    return result

def contract_view(p):
    c=p.contract
    if c is None:return None
    return encode({k:getattr(c,k)for k in ['club_uid','club_name','team_id','wage','start','end','end_source','squad_status','kind','clauses',
                                             'on_loan','loan_parent_club_uid','loan_parent_club_name','loan_start','loan_end']})

def player_view(p):
    attrs={k:v for k,v in encode(p.attributes).items()if k not in HIDDEN}
    return {'uid':p.uid,'unique_id':p.unique_id,'name':p.name,'age':p.age,'birth_date':str(p.birth_date)if p.birth_date else None,
            'club_uid':p.club_uid,'club_name':p.club_name,'team_id':p.team_id,'team_slot':p.team_slot,
            'positions':encode(p.positions),'natural_positions':encode(p.natural_positions),'accomplished_positions':encode(p.accomplished_positions),
            'attributes':attrs,'left_foot':p.left_foot,'right_foot':p.right_foot,'height_cm':p.height_cm,
            'condition_raw':p.raw_condition,'match_sharpness_raw':p.raw_match_sharpness,
            'traits':encode(p.traits),'on_loan':p.on_loan,'loan_parent_club_uid':p.loan_parent_club_uid,
            'transfer_value':p.transfer_value,'transfer_value_state':encode(p.transfer_value_state),
            'contract':contract_view(p),'suspensions':encode(p.suspensions)}

class Session:
    def __init__(self,args):
        self.args=args;self.notices=[];self.filters={};self.coverage={};self._cache=None
        config=load_config(args.config)
        dll,dll_source=resolve_dll(args.game_dir,config)
        self.path,save_source=resolve_save(args.save,config)
        self.path_selection={'save':save_source,'game_dll':dll_source,'config_path':str(args.config.resolve())}
        self.notices.append(f'Path selection: save={save_source}; game DLL={dll_source}. Verify source path and in-game date.')
        with dll.open('rb')as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        if digest!=DLL_HASH:raise ValueError('UNSUPPORTED_BUILD: game DLL changed; revalidate the profile before decoding.')
        os.environ['FM27_GAME_DLL']=str(dll)
        import fmsave
        self.path=self.path.resolve();self.before=self.path.stat();self.save=fmsave.open(self.path,strict=True)
        if self.save.info.build!=BUILD:
            self.save.close();raise ValueError(f'UNSUPPORTED_BUILD: save {self.save.info.build}; supported {BUILD}')
        self.clubs=list(self.save.managed_clubs());ids={c.club_uid for c in self.clubs}
        if args.club_uid is None and len(ids)!=1 and args.command not in ('doctor','context'):
            raise ValueError(f'Multiple managed clubs: specify --club-uid from {sorted(ids)}.')
        if args.club_uid is None and len(ids)>1:self.notices.append('Inventory uses the first managed club only as a display context; choose --club-uid for data queries.')
        self.club_uid=args.club_uid if args.club_uid is not None else next(iter(ids))
        club=next((c for c in self.save.clubs()if c.uid==self.club_uid),None)
        if club is None:raise ValueError('Requested club UID not found')
        self.club=club
        self.team_id=args.team_id if args.team_id is not None else club.teams[0].team_id
        if self.team_id not in [t.team_id for t in club.teams]:raise ValueError('--team-id does not belong to the selected club; supply the matching --club-uid.')
        self.profile={'save_build':BUILD,'game_dll_sha256':digest,'profile_validated':True,'game_dll':str(dll)}
        if not self.save.info.known_build:
            self.notices.append('The community parser does not list this build as verified. The custom native profile is pinned and checked separately; this does not establish every secondary field meaning or UI label.')
        if save_source=='newest_discovered_save':self.notices.append('Auto-selected newest modified save; verify source path and in-game date before using the result.')
    def close(self):self.save.close()
    def context(self):
        return {'managed_clubs':[{'club_uid':c.club_uid,'club_name':c.club_name}for c in self.clubs],
                'selected_club':{'uid':self.club_uid,'name':self.club.name},
                'selected_team_id':self.team_id,'club_teams':encode(self.club.teams),
                'game_date':str(self.save.info.game_date),'known_by_community_parser':self.save.info.known_build}
    def checked(self):
        after=self.path.stat()
        if (after.st_size,after.st_mtime_ns)!=(self.before.st_size,self.before.st_mtime_ns):raise RuntimeError('SAVE_CHANGED: wait until the game finishes saving and retry.')
    def rows(self,rows,limit=None):
        rows=list(rows);n=len(rows);limit=self.args.limit if limit is None else limit
        returned=rows[:limit]if limit is not None else rows
        self.coverage={'matched_rows':n,'returned_rows':len(returned),'truncated':len(returned)<n}
        return [project(r,self.args.fields)for r in returned]
    def players(self,scope=None):
        a=self.args;scope=scope or a.scope;result=[]
        for p in self.save.players():
            if scope=='team'and p.team_id!=self.team_id:continue
            if scope=='club'and p.club_uid!=self.club_uid:continue
            if a.player_uid and p.uid not in a.player_uid:continue
            if a.player_unique_id and p.unique_id not in a.player_unique_id:continue
            if a.name and a.name.casefold()not in (p.name or '').casefold():continue
            if a.age_max is not None and (p.age is None or p.age>a.age_max):continue
            if a.age_min is not None and (p.age is None or p.age<a.age_min):continue
            if a.position and getattr(p.positions,a.position)<a.position_min:continue
            if a.value_max is not None and (p.transfer_value is None or p.transfer_value>a.value_max):continue
            for condition in a.attribute_min:
                k,raw=condition.split('=',1)
                if k in HIDDEN or not hasattr(p.attributes,k):raise ValueError(f'Unsupported public attribute: {k}')
                value=getattr(p.attributes,k)
                if value is None or value<int(raw):break
            else:result.append(player_view(p))
        self.filters={'scope':scope,'team_id':self.team_id,'club_uid':self.club_uid,'player_uid':a.player_uid,
                      'name':a.name,'position':a.position,'position_min':a.position_min,'attribute_min':a.attribute_min}
        self.notices.append('Player data comes from the save database; it is not a reconstruction of manager scouting visibility. CA/PA and hidden attributes are excluded.')
        return self.rows(sorted(result,key=lambda p:p['uid']))
    def fixtures(self):
        a=self.args;rows=[]
        for f in self.save.fixtures():
            if self.team_id not in (f.home_team_id,f.away_team_id):continue
            r=encode(f)
            if a.played!='any'and bool(r['played'])!=(a.played=='yes'):continue
            if a.since and (not r['date']or r['date']<a.since):continue
            if a.until and (not r['date']or r['date']>a.until):continue
            if a.date and r['date']!=a.date:continue
            rows.append(r)
        rows.sort(key=lambda f:f['date']or '',reverse=a.played!='no')
        self.filters={'team_id':self.team_id,'played':a.played,'since':a.since,'until':a.until,'date':a.date}
        return self.rows(rows)
    def cache(self):
        if self._cache is None:
            from match_codec import Cache
            with self.save._context.section('match_stats_cfg')as data:self._cache=Cache(bytes(data))
        return self._cache
    def cache_candidates(self):
        from backports import zstd
        cache=self.cache();candidates=[];marker=b'\x03\x02'+struct.pack('<I',self.team_id)
        for key,e in cache.index.items():
            z=zstd.ZstdDecompressor();prefix=z.decompress(cache.data[e['offset']:e['offset']+e['size']],max_length=256)
            if prefix[:5]!=bytes.fromhex('0100013c1f')or marker not in prefix[100:250]:continue
            dt=str(datetime.datetime(1,1,1)+datetime.timedelta(minutes=struct.unpack_from('<i',prefix,11)[0]))
            if self.args.date and dt[:10]!=self.args.date:continue
            if self.args.since and dt[:10]<self.args.since:continue
            if self.args.until and dt[:10]>self.args.until:continue
            candidates.append({'cache_key':key,'kick_off':dt})
        self.notices.append('Cache selection checks only a bounded prefix before decoding the requested match. This prefix profile is validated for the pinned build; absence is not proof of complete historical coverage.')
        return sorted(candidates,key=lambda x:(x['kick_off'],x['cache_key']),reverse=True)
    def cached_fixtures(self):
        from decode_match_details import decode_data
        candidates=self.cache_candidates();rows=[]
        for c in candidates[:self.args.limit]:
            teams=decode_data(self.cache().read(c['cache_key']))
            if len(teams)!=2 or self.team_id not in [t['team_id']for t in teams]:raise ValueError('cache/team header disagreement')
            rows.append({**c,'home_team_id':teams[0]['team_id'],'away_team_id':teams[1]['team_id'],
                         'home_goals':teams[0]['raw_fields']['0x160'],'away_goals':teams[1]['raw_fields']['0x160'],
                         'expected_goals':[t['xg']for t in teams]})
        self.coverage={'matched_rows':len(candidates),'returned_rows':len(rows),'truncated':len(rows)<len(candidates)}
        return [project(r,self.args.fields)for r in rows]
    def match(self):
        from match_codec import read_match
        key=self.args.match_key
        if key is None:
            candidates=self.cache_candidates()
            if not candidates:raise ValueError('No matching cached game; inspect fixtures/cache-matches and coverage.')
            if self.args.date and len(candidates)!=1:raise ValueError('Ambiguous match date; specify --match-key.')
            key=candidates[0]['cache_key']
        records=self.save._context.player_records();players={p.uid:p for p in self.save.players()}
        names={str(index):{'uid':uid,'unique_id':players[uid].unique_id,'name':players[uid].name}
               for index,uid in zip(records.pindexes,records.uids)if uid in players}
        uids={p.unique_id:{'uid':p.uid,'unique_id':p.unique_id,'name':p.name}for p in players.values()if p.unique_id is not None}
        raw_match=self.cache().read(key)
        data=read_match(raw_match,names,uids)
        if self.team_id not in [t['team_id']for t in data['teams']]:raise ValueError('Requested match does not contain selected team')
        day=data['kick_off'][:10]
        if self.args.date and day!=self.args.date:raise ValueError('--match-key and --date select different matches')
        if self.args.since and day<self.args.since or self.args.until and day>self.args.until:raise ValueError('Requested match is outside the date filters')
        data['cache_key']=key;part=self.args.part
        self.filters={'match_key':key,'date':self.args.date,'part':part,'side':self.args.side,
                      'player_uid':self.args.player_uid,'player_unique_id':self.args.player_unique_id,'name':self.args.name}
        self.notices.extend(data['limitations'])
        self.coverage={'matches_returned':1,'verification':data['verification'],
                       'unresolved_player_identities':sum(not p['identity']for t in data['teams']for p in t['players']),
                       'truncated':False,'unparsed_following_bytes':data['extras']['following_bytes_not_decoded']}
        if part in ('tactics','tactic-timeline','all'):
            from match_tactics import read_match_tactics
            historical=read_match_tactics(raw_match,data['teams'],data['extras']['end'])
            self.coverage['historical_tactics']={'team_count':len(historical['teams']),
                'binding':'bounded_structural_owner_binding','timeline_decoded':False,
                'unknown_team_bits':{str(t['team_id']):t['team_instructions']['unknown_set_bits']for t in historical['teams']}}
            self.notices.extend(historical['limitations'])
            self.notices.append('Following-byte count is the region outside the statistics decoder; it includes separately located tactic prefixes and is not a count of wholly unread bytes.')
            data['historical_tactics']=historical
            if part in ('tactic-timeline','all'):
                from tactic_timeline import read_timeline
                timeline=read_timeline(raw_match,data,historical)
                data['tactic_timeline']=timeline
                self.coverage['historical_tactics']['timeline_decoded']=True
                self.coverage['tactical_command_queue']={'records_decoded':timeline['count'],
                    'source_start':timeline['source_start'],'source_end':timeline['source_end'],
                    **timeline['verification'],'effective_behavior_replayed':False}
                self.notices.extend(timeline['limitations'])
                if part=='tactic-timeline':
                    if self.args.side=='selected':
                        timeline['initial_state']['teams']=[t for t in timeline['initial_state']['teams']if t['team_id']==self.team_id]
                    events=[e for e in timeline['changes']if self.args.side!='selected'or e['team_id']==self.team_id]
                    previous=self.coverage.copy();returned=self.rows(events)
                    self.coverage.update({k:v for k,v in previous.items()if k!='truncated'})
                    return {'cache_key':key,'kick_off':data['kick_off'],
                            **{k:v for k,v in timeline.items()if k!='changes'},'changes':returned}
            if part=='tactics':
                if self.args.side=='selected':historical['teams']=[t for t in historical['teams']if t['team_id']==self.team_id]
                return {'cache_key':key,'kick_off':data['kick_off'],**historical}
        if part=='all':return data
        if part=='summary':
            ticks=sum(t['header']['possession_ticks']for t in data['teams'])
            return {'cache_key':key,'kick_off':data['kick_off'],'teams':[{'team_id':t['team_id'],
                    **{k:t['header'][k]for k in ['xg','shots','shots_on_target','passes_attempted','passes_completed']},
                    'goals':t['header']['raw_fields']['0x160'],'possession_percent':100*t['header']['possession_ticks']/ticks}for t in data['teams']]}
        if part=='events':
            previous=self.coverage.copy();rows=data['extras']['incidents']
            if self.args.side=='selected':rows=[e for e in rows if data['teams'][e['side']]['team_id']==self.team_id]
            if self.args.player_uid:rows=[e for e in rows if (e['player']or {}).get('uid')in self.args.player_uid]
            if self.args.player_unique_id:rows=[e for e in rows if (e['player']or {}).get('unique_id')in self.args.player_unique_id]
            if self.args.name:rows=[e for e in rows if self.args.name.casefold()in (e['player']or {}).get('name','').casefold()]
            returned=self.rows(rows);self.coverage.update({k:v for k,v in previous.items()if k!='truncated'})
            return {'cache_key':key,'kick_off':data['kick_off'],'events':returned}
        if part=='snapshots':return {'cache_key':key,'teams':[{'team_id':t['team_id'],'snapshots':t['tail']['selection_history']}for t in data['teams']]}
        rows=[]
        for t in data['teams']:
            for p in t['players']:
                identity=p['identity']or {}
                if self.args.side=='selected'and t['team_id']!=self.team_id:continue
                if self.args.player_uid and identity.get('uid')not in self.args.player_uid:continue
                if self.args.player_unique_id and identity.get('unique_id')not in self.args.player_unique_id:continue
                if self.args.name and self.args.name.casefold()not in identity.get('name','').casefold():continue
                if part=='players':rows.append({'team_id':t['team_id'],'identity':p['identity'],'reference':p['reference'],
                                               'stats':p['stats'],'on_tick_raw':p['on_tick_raw'],'off_tick_raw':p['off_tick_raw']})
                elif part=='shots':
                    for shot in p['shots_raw']:
                        raw=bytes.fromhex(shot['payload_hex']);rows.append({'team_id':t['team_id'],'identity':p['identity'],
                        'minute_raw':raw[5],'second_raw':raw[6],'outcome_code':raw[4],'shot_flags':shot['group'],
                        'native_tick':struct.unpack_from('<H',raw,2)[0],'coordinate_values_unconfirmed':list(struct.unpack_from('<4f',raw,8))})
        if part=='advanced-shots':
            rows=data['extras']['advanced_shots']
            if self.args.side=='selected':rows=[e for e in rows if e['side']in(0,1)and data['teams'][e['side']]['team_id']==self.team_id]
            if self.args.player_uid:rows=[e for e in rows if (e['player']or {}).get('uid')in self.args.player_uid]
            if self.args.player_unique_id:rows=[e for e in rows if (e['player']or {}).get('unique_id')in self.args.player_unique_id]
            if self.args.name:rows=[e for e in rows if self.args.name.casefold()in (e['player']or {}).get('name','').casefold()]
        previous=self.coverage.copy();returned=self.rows(rows);self.coverage.update({k:v for k,v in previous.items()if k!='truncated'})
        return {'cache_key':key,'kick_off':data['kick_off'],'rows':returned}
    def baseline(self):
        from tactic_codec import read_tactics
        tactics=read_tactics(self.save,self.team_id)
        if not tactics:raise ValueError('No saved tactic for selected team; baseline is incomplete.')
        selection=[encode(r)for r in self.save.selections()if r.team_id==self.team_id]
        self.coverage={'tactics':len(tactics),'selection_rows':len(selection),'truncated':False}
        return {'context':self.context(),'tactics':tactics,'selection':selection,
                'mandatory_read_complete':True,'current_tactic_selected':None,
                'interpretation':['Saved selections may differ from the next match lineup.',
                                  'In-possession and out-of-possession formations are distinct.',
                                  'Personal instructions are stored overrides; default role instructions are not expanded.']}
    def dispatch(self):
        c=self.args.command
        if c=='context':return project(self.context(),self.args.fields)
        if c=='baseline':return self.baseline()
        if c=='tactics':return self.baseline()['tactics']
        if c=='selection':return self.rows(encode(r)for r in self.save.selections()if r.team_id==self.team_id)
        if c=='players':return self.players()
        if c=='contracts':
            data=self.players();return data
        if c=='fixtures':return self.fixtures()
        if c=='cache-matches':return self.cached_fixtures()
        if c=='match':return self.match()
        if c=='set-pieces':
            self.notices.append('Only saved routine names and slots are available; complete routine instructions are not decoded.')
            return self.rows(encode(r)for r in self.save.set_pieces()if r.team_id==self.team_id)
        if c=='season':
            a=self.args;rows=[];selected_uids=None
            if a.player_unique_id:selected_uids={p.uid for p in self.save.players()if p.unique_id in a.player_unique_id}
            for p in self.save.player_season_stats():
                if p.team_id!=self.team_id:continue
                if a.player_uid and p.player_uid not in a.player_uid:continue
                if selected_uids is not None and p.player_uid not in selected_uids:continue
                if a.name and a.name.casefold()not in (p.player_name or '').casefold():continue
                r=encode(p)
                if a.kind and r['kind']!=a.kind:continue
                rows.append(r)
            self.notices.append('Season aggregate scope is separate from cached detailed matches and truncated basic match history. Do not add overall and competition rows together.')
            self.filters={'team_id':self.team_id,'kind':a.kind,'player_uid':a.player_uid,'player_unique_id':a.player_unique_id,'name':a.name}
            return self.rows(rows)
        if c=='finances':
            rows=[encode(r)for r in self.save.finances()if r.club_uid==self.club_uid]
            rows.sort(key=lambda r:r['month'],reverse=True)
            self.notices.append('Historical month-end data in unconverted save base currency. It is not a confirmed current spendable budget; transfer_budget_allocated has unconfirmed semantics.')
            return self.rows(rows)
        raise ValueError('Unknown command')

def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['doctor','baseline','context','tactics','selection','players','contracts','fixtures','cache-matches','match','season','finances','set-pieces'])
    p.add_argument('--save',type=pathlib.Path);p.add_argument('--game-dir',type=pathlib.Path)
    p.add_argument('--config',type=pathlib.Path,default=DEFAULT_CONFIG,help='Machine-local paths JSON; defaults to this skill/local/paths.json.')
    p.add_argument('--remember-paths',action='store_true',help='doctor only: persist validated save/DLL paths for subsequent calls.')
    p.add_argument('--club-uid',type=int);p.add_argument('--team-id',type=int)
    p.add_argument('--out',type=pathlib.Path);p.add_argument('--limit',type=int,default=50);p.add_argument('--fields')
    p.add_argument('--scope',choices=['team','club','all'],default='team')
    p.add_argument('--player-uid',action='append',type=int,default=[]);p.add_argument('--player-unique-id',action='append',type=int,default=[])
    p.add_argument('--name');p.add_argument('--position',choices=sorted(POSITIONS));p.add_argument('--position-min',type=int,default=15)
    p.add_argument('--age-min',type=int);p.add_argument('--age-max',type=int);p.add_argument('--value-max',type=int)
    p.add_argument('--attribute-min',action='append',default=[],metavar='NAME=VALUE')
    p.add_argument('--played',choices=['yes','no','any'],default='yes');p.add_argument('--since');p.add_argument('--until');p.add_argument('--date')
    p.add_argument('--match-key',type=int);p.add_argument('--side',choices=['both','selected'],default='both')
    p.add_argument('--part',choices=['summary','players','events','shots','advanced-shots','snapshots','tactics','tactic-timeline','all'],default='summary')
    p.add_argument('--kind',default='overall')
    return p

def main():
    a=parser().parse_args();s=None
    try:
        if sys.version_info[:2]!=(3,12)or sys.maxsize<=2**32 or sys.platform!='win32':raise ValueError('Bundled runtime requires Windows x64 and Python 3.12; do not silently replace pinned packages.')
        if not 1<=a.limit<=1000:raise ValueError('--limit must be 1..1000; use narrower filters for larger requests.')
        if a.remember_paths and a.command!='doctor':raise ValueError('--remember-paths is supported only for doctor, after successful validation.')
        if a.fields and a.command in ('baseline','tactics','doctor'):raise ValueError('--fields is not supported for this mandatory/context command; read its complete structure.')
        allowed={
            'player_uid':{'players','contracts','season','match'},'player_unique_id':{'players','contracts','season','match'},
            'name':{'players','contracts','season','match'},'position':{'players','contracts'},'age_min':{'players','contracts'},
            'age_max':{'players','contracts'},'value_max':{'players','contracts'},'attribute_min':{'players','contracts'},
            'since':{'fixtures','cache-matches','match'},'until':{'fixtures','cache-matches','match'},'date':{'fixtures','cache-matches','match'},
            'match_key':{'match'}}
        for field,commands in allowed.items():
            if getattr(a,field)not in (None,[],False)and a.command not in commands:raise ValueError(f'--{field.replace("_","-")} is not supported for {a.command}')
        if a.scope!='team'and a.command not in ('players','contracts'):raise ValueError('--scope is only supported for players/contracts')
        if a.played!='yes'and a.command!='fixtures':raise ValueError('--played is only supported for fixtures')
        if a.kind!='overall'and a.command!='season':raise ValueError('--kind is only supported for season')
        if a.part!='summary'and a.command!='match':raise ValueError('--part is only supported for match')
        if a.command=='match'and a.part=='tactics'and (a.fields or a.player_uid or a.player_unique_id or a.name):
            raise ValueError('Historical tactics are a team structure; use --side, without player or row-field filters.')
        if a.command=='match'and a.part=='tactic-timeline'and (a.player_uid or a.player_unique_id or a.name):
            raise ValueError('Tactical command timelines use team/slot/roster indices; use --side, without player-name filters.')
        if a.side!='both'and a.command!='match':raise ValueError('--side is only supported for match')
        for name in ('since','until','date'):
            if getattr(a,name):datetime.date.fromisoformat(getattr(a,name))
        if a.command=='contracts'and not a.fields:a.fields='uid,unique_id,name,club_name,team_id,contract'
        with warnings.catch_warnings(record=True)as caught:
            warnings.simplefilter('always');s=Session(a)
            data={'python':sys.version.split()[0],'profile':s.profile,'context':s.context(),
                  'cache_records':len(s.cache().index),'read_only':True}if a.command=='doctor'else s.dispatch()
            s.checked()
        notices=list(dict.fromkeys([*s.notices,*[str(w.message)for w in caught]]))
        result={'ok':True,'schema_version':1,'data_type':a.command,
                'source':{'save_path':str(s.path),'save_mtime_ns':s.before.st_mtime_ns,'save_bytes':s.before.st_size,
                          'game_date':str(s.save.info.game_date),'build':BUILD,'game_dll_sha256':DLL_HASH,
                          'club_uid':s.club_uid,'team_id':s.team_id,'path_selection':s.path_selection},
                'coverage':s.coverage,'filters':s.filters,'notices':notices,'data':data}
        result['interpretation_status']=('native_profile_and_independent_structure_checks'if a.command in ('baseline','tactics','match')
                                         else 'community_parser_structure_checked; field_semantics_may_be_partial')
        body=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)
        if a.remember_paths:
            saved_config=remember_paths(a.config,s.path,s.profile['game_dll'])
            result['notices'].append(f'Validated paths saved to {saved_config}; later calls reuse this exact save file unless overridden.')
            body=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)
        if a.out:
            destination=a.out.resolve()
            game_root=pathlib.Path(s.profile['game_dll']).parents[3]
            if destination.suffix.lower()!='.json'or destination==s.path or destination.is_relative_to(game_root)or destination.is_relative_to(s.path.parent):
                raise ValueError('Output must be a workspace JSON outside the game installation and save directory.')
            destination.write_text(body,encoding='utf8')
            print(json.dumps({'ok':True,'data_type':a.command,'output':str(destination),'source':result['source'],'coverage':s.coverage},ensure_ascii=False))
        else:print(body)
    except Exception as error:
        print(json.dumps({'ok':False,'error_type':type(error).__name__,'message':str(error),'data_type':a.command},ensure_ascii=False))
        return 1
    finally:
        if s is not None:s.close()
    return 0

if __name__=='__main__':raise SystemExit(main())
