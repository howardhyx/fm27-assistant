import sys
import os
import struct
import hashlib
from functools import lru_cache
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'vendor'))

DLL=Path(os.environ['FM27_GAME_DLL'])

@lru_cache(maxsize=4)
def _dll_hash(path,mtime_ns,size):
    with Path(path).open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    after=Path(path).stat()
    if (after.st_mtime_ns,after.st_size)!=(mtime_ns,size):raise ValueError('Game DLL changed during validation')
    return digest

def dll_hash():
    stat=DLL.stat()
    return _dll_hash(str(DLL),stat.st_mtime_ns,stat.st_size)
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
