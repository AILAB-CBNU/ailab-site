(function () {
  'use strict';
  function esc(v) {return String(v||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  window.AILAB_ADMIN_CATALOG={create:function(options){
    var host=document.getElementById('catalog-manager'), kind='', rows=[], selected=null, busy=false, dirty=false, epoch=0;
    var statuses={active:'진행 중',completed:'완료',planned:'예정',unknown:'상태 미확인'};
    function canLeave(){return !busy&&(!dirty||window.confirm('저장하지 않은 내용을 버리고 이동할까요?'));}
    function reset(){epoch++;kind='';dirty=false;host.innerHTML='';}
    function message(value){var el=host.querySelector('[role=status]');if(el)el.textContent=value;}
    function local(v){return typeof v==='string'?v:v&&(v.ko||v.en)||'';}
    function input(name,label,value,type,extra){return '<label>'+label+'<input name="'+name+'" type="'+(type||'text')+'" value="'+esc(value)+'" '+(extra||'')+'></label>';}
    function bilingual(key,label,values,long){return ['ko','en'].map(lang=>'<label>'+label+' · '+(lang==='ko'?'한국어':'English')+(long?'<textarea name="'+key+'_'+lang+'" maxlength="4000">'+esc(values&&values[lang])+'</textarea>':'<input name="'+key+'_'+lang+'" maxlength="'+(key==='title'?240:300)+'" value="'+esc(values&&values[lang])+'">')+'</label>').join('');}
    function draw(){
      var r=selected||{}, project=kind==='projects';
      host.innerHTML='<div class="catalog-admin-tools"><button type="button" id="catalog-new">'+(project?'새 과제 추가':'사진 추가')+'</button><button type="button" id="catalog-refresh" class="quiet">목록 새로고침</button></div><p role="status" aria-live="polite"></p><div class="catalog-editor-grid"><div class="catalog-item-list">'+rows.map(item=>'<button type="button" data-item="'+item.id+'" aria-pressed="'+(r.id===item.id)+'"><strong>'+esc(local(item.title))+'</strong><span>'+esc(project?item.year+' · '+statuses[item.status]:item.date)+'</span></button>').join('')+'</div><form id="catalog-form"><h2>'+(r.id?'내용 수정':project?'새 연구 과제':'새 갤러리 사진')+'</h2><p class="profile-help">제목은 한국어 또는 영어 중 하나 이상 입력하세요. 비어 있는 언어는 입력한 언어로 표시합니다.</p>'+bilingual('title','제목',r.title,false)+
        (project?'<div class="catalog-field-pair">'+input('year','표시 연도',r.year||new Date().getFullYear(),'number','required min="1900" max="2200"')+'<label>진행 상태<select name="status">'+Object.keys(statuses).map(s=>'<option value="'+s+'" '+((r.status||'active')===s?'selected':'')+'>'+statuses[s]+'</option>').join('')+'</select></label></div>'+input('period','연구 기간 (예: 2026.03–2028.02)',r.period)+bilingual('funder','지원기관',r.funder,false)+input('source','관련 링크 (선택)',r.source,'url'):
          input('date','촬영일',r.date||new Date().toLocaleDateString('sv-SE'),'date','required')+'<label>사진 선택 (JPEG·PNG·WebP, 10MB 이하)<input name="image" type="file" accept="image/jpeg,image/png,image/webp" '+(r.id?'':'required')+'></label><img class="catalog-upload-preview" '+(r.photo?'src="'+esc(r.photo)+'"':'hidden')+' alt="사진 미리보기"><p class="profile-help">사진은 원본 비율로 최대 1200px까지 축소하여 서버에 저장합니다.</p>')+
        bilingual('description','설명',r.description,true)+'<div class="catalog-admin-tools"><button type="submit">'+(r.id?'변경사항 저장':'등록')+'</button>'+(r.id?'<button type="button" id="catalog-delete" class="danger-outline">삭제</button>':'')+'</div></form></div>';
      host.querySelector('#catalog-new').onclick=()=>{if(canLeave()){dirty=false;selected=null;draw();}};
      host.querySelector('#catalog-refresh').onclick=()=>{if(canLeave())open(kind);};
      host.querySelectorAll('[data-item]').forEach(b=>b.onclick=()=>{if(canLeave()){dirty=false;selected=rows.find(r=>r.id===b.dataset.item);draw();}});
      var form=host.querySelector('form');form.oninput=()=>{dirty=true;};form.onsubmit=save;
      var remove=host.querySelector('#catalog-delete');if(remove)remove.onclick=destroy;
      var file=form.elements.image;if(file)file.onchange=()=>{
        dirty=true; var image=host.querySelector('.catalog-upload-preview');
        if(!file.files[0])return;var url=URL.createObjectURL(file.files[0]);image.onload=image.onerror=()=>URL.revokeObjectURL(url);image.src=url;image.hidden=false;
      };
    }
    function setBusy(value){busy=value;host.querySelectorAll('button,input,textarea,select').forEach(el=>{el.disabled=value;});}
    async function open(next){kind=next;dirty=false;selected=null;var request=++epoch;host.innerHTML='<p role="status">목록을 불러오는 중입니다.</p>';
      try{var data=await options.api('/api/'+next);if(request!==epoch)return;if(!Array.isArray(data))throw new Error('목록 형식 오류');rows=data;draw();}
      catch(error){if(request!==epoch)return;message('목록을 불러오지 못했습니다. 최신 서버 업데이트 적용 여부를 확인해 주세요.');}
    }
    function errorText(error){if(error.status===401){options.onUnauthorized();return;}message(error.message||'저장에 실패했습니다. 입력 내용은 유지됩니다.');}
    function base64(blob){return new Promise((resolve,reject)=>{var reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('사진을 읽지 못했습니다.'));reader.readAsDataURL(blob);});}
    async function save(event){event.preventDefault();if(busy)return;var form=event.target, values=new FormData(form), payload={};
      ['title','description'].concat(kind==='projects'?['funder']:[]).forEach(key=>payload[key]={ko:values.get(key+'_ko').trim(),en:values.get(key+'_en').trim()});
      if(!payload.title.ko&&!payload.title.en){message('제목을 입력해 주세요.');return;}
      if(kind==='projects'){payload.year=Number(values.get('year'));payload.status=values.get('status');payload.period=values.get('period');payload.source=values.get('source');}else payload.date=values.get('date');
      if(selected)payload.revision=selected.revision;
      var request=epoch, id=selected&&selected.id, target=kind;setBusy(true);message('저장 중입니다.');
      try{if(target==='gallery'&&values.get('image').size)payload.image=await base64(await window.AILAB_ADMIN_PEOPLE.photoPng(values.get('image'),1200));
        var saved=await options.api('/api/admin/'+target+(id?'/'+id:''),{method:id?'PUT':'POST',body:JSON.stringify(payload)});
        if(request!==epoch)return;rows=id?rows.map(r=>r.id===id?saved:r):[saved].concat(rows);selected=saved;dirty=false;draw();message('저장했습니다. 홈페이지에 바로 반영됩니다.');
      }catch(error){if(request===epoch)errorText(error);}finally{setBusy(false);}
    }
    async function destroy(){if(busy||!selected||!window.confirm('이 항목을 홈페이지에서 삭제할까요?'))return;var request=epoch,id=selected.id;setBusy(true);
      try{await options.api('/api/admin/'+kind+'/'+id,{method:'DELETE',body:JSON.stringify({revision:selected.revision})});if(request!==epoch)return;rows=rows.filter(r=>r.id!==id);selected=null;dirty=false;draw();message('삭제했습니다.');}catch(error){if(request===epoch)errorText(error);}finally{setBusy(false);}
    }
    window.addEventListener('beforeunload',event=>{if(dirty||busy){event.preventDefault();event.returnValue='';}});
    return {open:open,reset:reset,canLeave:canLeave};
  }};
})();
