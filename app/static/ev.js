// 전기차 vs 내연기관 유지비 계산기 (입력값은 이 기기의 localStorage 'evice'에 저장, 대시보드 카드도 이 값을 읽음)
const DEF={dist:1500,evEffIn:5.0,evPrice:347,evLoss:10,iceEff:12,icePrice:1700};
const ids=Object.keys(DEF);
const $=id=>document.getElementById(id);
let period=1;
const won=v=>Math.round(v).toLocaleString('ko-KR')+'원';
const short=v=>{v=Math.round(v);if(Math.abs(v)>=10000){const m=v/10000;return (Math.abs(m)>=100?Math.round(m):m.toFixed(1)).toLocaleString('ko-KR')+'만원'}return v.toLocaleString('ko-KR')+'원'};

function paint(r){const p=(r.value-r.min)/(r.max-r.min)*100;r.style.setProperty('--p',Math.max(0,Math.min(100,p))+'%')}
function set(id,v){$(id).value=v;const r=document.querySelector(`[data-for="${id}"]`);r.value=v;paint(r)}
function get(id){const v=parseFloat($(id).value);return isFinite(v)?v:0}

ids.forEach(id=>{
  const r=document.querySelector(`[data-for="${id}"]`);
  r.addEventListener('input',()=>{$(id).value=r.value;paint(r);calc()});
  $(id).addEventListener('input',()=>{r.value=$(id).value;paint(r);calc()});
  $(id).addEventListener('focus',e=>e.target.select());
});
$('period').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
  period=+b.dataset.p;[...$('period').children].forEach(x=>x.classList.toggle('on',x===b));calc()});
$('reset').addEventListener('click',()=>{ids.forEach(id=>set(id,DEF[id]));calc()});

function calc(){
  const d=get('dist'),eff=get('evEffIn'),ep=get('evPrice'),loss=Math.min(get('evLoss'),95)/100,
        fe=get('iceEff'),fp=get('icePrice');
  const effEff=eff*(1-loss);                       // 실효 전비 (계량기 기준)
  const evKm=effEff>0?ep/effEff:0;
  const iceKm=fe>0?fp/fe:0;
  const evM=evKm*d*period, iceM=iceKm*d*period, diff=iceM-evM;
  const lossCost=(effEff>0&&eff>0)?(ep/effEff-ep/eff)*d:0; // 월 손실분 비용

  $('sumLabel').textContent=({1:'월',12:'1년',60:'5년'})[period]+' 기준 · '+(d*period).toLocaleString('ko-KR')+'km';
  const big=$('sumBig');
  if(Math.abs(diff)<1){big.className='big';big.innerHTML='두 차량 비용이 같아요'}
  else if(diff>0){big.className='big';big.innerHTML=`전기차가 <b>${short(diff)}</b> 절약`}
  else{big.className='big ice';big.innerHTML=`내연기관이 <b>${short(-diff)}</b> 저렴`}
  const mx=Math.max(evM,iceM,1);
  $('barEv').style.width=(evM/mx*100)+'%';$('barIce').style.width=(iceM/mx*100)+'%';
  $('valEv').textContent=short(evM);$('valIce').textContent=short(iceM);

  $('evKm').textContent=evKm.toFixed(1)+'원';
  $('evEff').textContent=effEff.toFixed(2)+' km/kWh';
  $('iceKm').textContent=iceKm.toFixed(1)+'원';
  // 데스크탑 요약의 km당 비용·손익 분기 충전 단가 (휴대폰은 숨김)
  $('sumEvKm').textContent=evKm.toFixed(1)+'원';$('sumIceKm').textContent=iceKm.toFixed(1)+'원';
  $('sumBe').textContent=Math.round(iceKm*effEff).toLocaleString('ko-KR')+'원';
  $('lossNote').innerHTML=loss>0
    ?`충전 손실로 월 약 <b>${won(lossCost)}</b> 더 듭니다 (실제 결제 전력 ${(d/effEff).toFixed(0)}kWh)`
    :'충전 손실 없이 계산 중';

  const EV='#0f9d7a',ICE='#e0782a';
  // ① 전기료 변화
  const beP=iceKm*effEff;
  const eX1=Math.min(1500,Math.max(600,Math.ceil(beP*1.2/100)*100));
  drawChart({id:'chartEv',x0:50,x1:eX1,xs:ticks(100,eX1),varAt:p=>effEff>0?p/effEff:0,flat:iceKm,cur:ep,
    vc:EV,fc:ICE,unit:'충전 단가 (원/kWh)',be:beP,shadeRight:true,shadeLabel:'전기차가 더 비싼 구간'});
  const per10e=effEff>0?10/effEff*d:0;
  $('insightEv').innerHTML=`충전 단가가 <b>${Math.round(beP).toLocaleString('ko-KR')}원/kWh</b>를 넘으면 전기차가 더 비싸져요.`+
    `<br>충전 단가가 10원 오를 때마다 월 <b>${won(per10e)}</b>씩 늘어납니다.`;
  // ② 유류비 변화
  const beF=evKm*fe;
  const fX0=Math.max(300,Math.min(1000,Math.floor(beF*0.8/100)*100));
  drawChart({id:'chartIce',x0:fX0,x1:2500,xs:ticks(fX0,2500),varAt:p=>fe>0?p/fe:0,flat:evKm,cur:fp,
    vc:ICE,fc:EV,unit:'유가 (원/L)',be:beF,shadeRight:false,shadeLabel:'내연기관이 더 싼 구간'});
  const per100f=fe>0?100/fe*d:0;
  $('insightIce').innerHTML=`유가가 <b>${Math.round(beF).toLocaleString('ko-KR')}원/L</b> 아래로 내려가야 내연기관이 더 저렴해져요.`+
    `<br>유가가 100원 오를 때마다 월 <b>${won(per100f)}</b>씩 늘어납니다.`;
}

function ticks(a,b){const st=Math.ceil((b-a)/5/100)*100||100,out=[];for(let x=Math.ceil(a/st)*st;x<=b;x+=st)out.push(x);return out}
// 공통 그래프: 가로축 단가가 바뀌는 쪽(var) vs 고정된 쪽(flat)
function drawChart(o){
  const W=340,H=214,L=36,R=10,T=18,B=40,{x0,x1,xs,varAt,flat,cur,vc,fc,unit,be,shadeRight,shadeLabel}=o;
  const maxY=Math.max(varAt(x1),flat,10)*1.12;
  const X=v=>L+(v-x0)/(x1-x0)*(W-L-R), Y=v=>T+(1-v/maxY)*(H-T-B);
  let s='';
  const step=maxY>150?50:maxY>60?20:10;
  for(let y=0;y<=maxY;y+=step){s+=`<line x1="${L}" x2="${W-R}" y1="${Y(y)}" y2="${Y(y)}" stroke="#eef0f3"/><text x="${L-6}" y="${Y(y)+4}" font-size="10" fill="#9ca3af" text-anchor="end">${y}</text>`}
  xs.forEach(x=>{s+=`<text x="${X(x)}" y="${H-B+15}" font-size="10" fill="#9ca3af" text-anchor="middle">${x.toLocaleString()}</text>`});
  s+=`<text x="${(L+W-R)/2}" y="${H-3}" font-size="10" fill="#6b7280" text-anchor="middle">${unit}</text>`;
  if(be>x0&&be<x1){
    const a=shadeRight?X(be):X(x0), w=shadeRight?X(x1)-X(be):X(be)-X(x0);
    s+=`<rect x="${a}" y="${T}" width="${w}" height="${H-T-B}" fill="#fdeee2" opacity=".6"/>`;
    s+=`<line x1="${X(be)}" x2="${X(be)}" y1="${T}" y2="${H-B}" stroke="#c9ced6" stroke-dasharray="3 3"/>`;
    const lw=shadeLabel.length*9+8, inside=w>=lw;
    // 음영이 좁으면 경계선 바깥쪽(안쪽 그래프 방향)에 라벨 배치
    const lx=inside?a+w/2:(shadeRight?X(be)-4:X(be)+4), anc=inside?'middle':(shadeRight?'end':'start');
    s+=`<text x="${lx}" y="${T-5}" font-size="9" font-weight="600" fill="#b45a1c" text-anchor="${anc}">${inside?'':(shadeRight?'':'◀ ')}${shadeLabel}${inside?'':(shadeRight?' ▶':'')}</text>`}
  s+=`<line x1="${X(x0)}" x2="${X(x1)}" y1="${Y(flat)}" y2="${Y(flat)}" stroke="${fc}" stroke-width="2.5" stroke-linecap="round"/>`;
  s+=`<line x1="${X(x0)}" x2="${X(x1)}" y1="${Y(varAt(x0))}" y2="${Y(varAt(x1))}" stroke="${vc}" stroke-width="2.5" stroke-linecap="round"/>`;
  if(cur>=x0&&cur<=x1){s+=`<circle cx="${X(cur)}" cy="${Y(varAt(cur))}" r="5" fill="#fff" stroke="${vc}" stroke-width="2.5"/>`;
    s+=`<text x="${X(cur)}" y="${Y(varAt(cur))-10}" font-size="10" font-weight="700" fill="${vc}" text-anchor="middle">현재</text>`}
  $(o.id).innerHTML=s;
}


// −/+ 버튼 (길게 누르면 연속 변경)
const STEP={dist:50,evEffIn:0.1,evPrice:1,evLoss:0.5,iceEff:0.1,icePrice:5};
const MAXV={evLoss:95};
ids.forEach(id=>{
  const box=$(id).closest('.num'),wrap=document.createElement('div');wrap.className='stepper';
  box.parentNode.insertBefore(wrap,box);
  const mk=(t,dir)=>{const b=document.createElement('button');b.type='button';b.textContent=t;
    b.setAttribute('aria-label',(dir>0?'증가 ':'감소 ')+id);
    const bump=()=>{const st=STEP[id],dec=(String(st).split('.')[1]||'').length;
      let v=get(id)+dir*st;v=Math.max(0,Math.min(MAXV[id]??Infinity,v));set(id,+v.toFixed(dec));calc()};
    let t1=null,t2=null;const stop=()=>{clearTimeout(t1);clearInterval(t2);t1=t2=null};
    b.addEventListener('pointerdown',e=>{e.preventDefault();bump();t1=setTimeout(()=>{t2=setInterval(bump,70)},400)});
    ['pointerup','pointerleave','pointercancel'].forEach(ev=>b.addEventListener(ev,stop));
    b.addEventListener('contextmenu',e=>e.preventDefault());
    b.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();bump()}});
    return b};
  wrap.append(mk('−',-1),box,mk('+',1));
});

// 스크롤 중 오터치 방지: 가로로 확실히 끌 때만 값 변경, 탭/세로 스크롤은 무시
document.querySelectorAll('input[type=range]').forEach(r=>{
  const wrap=document.createElement('div');wrap.className='slider';
  r.parentNode.insertBefore(wrap,r);wrap.appendChild(r);r.tabIndex=-1;
  let sx=0,sy=0,sv=0,state=null,pid=null; // state: null | 'wait' | 'drag'
  const TH=10; // 판단 임계값(px)
  wrap.addEventListener('pointerdown',e=>{
    if(e.pointerType==='mouse'&&e.button!==0)return;
    sx=e.clientX;sy=e.clientY;sv=parseFloat(r.value);state='wait';pid=e.pointerId;
  });
  wrap.addEventListener('pointermove',e=>{
    if(!state||e.pointerId!==pid)return;
    const dx=e.clientX-sx,dy=e.clientY-sy;
    if(state==='wait'){
      if(Math.abs(dy)>TH&&Math.abs(dy)>Math.abs(dx)){state=null;return} // 세로 스크롤 → 무시
      if(Math.abs(dx)>TH&&Math.abs(dx)>Math.abs(dy)*1.5){
        state='drag';sx=e.clientX; // 판단 지점부터 이동량 계산(값이 튀지 않게)
        wrap.classList.add('dragging');try{wrap.setPointerCapture(pid)}catch(_){}
      }else return;
    }
    e.preventDefault();
    const min=+r.min,max=+r.max,st=+r.step||1,w=wrap.clientWidth||1;
    let v=sv+(e.clientX-sx)/w*(max-min);
    v=Math.round(v/st)*st;v=Math.max(min,Math.min(max,v));
    v=+v.toFixed(4);
    if(String(v)!==r.value){r.value=v;r.dispatchEvent(new Event('input',{bubbles:true}))}
  },{passive:false});
  const end=()=>{state=null;pid=null;wrap.classList.remove('dragging')};
  wrap.addEventListener('pointerup',end);wrap.addEventListener('pointercancel',end);
});

let saved={};try{saved=JSON.parse(localStorage.getItem('evice')||'{}')}catch(e){}
ids.forEach(id=>set(id,saved[id]??DEF[id]));
const _calc=calc;calc=function(){_calc();try{const o={};ids.forEach(id=>o[id]=get(id));localStorage.setItem('evice',JSON.stringify(o))}catch(e){}};
calc();

// ==========================================
// 저장한 조건: 지금 입력값을 이름 붙여 서버에 저장하고, 눌러서 불러옴 (관리자 로그인 키는 다른 페이지와 같은 admin_token)
// ==========================================
const TOKEN_KEY='admin_token';
let presets=[];
const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
const token=()=>{try{return localStorage.getItem(TOKEN_KEY)||''}catch(e){return ''}};
function setToken(v){try{if(v)localStorage.setItem(TOKEN_KEY,v);else localStorage.removeItem(TOKEN_KEY)}catch(e){}}
function presetMsg(text,isError){const m=$('preset-msg');m.textContent=text||'';m.classList.toggle('is-error',!!isError)}
function showPresetLogin(){setToken('');presets=[];$('preset-login').hidden=false;$('preset-open').hidden=true;$('preset-form').hidden=true;renderPresets()}

// 로그인이 풀렸으면 null (로그인 칸이 보임), 실패하면 Error
async function evApi(body){
  const res=await fetch('/api/ev',{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},
    body:JSON.stringify({...body,password:token()})});
  if(res.status===401){showPresetLogin();return null}
  const data=await res.json();
  if(!data.success)throw new Error(String(data.message||'').replace(/^❌\s*/,'')||'처리하지 못했습니다.');
  return data;
}
async function loadPresets(){
  if(!token()){showPresetLogin();return}
  try{
    const data=await evApi({action:'list'});
    if(!data)return;
    presets=data.presets;$('preset-login').hidden=true;$('preset-open').hidden=false;renderPresets();
  }catch(e){presetMsg('저장한 조건을 불러오지 못했습니다.',true)}
}
function presetDiff(v){
  const effEff=v.evEffIn*(1-Math.min(v.evLoss,95)/100);
  const evKm=effEff>0?v.evPrice/effEff:0,iceKm=v.iceEff>0?v.icePrice/v.iceEff:0;
  return (iceKm-evKm)*v.dist;
}
function renderPresets(){
  const now={};ids.forEach(id=>now[id]=get(id));
  $('preset-list').innerHTML=presets.map(p=>{
    const v=p.values,diff=presetDiff(v),same=ids.every(id=>Math.abs((v[id]??NaN)-now[id])<1e-9);
    const result=Math.abs(diff)<1?'두 차량 비용이 같아요':diff>0?`월 ${short(diff)} 절약`:`월 ${short(-diff)} 손해`;
    return `<div class="preset${same?' is-on':''}">
      <button type="button" class="preset-load" data-load="${p.id}"${same?' aria-current="true"':''}>
        <span class="preset-name">${esc(p.name)}</span>
        <span class="preset-vals">${v.dist.toLocaleString('ko-KR')}km · 전비 ${v.evEffIn} · 충전 ${v.evPrice.toLocaleString('ko-KR')}원 · 연비 ${v.iceEff} · 유가 ${v.icePrice.toLocaleString('ko-KR')}원</span>
        <span class="preset-result${diff<0?' is-ice':''}">${result}</span>
        <span class="preset-date">${esc(p.created_at.slice(5,10).replace('-','/'))} 저장</span>
      </button>
      <button type="button" class="preset-del" data-del="${p.id}" aria-label="${esc(p.name)} 삭제">×</button>
    </div>`}).join('');
}
// 입력값이 바뀔 때마다 지금 값과 같은 조건을 표시
const _calcPresets=calc;calc=function(){_calcPresets();renderPresets()};

$('preset-open').addEventListener('click',()=>{$('preset-form').hidden=false;presetMsg('');$('preset-name').focus()});
$('preset-cancel').addEventListener('click',()=>{$('preset-form').hidden=true;$('preset-name').value='';presetMsg('')});
$('preset-name').addEventListener('input',()=>presetMsg(''));
$('preset-form').addEventListener('submit',async e=>{
  e.preventDefault();
  const name=$('preset-name').value.trim();
  if(!name){presetMsg('이름을 입력하세요.',true);$('preset-name').focus();return}
  const values={};ids.forEach(id=>values[id]=get(id));
  try{
    const data=await evApi({action:'add',name,values});
    if(!data)return;
    $('preset-name').value='';$('preset-form').hidden=true;
    await loadPresets();presetMsg(`'${name}' 저장했습니다`);
  }catch(err){presetMsg(err.message,true)}
});
$('preset-list').addEventListener('click',async e=>{
  const del=e.target.closest('[data-del]');
  if(del){
    const p=presets.find(x=>x.id===+del.dataset.del);
    try{const data=await evApi({action:'delete',id:+del.dataset.del});if(!data)return;await loadPresets();presetMsg(`'${p?p.name:''}' 삭제했습니다`)}
    catch(err){presetMsg(err.message,true)}
    return;
  }
  const load=e.target.closest('[data-load]');
  if(!load)return;
  const p=presets.find(x=>x.id===+load.dataset.load);
  if(!p)return;
  ids.forEach(id=>{if(p.values[id]!=null)set(id,p.values[id])});
  calc();
  presetMsg(`'${p.name}' 값을 불러왔습니다`);
});
$('preset-login').addEventListener('submit',async e=>{
  e.preventDefault();
  const input=$('preset-password');
  if(!input.value.trim()){input.focus();return}
  try{
    const res=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify({password:input.value})});
    const data=await res.json();
    if(!data.success){presetMsg(String(data.message||'').replace(/^❌\s*/,''),true);input.select();return}
    setToken(data.token);input.value='';presetMsg('');await loadPresets();
  }catch(err){presetMsg('서버에 연결하지 못했습니다.',true)}
});
loadPresets();

