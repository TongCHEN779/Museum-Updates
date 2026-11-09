const DAYS = ["sun","mon","tue","wed","thu","fri","sat"];
const DAYZH = {sun:"周日",mon:"周一",tue:"周二",wed:"周三",thu:"周四",fri:"周五",sat:"周六"};
const $ = s => document.querySelector(s);
const iso = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let DATA = null;

// 丹麦公共假日（按复活节推算）
function easter(y){const a=y%19,b=Math.floor(y/100),c=y%100,d=Math.floor(b/4),e=b%4,f=Math.floor((b+8)/25),g=Math.floor((b-f+1)/3),
  h=(19*a+b-d-g+15)%30,i=Math.floor(c/4),k=c%4,l=(32+2*e+2*i-h-k)%7,m=Math.floor((a+11*h+22*l)/451),
  mo=Math.floor((h+l-7*m+114)/31),da=((h+l-7*m+114)%31)+1;return new Date(y,mo-1,da);}
function holidays(y){
  const E=easter(y), add=n=>{const d=new Date(E);d.setDate(d.getDate()+n);return d;};
  const list=[[new Date(y,0,1),"元旦"],[add(-3),"濯足节"],[add(-2),"耶稣受难日"],[E,"复活节"],[add(1),"复活节星期一"],
    [add(39),"耶稣升天节"],[add(49),"圣灵降临节"],[add(50),"圣灵降临节星期一"],
    [new Date(y,5,5),"宪法日(半天)"],[new Date(y,11,24),"平安夜"],[new Date(y,11,25),"圣诞节"],[new Date(y,11,26),"圣诞节次日"]];
  return Object.fromEntries(list.map(([d,n])=>[iso(d),n]));
}
const holidayName = d => holidays(d.getFullYear())[iso(d)];
function nextHoliday(from){
  for (let i=0;i<400;i++){const d=new Date(from);d.setDate(d.getDate()+i);if(holidayName(d)) return d;}
}
function parseDate(s){const [y,m,d]=s.split("-").map(Number);return new Date(y,m-1,d);}

function hoursFor(m, d){
  const h = m.hours?.[DAYS[d.getDay()]];
  return h || null;
}
function isOpen(m, d){const h=hoursFor(m,d);return h ? h!=="closed" : null;}

function exhibitionOnView(e, dstr){
  if (e.start && dstr < e.start) return false;
  if (e.end && dstr > e.end) return false;
  return true;
}

function render(){
  const d = parseDate($("#date").value), ds = iso(d);
  const hol = holidayName(d), wd = DAYZH[DAYS[d.getDay()]];
  $("#dateinfo").textContent = `${wd}${hol ? " · 丹麦公共假日：" + hol : ""}${hol ? "（部分馆开放时间会调整）" : ""}`;
  const q = $("#q").value.trim().toLowerCase(), city = $("#city").value, openOnly = $("#openOnly").checked;
  const cards = DATA.museums.filter(m => {
    if (city && m.city !== city) return false;
    if (openOnly && isOpen(m,d) === false) return false;
    if (q) { const hay = (m.name+" "+m.city+" "+(m.exhibitions||[]).map(e=>e.title).join(" ")).toLowerCase(); if(!hay.includes(q)) return false; }
    return true;
  }).map(m => {
    const open = isOpen(m,d), h = hoursFor(m,d);
    const badge = open===null ? "" : open ? `<span class="badge open">当天开放 ${esc(h)}</span>` : `<span class="badge closed">当天闭馆</span>`;
    const recent = (m.changes||[]).filter(c => (Date.now()-new Date(c.date))/864e5 <= 7);
    const chg = recent.length ? `<div class="changes">🔔 最近变动：${recent.map(c=>esc(c.text)+"（"+esc(c.date)+"）").join("；")}</div>` : "";
    const exs = (m.exhibitions||[]).filter(e => exhibitionOnView(e, ds));
    const exHtml = exs.length
      ? `<ul>${exs.map(e=>`<li>${e.url?`<a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.title)}</a>`:esc(e.title)}${e.start||e.end?` <span class="meta">${esc(e.start||"")} ~ ${esc(e.end||"")}</span>`:""}${e.summary?`<div class="meta">${esc(e.summary)}</div>`:""}</li>`).join("")}</ul>`
      : `<p class="meta">暂无展览信息，请到官网查看。</p>`;
    const stale = m.scrape_status==="stale" ? `<p class="meta">⚠️ 最近一次自动更新失败，以下信息可能不是最新。</p>` : "";
    const prices = (m.prices||[]).length
      ? `<ul class="prices">${m.prices.map(p=>`<li>${esc(p.category)}：<b>${p.amount_dkk===0?"免费":p.amount_dkk==null?"见官网":p.amount_dkk+" DKK"}</b>${p.note?` <span class="meta">${esc(p.note)}</span>`:""}</li>`).join("")}</ul>`
      : `<p class="meta">票价：见官网</p>`;
    const offers = (m.offers||[]).length
      ? `<div class="offers">🎁 ${m.offers.map(o=>`<div><b>${esc(o.title)}</b>${o.description?"："+esc(o.description):""}</div>`).join("")}</div>` : "";
    const notes = [m.hours_note, ...(m.notices||[])].filter(Boolean).map(n=>`<div class="meta">ℹ️ ${esc(n)}</div>`).join("");
    const checked = m.checked_at ? `<span class="meta">核对于 ${new Date(m.checked_at).toLocaleString("zh-CN")}</span>` : `<span class="meta">尚未自动核对</span>`;
    return `<article class="card">
      <h2>${esc(m.name)} ${badge}</h2>
      <div class="meta">📍 ${esc(m.address)} · ${checked}</div>
      ${chg}${stale}${notes}
      <h3>票价</h3>${prices}${offers}
      <h3>展览</h3>${exHtml}
      <div class="links"><a href="${esc(m.hours_url)}" target="_blank" rel="noopener">开放时间</a>
      <a href="${esc(m.tickets_url)}" target="_blank" rel="noopener">购票</a>
      <a href="${esc(m.exhibitions_url)}" target="_blank" rel="noopener">全部展览</a>
      <a href="${esc(m.url)}" target="_blank" rel="noopener">官网</a></div></article>`;
  });
  $("#list").innerHTML = cards.join("") || `<div class="empty">没有符合条件的博物馆</div>`;
}

function quick(kind){
  const now = new Date(); let d = new Date(now);
  if (kind==="weekend"){ const add = (6 - d.getDay() + 7) % 7; if (d.getDay()===0) d.setDate(d.getDate()); else d.setDate(d.getDate()+add); }
  if (kind==="holiday") d = nextHoliday(now);
  $("#date").value = iso(d); render();
}

fetch("data/museums.json").then(r=>r.json()).then(j=>{
  DATA = j;
  $("#updated").textContent = ` 数据更新于 ${new Date(j.generated_at).toLocaleString("zh-CN")}`;
  [...new Set(j.museums.map(m=>m.city))].sort().forEach(c=>$("#city").add(new Option(c,c)));
  $("#date").value = iso(new Date());
  ["#date","#q","#city","#openOnly"].forEach(s=>$(s).addEventListener("input",render));
  document.querySelectorAll("[data-quick]").forEach(b=>b.addEventListener("click",()=>quick(b.dataset.quick)));
  render();
}).catch(e=>{$("#list").innerHTML=`<div class="empty">数据加载失败：${esc(e.message)}</div>`;});
