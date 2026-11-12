"""Pinned 27.0.1 player scalar reader, using a bounded virtual stream only."""
import struct
from emulate_player_reader import PlayerDecoder
from unicorn import UcError
from unicorn.x86_const import *


class PlayerDecoder2701(PlayerDecoder):
    IO=0x10006000
    VTABLE=0x10007000
    ENTRY=0x263d150
    END=0x263da5b
    def __init__(self,data,start):
        if not 0<=start<len(data):raise ValueError('player start outside bounded stream')
        super().__init__(data,start)
        self.write64(self.STREAM,self.VTABLE)
        self.write64(self.STREAM+8,2)  # Keep the virtual stream alive across the pure reader.
        self.write64(self.VTABLE+0x28,self.IO)
    def step(self,uc,address,size,user):
        self.steps+=1
        if self.steps>100000:raise RuntimeError('instruction bound')
        if address==self.STOP:uc.emu_stop();return
        rva=address-self.pe.base
        if self.ENTRY<=rva<self.END:return
        # This leaf only maps position bits to a constant mask and has no calls.
        if 0x4bac170<=rva<0x4bac292:return
        try:
            if address==self.IO:
                if self.reg(UC_X86_REG_RCX)!=self.STREAM:raise ValueError('unexpected stream object')
                self.take(self.reg(UC_X86_REG_RDX),self.reg(UC_X86_REG_R8));self.ret(1)
            elif rva==0x7c940:
                key=struct.unpack('<H',uc.mem_read(self.reg(UC_X86_REG_RDX),2))[0]
                self.ret(self.event_vector(self.reg(UC_X86_REG_RCX),key))
            else:
                raise RuntimeError(f'unhandled 27.0.1 helper {rva:#x} at stream {self.pos}')
        except Exception as exc:
            self.error=exc;uc.emu_stop()
    def decode(self):
        sp=self.STACK+0x1ff008;self.write64(sp,self.STOP)
        self.uc.reg_write(UC_X86_REG_RSP,sp)
        self.uc.reg_write(UC_X86_REG_RCX,self.OBJECT)
        self.uc.reg_write(UC_X86_REG_RDX,self.REF)
        self.uc.reg_write(UC_X86_REG_R8,60)
        try:self.uc.emu_start(self.pe.base+self.ENTRY,self.STOP+1,count=100000)
        except UcError as exc:raise RuntimeError(f'CPU error {exc}; rip={self.reg(UC_X86_REG_RIP):#x} stream={self.pos}')from exc
        if self.error:raise self.error
        if self.reg(UC_X86_REG_RAX)&255!=1:raise ValueError('native scalar reader rejected input')
        return bytes(self.uc.mem_read(self.OBJECT,0x110)),self.pos,self.trace
