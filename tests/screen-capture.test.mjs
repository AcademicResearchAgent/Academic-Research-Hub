import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../overlays/open-webui/screen-capture.js',import.meta.url),'utf8').replace('export ','');
function setup({secure=true,reject=false,badCanvas=false}={}) {
 const state={stopped:0,picked:0,calls:0,files:[],info:[],errors:[]};
 const picker={click(){state.picked++;}};
 const video={videoWidth:10,videoHeight:10,async play(){}};
 const scope={Blob,File:class extends Blob {constructor(parts,name,options){super(parts,options);this.name=name;}},
  window:{isSecureContext:secure,focus(){}},
  navigator:{mediaDevices:{async getDisplayMedia(){state.calls++;if(reject)throw {name:'NotAllowedError'};return {getTracks:()=>[{stop(){state.stopped++;}}]};}}},
  document:{createElement(name){return name==='input'?picker:name==='video'?video:{getContext:()=>badCanvas?null:{drawImage(){}},toBlob(callback){callback(new Blob(['synthetic pixels'],{type:'image/png'}));}};}}};
 vm.createContext(scope);vm.runInContext(source,scope);
 const run=()=>scope.captureScreenshot(files=>{state.files.push(...files);},{info:message=>state.info.push(message),error:message=>state.errors.push(message)});
 return {state,run,picker,video};
}
test('HTTP opens image picker with explanation and does not request screen sharing',async()=>{
 const {state,run,picker}=setup({secure:false});await run();
 assert.equal(state.picked,1);assert.equal(state.calls,0);assert.match(state.info[0],/HTTPS/);
 picker.files=[{name:'screenshot.png'}];picker.onchange();assert.equal(state.files.length,1);
});
test('secure capture delivers PNG and stops sharing',async()=>{
 const {state,run,video}=setup();await run();
 assert.equal(state.files[0].type,'image/png');assert.equal(state.stopped,1);assert.equal(video.srcObject,null);
});
test('denied or cancelled capture has visible feedback',async()=>{
 const {state,run}=setup({reject:true});await run();assert.equal(state.info.length,1);assert.equal(state.files.length,0);
});
test('capture failure stops sharing and reports a visible error',async()=>{
 const {state,run,video}=setup({badCanvas:true});await run();
 assert.equal(state.errors.length,1);assert.equal(state.stopped,1);assert.equal(video.srcObject,null);
});
