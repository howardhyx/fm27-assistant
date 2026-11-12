"""Pinned, bounded reader for the recorded tactical-command queue.

The native queue reader (49740d0) reads a count/revision and then a seven-byte
base header plus a kind-specific payload. Never resynchronize past an unknown
payload. A located candidate must consume the frame exactly and be unique.
"""
import struct
from extended_match_reader import Buffer,UnsupportedVariant,selection_snapshot
from tactic_codec import Reader,decode_team,slot,catalog,enums

KINDS={1:'in_possession_slot_change',4:'substitution',7:'team_talk',8:'tactic_name_change',
       9:'human_flag_change',13:'team_settings_change',14:'marker',17:'touchline_team_talk',
       24:'ip_to_oop_mapping_change',25:'out_of_possession_slot_change',
       27:'apply_tactical_tweak',28:'remove_tactical_tweak'}
TWEAK_ZH={0:'喘口气',1:'从后场组织',2:'全力进攻',3:'稳守',4:'门将参与定位球',
          5:'长传推进',6:'提高紧迫性',7:'踢得更耐心',8:'加强身体对抗',9:'利用宽度'}
GROUPS={g['id']:g for g in catalog['team_instructions']}


def string(r):return r.take(r.bounded_count(4,10000)).decode('utf8')


def tweak_name(number):return enums.get('FM.UI.TacticalTweak',{}).get(number,'unknown')


def parse_queue(data,start):
    r=Buffer(data,start);count=r.bounded_count(2,1000);revision=r.u(2)
    if revision!=68:raise UnsupportedVariant('tactical command revision')
    rows=[];previous_tick=0
    for index in range(count):
        at=r.pos;kind=r.u();tick=r.u(4);side=r.u();minute=r.u()
        if kind not in KINDS:raise UnsupportedVariant(f'Unsupported tactical command kind {kind} at {at}')
        if side not in(0,1)or tick>1000000 or tick<previous_tick:
            raise UnsupportedVariant('tactical command side or time order')
        previous_tick=tick;payload={}
        if kind==14:pass
        elif kind==7:payload=selection_snapshot(r)
        elif kind==9:payload={'human_flags_raw':r.u(4)}
        elif kind==4:payload={'off_roster_index':r.u(),'on_roster_index':r.u()}
        elif kind==8:payload={'name':string(r)}
        elif kind==13:
            payload={'team_instructions':decode_team(r.take(19)),'style_name':string(r),'style_code':r.u(4)}
        elif kind in(1,25):
            number=r.u()
            if number>=11:raise UnsupportedVariant('tactical slot out of range')
            reader=Reader(data,r.pos);settings=slot(reader,0 if kind==1 else 1);r.pos=reader.pos
            payload={'slot':number,'phase':'in_possession'if kind==1 else 'out_of_possession','settings':settings}
        elif kind==24:
            payload={'in_possession_slot':r.u(),'out_of_possession_index':r.u()}
            if max(payload.values())>=11:raise UnsupportedVariant('tactical mapping out of range')
        elif kind==27:
            number=r.u();target=r.u();axis=r.u()
            payload={'tweak_id':number,'tweak_name':tweak_name(number),'label_zh':TWEAK_ZH.get(number),
                     'target_raw':target,'axis_raw':axis}
            absolute=[]
            for _ in range(r.bounded_count(2,100)):
                native_bit=r.u();group_id=r.u();entry={'native_bit':native_bit,'group_id':group_id}
                if axis==0 and group_id in GROUPS:
                    group=GROUPS[group_id];options=[o for o in group['options']if o['native_bit']==native_bit]
                    if len(options)!=1:raise UnsupportedVariant('unmapped tactical tweak absolute override')
                    option=options[0];name=enums['FM.UI.TacticTeamInstructionOptions'][option['id']]
                    label={'AttackTransitionHoldShape':'保持阵型','AttackTransitionCounter':'反击'}.get(name,option['label'])
                    entry.update(group=group['name'],option=name,option_label=label)
                absolute.append(entry)
            payload['absolute_overrides']=absolute
            payload['shift_overrides']=[{'group_id':r.u(),'direction_code':r.u()}for _ in range(r.bounded_count(2,100))]
            payload['mentality_override_code']=r.u()
        elif kind==28:
            number=r.u();payload={'tweak_id':number,'tweak_name':tweak_name(number),
                                  'label_zh':TWEAK_ZH.get(number),'target_raw':r.u()}
        elif kind==17:
            version=r.u()
            if version not in(1,2):raise UnsupportedVariant('touchline talk version')
            payload={'version':version,'value0_raw':r.u(4),'value1_raw':r.u(4)}
            if version>=2:payload['flag_raw']=r.u()
            payload['players']=[{'reference':r.ref(),'value_raw':r.u(4)}for _ in range(r.bounded_count(1,100))]
        rows.append({'index':index,'source_offset':at,'source_end':r.pos,'kind':kind,'type':KINDS[kind],
                     'native_tick':tick,'side':side,'recorded_minute':minute,'payload':payload})
    return {'source_start':start,'source_end':r.pos,'revision':revision,'count':count,'changes':rows}


def read_timeline(data,match,historical):
    lower=max(len(data)-65536,match['extras']['end'],
              max(t['evidence']['decoded_creator_prefix_end']for t in historical['teams']))
    candidates=[];unsupported_payloads=[]
    for at in range(lower,len(data)-3):
        if data[at+2:at+4]!=b'\x44\x00':continue
        count=struct.unpack_from('<H',data,at)[0]
        if count>1000:continue
        if count and (at+11>len(data)or data[at+4]not in KINDS):continue
        try:queue=parse_queue(data,at)
        except (ValueError,UnicodeDecodeError,KeyError,IndexError)as error:
            if 'Unsupported tactical command kind' in str(error):unsupported_payloads.append(str(error))
            continue
        if queue['source_end']==len(data):candidates.append(queue)
    if len(candidates)!=1:
        detail='; '.join(dict.fromkeys(unsupported_payloads))[:500]
        raise UnsupportedVariant(f'Expected unique complete tactical queue; found {len(candidates)}. Unsupported kinds/layouts are not skipped.'+(f' {detail}'if detail else''))
    queue=candidates[0]
    initial={t['team_id']:t for t in historical['teams']}
    previous={key:value['team_instructions']for key,value in initial.items()}
    substitutions=0
    for event in queue['changes']:
        team=match['teams'][event['side']];team_id=team['team_id'];event['team_id']=team_id
        payload=event['payload']
        if event['kind']==13:
            before=previous[team_id];after=payload['team_instructions'];diff=[]
            if before['mentality_code']!=after['mentality_code']:
                diff.append({'field':'mentality_code','before':before['mentality_code'],'after':after['mentality_code']})
            for a,b in zip(before['groups'],after['groups']):
                if a['group']!=b['group']:raise ValueError('instruction group order changed')
                if a['option']!=b['option']:
                    diff.append({'field':b['group'],'label':b['label'],'before':a['option'],'after':b['option'],
                                 'before_label':a['option_label'],'after_label':b['option_label']})
            payload['base_setting_changes']=diff
            delta=int(before['bits'])^int(after['bits'])
            payload['changed_native_bits']=[b for b in range(84)if delta>>b&1]
            previous[team_id]=after
        elif event['kind']==4:
            off=payload['off_roster_index'];on=payload['on_roster_index'];roster=team['players']
            if off>=len(roster)or on>=len(roster):raise ValueError('substitution roster index out of range')
            if roster[off]['off_tick_raw']!=event['native_tick']or roster[on]['on_tick_raw']!=event['native_tick']:
                raise ValueError('substitution tick disagrees with independent player statistics')
            payload['off_player']=roster[off]['identity'];payload['on_player']=roster[on]['identity'];substitutions+=1
    queue.update(initial_state={'scope':'serialized manager baseline preceding recorded commands; not a full effective-behavior snapshot',
                               'teams':historical['teams']},
                 verification={'whole_queue_consumed':True,'queue_ends_at_frame_eof':True,
                               'time_order_checked':True,'substitution_tick_cross_checks':substitutions},
                 limitations=[
                     'Recorded command time and order are decoded; no guessed conversion to seconds or stoppage display.',
                     'Queue coverage does not prove that every automatic AI adjustment was recorded.',
                     'Base team-setting replacements and tactical tweaks are separate layers; effective values/conflicts are not simulated.',
                     'Some talk/tweak/player-target fields and unknown instruction bits retain raw meanings.',
                     'Unsupported command kinds fail the whole timeline; they are never skipped.'])
    return queue
