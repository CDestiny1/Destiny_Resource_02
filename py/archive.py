"""Strict CRI CPK / UTF and PES WESYS codec. Standard library only."""
import struct
import zlib
from pathlib import PurePosixPath

MAX_RAW = 256 * 1024 * 1024
FORMATS = {0:'>B',1:'>b',2:'>H',3:'>h',4:'>I',5:'>i',6:'>Q',7:'>q',8:'>f',10:'>I',11:'>II'}

def crypt(data):
    key=0x655f; out=bytearray()
    for v in data:
        out.append(v^(key&255)); key=(key*0x4115)&0xffffffff
    return bytes(out)

def cstr(data, off, length=None):
    if off < 0 or off >= len(data): raise ValueError('Texto fuera del archivo')
    b=data[off:off+length] if length is not None else data[off:]
    return b.split(b'\0',1)[0].decode('utf-8','replace')

def inflate(data):
    d=zlib.decompressobj(); raw=d.decompress(data,MAX_RAW+1)
    if len(raw)>MAX_RAW or d.unconsumed_tail: raise ValueError('Archivo descomprimido demasiado grande')
    if not d.eof: raise ValueError('Compresión zlib incompleta')
    return raw

def unlayla(data):
    if not data.startswith(b'CRILAYLA'): return data
    if len(data)<16: raise ValueError('CRILAYLA incompleto')
    size,offset=struct.unpack_from('<II',data,8)
    if size>MAX_RAW or 16+offset+256>len(data): raise ValueError('Tamaño CRILAYLA no válido')
    out=bytearray(size+256); out[:256]=data[16+offset:16+offset+256]
    pos=15+offset; pool=0; available=0; dst=len(out)-1
    def bits(n):
        nonlocal pos,pool,available
        v=0
        for _ in range(n):
            if not available:
                if pos<16: raise ValueError('Flujo CRILAYLA truncado')
                pool=data[pos];pos-=1;available=8
            available-=1; v=(v<<1)|((pool>>available)&1)
        return v
    while dst>=256:
        if bits(1):
            distance=bits(13)+3; count=3
            for width in (2,3,5,8):
                v=bits(width);count+=v
                if v != (1<<width)-1: break
            else:
                while v==255: v=bits(8);count+=v
            if count>dst-255: raise ValueError('Referencia CRILAYLA fuera de rango')
            for _ in range(count):
                if dst+distance>=len(out): raise ValueError('Referencia CRILAYLA no válida')
                out[dst]=out[dst+distance];dst-=1
        else: out[dst]=bits(8);dst-=1
    return bytes(out)

def unwrap(blob):
    if blob[3:8]==b'WESYS':
        if len(blob)<16: raise ValueError('WESYS incompleto')
        cs,us=struct.unpack_from('<II',blob,8)
        if cs+16 != len(blob) or us>MAX_RAW: raise ValueError('Tamaño WESYS no válido')
        if blob[2] not in (0,1,0x80,0x81): raise ValueError('Variante WESYS no compatible')
        raw=inflate(blob[16:]) if blob[2]&1 else blob[16:]
        if len(raw)!=us: raise ValueError('Tamaño interno WESYS incorrecto')
        return raw,blob[:8]
    if len(blob)>2 and blob[0]==0x78 and ((blob[0]<<8)|blob[1])%31==0:
        return inflate(blob),b'ZLIB'
    return blob,b''

def wrap(raw,header):
    if header==b'ZLIB': return zlib.compress(raw,6)
    if not header:return raw
    payload=zlib.compress(raw,6) if header[2]&1 else raw
    return header+struct.pack('<II',len(payload),len(raw))+payload

class UTF:
    def __init__(self,raw):
        if raw[:4]!=b'@UTF' or len(raw)<32:raise ValueError('Tabla UTF no válida')
        self.raw=bytearray(raw); self.rows=[];self.locations=[];self.columns=[]
        ro,so,do,no,nc,rw,nr=struct.unpack_from('>IIIIHHI',raw,8)
        ro+=8;so+=8;do+=8
        if nr>1000000 or ro+rw*nr>len(raw) or so>len(raw):raise ValueError('Offsets UTF no válidos')
        p=32
        for i in range(nc):
            flag=raw[p];p+=1
            if flag==0:p+=3;flag=raw[p];p+=1
            name=cstr(raw,so+struct.unpack_from('>I',raw,p)[0]);p+=4
            typ=flag&15;storage=flag&240
            if typ not in FORMATS:raise ValueError('Tipo UTF no compatible')
            loc=None
            if storage==0x30:loc=p;p+=struct.calcsize(FORMATS[typ])
            elif storage not in (0x10,0x50):raise ValueError('Almacenamiento UTF no compatible')
            self.columns.append((name,typ,storage,loc))
        for r in range(nr):
            vals=[];locs=[];p=ro+r*rw
            for name,typ,storage,constant in self.columns:
                loc=constant if storage==0x30 else (p if storage==0x50 else None)
                if storage==0x50:p+=struct.calcsize(FORMATS[typ])
                value=0 if loc is None else struct.unpack_from(FORMATS[typ],raw,loc)
                if isinstance(value,tuple):value=value[0] if len(value)==1 else value
                if typ==10:value=cstr(raw,so+value) if loc is not None else ''
                vals.append(value);locs.append(loc)
            self.rows.append(vals);self.locations.append(locs)
        self.names={c[0]:i for i,c in enumerate(self.columns) if c[0]}
    def get(self,name,row=0,default=0):
        return self.rows[row][self.names[name]] if name in self.names else default
    def set(self,name,value,row=0):
        idx=self.names[name] if isinstance(name,str) else name
        if self.rows[row][idx]==value:return
        loc=self.locations[row][idx]
        if loc is None:raise ValueError('Campo UTF constante no modificable: '+str(name))
        if self.columns[idx][2]==0x30 and len(self.rows)>1:raise ValueError('Campo UTF compartido no modificable')
        struct.pack_into(FORMATS[self.columns[idx][1]],self.raw,loc,value);self.rows[row][idx]=value

class CPK:
    def __init__(self,data):
        self.data=bytes(data)
        self.header,self.header_encrypted=self.packet(0,b'CPK ')
        h=self.header
        self.content=h.get('ContentOffset');self.tocoffset=h.get('TocOffset');self.align=h.get('Align') or 2048
        if not self.content or not self.tocoffset or self.align not in (16,32,64,128,256,512,1024,2048,4096):raise ValueError('CPK sin índice de nombres compatible')
        self.toc,self.toc_encrypted=self.packet(self.tocoffset,b'TOC ')
        self.base=min(self.content,self.tocoffset);self.entries=[];self.by_name={}
        expected=['DirName','FileName','FileSize','ExtractSize','FileOffset','ID']
        self.tc=[self.toc.names[x] for x in expected] if all(x in self.toc.names for x in expected) else list(range(6))
        if len(self.toc.columns)<6:raise ValueError('Índice CPK no compatible')
        for i,row in enumerate(self.toc.rows):
            d,n,fs,es,fo,fid=[row[j] for j in self.tc]
            name=(str(d).rstrip('/')+'/'+str(n)).lstrip('/').replace('\\','/')
            p=PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or ':' in name or '\x00' in name:raise ValueError('Ruta CPK no válida')
            if name.casefold() in self.by_name:raise ValueError('Ruta CPK duplicada')
            if fs<0 or self.base+fo<16 or self.base+fo+fs>len(data):raise ValueError('Contenido CPK truncado: '+name)
            e={'path':name,'size':fs,'extract':es,'offset':fo,'id':fid,'row':i}
            self.entries.append(e);self.by_name[name.casefold()]=e
        if h.get('Files')!=len(self.entries):raise ValueError('Conteo de archivos CPK inconsistente')
    def packet(self,offset,magic):
        if offset<0 or offset+16>len(self.data) or self.data[offset:offset+4]!=magic:raise ValueError('Paquete CPK no válido')
        size=struct.unpack_from('<Q',self.data,offset+8)[0]
        if size>32*1024*1024 or offset+16+size>len(self.data):raise ValueError('Paquete CPK incompleto')
        raw=self.data[offset+16:offset+16+size];encrypted=raw[:4]!=b'@UTF'
        return UTF(crypt(raw) if encrypted else raw),encrypted
    def stored(self,e):return self.data[self.base+e['offset']:self.base+e['offset']+e['size']]
    def read(self,e):
        raw=unlayla(self.stored(e))
        if len(raw)!=e['extract']:raise ValueError('Tamaño de entrada CPK incorrecto: '+e['path'])
        return raw
    def rebuild(self,replacements):
        if not replacements:return self.data
        h= self.header
        for field in ('ItocOffset','GtocOffset','HtocOffset','HgtocOffset','EnableTocCrc','EnableFileCrc'):
            if h.get(field) not in (0,0xffffffffffffffff):raise ValueError('CPK con índice/CRC adicional no soportado: '+field)
        header= UTF(bytes(h.raw));toc=UTF(bytes(self.toc.raw))
        out=bytearray(self.data[:self.content]);total_stored=0;total_extract=0
        def pad():out.extend(b'\0'*((-len(out))%self.align))
        for e in sorted(self.entries,key=lambda e:e['offset']):
            pad();payload=replacements.get(e['path'],self.stored(e));es=len(payload) if e['path'] in replacements else e['extract']
            for field,val in [(2,len(payload)),(3,es),(4,len(out)-self.content)]:toc.set(self.tc[field],val,e['row'])
            out.extend(payload);total_stored+=len(payload);total_extract+=es
        pad();to=len(out)
        def emit(magic,tbl,enc):
            raw=bytes(tbl.raw);raw=crypt(raw) if enc else raw
            return magic+struct.pack('<IQ',0xff,len(raw))+raw
        tp=emit(b'TOC ',toc,self.toc_encrypted);out.extend(tp);pad()
        etocoffset=0;etocsize=0
        old_etoc=h.get('EtocOffset')
        if old_etoc and old_etoc!=0xffffffffffffffff:
            etocoffset=len(out); tbl,enc=self.packet(old_etoc,b'ETOC');ep=emit(b'ETOC',tbl,enc);out.extend(ep);etocsize=len(ep);pad()
        values={'TocOffset':to,'TocSize':len(tp),'ContentSize':to-self.content,'EtocOffset':etocoffset,'EtocSize':etocsize,
                'EnabledPackedSize':total_stored,'EnabledDataSize':total_extract}
        if h.get('FileSize'):values['FileSize']=len(out)
        if h.get('TotalDataSize'):values['TotalDataSize']=total_extract
        for key,value in values.items():
            if key in header.names:header.set(key,value)
        hp=emit(b'CPK ',header,self.header_encrypted)
        if len(hp)>self.content:raise ValueError('Cabecera CPK demasiado grande')
        out[:len(hp)]=hp
        # Reopen independently from offsets; verify EVERY original stored payload.
        result=bytes(out);check=CPK(result)
        for e in self.entries:
            ce=check.by_name[e['path'].casefold()]
            expected=replacements.get(e['path'],self.stored(e))
            if check.stored(ce)!=expected:raise ValueError('Verificación CPK fallida: '+e['path'])
        return result
