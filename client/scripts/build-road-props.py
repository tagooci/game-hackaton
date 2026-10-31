"""Малые локальные GLB: тоннель, остановка и знак переезда. Без текстур/CDN."""
import json
import math
import struct
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'public/content'


def model(name, boxes):
    positions=[];normals=[];colors=[];indices=[]
    for center,size,color,angle in boxes:
        for axis in range(3):
            for sign in [-1,1]:
                other=[i for i in range(3) if i!=axis]
                corners=[]
                for a,b in [(-1,-1),(1,-1),(1,1),(-1,1)]:
                    p=list(center);p[axis]+=sign*size[axis]/2
                    p[other[0]]+=a*size[other[0]]/2;p[other[1]]+=b*size[other[1]]/2
                    x,y=p[0]-center[0],p[1]-center[1]
                    p[0]=center[0]+x*math.cos(angle)-y*math.sin(angle)
                    p[1]=center[1]+x*math.sin(angle)+y*math.cos(angle)
                    corners.append(p)
                n=[0,0,0];n[axis]=sign
                n=[n[0]*math.cos(angle)-n[1]*math.sin(angle),n[0]*math.sin(angle)+n[1]*math.cos(angle),n[2]]
                u=[corners[1][i]-corners[0][i] for i in range(3)];v=[corners[2][i]-corners[0][i] for i in range(3)]
                cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
                base=len(positions)
                order=[0,1,2,0,2,3] if sum(a*b for a,b in zip(cross,n))>0 else [0,2,1,0,3,2]
                positions.extend([tuple(round(x*1000) for x in p)+(0,) for p in corners])
                normals.extend([tuple(round(x*127) for x in n)+(0,)]*4)
                def linear(c):return round(255*((c/255)/12.92 if c/255<=.04045 else ((c/255+.055)/1.055)**2.4))
                colors.extend([tuple(linear(c) for c in color)+(255,)]*4)
                indices.extend((base+i,) for i in order)
    data=bytearray();views=[];accessors=[]
    for rows,code,component,kind,stride,normalized in [(positions,'h',5122,'VEC3',8,False),(normals,'b',5120,'VEC3',4,True),(colors,'B',5121,'VEC4',4,True),(indices,'H',5123,'SCALAR',0,False)]:
        data.extend(b'\0'*(-len(data)%4));payload=b''.join(struct.pack('<'+code*len(row),*row) for row in rows)
        view={'buffer':0,'byteOffset':len(data),'byteLength':len(payload)}
        if stride:view['byteStride']=stride
        views.append(view);data.extend(payload)
        a={'bufferView':len(views)-1,'componentType':component,'count':len(rows),'type':kind}
        if normalized:a['normalized']=True
        if rows is positions:
            a['min']=[min(p[i] for p in rows) for i in range(3)];a['max']=[max(p[i] for p in rows) for i in range(3)]
        accessors.append(a)
    doc={'asset':{'version':'2.0'},'scene':0,'scenes':[{'nodes':[0]}],'nodes':[{'mesh':0,'name':name,'scale':[.001,.001,.001]}],
         'meshes':[{'primitives':[{'attributes':{'POSITION':0,'NORMAL':1,'COLOR_0':2},'indices':3,'material':0}]}],
         'materials':[{'name':name,'pbrMetallicRoughness':{'metallicFactor':0,'roughnessFactor':1}}],
         'buffers':[{'byteLength':len(data)}],'bufferViews':views,'accessors':accessors,
         'extensionsUsed':['KHR_mesh_quantization'],'extensionsRequired':['KHR_mesh_quantization']}
    j=json.dumps(doc,separators=(',',':')).encode();j+=b' '*(-len(j)%4);data.extend(b'\0'*(-len(data)%4))
    raw=struct.pack('<III',0x46546c67,2,28+len(j)+len(data))+struct.pack('<II',len(j),0x4e4f534a)+j+struct.pack('<II',len(data),0x004e4942)+data
    path=ROOT/'assets/props'/f'{name}.glb';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    return {'id':name,'kind':'model','url':f'/content/assets/props/{name}.glb','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def box(center,size,color,angle=0):return (center,size,color,angle)


def main():
    concrete=(133,142,154);blue=(42,115,165);metal=(58,69,78);earth=(104,132,92)
    tunnel=[box((-5.6,2.4,0),(1.2,4.8,10),concrete),box((5.6,2.4,0),(1.2,4.8,10),concrete),
            box((0,5.2,0),(12.4,.8,10),concrete),box((0,5.8,0),(15,.4,10),earth),
            box((-6.7,2.7,0),(1,5.4,10),earth),box((6.7,2.7,0),(1,5.4,10),earth)]
    stop=[box((0,.15,0),(8,.3,2.8),concrete),box((0,3.3,0),(8,.25,2.8),blue),
          box((-3.6,1.8,1),(.14,3,.14),metal),box((3.6,1.8,1),(.14,3,.14),metal),
          box((0,.8,.7),(6,.18,.7),(171,120,74)),box((-2,.4,.7),(.15,.8,.4),metal),box((2,.4,.7),(.15,.8,.4),metal),
          box((4.7,1.7,0),(.12,3.4,.12),metal),box((4.7,3.1,0),(.8,.8,.1),blue)]
    crossing=[box((0,1.8,0),(.12,3.6,.12),metal),box((0,3.2,0),(1.6,.2,.12),(239,235,219),math.pi/4),
              box((0,3.2,.02),(1.6,.2,.12),(205,58,48),-math.pi/4)]
    # Рельсовые головки выступают на 1 см; шпалы под асфальт не накладываются.
    inset=[box((0,-.02,z),(10,.06,.2),(94,103,112)) for z in [-.6,.6]]
    catalog=json.loads((ROOT/'asset-catalog.json').read_text())
    for name,boxes in [('tunnel-section',tunnel),('bus-stop',stop),('rail-crossing-sign',crossing),('railroad-crossing',inset)]:catalog[name]=model(name,boxes)
    (ROOT/'asset-catalog.json').write_text(json.dumps(catalog,indent=2)+'\n')
    print({name:catalog[name]['bytes'] for name in ['tunnel-section','bus-stop','rail-crossing-sign']})

if __name__=='__main__':main()
