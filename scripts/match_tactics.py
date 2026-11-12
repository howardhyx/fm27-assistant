"""Recover team-owned creator snapshots from the cached simulation state.

This is a bounded structural locator, not a complete engine-state deserializer.
The owning team root and primary/secondary creator order are checked against
the pinned native reader. No lookup of today's saved tactic boards is used.
"""
import struct
from tactic_codec import decode_record
from extended_match_reader import UnsupportedVariant
from fmsave.models.tactics import TacticPosition

SIGNATURE = bytes.fromhex('2244001b000000')
NEW_SIGNATURE = bytes.fromhex('2244001b000100')

def creator_at(data,start,stop):
    # Inspect the first creator-shaped header; never skip an unfamiliar one.
    at=data.find(SIGNATURE[:4],start,stop)
    if at>=0 and data[at:at+7]not in(SIGNATURE,NEW_SIGNATURE):
        raise UnsupportedVariant('Unrecognized creator header; refusing template fallback')
    return at
# Opaque preset-tail profile observed before manager primary creators. It is
# not a semantic field mapping; unfamiliar variants must fail, not fall through
# to the next valid-looking default creator in the same team region.
PRIMARY_PREFIX = bytes(11)+(b'\x01'+bytes(21))*3+b'\x01'+bytes(2)
MENTALITY = {1:'very_defensive',2:'defensive',3:'cautious',4:'balanced',
             5:'positive',6:'attacking',7:'very_attacking'}


def read_match_tactics(data, teams, stats_end):
    roots=[]
    for team in teams:
        team_id=team['team_id']
        needle=b'\x03\x02'+struct.pack('<I',team_id)+b'\x02'
        cursor=stats_end
        candidates=[]
        while True:
            at=data.find(needle,cursor)
            if at<0:break
            cursor=at+1
            # Team-reference v3 followed by the engine team's own scalar body.
            # Input metadata repeats the reference but follows it with another
            # reference (03/0b), not the team's scalar flag (00/01).
            if at+24>len(data):continue
            if data[at+11:at+14]!=b'\x00\x00\x01':continue
            club_id=struct.unpack_from('<I',data,at+7)[0]
            if struct.unpack_from('<I',data,at+18)[0]!=club_id:continue
            if data[at+22]!=0 or data[at+23]not in (0,1):continue
            candidates.append({'offset':at,'team_id':team_id,'club_uid':club_id})
        if len(candidates)!=1:
            raise UnsupportedVariant(f'Ambiguous simulation team root for {team_id}: {len(candidates)}')
        roots.extend(candidates)
    roots.sort(key=lambda r:r['offset'])
    if len(roots)!=2 or [r['team_id']for r in roots]!=[t['team_id']for t in teams]:
        raise UnsupportedVariant('Simulation team roots disagree with match sides')
    result=[]
    for index,root in enumerate(roots):
        stop=roots[index+1]['offset']if index+1<len(roots)else len(data)
        start=creator_at(data,root['offset']+24,stop)
        if start<0 or start-root['offset']>65536:
            raise UnsupportedVariant('No bounded primary manager creator')
        if data[start-len(PRIMARY_PREFIX):start]!=PRIMARY_PREFIX:
            raise UnsupportedVariant('Unrecognized primary-manager creator prefix; refusing template fallback')
        record=decode_record(data,start)
        if record['end']>stop:raise UnsupportedVariant('Primary creator crosses team boundary')
        # Native 16dcf3 and 16dd0f read two creators in this order for revision68.
        secondary=creator_at(data,record['end'],stop)
        if secondary<0:raise UnsupportedVariant('Missing secondary manager creator')
        other=decode_record(data,secondary)
        if other['end']>stop:raise UnsupportedVariant('Secondary creator crosses team boundary')
        def phase(p):
            result={k:v for k,v in p.items()if k not in ('offset','end','stored_role_overrides')}
            labels=[]
            for bit in range(15):
                if not p['position_mask']>>bit&1:continue
                try:labels.append(TacticPosition(bit).name.lower())
                except ValueError:labels.append('unknown')
            result['position_labels']=labels
            return result
        result.append({'team_id':root['team_id'],'club_uid':root['club_uid'],
            'name':record['name'],'style_name':record['style'],
            'mentality':MENTALITY.get(record['team']['mentality_code'],'unknown'),
            'team_instructions':record['team'],
            'formation':[{'slot':s['number'],'in_possession':phase(s['ip']),
                          'out_of_possession':phase(s['oop']),
                          'out_of_possession_index':s['oop_index']}for s in record['slots']],
            'state_scope':'serialized simulation manager primary baseline; static view omits subsequent recorded commands',
            'opening_tactic_confirmed':False,'whole_match_tactic_confirmed':False,
            'personal_instruction_scope':'stored overrides for current role; role defaults are not expanded',
            'evidence':{'binding':'bounded team-root and creator-order checks; partial engine-state walk',
                        'team_root_offset':root['offset'],'team_region_end':stop,
                        'creator_offset':start,'decoded_creator_prefix_end':record['end'],
                        'secondary_creator_offset':secondary,
                        'opaque_primary_prefix_checked':True,
                        'creator_header_hex':data[start:start+8].hex(),
                        'native_reader_rvas':['4973930','15bde0','16c160','16dc80','16fca0']if data[start:start+7]==SIGNATURE else [],
                        'creator_order_evidence':'legacy native chain and structural checks'if data[start:start+7]==SIGNATURE else '27.0.1 structure revalidated; native owner-chain addresses not rederived',
                        'current_saved_boards_used':False}})
    return {'teams':result,'limitations':[
        'The static baseline alone does not establish effective kickoff/final settings or whole-match behavior.',
        'Read tactic-timeline for recorded timed changes; this static view omits them.',
        'Only the creator prefix is decoded; following creator/engine fields remain partial.',
        'Unknown set bits and duty bits are retained without guessed meanings.']}
