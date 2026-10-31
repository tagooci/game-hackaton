import './style.css';
import { Engine, Scene, ArcRotateCamera, FreeCamera, Vector3, HemisphericLight, Color4, MeshBuilder, StandardMaterial, Color3 } from '@babylonjs/core';
import { RoadContent } from './road-content.js';

const canvas = document.querySelector('#renderCanvas');
const engine = new Engine(canvas, true);
const scene = new Scene(engine);
scene.clearColor = new Color4(.73,.82,.87,1);
scene.useRightHandedSystem = false;
const light = new HemisphericLight('sky',new Vector3(.3,1,.2),scene);light.intensity=1.1;
const ground = MeshBuilder.CreateGround('ground',{width:2700,height:2300},scene);
ground.position.y=-.12;
const material=new StandardMaterial('ground',scene);material.diffuseColor=Color3.FromHexString('#7D9478');material.specularColor=Color3.Black();ground.material=material;
// Земля — служебная однотонная плоскость просмотра, не опубликованный ресурс мира.
const camera=new ArcRotateCamera('map-camera',-Math.PI/2,.65,110,new Vector3(-675,0,600),scene);
camera.minZ=.1;camera.maxZ=8000;camera.lowerRadiusLimit=12;camera.upperRadiusLimit=240;camera.upperBetaLimit=Math.PI/2-.02;
camera.attachControl(canvas,true);camera.panningSensibility=0;
const walkCamera=new FreeCamera('walk-camera',new Vector3(-675,1.6,598),scene);walkCamera.inputs.clear();walkCamera.minZ=.05;walkCamera.maxZ=800;
scene.activeCamera=camera;

const panel=document.createElement('aside');panel.className='map-panel';
panel.innerHTML=`<div class="eyebrow">ДОРОЖНАЯ СЕТЬ · ПРЕДПРОСМОТР</div><h1>Учебная карта</h1>
<p>WASD — перемещение камеры<br>Мышь и колесо — обзор<br>Shift — быстрее · Tab — с земли / сверху</p>
<svg id="road-map" viewBox="-1270 -1070 2540 2140" role="img" aria-label="Схема дорог. Выберите узел для перехода"></svg>
<div class="map-legend">Клик по узлу — перейти к участку</div>
<label class="reference-control">Масштаб: <select id="vehicle-reference"><option value="">без машины</option><option value="car">легковая 4,5 × 1,8 м</option><option value="truck">грузовик 7,2 × 2,5 м</option></select></label>
<div id="cache-stats" aria-live="polite">Подготовка ресурсов…</div><div id="map-error" role="alert"></div>
<div class="map-note">Авторский просмотр карты. Автомобильная физика и подключение v2 не включены.</div>`;
document.body.append(panel);
const stats=panel.querySelector('#cache-stats'),errorBox=panel.querySelector('#map-error');
let ready=false, loading=false, current={x:-675,z:598}, safe={...current};
const content=new RoadContent(scene,state=>{
 const percent=(state.active+state.reserved)/state.worldBytes*100;
 stats.innerHTML=`<strong>${percent.toFixed(2)}% мира / лимит 10%</strong><br>Активно: ${(state.active/1024).toFixed(1)} КиБ<br>Резерв: ${(state.reserved/1024).toFixed(1)} КиБ<br>Бюджет: ${(state.budget/1024).toFixed(1)} КиБ${state.chunks!==undefined?`<br>Участков: ${state.chunks} · объектов: ${state.objects}`:''}`;
 if(state.error)errorBox.textContent=state.error;
 if(state.transitioning!==undefined)loading=state.transitioning;
});
panel.querySelector('#vehicle-reference').addEventListener('change', async event => {
 content.vehicleType=event.target.value;
 await moveTo(current.x,current.z);
});
const keys=new Set();
function syncCameras(){camera.target.set(current.x,0,current.z);walkCamera.position.set(current.x,1.6,current.z);}
async function moveTo(x,z){
 ready=false;errorBox.textContent='';
 try{await content.update(x,z);current={x,z};safe={...current};syncCameras();ready=true;}
 catch(error){console.error(error);errorBox.textContent=`Загрузка остановлена: ${error.message}`;loading=false;current={...safe};syncCameras();}
}
function drawOverview(){
 const svg=panel.querySelector('#road-map'),nodes=new Map(content.overview.nodes.map(n=>[n.id,n]));
 const ns='http://www.w3.org/2000/svg';
 for(const edge of content.overview.edges){
  const a=nodes.get(edge.from),b=nodes.get(edge.to),line=document.createElementNS(ns,'line');
  for(const [key,value] of Object.entries({x1:a.x,y1:-a.z,x2:b.x,y2:-b.z}))line.setAttribute(key,value);
  line.setAttribute('class',edge.oneWay?'one-way':'road');svg.append(line);
 }
 for(const node of nodes.values()){
  const group=document.createElementNS(ns,'g');group.setAttribute('class','map-node');group.setAttribute('tabindex','0');group.setAttribute('role','button');group.setAttribute('aria-label',`Перейти к ${node.id}`);
  const circle=document.createElementNS(ns,'circle');circle.setAttribute('cx',node.x);circle.setAttribute('cy',-node.z);circle.setAttribute('r',node.id.startsWith('O')?28:16);
  circle.setAttribute('class',node.id.startsWith('O')?'roundabout':node.id.startsWith('X')?'crossroad':'junction');
  const title=document.createElementNS(ns,'title');title.textContent=node.id;circle.append(title);group.append(circle);
  if(node.id.startsWith('O')||node.id.startsWith('X')){const text=document.createElementNS(ns,'text');text.setAttribute('x',node.x+23);text.setAttribute('y',-node.z-24);text.textContent=node.id;group.append(text);}
  const go=()=>moveTo(node.x+20,node.z-2);group.addEventListener('click',go);group.addEventListener('keydown',e=>{if(e.key==='Enter')go();});svg.append(group);
 }
 const marker=document.createElementNS(ns,'circle');marker.id='camera-marker';marker.setAttribute('r','22');svg.append(marker);
}
window.addEventListener('keydown',event=>{
 if(event.target.closest?.('aside'))return;
 if(['KeyW','KeyA','KeyS','KeyD','ShiftLeft','ShiftRight','Tab'].includes(event.code))event.preventDefault();
 if(event.code==='Tab'&&!event.repeat){
  keys.clear();
  if(scene.activeCamera===camera){camera.detachControl();scene.activeCamera=walkCamera;syncCameras();canvas.requestPointerLock()?.catch(console.warn);}
  else{if(document.pointerLockElement===canvas)document.exitPointerLock();scene.activeCamera=camera;camera.attachControl(canvas,true);syncCameras();}
 }else keys.add(event.code);
});
window.addEventListener('keyup',event=>keys.delete(event.code));window.addEventListener('blur',()=>keys.clear());
document.addEventListener('pointerlockchange',()=>keys.clear());
canvas.addEventListener('click',()=>{if(scene.activeCamera===walkCamera&&document.pointerLockElement!==canvas)canvas.requestPointerLock()?.catch(console.warn);});
document.addEventListener('mousemove',event=>{
 if(scene.activeCamera!==walkCamera||document.pointerLockElement!==canvas)return;
 walkCamera.rotation.y+=event.movementX*.002;walkCamera.rotation.x=Math.max(-1.5,Math.min(1.5,walkCamera.rotation.x+event.movementY*.002));
});
engine.runRenderLoop(()=>{
 const dt=Math.min(engine.getDeltaTime()/1000,.05);
 if(ready&&!loading&&(scene.activeCamera===camera||document.pointerLockElement===canvas)){
  let forward=Number(keys.has('KeyW'))-Number(keys.has('KeyS')),right=Number(keys.has('KeyD'))-Number(keys.has('KeyA'));
  const length=Math.hypot(forward,right);
  if(length){
   forward/=length;right/=length;
   const heading=scene.activeCamera===walkCamera?walkCamera.rotation.y:-camera.alpha-Math.PI/2;
   const speed=(keys.has('ShiftLeft')||keys.has('ShiftRight')?100:25)*dt;
   const next={x:current.x+(Math.sin(heading)*forward+Math.cos(heading)*right)*speed,z:current.z+(Math.cos(heading)*forward-Math.sin(heading)*right)*speed};
   const b=content.manifest.bounds;next.x=Math.max(b.minX,Math.min(b.maxX,next.x));next.z=Math.max(b.minZ,Math.min(b.maxZ,next.z));
   const size=content.manifest.chunkSize;
   if(Math.floor(next.x/size)!==Math.floor(current.x/size)||Math.floor(next.z/size)!==Math.floor(current.z/size))void moveTo(next.x,next.z);
   else{current=next;safe={...current};syncCameras();}
  }
 }
 const marker=panel.querySelector('#camera-marker');if(marker){marker.setAttribute('cx',current.x);marker.setAttribute('cy',-current.z);}
 scene.render();
});
window.addEventListener('resize',()=>engine.resize());
try{
 const manifest=await content.init();drawOverview();await moveTo(manifest.spawn.x,manifest.spawn.z);
}catch(error){console.error(error);errorBox.textContent=`Ошибка подготовки карты: ${error.message}`;}
// Только интерфейс для автоматизированной проверки авторского просмотра.
if(import.meta.env.DEV)window.roadPreview={content,scene,camera,moveTo,get ready(){return ready;}};
