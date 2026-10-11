'use strict';
// Extend existing components and use their real row arrays, not scraped cells.
let exportTables=[];
const exportRender=render,exportTable=table,exportAudit=audit,exportBacklogs=backlogs,
      exportEvents=events,exportSimulation=simulation,exportPreview=preview,exportSheet=sheet;
function exportActions(dataset){return `<div class="export-actions"><button data-download="csv" data-dataset="${dataset}">Download CSV</button><button data-download="pdf" data-dataset="${dataset}">Download PDF</button></div>`;}
render=function(){exportTables=[];exportRender();};
table=function(rows){const index=exportTables.push(rows.map(r=>({...r})))-1;return `<div class="export-actions"><button data-csv-table="${index}">Download CSV</button></div>`+exportTable(rows);};
audit=function(){return exportActions('history')+exportAudit();};
backlogs=function(){return exportActions('backlog')+exportBacklogs();};
events=function(){return exportActions('disruptions')+exportEvents();};
simulation=function(){return `<div class="export-actions"><button data-csv-editable>Download CSV - editable timetable</button><button data-download="csv" data-dataset="timetable">Download CSV - ${user.role==='authority'?'all stations':'my station'}</button></div>`+exportSimulation();};
preview=function(){return exportPreview().replace('<h3 class="section-gap">Changes and downstream effects</h3>',`<div class="export-actions"><button data-csv-changes>Download CSV - scheduling changes</button></div><h3 class="section-gap">Changes and downstream effects</h3>`);};
sheet=function(){return `<div class="export-actions"><button data-csv-sheet>Download CSV - selected day (all columns)</button></div>`+exportSheet();};
function csvCell(v){if(v==null)return '';let s=String(v);if(typeof v==='string'&&(/^\s*[=+@-]/.test(s)||/^[\t\r\n]/.test(s)))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';}
async function saveCsv(headers,rows,name){
 const parts=['\ufeff',headers.map(csvCell).join(',')+'\r\n'];
 for(let i=0;i<rows.length;i+=250){parts.push(rows.slice(i,i+250).map(r=>headers.map(h=>csvCell(r[h])).join(',')).join('\r\n')+'\r\n');if(i+250<rows.length)await new Promise(resolve=>setTimeout(resolve,0));}
 saveBlob(new Blob(parts,{type:'text/csv;charset=utf-8'}),name);
}
function saveBlob(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);}
function exportFilename(kind){return `railflow-${kind}-${(title(selected)||'all').replace(/[^\p{L}\p{N}-]+/gu,'-')}-${state.service_date}.csv`;}
function fullTime(m,base=state.service_date){return m==null?'':dateAt(m,base)+' '+time(m);}
function timetableRecords(rows){return rows.map(r=>({train:r.train,name:r.name,stop:r.stop+1,station:r.station,station_name:title(r.station),service_date:r.service_date||state.service_date,planned_arrival:fullTime(r.scheduled_arrival,r.service_date),arrival:fullTime(r.arrival,r.service_date),planned_departure:fullTime(r.scheduled_departure,r.service_date),departure:fullTime(r.departure,r.service_date),platform:r.platform,previous_platform:r.previous_platform||'',arrival_delay:r.arrival-r.scheduled_arrival,departure_delay:r.departure-r.scheduled_departure,status:r.departure<r.scheduled_departure?'Early departure':r.departure>r.scheduled_departure?'Delayed departure':'On-time departure',reason:r.reason}));}
const timetableHeaders=['train','name','stop','station','station_name','service_date','planned_arrival','arrival','planned_departure','departure','platform','previous_platform','arrival_delay','departure_delay','status','reason'];
document.addEventListener('click',async event=>{const b=event.target.closest('button');if(!b)return;
 if(!b.dataset.download&&!b.hasAttribute('data-csv-table')&&!b.hasAttribute('data-csv-editable')&&!b.hasAttribute('data-csv-changes')&&!b.hasAttribute('data-csv-sheet'))return;
 b.disabled=true;try{
  if(b.dataset.download){const q=new URLSearchParams({dataset:b.dataset.dataset,format:b.dataset.download,revision:state.revision});
   const response=await fetch('/api/download?'+q,{credentials:'same-origin'});if(!response.ok){const d=await response.json();throw Error(d.error||'Export failed');}
   const header=response.headers.get('Content-Disposition')||'';const name=/filename=([^;]+)/.exec(header)?.[1]||`railflow-${b.dataset.dataset}.${b.dataset.download}`;
   saveBlob(await response.blob(),name);
  }else if(b.hasAttribute('data-csv-table')){await saveCsv(timetableHeaders,timetableRecords(exportTables[Number(b.dataset.csvTable)]||[]),exportFilename('timetable'));
  }else if(b.hasAttribute('data-csv-editable')){
   const rows=state.plan.rows.filter(r=>user.role==='authority'||r.station===user.station).sort((a,b)=>a.arrival-b.arrival||a.train.localeCompare(b.train));
   const records=timetableRecords(rows).map(r=>{const el=[...document.querySelectorAll('[data-edit-train]')].find(e=>e.dataset.editTrain===r.train&&Number(e.dataset.editStop)===r.stop-1);
    return {...r,requested_arrival:el?fullTime(minutes(el.querySelector('[data-field=arrival]').value)):r.arrival,requested_departure:el?fullTime(minutes(el.querySelector('[data-field=departure]').value)):r.departure,required_platform:el?.querySelector('[data-field=required_platform]').value||'',edit_reason:el?.querySelector('[data-field=reason]').value||'',publication:'Editable inputs - not an approved schedule'};});
   await saveCsv([...timetableHeaders,'requested_arrival','requested_departure','required_platform','edit_reason','publication'],records,exportFilename('editable'));
  }else if(b.hasAttribute('data-csv-changes')){
   const cc=pending?.result.state.last_changes||[];const records=cc.map(c=>({train:c.train,station:c.station,station_name:title(c.station),before_arrival:fullTime(c.before?.arrival,c.before?.service_date),before_departure:fullTime(c.before?.departure,c.before?.service_date),before_platform:c.before?.platform??'',arrival:fullTime(c.after?.arrival,c.after?.service_date),departure:fullTime(c.after?.departure,c.after?.service_date),platform:c.after?.platform??'',arrival_change:c.before&&c.after?c.after.arrival-c.before.arrival:'',departure_change:c.before&&c.after?c.after.departure-c.before.departure:'',reason:c.reason,status:c.after?'Draft - review required':'Unscheduled - cannot publish'}));
   await saveCsv(['train','station','station_name','before_arrival','before_departure','before_platform','arrival','departure','platform','arrival_change','departure_change','reason','status'],records,exportFilename('draft-changes'));
  }else{
   const sid=user.role==='master'?user.station:(sheetStation||selected),start=sheetDay*1440,end=start+1440;
   const rows=state.plan.rows.filter(r=>(sheetMode!=='station'&&user.role==='authority'||r.station===sid)&&r.departure>start&&r.arrival<end);
   if(sheetMode==='lines'&&user.role==='authority'){
    const movements=state.trains.flatMap(t=>{const calls=state.plan.rows.filter(r=>r.train===t.id).sort((a,b)=>a.stop-b.stop);return calls.slice(1).map((r,i)=>({train:t.id,name:t.name,from:title(calls[i].station),to:title(r.station),departure:fullTime(calls[i].departure),arrival:fullTime(r.arrival),platform:r.platform,reason:r.reason,start:calls[i].departure,end:r.arrival}));}).filter(r=>r.end>start&&r.start<end);
    await saveCsv(['train','name','from','to','departure','arrival','platform','reason'],movements,exportFilename('line-movements'));
   }else await saveCsv(timetableHeaders,timetableRecords(rows),exportFilename('occupancy-day'));
  }
 }catch(error){toast(error.message,true);}finally{b.disabled=false;}
});
// A purple badge is only derived from a real previous assignment.
function platformReassignment(r){return r.previous_platform&&r.previous_platform!==r.platform?badge(`Platform reassigned: P${r.previous_platform} → P${r.platform}`,'purple'):'';}
const exportCallStatus=callStatus;
callStatus=function(r){return exportCallStatus(r)+platformReassignment(r);};
