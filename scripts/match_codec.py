"""Read one FM27 match on request; never writes to a save or game process."""
import pathlib,sys,json,struct,datetime,hashlib,argparse,warnings,collections
ROOT=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'vendor'))
from backports import zstd
from decode_match_details import decode_data
from emulate_player_reader import PlayerDecoder
from extended_match_reader import Buffer,team_tail,match_extras,UnsupportedVariant
from native_inspect import DLL,dll_hash
EXPECTED_DLL='252ff8fb5b7a4a5a5464db6ba632e309eef9b6e65ffa992ae20575a189e66c6a'

class Cache:
    def __init__(self,data):
        self.data=data;r=Buffer(data)
        if r.take(8)!=bytes.fromhex('03017461642e0600'):raise UnsupportedVariant('match cache header')
        self.next_id=r.u(4);r.take(2);pages=r.bounded_count(4,64);self.index={}
        for page in range(pages):
            if page and r.u()!=1:raise ValueError('page separator')
            number=r.u(4);name=r.take(r.bounded_count(4,1000)).decode('ascii');capacity=r.u(4)
            if r.take(2)!=b'\x01\x01':raise UnsupportedVariant('page markers')
            count=r.bounded_count(4,1000000);rows=[(r.u(4),r.u(4),r.u(4))for _ in range(count)]
            if r.u(4)!=capacity:raise ValueError('page capacity disagreement')
            cursor=r.u(4)
            if r.u()!=3:raise UnsupportedVariant('storage marker')
            size=r.bounded_count(4,128*1024*1024);base=r.pos
            if cursor>size:raise ValueError('write cursor outside storage')
            r.take(size)
            for key,off,n in rows:
                if off+n>size or key in self.index:raise ValueError('invalid or duplicate cache entry')
                self.index[key]={'offset':base+off,'size':n,'page':number,'page_name':name}
        if r.take(1)!=b'\x01'or r.pos!=len(data):raise UnsupportedVariant('cache trailer')
    def read(self,key):
        e=self.index[key];compressed=self.data[e['offset']:e['offset']+e['size']]
        z=zstd.ZstdDecompressor();data=z.decompress(compressed,max_length=32*1024*1024)
        if not z.eof or z.unused_data:raise ValueError('invalid or oversized match frame')
        return data

def read_match(data,names,uidnames=None,*,build=None):
    # Keep a fingerprint for source stability; never use it as an admission gate.
    digest=dll_hash()
    decoder=PlayerDecoder
    modern=(build.split('+',1)[0]!='27.0.0')if build else digest!=EXPECTED_DLL
    if modern:
        from emulate_player_2701 import PlayerDecoder2701
        decoder=PlayerDecoder2701
    if data[:5]!=bytes.fromhex('0100013c1f'):raise UnsupportedVariant('match stream version')
    candidates=decode_data(data)
    if len(candidates)!=2:raise UnsupportedVariant(f'Expected two validated team headers; found {len(candidates)}')
    schema=json.loads((ROOT/'resources/field-schema.json').read_text(encoding='utf8'))['player_field_schema']
    teams=[]
    for side,t in enumerate(candidates):
        pos=t['players_start'];players=[]
        for _ in range(t['roster_count']):
            reader=decoder(data,pos);memory,end,_=reader.decode();extension=data[end]
            if extension not in (0,1):raise UnsupportedVariant('player identity extension')
            pos=end+1+(11 if extension else 0)
            reference=struct.unpack_from('<I',memory,0x18)[0]
            stats={k:(struct.unpack_from(v['format'],memory,v['offset'])[0]-(memory[v['subtract_offset']]if 'subtract_offset'in v else 0))*v['scale']for k,v in schema.items()}
            players.append({'reference':reference,'identity':names.get(str(reference-1)),
                            'stats':stats,'shots_raw':reader.events(),
                            'on_tick_raw':struct.unpack_from('<i',memory,0x54)[0],
                            'off_tick_raw':struct.unpack_from('<i',memory,0x58)[0]})
        tail=team_tail(data,pos)
        if side==0 and tail['end']!=candidates[1]['start']:raise ValueError('team boundary disagreement')
        if uidnames:
            for selection in tail['selection_history']:
                for p in selection['players']:p['identity']=uidnames.get(p['reference'])
        teams.append({'team_id':t['team_id'],'side':side,'players':players,'header':t,'tail':tail})
    extras=match_extras(data,teams[1]['tail']['end'])
    def actor(side,index):
        if side not in (0,1)or index>=len(teams[side]['players']):return None
        return teams[side]['players'][index]['identity']
    for e in extras['incidents']:
        e['player']=actor(e['side'],e['roster_index']);e['other_player']=actor(e['other_side'],e['other_index'])
    for e in extras['advanced_shots']:e['player']=actor(e['side'],e['roster_index'])
    checks=[]
    for side,t in enumerate(teams):
        for k in ('shots','shots_on_target','passes_attempted','passes_completed','expected_goals'):
            headerkey='xg'if k=='expected_goals'else k
            if abs(sum(p['stats'][k]for p in t['players'])-t['header'][headerkey])>.0002:raise ValueError(f'{k} team sum disagreement')
        for index,p in enumerate(t['players']):
            incidents=[e for e in extras['incidents']if e['side']==side and e['roster_index']==index]
            goals=sum(e['kind']in(1,3)for e in incidents)
            yellows=sum(e['kind']in(14,38)for e in incidents);reds=sum(e['kind']in(14,15)for e in incidents)
            assists=sum(e['kind']in(1,3)and e['side']==side and e['other_side']==side and e['other_index']==index and e['roster_index']!=index for e in extras['incidents'])
            for k,value in [('goals',goals),('assists',assists),('yellow_cards',yellows),('red_cards',reds)]:
                if p['stats'][k]!=value:raise ValueError(f'{k} incident disagreement for team {side}, player {index}')
            checks.append({'side':side,'roster_index':index,'goal_and_card_counts_match':True})
    if dll_hash()!=digest:raise UnsupportedVariant('Game DLL changed during match decoding')
    return {'kick_off':str(datetime.datetime(1,1,1)+datetime.timedelta(minutes=struct.unpack_from('<i',data,11)[0])),
            'teams':teams,'extras':extras,'verification':{'team_sum_checks':10,'player_goal_assist_card_checks':len(checks)*4,'passed':True},
            'limitations':['Other event kinds and advanced-shot coordinates/flags remain unconfirmed.',
                           'Following bytes are retained in source but not decoded by this codec.',
                           'Continuous tracking, heatmaps and full pass/touch streams are not established capabilities.']}
