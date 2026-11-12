import json
import struct
import sys
import warnings
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'vendor'))
import fmsave

catalog=json.loads((ROOT/'resources/tactic-catalog.json').read_text(encoding='utf8'))
enums={t['Type']:{x['Value']:x['Name'] for x in t['Values']} for t in json.loads((ROOT/'resources/ui-enums.json').read_text(encoding='utf-8-sig'))}
ROLE_MASK=0xfffffffbf91fffff
PI_ZH={'PI_STAY_WIDER':'拉开宽度','PI_SHOOT_LESS':'减少射门','PI_PLAY_NARROW':'靠近中路',
       'PI_HOLD_UP_BALL':'控球等待支援','PI_ROAM_FROM_POSITION':'自由跑位','PI_DRIBBLE_MORE':'更多盘带',
       'PI_CUT_INSIDE_WITH_BALL':'带球内切','PI_SHOOT_MORE':'更多射门'}

class Reader:
    def __init__(self,data,offset=0):self.data=data;self.pos=offset
    def take(self,n):
        if n<0 or self.pos+n>len(self.data):raise ValueError('truncated stream')
        result=self.data[self.pos:self.pos+n];self.pos+=n;return result
    def u(self,n):return int.from_bytes(self.take(n),'little')
    def string(self):
        n=self.u(4)
        if n>10000:raise ValueError('bad string length')
        return self.take(n).decode('utf8')

def pi(r):
    tag=r.u(1);version=r.u(1)
    if tag!=2 or version!=2:raise ValueError(f'unsupported PI header {tag}:{version}')
    count=r.u(1)
    if count>2:raise ValueError('unexpected PI word count')
    flags=r.u(count*4)
    if flags>>43:raise ValueError('unexpected PI flags')
    target_player=r.u(1);target_position=r.u(4)
    selected=[x['Name'] for x in enum_pi if x['Value'] and flags>>x['Value']&1]
    return {'flags':str(flags),'instructions':selected,'instructions_zh':[PI_ZH.get(x,x) for x in selected],
            'target_player':target_player,'target_position':target_position}

enum_pi=next(t['Values'] for t in json.loads((ROOT/'resources/ui-enums.json').read_text(encoding='utf-8-sig')) if t['Type']=='FM.UI.PlayerInstruction')

def slot(r,phase):
    start=r.pos
    revision=r.u(2);tag=r.u(1)
    if revision!=68 or tag!=2:raise ValueError(f'unexpected slot header {revision}:{tag} at {start}')
    position=r.u(4)
    flags=[r.u(1) for _ in range(3)]
    count=r.u(4)
    if count>100:raise ValueError('invalid role overrides')
    overrides=[]
    for _ in range(count):
        key=r.u(8)
        overrides.append({'role_key':str(key),'personal':pi(r)})
    count2=r.u(4)
    if count2>100:raise ValueError('invalid player overrides')
    player_overrides=[{'player_reference':r.u(4),'flags':str(r.u(8))} for _ in range(count2)]
    current=r.u(8)
    enum_name='FM.UI.InPossessionRole' if phase==0 else 'FM.UI.OutOfPossessionRole'
    role=current&ROLE_MASK
    if role not in enums[enum_name]:raise ValueError(f'unmapped current role {role}')
    active=[p for p in overrides if int(p['role_key'])&ROLE_MASK==role]
    if len(active)>1:raise ValueError('ambiguous role overrides')
    role_id=enums[enum_name][role]
    c=next((c for c in catalog['roles'] if c['phase']==phase and int(c['flags'])==role),None)
    return {'offset':start,'end':r.pos,'position_mask':position,'flags':flags,'current_role_flags':str(current),
            'current_role_name':role_id,'current_role_label':c['label'] if c else None,'duty_bits':str(current&~ROLE_MASK),
            'personal':active[0]['personal'] if active else None,'stored_role_overrides':overrides,'player_overrides':player_overrides}

def decode_team(raw):
    if raw[:1]!=b'\x04' or raw[3:6]!=bytes([7,2,3]):raise ValueError('unsupported team instruction layout')
    bits=int.from_bytes(raw[6:18],'little')
    if bits>>84:raise ValueError('unexpected team bits')
    groups=[]
    for group in catalog['team_instructions']:
        active=[o for o in group['options'] if o['native_bit'] and bits>>o['native_bit']&1]
        if len(active)>1:raise ValueError(f'ambiguous team instruction {group["name"]}')
        default=next((o for o in group['options'] if not o['native_bit']),None)
        option=active[0] if active else default
        if option is None:raise ValueError(f'no value/default for {group["name"]}')
        if enums['FM.UI.TacticTeamInstructionOptions'].get(option['id']) is None:raise ValueError('local option enum mismatch')
        enum_option=enums['FM.UI.TacticTeamInstructionOptions'][option['id']]
        corrected_label={'AttackTransitionHoldShape':'保持阵型','AttackTransitionCounter':'反击'}.get(enum_option,option['label'])
        groups.append({'group':group['name'],'label':group['label'],'phase':group['possession_phase'],
                       'option':enum_option,'option_label':corrected_label,'source_catalog_label':option['label'],
                       'native_bit':option['native_bit'],'explicit_bit':bool(active)})
    known=sum(1<<b for b in {o['native_bit'] for g in catalog['team_instructions'] for o in g['options'] if o['native_bit']})
    return {'raw_hex':raw.hex(),'bits':str(bits),'unknown_set_bits':[b for b in range(84) if bits>>b&1 and not known>>b&1],
            'style_code':raw[1],'mentality_code':raw[2],'groups':groups}

def decode_record(section,start):
    r=Reader(section,start+8);name=r.string()
    if r.take(12)!=bytes(12):raise ValueError('unsupported tactic metadata')
    team=decode_team(r.take(19));style=r.string();style_code=r.u(4);slots=[]
    for number in range(11):
        ip=slot(r,0);oop=slot(r,1);index=r.u(1)
        if index>=11:raise ValueError('invalid out-of-possession slot index')
        slots.append({'number':number,'ip':ip,'oop':oop,'oop_index':index})
    if sorted(x['oop_index']for x in slots)!=list(range(11)):raise ValueError('invalid out-of-possession permutation')
    return {'record_offset':start,'end':r.pos,'name':name,'team':team,'style':style,'style_code':style_code,'slots':slots}

def read_tactics(save,team_id):
    """Locate declared records by arbitrary stored names, then verify against the independent team walk."""
    rows=list(save.tactics())
    with save._context.section('tactics_man')as section:
        signature=bytes.fromhex('2244001b000000')
        if save.info.build=='27.0.1+2494687':
            from fmsave.readers.tactics import primary_collection_end,find_tactics_layout
            layout=find_tactics_layout(save.info.section_schemas.get('tactics_man'),save.info.build)
            section=section[:primary_collection_end(section,layout,save.info.file_name)]
            signature=bytes.fromhex('2244001b000100')
        byname={}
        for row in rows:byname.setdefault(row.name,[]).append(row)
        decoded=[]
        for name,declared in byname.items():
            word=name.encode('utf8');needle=struct.pack('<I',len(word))+word;starts=[];at=0
            while True:
                at=section.find(needle,at)
                if at<0:break
                if at>=8 and section[at-8:at-1]==signature:starts.append(at-8)
                at+=1
            if len(starts)!=len(declared):raise ValueError(f'ambiguous tactic record binding for {name!r}: declared {len(declared)}, located {len(starts)}')
            for row,start in zip(declared,starts):
                if row.team_id!=team_id:continue
                current=decode_record(section,start)
                raw=bytes(row.unknown[f'team_instruction_{i:02d}']for i in range(19))
                if current['team']['raw_hex']!=raw.hex():raise ValueError('tactic/team instruction binding disagreement')
                for actual,old in zip(current['slots'],row.slots):
                    actual['ip']['position_labels']=[p.label_text for p in old.in_possession_positions]
                    actual['oop']['position_labels']=[p.label_text for p in old.out_of_possession_positions]
                    if actual['ip']['position_mask']!=old.in_possession_mask or actual['oop']['position_mask']!=old.out_of_possession_mask:
                        raise ValueError('tactic/formation binding disagreement')
                    if actual['oop_index']!=old.unknown['out_of_possession_position_index']:raise ValueError('tactic permutation disagreement')
                    for phase,prefix,settings in [('ip','in_possession',old.in_possession_settings),('oop','out_of_possession',old.out_of_possession_settings)]:
                        if settings:
                            expected=(old.unknown[prefix+'_trail_bits']<<32)|settings[-1].second_bits_high
                            if int(actual[phase]['current_role_flags'])!=expected:raise ValueError('selected role binding disagreement')
                def phase(p):
                    return {k:v for k,v in p.items()if k not in ('offset','end','stored_role_overrides')}
                decoded.append({'team_id':row.team_id,'team_slot':row.team_slot,'club_uid':row.club_uid,'index':row.index,
                    'name':current['name'],'style_name':current['style'],'mentality':row.mentality.label_text,
                    'team_instructions':current['team'],'formation':[{'slot':s['number'],'in_possession':phase(s['ip']),
                    'out_of_possession':phase(s['oop']),'out_of_possession_index':s['oop_index']}for s in current['slots']],
                    'source_record_offset':start,'current_tactic_selected':None,
                    'personal_instruction_scope':'stored overrides for current role; role defaults are not expanded'})
    return decoded

