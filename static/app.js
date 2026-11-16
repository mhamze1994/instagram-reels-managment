const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const fa = n => new Intl.NumberFormat('fa-IR').format(n || 0);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const statusNames = {ready:'آماده', trial:'Trial', published:'منتشرشده', archived:'بایگانی'};
const state = {view:'library', page:1, status:'', videos:[], total:0, selected:null, file:null, groups:[], cached:new Set(), bankPage:1};
let preparation, toastTimer, searchTimer;
function toast(text) { $('#toast').textContent=text; $('#toast').classList.add('visible'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),4500); }
async function api(path, options={}) {
  const headers = {...options.headers};
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type']='application/json';
  const r=await fetch(path,{...options,headers});
  if (!r.ok) {
    let message='ارتباط با سرور انجام نشد.';
    try { const data=await r.json(); message=typeof data.detail==='string'?data.detail:'لطفاً ورودی‌ها و گزینه‌های سؤال را بررسی کن.'; } catch {}
    throw new Error(message);
  }
  return r.json();
}
function view(name) {
  state.view=name;
  $$('.view').forEach(x=>x.hidden=x.id!==`view-${name}`);
  $$('.nav').forEach(x=>x.classList.toggle('active',x.dataset.view===name));
  $('#page-label').textContent={library:'کتابخانه',upload:'ورود ویدیوها',create:'ساخت ریلز',jobs:'صف تولید'}[name];
  if(name==='library') loadVideos(); if(name==='jobs') loadJobs();
  window.scrollTo({top:0,behavior:'smooth'});
}
$$('[data-view]').forEach(x=>x.onclick=()=>view(x.dataset.view));
$$('[data-go]').forEach(x=>x.onclick=()=>view(x.dataset.go));
async function loadVideos() {
  try {
    const query=new URLSearchParams({page:state.page,q:$('#search').value,status:state.status,category:$('#category-filter').value});
    const data=await api('/api/videos?'+query);
    state.videos=data.items;state.total=data.total;
    const counts=data.counts;const all=Object.values(counts).reduce((a,b)=>a+b,0);
    $('#nav-count').textContent=fa(all);$('#stat-all').textContent=fa(all);$('#stat-ready').textContent=fa(counts.ready);$('#stat-published').textContent=fa((counts.published||0)+(counts.trial||0));
    const selected=$('#category-filter').value;
    $('#category-filter').innerHTML='<option value="">همهٔ موضوع‌ها</option>'+data.categories.map(x=>`<option value="${esc(x)}">${esc(x||'بدون موضوع')}</option>`).join('');$('#category-filter').value=selected;
    $('#cards').innerHTML=data.items.map(v=>`<article class="card"><button class="card-visual" data-open="${v.id}" aria-label="باز کردن ${esc(v.title)}"><img src="${v.cover_url}" alt="کاور ${esc(v.title)}" loading="lazy"><span class="card-badge ${v.status}">${statusNames[v.status]}</span><span class="play-circle">▷</span><span class="duration">${Math.floor(v.duration/60)}:${String(Math.round(v.duration)%60).padStart(2,'0')}</span></button><div class="card-body"><span class="card-category">${esc(v.category||'بدون موضوع')}</span><h3 class="card-title">${esc(v.title)}</h3><div class="card-info"><span>${fa((v.size/1048576).toFixed(1))} مگابایت</span><span>${state.cached.has(v.id)?'روی این دستگاه آماده است':v.intended_mode==='trial'?'برای Trial':'برای انتشار عمومی'}</span></div><button class="primary" data-open="${v.id}">آماده‌سازی و انتشار ↗</button></div></article>`).join('');
    $('#empty').hidden=data.items.length>0;$('#results-label').textContent=`${fa(data.total)} ویدیو`;
    if(data.total===0 && ($('#search').value||state.status||selected)) {$('#empty h2').textContent='چیزی با این فیلتر پیدا نشد';$('#empty p').textContent='جست‌وجو یا فیلتر را تغییر بده.';} else {$('#empty h2').textContent='این قفسه منتظر اولین ریلز است';$('#empty p').textContent='ویدیوهای آماده را با کاور و کپشن وارد کن، یا سه سؤال انتخاب کن و ریلز بساز.';}
    $('#page-number').textContent=`${fa(state.page)} / ${fa(Math.max(1,Math.ceil(data.total/30)))}`;$('#prev').disabled=state.page<=1;$('#next').disabled=state.page*30>=data.total;
    $$('[data-open]').forEach(x=>x.onclick=()=>openVideo(x.dataset.open));
    $('#connection-label').textContent='متصل به کتابخانه';
  }catch(e){$('#results-label').textContent=e.message;$('#connection-label').textContent='خطای ارتباط';}
}
$$('[data-status]').forEach(x=>x.onclick=()=>{state.status=x.dataset.status;state.page=1;$$('[data-status]').forEach(b=>b.classList.toggle('selected',b===x));loadVideos();});
$('#search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.page=1;loadVideos();},250);};
$('#category-filter').onchange=()=>{state.page=1;loadVideos();};
$('#prev').onclick=()=>{state.page--;loadVideos();};$('#next').onclick=()=>{state.page++;loadVideos();};

// Small, device-local cache. Only videos deliberately opened by the user are fetched.
function cacheDB() {return new Promise((resolve,reject)=>{const r=indexedDB.open('quiz-studio-files',1);r.onupgradeneeded=()=>r.result.createObjectStore('files',{keyPath:'id'});r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
async function cacheGet(id){const d=await cacheDB();return new Promise((resolve,reject)=>{const t=d.transaction('files');const r=t.objectStore('files').get(id);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);t.oncomplete=()=>d.close();});}
async function cachePut(id,blob){if(blob.size>150*1048576)return;const d=await cacheDB();await new Promise((resolve,reject)=>{const t=d.transaction('files','readwrite');const s=t.objectStore('files');const r=s.getAll();r.onsuccess=()=>{const items=r.result.filter(x=>x.id!==id).sort((a,b)=>a.used-b.used);let bytes=items.reduce((n,x)=>n+x.blob.size,0);while(items.length>3||bytes+blob.size>180*1048576){const old=items.shift();if(!old)break;bytes-=old.blob.size;s.delete(old.id);state.cached.delete(old.id);}s.put({id,blob,used:Date.now()});};t.oncomplete=resolve;t.onerror=()=>reject(t.error);});d.close();state.cached.add(id);}
async function cacheKeys(){try{const d=await cacheDB();const r=d.transaction('files').objectStore('files').getAllKeys();r.onsuccess=()=>{state.cached=new Set(r.result);d.close();};}catch{}}
async function prepareVideo(v) {
  preparation?.abort();const controller=new AbortController();preparation=controller;
  state.file=null;$('#share-button').disabled=true;$('#prepare-retry').hidden=true;
  $('#prepare-label').textContent='آماده‌سازی برای همین گوشی…';$('#prepare-message').textContent='در حال دریافت فایل؛ برای این مرحله صفحه را باز نگه دار.';$('#prepare-progress').value=0;
  try{
    let cached;try{cached=await cacheGet(v.id);}catch{}
    let blob=cached?.blob;
    if(!blob){const response=await fetch(v.video_url,{signal:controller.signal});if(!response.ok)throw new Error('دریافت فایل انجام نشد.');
      const total=Number(response.headers.get('content-length'))||v.size;const chunks=[];let received=0;
      if(response.body?.getReader){const reader=response.body.getReader();while(true){const {done,value}=await reader.read();if(done)break;chunks.push(value);received+=value.length;if(received>512*1048576)throw new Error('فایل برای آماده‌سازی در مرورگر بزرگ است؛ از دانلود ویدیو استفاده کن.');$('#prepare-progress').value=Math.round(received/total*100);}blob=new Blob(chunks,{type:'video/mp4'});}else blob=await response.blob();
      cachePut(v.id,blob).catch(()=>{});
    }
    if(controller.signal.aborted||state.selected?.id!==v.id)return;
    state.file=new File([blob],`quiz-${v.id}.mp4`,{type:'video/mp4'});$('#prepare-progress').value=100;
    const supported=!!navigator.canShare?.({files:[state.file]});
    $('#prepare-label').textContent='آمادهٔ اشتراک روی این دستگاه';
    $('#prepare-message').textContent=!isSecureContext?'این آدرس HTTP است. اشتراک مستقیم و کپی خودکار به HTTPS نیاز دارند؛ فعلاً ویدیو و کاور را دانلود کن.':supported?'کپشن کپی می‌شود و منوی اشتراک گوشی باز می‌شود.':'اشتراک فایل در این مرورگر در دسترس نیست. پنل را در Chrome اندروید باز کن؛ یا ویدیو را دانلود کن.';
    $('#share-button').disabled=!supported;
  }catch(e){if(e.name==='AbortError')return;$('#prepare-label').textContent='فایل هنوز آماده نشده';$('#prepare-message').textContent=e.message;$('#prepare-retry').hidden=false;}
}
async function openVideo(id){
  try{const v=await api('/api/videos/'+id);state.selected=v;$('#detail-title').textContent=v.title;$('#detail-meta').textContent=`${v.category} · ${fa(Math.round(v.duration))} ثانیه · ${fa((v.size/1048576).toFixed(1))} مگابایت`;
    $('#detail-video').src=v.video_url;$('#detail-video').poster=v.cover_url;$('#detail-mode').textContent=statusNames[v.status]+' / '+(v.intended_mode==='trial'?'قصد انتشار: Trial':'قصد انتشار: عمومی');
    $('#edit-title').value=v.title;$('#edit-category').value=v.category;$('#edit-caption').value=v.caption;$('#edit-mode').value=v.intended_mode;$('#post-url').value=v.published_url;
    $('#download-video').href=v.video_url+'?download=1';$('#download-cover').href=v.cover_url+'?download=1';$('#share-message').textContent='';
    $('#video-dialog').showModal();prepareVideo(v);
  }catch(e){toast(e.message);}
}
function closeVideo(){preparation?.abort();$('#detail-video').pause();$('#detail-video').removeAttribute('src');state.file=null;$('#video-dialog').close();loadVideos();}
$('#close-video').onclick=closeVideo;
$('#video-dialog').addEventListener('cancel',e=>{e.preventDefault();closeVideo();});
$('#prepare-retry').onclick=()=>prepareVideo(state.selected);
async function copyCaption(){try{if(!navigator.clipboard)throw new Error();await navigator.clipboard.writeText($('#edit-caption').value);toast('کپشن کپی شد؛ در اینستاگرام Paste کن.');return true;}catch{$('.caption-details').open=true;$('#edit-caption').focus();$('#edit-caption').select();toast('کپی خودکار در دسترس نیست؛ متن کپشن را انتخاب و Copy کن.');return false;}}
$('#copy-caption').onclick=copyCaption;
$('#share-button').onclick=async()=>{
  if(!state.file||!navigator.canShare?.({files:[state.file]}))return;
  const id=state.selected.id;const file=state.file;
  // Both API calls begin inside the real click. No network awaits before navigator.share.
  let copyPromise;try{copyPromise=navigator.clipboard?.writeText($('#edit-caption').value);}catch{}
  let sharePromise;try{sharePromise=navigator.share({files:[file]});}catch(e){sharePromise=Promise.reject(e);}
  const shareResult=Promise.resolve(sharePromise).then(()=>({ok:true}),error=>({ok:false,error}));
  const copied=await Promise.resolve(copyPromise).then(()=>!!copyPromise,()=>false);
  try{const result=await shareResult;if(!result.ok)throw result.error;$('#share-message').textContent=copied?'کپشن کپی شد و فایل به مقصد اشتراک تحویل شد. پس از انتشار، وضعیت را ثبت کن.':'فایل به مقصد اشتراک تحویل شد. کپشن کپی نشد؛ دکمهٔ کپی کپشن را بزن.';await api('/api/videos/'+id+'/shared',{method:'POST'});}catch(e){$('#share-message').textContent=e.name==='AbortError'?(copied?'اشتراک لغو شد؛ کپشن کپی شده است.':'اشتراک لغو شد.'):('منوی اشتراک باز نشد. از دانلود ویدیو و کپی کپشن استفاده کن.');}
};
async function saveEdit(status=state.selected.status){
  const payload={title:$('#edit-title').value.trim(),category:$('#edit-category').value.trim(),caption:$('#edit-caption').value,intended_mode:$('#edit-mode').value,status,published_url:$('#post-url').value.trim()};
  try{state.selected=await api('/api/videos/'+state.selected.id,{method:'PATCH',body:JSON.stringify(payload)});$('#detail-title').textContent=state.selected.title;$('#detail-mode').textContent=statusNames[status];toast('ذخیره شد: '+statusNames[status]);loadVideos();}catch(e){toast(e.message);}
}
$('#save-edit').onclick=()=>saveEdit();$('#mark-trial').onclick=()=>saveEdit('trial');$('#mark-public').onclick=()=>saveEdit('published');$('#mark-ready').onclick=()=>saveEdit('ready');$('#archive-video').onclick=async()=>{await saveEdit('archived');};

function fileGroups(files){
  const groups=new Map();for(const file of files){const path=file.webkitRelativePath||file.name;const parent=path.includes('/')?path.slice(0,path.lastIndexOf('/')):'';const name=file.name.toLowerCase();const stem=name.replace(/\.[^.]+$/,'');let key=parent||stem.replace(/[-_](cover|caption)$/,'');
    if(!parent&&['cover.png','cover.jpg','cover.jpeg','caption.txt','episode.json'].includes(name)){const videos=[...files].filter(x=>x.name.toLowerCase().endsWith('.mp4'));if(videos.length===1)key=videos[0].name.replace(/\.mp4$/i,'').toLowerCase();}
    if(!groups.has(key))groups.set(key,{key,title:parent?parent.split('/').pop():stem,state:'منتظر ورود'});const g=groups.get(key);
    if(name.endsWith('.mp4')){if(g.video){g.error='در هر پوشه فقط یک ویدیوی MP4 قرار بده.';}else g.video=file;}
    else if(/\.(png|jpe?g)$/.test(name))g.cover=file;
    else if(name.endsWith('.txt')&&!name.includes('private')&&!name.includes('answer'))g.caption=file;
    else if(name==='episode.json')g.episode=file;
  }return [...groups.values()].filter(x=>x.video);
}
async function selectFiles(files){state.groups=fileGroups([...files]);for(const g of state.groups){if(g.episode){try{const ep=JSON.parse(await g.episode.text());g.title=ep.hook||ep.title||g.title;g.category=ep.category||'';}catch{}}}$('#upload-summary').hidden=false;renderUploadRows();$('#upload-message').textContent=state.groups.length?`${fa(state.groups.length)} ویدیو شناسایی شد.`:'فایل MP4 پیدا نشد.';$('#upload-start').disabled=!state.groups.length;}
function renderUploadRows(){$('#upload-list').innerHTML=state.groups.map(g=>`<div class="upload-row"><div>${esc(g.title)}<small>${g.cover?'کاور ✓':'کاور از ویدیو'} · ${g.caption?'کپشن ✓':'بدون کپشن'} · ${fa((g.video.size/1048576).toFixed(1))} MB</small></div><span class="upload-state ${g.error?'error':''}">${esc(g.error||g.state)}</span></div>`).join('');}
$('#upload-files').onchange=e=>selectFiles(e.target.files);$('#upload-folder').onchange=e=>selectFiles(e.target.files);
$('#dropzone').ondragover=e=>{e.preventDefault();$('#dropzone').classList.add('drag');};$('#dropzone').ondragleave=()=>$('#dropzone').classList.remove('drag');$('#dropzone').ondrop=e=>{e.preventDefault();$('#dropzone').classList.remove('drag');selectFiles(e.dataTransfer.files);};
function uploadOne(data,onProgress){return new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST','/api/upload');xhr.upload.onprogress=e=>{if(e.lengthComputable)onProgress(e.loaded/e.total);};xhr.onload=()=>{try{const d=JSON.parse(xhr.responseText);if(xhr.status<200||xhr.status>=300)throw new Error(d.detail||'ورود فایل انجام نشد.');resolve(d);}catch(e){reject(e);}};xhr.onerror=()=>reject(new Error('ارتباط قطع شد؛ فایل‌های واردشده محفوظ‌اند.'));xhr.send(data);});}
$('#upload-start').onclick=async()=>{
  const button=$('#upload-start');button.disabled=true;let done=0;const groups=state.groups;
  for(let i=0;i<groups.length;i++){const g=groups[i];if(g.error)continue;g.state='در حال ارسال…';renderUploadRows();const data=new FormData();data.append('video',g.video);if(g.cover)data.append('cover',g.cover);data.append('title',g.title.slice(0,160));data.append('category',g.category||$('#upload-category').value);data.append('caption',g.caption?await g.caption.text():'');
    try{const r=await uploadOne(data,p=>$('#upload-progress').value=(i+p)/groups.length*100);g.state=r.created?'وارد شد ✓':'از قبل موجود است ✓';done++;}catch(e){g.error=e.message;}renderUploadRows();
  }$('#upload-progress').value=100;$('#upload-message').textContent=`${fa(done)} از ${fa(groups.length)} فایل وارد یا تطبیق داده شد.`;button.disabled=false;loadVideos();
};

$('#question-forms').innerHTML=[1,2,3].map(i=>`<fieldset class="question-block" data-question="${i}"><div class="question-heading"><strong>سؤال ${fa(i)}</strong><small>${['شروع آشنا','فرصت امتیاز گرفتن','خاطره‌انگیزترین سؤال؛ پاسخ پنهان'][i-1]}</small></div><label>متن سؤال<textarea data-qtext required maxlength="240" placeholder="متن سؤال ${fa(i)}"></textarea></label><div class="options-grid">${['الف','ب','ج','د'].map((letter,j)=>`<label class="option-field"><input type="radio" name="answer-${i}" value="${j}" ${j===0?'checked':''} aria-label="گزینهٔ درست ${letter} سؤال ${fa(i)}"><input type="text" data-option required maxlength="80" placeholder="گزینهٔ ${letter}" aria-label="گزینهٔ ${letter} سؤال ${fa(i)}"></label>`).join('')}</div><small class="correct-guide">دایرهٔ کنار گزینهٔ درست را انتخاب کن.</small></fieldset>`).join('');
$('#create-form').onsubmit=async e=>{e.preventDefault();const form=e.target;const submit=form.querySelector('[type=submit]');submit.disabled=true;$('#create-message').textContent='';
  try{const questions=$$('[data-question]').map(x=>({text:x.querySelector('[data-qtext]').value.trim(),options:[...x.querySelectorAll('[data-option]')].map(y=>y.value.trim()),answer_index:Number(x.querySelector('[type=radio]:checked').value)}));const ep={title:form.elements.title.value,category:form.elements.category.value,caption:form.elements.caption.value,intended_mode:form.elements.intended_mode.value,questions};await api('/api/render',{method:'POST',body:JSON.stringify({episodes:[ep]})});toast('به صف تولید اضافه شد.');view('jobs');}catch(err){$('#create-message').textContent=err.message;}finally{submit.disabled=false;}
};
$('#batch-file').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>10*1048576)throw new Error('فایل JSON بیش از حد بزرگ است.');const data=JSON.parse(await file.text());const episodes=Array.isArray(data)?data:data.episodes;if(!episodes?.length||episodes.length>300)throw new Error('بین ۱ تا ۳۰۰ مجموعه لازم است.');await api('/api/render',{method:'POST',body:JSON.stringify({episodes})});toast(`${fa(episodes.length)} مجموعه به صف تولید اضافه شد.`);view('jobs');}catch(err){toast(err.message);}};
let bankItems=[];
async function searchBank(append=false){try{if(!append)state.bankPage=1;const data=await api('/api/questions?'+new URLSearchParams({q:$('#bank-query').value,page:state.bankPage}));bankItems=append?[...bankItems,...data.items]:data.items;$('#bank-message').textContent=`${fa(data.total)} سؤال؛ صحت سؤال انتخابی را قبل از تولید بررسی کن.`;$('#bank-results').innerHTML=bankItems.map((q,i)=>`<article class="bank-item"><p>${esc(q.text)}</p><div class="button-row">${[1,2,3].map(n=>`<button class="secondary" data-bank="${i}" data-slot="${n}">سؤال ${fa(n)} ←</button>`).join('')}</div></article>`).join('');$$('[data-bank]').forEach(b=>b.onclick=()=>{const q=bankItems[Number(b.dataset.bank)];const f=$(`[data-question="${b.dataset.slot}"]`);f.querySelector('[data-qtext]').value=q.text;[...f.querySelectorAll('[data-option]')].forEach((o,i)=>o.value=q.options[i]);f.querySelector(`[type=radio][value="${q.answer_index}"]`).checked=true;toast('در سؤال '+fa(b.dataset.slot)+' قرار گرفت.');});$('#bank-more').hidden=bankItems.length>=data.total;}catch(e){$('#bank-message').textContent=e.message;}}
$('#bank-search').onclick=()=>searchBank();$('#bank-query').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();searchBank();}};$('#bank-more').onclick=()=>{state.bankPage++;searchBank(true);};
$('#bank-sync').onclick=async()=>{try{await api('/api/bank/sync',{method:'POST'});toast('همگام‌سازی به صف اضافه شد.');view('jobs');}catch(e){toast(e.message);}};
async function loadJobs(){try{const data=await api('/api/jobs');const active=data.items.filter(j=>['queued','running'].includes(j.state)).length;$('#jobs-count').textContent=fa(active);$('#jobs-list').innerHTML=data.items.length?data.items.map(j=>`<article class="job"><div><h3>${esc(j.title)}</h3><p>${j.kind==='sync'?'همگام‌سازی بانک سؤال':'تولید ویدیو با قالب تأییدشده'}${j.state==='running'?' · '+fa(j.progress)+'٪':''}</p>${j.error?`<p class="error">${esc(j.error)}</p>`:''}${j.state==='failed'?`<button class="secondary" data-retry="${j.id}">تلاش دوباره</button>`:''}${j.video_id?`<button class="secondary" data-job-video="${j.video_id}">باز کردن ویدیو ↗</button>`:''}</div><span class="job-badge ${j.state}">${({queued:'در انتظار',running:'در حال ساخت',done:'آماده ✓',failed:'انجام نشد'})[j.state]}</span>${j.state==='running'?`<progress max="100" value="${j.progress}"></progress>`:''}</article>`).join(''):'<div class="empty"><h2>صف تولید خالی است</h2><p>سه سؤال انتخاب کن، یا فایل JSON مجموعه‌ها را وارد کن.</p></div>';$$('[data-retry]').forEach(x=>x.onclick=async()=>{try{await api('/api/jobs/'+x.dataset.retry+'/retry',{method:'POST'});loadJobs();}catch(e){toast(e.message);}});$$('[data-job-video]').forEach(x=>x.onclick=()=>openVideo(x.dataset.jobVideo));}catch(e){$('#jobs-list').textContent=e.message;}}
$('#refresh-jobs').onclick=loadJobs;
$('#help-open').onclick=()=>{$('#help-dialog').showModal();$('#device-check').textContent=`اتصال امن: ${isSecureContext?'بله ✓':'خیر؛ HTTPS لازم است'} | کپی کپشن: ${navigator.clipboard?'موجود ✓':'ناموجود'} | منوی اشتراک فایل: ${navigator.canShare?.({files:[new File(['test'],'test.mp4',{type:'video/mp4'})]})?'موجود ✓':'ناموجود در این مرورگر'}`;};$('#close-help').onclick=()=>$('#help-dialog').close();
$('#mobile-help').onclick=$('#help-open').onclick;
$('#clear-cache').onclick=async()=>{try{const d=await cacheDB();await new Promise((resolve,reject)=>{const t=d.transaction('files','readwrite');t.objectStore('files').clear();t.oncomplete=resolve;t.onerror=()=>reject(t.error);});d.close();state.cached.clear();toast('فایل‌های موقت این دستگاه پاک شد؛ کتابخانهٔ سرور محفوظ است.');}catch{toast('حافظهٔ محلی در دسترس نیست.');}};
async function init(){await cacheKeys();await loadVideos();await loadJobs();try{const info=await api('/api/info');$('#bank-sync').disabled=!info.bank_sync_available;if(!info.bank_sync_available)$('#bank-sync').title='کلید API باید روی سرور تنظیم شود.';if(!info.render_available)$('#create-message').textContent='قالب رندر هنوز روی سرور نصب نشده است.';}catch{}if('serviceWorker'in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});}
setInterval(()=>{if(document.visibilityState==='visible'&&state.view==='jobs')loadJobs();},4000);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&state.view==='library')loadVideos();});
init();
