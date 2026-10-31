"""Импорт локальных Kenney ZIP; упаковка внешних изображений в GLB."""
import argparse, base64, hashlib, json, struct, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'public' / 'content'
ROADS = ['road-straight','road-bend','road-intersection','road-crossroad',
         'road-roundabout','road-side-entry','road-side-exit','road-side',
         'road-sign-stop','road-sign-warning','traffic-light','construction-barrier']

def pack(raw, archive, parent):
    # Kenney использует палитру с однотонными UV-островками.
    # Переносим её в vertex colors, удаляем текстуры и ненужные тангенты.
    # KHR_mesh_quantization встроен в GLTF loader и не требует WASM/CDN.
    import io, math
    from PIL import Image
    size = struct.unpack_from('<I', raw, 12)[0]
    doc = json.loads(raw[20:20+size]); source = raw[28+size:]
    image = Image.open(io.BytesIO(archive.read(parent+'/Textures/colormap.png'))).convert('RGB')
    old_accessors, old_views = doc['accessors'], doc['bufferViews']
    def values(index):
        a=old_accessors[index];v=old_views[a['bufferView']]
        count={'VEC2':2,'VEC3':3,'VEC4':4,'SCALAR':1}[a['type']]
        code={5126:'f',5125:'I',5123:'H',5121:'B'}[a['componentType']]
        stride=v.get('byteStride',struct.calcsize('<'+code*count))
        return [struct.unpack_from('<'+code*count,source,v.get('byteOffset',0)+a.get('byteOffset',0)+i*stride) for i in range(a['count'])]
    max_abs=max(abs(c) for m in doc['meshes'] for p in m['primitives'] for v in values(p['attributes']['POSITION']) for c in v)
    decode=max_abs/32760
    data=bytearray();views=[];accessors=[];blocks={}
    def add(rows,code,component,kind,normalized=False,bounds=False):
        packed=b''.join(struct.pack('<'+code*len(row),*row) for row in rows)
        key=(packed,component,kind,normalized)
        if key in blocks:return blocks[key]
        while len(data)%4:data.append(0)
        view=len(views);views.append({'buffer':0,'byteOffset':len(data),'byteLength':len(packed)})
        data.extend(packed)
        a={'bufferView':view,'componentType':component,'count':len(rows),'type':kind}
        if normalized:a['normalized']=True
        if bounds:
            a['min']=[min(row[i] for row in rows) for i in range(len(rows[0]))]
            a['max']=[max(row[i] for row in rows) for i in range(len(rows[0]))]
        index=len(accessors);accessors.append(a);blocks[key]=index;return index
    def linear(c):
        f=c/255
        return round(255*(f/12.92 if f<=0.04045 else ((f+0.055)/1.055)**2.4))
    for mesh in doc['meshes']:
        for primitive in mesh['primitives']:
            attrs=primitive['attributes'];positions=values(attrs['POSITION']);normals=values(attrs['NORMAL']);uvs=values(attrs['TEXCOORD_0'])
            colors=[]
            for u,v in uvs:
                color=image.getpixel((min(image.width-1,max(0,int(u*image.width))),min(image.height-1,max(0,int(v*image.height)))))
                colors.append(tuple(linear(c) for c in color)+(255,))
            primitive['attributes']={
                'POSITION':add([tuple(round(c/decode) for c in v)+(0,) for v in positions],'h',5122,'VEC4',bounds=True),
                'NORMAL':add([tuple(round(max(-1,min(1,c))*127) for c in v)+(0,) for v in normals],'b',5120,'VEC4',normalized=True),
                'COLOR_0':add(colors,'B',5121,'VEC4',normalized=True),
            }
            # POSITION/NORMAL имеют три компоненты с выравниванием 4 байта.
            pi=primitive['attributes']['POSITION'];accessors[pi]['type']='VEC3'
            accessors[pi]['min']=accessors[pi]['min'][:3];accessors[pi]['max']=accessors[pi]['max'][:3]
            views[accessors[pi]['bufferView']]['byteStride']=8
            ni=primitive['attributes']['NORMAL'];accessors[ni]['type']='VEC3';views[accessors[ni]['bufferView']]['byteStride']=4
            primitive['indices']=add(values(primitive['indices']),'H',5123,'SCALAR')
            primitive['material']=0
    for node in doc['nodes']:
        if 'mesh' in node:
            if node.get('children'):raise ValueError('Quantization requires leaf mesh nodes')
            node['scale']=[c*decode for c in node.get('scale',[1,1,1])]
    doc['materials']=[{'name':'Kenney palette','pbrMetallicRoughness':{'baseColorFactor':[1,1,1,1],'metallicFactor':0,'roughnessFactor':1}}]
    doc['accessors']=accessors;doc['bufferViews']=views;doc['buffers']=[{'byteLength':len(data)}]
    for key in ['images','textures','samplers','extensions']:doc.pop(key,None)
    doc['extensionsUsed']=['KHR_mesh_quantization'];doc['extensionsRequired']=['KHR_mesh_quantization']
    j=json.dumps(doc,separators=(',',':')).encode();j+=b' '*(-len(j)%4)
    data.extend(b'\0'*(-len(data)%4));total=12+8+len(j)+8+len(data)
    return struct.pack('<III',0x46546c67,2,total)+struct.pack('<II',len(j),0x4e4f534a)+j+struct.pack('<II',len(data),0x004e4942)+data

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--roads',required=True);parser.add_argument('--cars',required=True)
    args=parser.parse_args()
    catalog={}
    for path,names,folder in [(args.roads,ROADS,'environment'),(args.cars,['sedan','truck'],'vehicles')]:
        with zipfile.ZipFile(path) as archive:
            license_name=next(n for n in archive.namelist() if n.lower().endswith('license.txt'))
            dest=ROOT/'assets'/folder;dest.mkdir(parents=True,exist_ok=True)
            (dest/'License.txt').write_bytes(archive.read(license_name))
            for name in names:
                model='Models/GLB format/'+name+'.glb'
                data=pack(archive.read(model),archive,'Models/GLB format')
                (dest/(name+'.glb')).write_bytes(data)
                catalog[name]={'id':name,'kind':'model','url':f'/content/assets/{folder}/{name}.glb',
                               'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    (ROOT/'asset-catalog.json').write_text(json.dumps(catalog,indent=2)+'\n')
    print(f'Prepared {len(catalog)} self-contained GLB assets')

if __name__=='__main__':main()
