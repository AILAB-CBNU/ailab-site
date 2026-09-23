(function () {
  'use strict';
  var host = document.getElementById('catalog-public');
  if (!host) return;
  var kind = document.body.dataset.page, rows = [], filter = 'all', selectedYear = 'all', failure = false;
  var names = {all:['전체','All'],active:['진행 중','Ongoing'],completed:['완료','Completed'],planned:['예정','Planned'],unknown:['상태 미확인','Unconfirmed']};
  function text(ko,en) { return window.AILAB.lang === 'ko' ? ko : en; }
  function label(key) { return text.apply(null,names[key]); }
  function esc(value) { return String(value || '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function safeLink(value) { try { var u=new URL(value); return /^https?:$/.test(u.protocol)&&!u.username&&!u.password?u.href:''; } catch(e) { return ''; } }
  function render() {
    if (failure) { host.innerHTML='<p>'+text('자료를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.','Unable to load items. Please refresh in a moment.')+'</p>'; return; }
    var L=window.AILAB.L;
    var years=Array.from(new Set(rows.map(r=>String(kind==='projects'?r.year:r.date.slice(0,4))))).sort((a,b)=>b-a);
    host.innerHTML='<div class="catalog-toolbar">'+(kind==='projects'?'<div class="filter-group">'+Object.keys(names).filter(k=>k!=='unknown'||rows.some(r=>r.status==='unknown')).map(k=>'<button type="button" class="filter-btn" data-status="'+k+'" aria-pressed="'+(filter===k)+'">'+label(k)+'</button>').join('')+'</div>':'')+
      '<label>'+text('연도','Year')+' <select id="catalog-year"><option value="all">'+text('전체 연도','All years')+'</option>'+years.map(y=>'<option '+(y===selectedYear?'selected':'')+'>'+y+'</option>').join('')+'</select></label></div><div id="catalog-rows"></div>';
    host.querySelectorAll('[data-status]').forEach(b=>b.addEventListener('click',()=>{filter=b.dataset.status;render();}));
    host.querySelector('select').addEventListener('change',e=>{selectedYear=e.target.value;render();});
    var visible=rows.filter(r=>(kind!=='projects'||filter==='all'||r.status===filter)&&(selectedYear==='all'||String(kind==='projects'?r.year:r.date.slice(0,4))===selectedYear));
    var groups={}; visible.forEach(r=>{var y=kind==='projects'?r.year:r.date.slice(0,4);(groups[y]||(groups[y]=[])).push(r);});
    var target=host.querySelector('#catalog-rows');
    target.innerHTML=visible.length?Object.keys(groups).sort((a,b)=>b-a).map(y=>'<div class="pub-year-head"><h2 class="heading-sm num">'+esc(y)+'</h2><span class="count">'+groups[y].length+'</span></div>'+
      (kind==='projects'?'<ul class="rule-list">'+groups[y].map(r=>'<li class="news-item catalog-project"><div class="date">'+esc(r.period||r.year)+'</div><div><span class="project-status status-'+r.status+'">'+label(r.status)+'</span><h3 class="title">'+esc(L(r.title))+'</h3><p class="body">'+esc(L(r.funder))+'</p>'+(L(r.description)?'<p class="body">'+esc(L(r.description))+'</p>':'')+(safeLink(r.source)?'<a href="'+esc(safeLink(r.source))+'" target="_blank" rel="noopener noreferrer">'+text('자세히 보기 ↗','Learn more ↗')+'</a>':'')+'</div></li>').join('')+'</ul>':
      '<div class="gallery-grid">'+groups[y].sort((a,b)=>b.date.localeCompare(a.date)).map(r=>'<article class="gallery-card"><button type="button" data-gallery="'+esc(r.id)+'" aria-label="'+esc(L(r.title))+'"><img loading="lazy" src="'+esc(r.photo)+'" alt="'+esc(L(r.title))+'"></button><p class="date">'+esc(r.date)+'</p><h3>'+esc(L(r.title))+'</h3><p>'+esc(L(r.description))+'</p></article>').join('')+'</div>')).join(''):
      '<div class="catalog-empty">'+text(kind==='gallery'?'아직 등록된 사진이 없습니다.':'해당 조건의 과제가 없습니다.',kind==='gallery'?'No photos yet.':'No projects match these filters.')+'</div>';
    host.querySelectorAll('[data-gallery]').forEach(b=>b.addEventListener('click',()=>{
      var r=rows.find(r=>r.id===b.dataset.gallery), dialog=document.getElementById('gallery-lightbox');
      dialog.querySelector('img').src=r.photo;dialog.querySelector('img').alt=L(r.title);dialog.querySelector('p').textContent=L(r.title);dialog.showModal();
    }));
  }
  var dialog=document.getElementById('gallery-lightbox');
  if(dialog){document.getElementById('gallery-close').addEventListener('click',()=>dialog.close());dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});}
  document.addEventListener('ailab:rendered',render);
  fetch('/api/'+kind,{cache:'no-store'}).then(r=>{if(!r.ok){if(kind==='projects'&&r.status===404)return fetch('data/projects.json');throw new Error();}return r;}).then(r=>{if(!r.ok)throw new Error();return r.json();}).then(data=>{
    if(!Array.isArray(data))throw new Error();
    rows=data.filter(r=>kind==='projects'?names[r.status]:/^\/gallery-photos\/[a-f0-9]{32}\.png$/.test(r.photo));render();
  }).catch(()=>{failure=true;render();});
})();
