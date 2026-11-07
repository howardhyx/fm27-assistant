import json,pathlib,struct,subprocess,sys,re
ROOT=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'vendor'))
OUT=ROOT.parents[1]/'outputs/fm27'
ops=json.loads((ROOT/'resources/team-header-schema.json').read_text(encoding='utf8'))

class Reader:
    def __init__(self,data,pos):self.data=data;self.pos=pos
    def take(self,n):
        if self.pos+n>len(self.data):raise ValueError('truncated')
        v=self.data[self.pos:self.pos+n];self.pos+=n;return v
    def u(self,n):return int.from_bytes(self.take(n),'little')

def team_header(data,start):
    r=Reader(data,start);fields={};offsets={}
    assert r.u(1)==2
    team_id=r.u(4);roster=r.u(1)
    assert 11<=roster<=40
    def apply(op):
        at,kind,offset,n=op
        if at==0x49cbc60:offset=0x152
        offsets[hex(offset)]=r.pos
        if kind=='REF':
            assert r.u(1)==2
            value=r.u(4)
        else:
            raw=r.take(n)
            if kind=='SWAP32':raw=bytes([raw[2],raw[1],raw[0],raw[3]])
            value=struct.unpack('<f',raw)[0]if kind=='FLOAT'else int.from_bytes(raw,'little')
        fields[hex(offset)]=value
    for op in ops:
        if 0x49cb14e<=op[0]<=0x49cb2ba:apply(op)
    maps=[]
    for _ in range(2):
        count=r.u(1)
        assert count<=100
        maps.append([(r.u(2),r.u(1))for _ in range(count)])
    for op in ops:
        if 0x49cb3f6<=op[0]<=0x49cc01b:apply(op)
    return {'team_id':team_id,'roster_count':roster,'start':start,'players_start':r.pos,
            'xg':fields['0x60'],'shots':fields['0x16f'],'shots_on_target':fields['0x170'],
            'passes_attempted':fields['0xd8'],'passes_completed':fields['0xda'],
            'possession_ticks':fields['0x7c'],'raw_fields':fields,'source_offsets':offsets,'maps':maps}

def decode_data(data):
    # The match input metadata is variable-sized; accept only candidates whose
    # team refs, roster counts and decoded statistics satisfy independent bounds.
    teams=[]
    for start in range(350,min(len(data),20000)):
        if data[start:start+1]!=b'\x02':continue
        try:t=team_header(data,start)
        except (AssertionError,ValueError,struct.error,KeyError):continue
        if not (0<=t['xg']<=30 and 0<=t['shots']<=100 and t['shots_on_target']<=t['shots'] and
                50<=t['passes_attempted']<=1800 and t['passes_completed']<=t['passes_attempted'] and
                100<=t['possession_ticks']<=200000):continue
        teams.append(t)
    return teams

def decode(key):
    return decode_data((ROOT/f'stats-city-{key}.bin').read_bytes())

