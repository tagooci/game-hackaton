"""Импорт локальных Kenney ZIP; упаковка внешних изображений в GLB."""
import argparse, base64, hashlib, json, struct, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'public' / 'content'

def pack(raw, archive, parent, unmarked=False, ramp=False, rail=False, level_crossing=False, keep_uv=False):
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
    all_positions=[]
    for mesh in doc['meshes']:
        for primitive in mesh['primitives']:
            for x,y,z in values(primitive['attributes']['POSITION']):
                if level_crossing:y=min(y,.01)
                if rail:y,z=y+1,z-2
                if ramp:y+=.1*(x+.5)
                all_positions.append((x,y,z))
    decode=max(abs(c) for point in all_positions for c in point)/32760 or 1/32760
    for mesh in doc['meshes']:
        for primitive in mesh['primitives']:
            attrs=primitive['attributes'];positions=values(attrs['POSITION']);normals=values(attrs['NORMAL']);uvs=values(attrs['TEXCOORD_0']) if 'TEXCOORD_0' in attrs else []
            if level_crossing: positions=[(x,min(y,.01),z) for x,y,z in positions]
            if rail: positions=[(x,y+1,z-2) for x,y,z in positions]
            colors=[]
            for u,v in uvs:
                color=image.getpixel((min(image.width-1,max(0,int(u*image.width))),min(image.height-1,max(0,int(v*image.height)))))
                if unmarked and len(colors) < len(positions):
                    point=positions[len(colors)];normal=normals[len(colors)]
                    if abs(point[1]-.01)<.002 and normal[1]>.9 and min(color)>120: color=(102,107,128)
                colors.append(tuple(linear(c) for c in color)+(255,))
            if not uvs and 'COLOR_0' in attrs:
                a=old_accessors[attrs['COLOR_0']]
                scale = 255 if a['componentType']==5126 else 255/65535 if a['componentType']==5123 and a.get('normalized') else 1
                colors=[tuple(max(0,min(255,round(c*scale))) for c in row)+(255,) for row in values(attrs['COLOR_0'])]
                colors=[row[:4] for row in colors]
            if not colors:
                material=doc.get('materials',[{}])[primitive.get('material',0)]
                factor=material.get('pbrMetallicRoughness',{}).get('baseColorFactor',[1,1,1,1])
                colors=[tuple(round(c*255) for c in factor)]*len(positions)
            if ramp:
                positions=[(x,y+.1*(x+.5),z) for x,y,z in positions]
                normals=[(x-.1*y,y,z) for x,y,z in normals]
                normals=[tuple(c/math.sqrt(sum(a*a for a in n)) for c in n) for n in normals]
            # Сливаем вершины, разделённые только UV-островками исходной палитры.
            unique={};mapping=[];new_p=[];new_n=[];new_c=[];new_uv=[]
            for vertex,(point,normal,color) in enumerate(zip(positions,normals,colors)):
                key=tuple(round(x,6) for x in (*point,*normal))+color
                if key not in unique:
                    unique[key]=len(new_p);new_p.append(point);new_n.append(normal);new_c.append(color)
                    if keep_uv:new_uv.append(uvs[vertex])
                mapping.append(unique[key])
            indices=[(mapping[row[0]],) for row in values(primitive['indices'])]
            positions,normals,colors=new_p,new_n,new_c
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
            if keep_uv:
                primitive['attributes'].pop('COLOR_0')
                primitive['attributes']['TEXCOORD_0']=add([tuple(round(c*65535) for c in uv) for uv in new_uv],'H',5123,'VEC2',normalized=True)
            primitive['indices']=add(indices,'H',5123,'SCALAR')
            primitive['material']=0
    for node in doc['nodes']:
        if 'mesh' in node:
            if node.get('children'):raise ValueError('Quantization requires leaf mesh nodes')
            node['scale']=[c*decode for c in node.get('scale',[1,1,1])]
    if not keep_uv:doc['materials']=[{'name':'Kenney palette','pbrMetallicRoughness':{'baseColorFactor':[1,1,1,1],'metallicFactor':0,'roughnessFactor':1}}]
    doc['accessors']=accessors;doc['bufferViews']=views;doc['buffers']=[{'byteLength':len(data)}]
    for key in (['extensions'] if keep_uv else ['images','textures','samplers','extensions']):doc.pop(key,None)
    doc['extensionsUsed']=['KHR_mesh_quantization'];doc['extensionsRequired']=['KHR_mesh_quantization']
    j=json.dumps(doc,separators=(',',':')).encode();j+=b' '*(-len(j)%4)
    data.extend(b'\0'*(-len(data)%4));total=12+8+len(j)+8+len(data)
    return struct.pack('<III',0x46546c67,2,total)+struct.pack('<II',len(j),0x4e4f534a)+j+struct.pack('<II',len(data),0x004e4942)+data



def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--roads',required=True)
    parser.add_argument('--rail',required=True)
    parser.add_argument('--markings',action='store_true')
    args=parser.parse_args()
    catalog={}
    models=['road-straight','road-bend','road-intersection','road-crossroad','bridge-pillar']
    for path,names,folder in [(args.roads,models,'environment'),(args.rail,['railroad-straight'],'railway')]:
        with zipfile.ZipFile(path) as archive:
            dest=ROOT/'assets'/folder;dest.mkdir(parents=True,exist_ok=True)
            license_name=next(n for n in archive.namelist() if n.lower().endswith('license.txt'))
            (dest/'License.txt').write_text('\n'.join(line.rstrip() for line in archive.read(license_name).decode('utf-8-sig').splitlines())+'\n')
            for name in names+(['road-ramp','road-level-crossing'] if folder=='environment' else []):
                source='road-straight' if name in ['road-ramp','road-level-crossing'] else name
                raw=archive.read('Models/GLB format/'+source+'.glb')
                data=pack(raw,archive,'Models/GLB format',unmarked=not args.markings and name.startswith('road-'),ramp=name=='road-ramp',rail=folder=='railway',level_crossing=name=='road-level-crossing')
                (dest/(name+'.glb')).write_bytes(data)
                catalog[name]={'id':name,'kind':'model','url':f'/content/assets/{folder}/{name}.glb','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    # Существующие reference-машины не меняем и не загружаем как декорации.
    old=json.loads((ROOT/'asset-catalog.json').read_text())
    for name in ['sedan','truck']: catalog[name]=old[name]
    (ROOT/'asset-catalog.json').write_text(json.dumps(catalog,indent=2)+'\n')
    print({name:entry['bytes'] for name,entry in catalog.items()})

if __name__=='__main__': main()
