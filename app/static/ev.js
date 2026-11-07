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
