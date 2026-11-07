import sys,struct,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'vendor'))
from unicorn import Uc,UC_ARCH_X86,UC_MODE_64,UC_HOOK_CODE,UC_HOOK_MEM_UNMAPPED,UcError
from unicorn.x86_const import *
from native_inspect import PE

class PlayerDecoder:
    """Run only the pure scalar reader in a virtual CPU, with bounded stream shims.

    No DLL is loaded into the host process and no operating-system/game API runs.
    An unknown helper immediately aborts rather than being silently approximated.
    """
    OBJECT=0x10010000;STREAM=0x10003000;REF=0x10002000
    STACK=0x20000000;STOP=0x10005000
    def __init__(self,data,start):
        self.pe=PE();self.data=data;self.pos=start;self.trace=[];self.error=None;self.steps=0
        self.uc=Uc(UC_ARCH_X86,UC_MODE_64)
        self.uc.mem_map(0x10000000,0x200000)
        self.uc.mem_map(self.STACK,0x200000)
        self.uc.mem_map(0x30000000,0x1000000)
        self.alloc_cursor=0x30000000
        self.event_maps={};self.event_vectors={}
        self.write64(self.REF,self.STREAM)
        self.uc.hook_add(UC_HOOK_MEM_UNMAPPED,self.map_native)
        self.uc.hook_add(UC_HOOK_CODE,self.step)
    def write64(self,at,value):self.uc.mem_write(at,struct.pack('<Q',value))
    def read64(self,at):return struct.unpack('<Q',self.uc.mem_read(at,8))[0]
    def reg(self,reg):return self.uc.reg_read(reg)
    def take(self,dest,size):
        if size>100000 or self.pos+size>len(self.data):raise ValueError('bounded reader overrun')
        self.trace.append({'source':self.pos,'dest':dest,'size':size})
        self.uc.mem_write(dest,self.data[self.pos:self.pos+size]);self.pos+=size
    def map_native(self,uc,access,address,size,value,user):
        page=address&~4095
        if not self.pe.base<=page<self.pe.base+0x18300000:return False
        try:b=self.pe.read(page-self.pe.base,4096)
        except ValueError:b=bytes(4096)
        uc.mem_map(page,4096);uc.mem_write(page,b)
        return True
    def flush(self,b):
        size=self.read64(b+0x10)
        if size:self.take(self.read64(b+8),size)
        self.uc.mem_write(b+8,bytes(24))
    def ret(self,value=1):
        sp=self.reg(UC_X86_REG_RSP);pc=self.read64(sp)
        self.uc.reg_write(UC_X86_REG_RAX,value)
        self.uc.reg_write(UC_X86_REG_RSP,sp+8)
        self.uc.reg_write(UC_X86_REG_RIP,pc)
    def allocate(self,n):
        at=self.alloc_cursor;self.alloc_cursor+=(n+15)&~15
        if self.alloc_cursor>=0x31000000:raise ValueError('virtual allocation bound')
        return at
    def event_vector(self,obj,key):
        if (obj,key) in self.event_vectors:return self.event_vectors[(obj,key)]
        if obj not in self.event_maps:
            base=self.allocate(64*32);self.event_maps[obj]=[base,0]
            self.write64(obj,base);self.write64(obj+8,base);self.write64(obj+16,base+64*32)
        base,count=self.event_maps[obj]
        if count>=64:raise ValueError('event group bound')
        record=base+32*count;self.uc.mem_write(record,struct.pack('<H',key))
        buf=self.allocate(256*32)
        self.write64(record+8,buf);self.write64(record+16,buf);self.write64(record+24,buf+256*32)
        self.event_maps[obj][1]+=1;self.write64(obj+8,record+32)
        self.event_vectors[(obj,key)]=record+8
        return record+8
    def step(self,uc,address,size,user):
        self.steps+=1
        if self.steps>100000:raise RuntimeError('instruction bound')
        if address==self.STOP:uc.emu_stop();return
        rva=address-self.pe.base
        if 0x49d0770<=rva<0x49d133b:return
        cx=self.reg(UC_X86_REG_RCX);dx=self.reg(UC_X86_REG_RDX)
        try:
            if rva==0x15bdb0:
                uc.mem_write(cx,struct.pack('<Q',self.read64(dx))+bytes(24));self.ret(cx)
            elif rva in (0x15bd70,0x384cd00,0x162af0):self.flush(cx);self.ret(cx)
            elif rva in (0x1637f0,0x1ac33b0):
                tag=self.data[self.pos];self.pos+=1
                if tag!=2:raise ValueError(f'unsupported reference marker {tag} at {self.pos-1}')
                self.take(cx,4);self.ret(1)
            elif rva==0x407def0:
                self.flush(cx);self.take(dx,4);self.ret(cx)
            elif rva==0x495c870:self.ret()
            elif rva==0x68f10:
                key=struct.unpack('<H',uc.mem_read(dx,2))[0]
                self.ret(self.event_vector(cx,key))
            else:raise RuntimeError(f'unhandled helper {rva:#x} at stream {self.pos}, cx={cx:#x}, dx={dx:#x}')
        except Exception as exc:
            self.error=exc;uc.emu_stop()
    def decode(self):
        sp=self.STACK+0x1ff008;self.write64(sp,self.STOP)
        self.uc.reg_write(UC_X86_REG_RSP,sp)
        self.uc.reg_write(UC_X86_REG_RCX,self.OBJECT)
        self.uc.reg_write(UC_X86_REG_RDX,self.REF)
        self.uc.reg_write(UC_X86_REG_R8,60)
        try:self.uc.emu_start(self.pe.base+0x49d0770,self.STOP+1,count=100000)
        except UcError as exc:raise RuntimeError(f'CPU error {exc}; rip={self.reg(UC_X86_REG_RIP):#x} stream={self.pos}') from exc
        if self.error:raise self.error
        if self.reg(UC_X86_REG_RAX)&255!=1:raise ValueError('native scalar reader rejected input')
        return bytes(self.uc.mem_read(self.OBJECT,0x110)),self.pos,self.trace
    def events(self):
        result=[]
        for (obj,key),vec in self.event_vectors.items():
            start=self.read64(vec);end=self.read64(vec+8)
            for at in range(start,end,32):
                result.append({'group':key,'payload_hex':bytes(self.uc.mem_read(at+8,24)).hex()})
        return result

