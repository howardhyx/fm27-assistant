"""Bounded, read-only FM27 27.0 cache codecs. Unknown variants fail explicitly."""
import struct,json,pathlib,math
ROOT=pathlib.Path(__file__).resolve().parent
from decode_match_details import ops

class UnsupportedVariant(ValueError):pass
class Buffer:
    def __init__(self,data,start=0):self.data=data;self.pos=start
    def take(self,n):
        if n<0 or self.pos+n>len(self.data):raise ValueError(f'truncated at {self.pos}, requested {n}')
        v=self.data[self.pos:self.pos+n];self.pos+=n;return v
    def u(self,n=1):return int.from_bytes(self.take(n),'little')
    def f(self):
        v=struct.unpack('<f',self.take(4))[0]
        if not math.isfinite(v):raise ValueError(f'nonfinite scalar at {self.pos-4}')
        return v
    def ref(self):
        marker=self.u()
        if marker!=2:raise UnsupportedVariant(f'reference marker {marker} at {self.pos-1}')
        return self.u(4)
    def bounded_count(self,width,maximum):
        n=self.u(width)
        if n>maximum:raise ValueError(f'count {n} exceeds bound {maximum} at {self.pos-width}')
        return n

def identity_context(r):
    version=r.u();refs=[]
    for _ in range(4):
        marker=r.u();refs.append(r.u(4 if marker>=2 else 8))
    extra=r.u()if version<=1 else None
    count=r.bounded_count(4,10000)
    groups=[]
    for _ in range(count):
        key=r.u();n=r.bounded_count(4,10000)
        groups.append({'key':key,'values':[r.u(4)for _ in range(n)]})
    return {'version':version,'refs':refs,'extra':extra,'groups':groups}

def selection_player(r,version):
    if version!=9:raise UnsupportedVariant(f'selection player version {version}')
    p={'reference':r.ref(),'0x0':r.u(4),'0x4':r.u(4),'0x8':r.u(8),'0x10':r.u(8),'0x24':r.u(4),
       '0x1c':r.ref(),'0x28':r.u(4),'0x2d':r.u(),'0x20':r.ref(),'0x2e':r.u(),'0x2f':r.u()}
    return p

def selection_snapshot(r):
    start=r.pos;version=r.u();count=r.bounded_count(1,40)
    players=[selection_player(r,version)for _ in range(count)]
    result={'start':start,'version':version,'players':players,'date_minutes_raw':r.u(4),
            'references':[r.ref()for _ in range(3)],'0x6c':r.u(),'0x68':r.u(2),
            'identity_context':identity_context(r),'0x6b':r.u(),'0x64':r.u(4)}
    if version<=2:raise UnsupportedVariant(f'selection base version {version}')
    result['base']={'version':r.u(),'mask1':r.u(8),'mask2':r.u(8),'value':r.u(4),'flag':r.u()}
    result['end']=r.pos
    return result

def read_scalar(r,op):
    at,kind,offset,n=op
    if kind=='REF':value=r.ref()
    elif kind=='FLOAT':value=r.f()
    else:
        b=r.take(n)
        if kind=='SWAP32':b=bytes([b[2],b[1],b[0],b[3]])
        value=int.from_bytes(b,'little')
    return hex(offset),value

def team_tail(data,start):
    r=Buffer(data,start);fields={}
    for op in ops:
        if 0x49cc14d<=op[0]<=0x49cc1a5:k,v=read_scalar(r,op);fields[k]=v
    version=r.u()
    if version!=1:raise UnsupportedVariant(f'selection history wrapper version {version}')
    count=r.bounded_count(4,64)
    selections=[selection_snapshot(r)for _ in range(count)]
    for op in ops:
        if 0x49cc1d2<=op[0]<=0x49cc63b and op[0]!=0x49cc5ef:
            k,v=read_scalar(r,op);fields[k]=v
    fields['0x78']=r.f()
    return {'start':start,'end':r.pos,'selection_history':selections,'raw_fields':fields}

def trend_vector(r):
    n=r.bounded_count(4,50000);rows=[]
    for _ in range(n):
        rows.append({'key':r.u(4),'float0':r.f(),'float4':r.f(),'float10':r.f(),
                     'int14':r.u(4),'int18':r.u(4),'flag':r.u()})
    return rows

INCIDENT_KINDS={1:'goal',2:'own_goal',3:'penalty_goal',14:'second_yellow',15:'red_card',38:'yellow_card'}

def incident(r):
    start=r.pos;version=r.u()
    if version not in (1,2,3):raise UnsupportedVariant(f'incident version {version}')
    result={'source_offset':start,'version':version,'side':r.u(),'roster_index':r.u(),'kind':r.u(),
            'native_tick':r.u(4),'nominal_minute':r.u(),'added_minute':r.u(),
            'value14':r.u(4),'flags8':r.u(8),'flags0':r.u(8),'other_side':r.u(),'other_index':r.u()}
    result['position_mask']=r.ref()if version>=2 else None
    if version<=2:result['legacy_extra_hex']=r.take(16).hex()
    result['type']=INCIDENT_KINDS.get(result['kind'],'unconfirmed')
    result['display_minute']=str(result['nominal_minute'])+('+'+str(result['added_minute'])if result['added_minute']else '')
    return result

def advanced_shot(r):
    start=r.pos
    values=struct.unpack('<ffHH7BIB',r.take(24))
    x,y,flags1,flags2,outcome,player,side,unknown25,unknown26,minute,second,tick,flag=values
    if not all(math.isfinite(v)for v in (x,y)):raise ValueError('nonfinite advanced shot coordinate')
    return {'source_offset':start,'coordinate_values_unconfirmed':[x,y],'shot_flags':[flags1,flags2],
            'outcome_code':outcome,'roster_index':player,'side':side,'unknown25':unknown25,'unknown26':unknown26,
            'minute_raw':minute,'second_raw':second,'native_tick':tick,'flag':flag}

def match_extras(data,start):
    r=Buffer(data,start);flag=r.u()
    if flag not in (0,1):raise UnsupportedVariant(f'trend presence flag {flag}')
    trends=[trend_vector(r),trend_vector(r)]if flag else None
    clock={'raw_bytes_hex':r.take(5).hex()}
    scalars={'0xbf':r.u(),'0xba':r.u(2),'0xbc':r.u(2),'0xc1':r.u(),'0xc2':r.u(),'0xac':r.ref()}
    metadata=[]
    for _ in range(r.bounded_count(2,1000)):
        version=r.u()
        if version!=3:raise UnsupportedVariant(f'match metadata version {version}')
        metadata.append({'version':version,'raw_flags':[r.u()for _ in range(4)],'reference0':r.ref(),
                         'raw_flag_d':r.u(),'reference4':r.ref(),'raw_flag_c':r.u()})
    incidents=[incident(r)for _ in range(r.bounded_count(2,2000))]
    shots=[advanced_shot(r)for _ in range(r.bounded_count(1,255))]
    flags={hex(o):r.u()for o in [0xc5,0xc4,0xc8,0xc9,0xca,0xcb,0xce,0xcc,0xcd,0xcf,0xd0,0xc6,0xc7]}
    return {'start':start,'end':r.pos,'trends':trends,'clock':clock,'scalars':scalars,'metadata':metadata,
            'incidents':incidents,'advanced_shots':shots,'flags':flags,
            'following_bytes_not_decoded':len(data)-r.pos}

