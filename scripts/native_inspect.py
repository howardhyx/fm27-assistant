import sys
import os
import struct
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'vendor'))

DLL=Path(os.environ['FM27_GAME_DLL'])
class PE:
    def __init__(self,path=DLL):
        self.path=path
        with path.open('rb') as f:
            header=f.read(4096)
        pe=struct.unpack_from('<I',header,0x3c)[0]
        n=struct.unpack_from('<H',header,pe+6)[0]
        opt=struct.unpack_from('<H',header,pe+20)[0]
        self.base=struct.unpack_from('<Q',header,pe+24+24)[0]
        self.sections=[]
        for i in range(n):
            at=pe+24+opt+40*i
            vs,rva,rs,off=struct.unpack_from('<4I',header,at+8)
            self.sections.append((rva,rs,off))
    def read(self,rva,size):
        for start,length,off in self.sections:
            if start<=rva and rva+size<=start+length:
                with self.path.open('rb') as f:
                    f.seek(off+rva-start)
                    return f.read(size)
        raise ValueError(hex(rva))
