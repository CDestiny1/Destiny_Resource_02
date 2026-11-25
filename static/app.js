"use strict";

const $ = (q, root=document) => root.querySelector(q);
const $$ = (q, root=document) => [...root.querySelectorAll(q)];
const state = {loaded:false, meta:null, current:null, original:null, page:1, pages:1, query:"", team:"", table:"", formDirty:false, replaceChoice:null,lineup:null,lineupOrder:[],lineupFormation:[],lineupDirty:false,swapIndex:null,adminTeam:null,assetsStatus:null,importSourceTeams:[],importDbSummary:null,importPreview:null};
const base = location.pathname.endsWith("/") ? location.pathname : location.pathname + "/";

const STAT_LABELS = {
  offensive_awareness:"Actitud ofensiva",ball_control:"Control de balón",dribbling:"Regate",tight_possession:"Conservación",
  low_pass:"Pase raso",lofted_pass:"Pase bombeado",finishing:"Finalización",heading:"Cabeceo",place_kicking:"Balón parado",
  curl:"Efecto",speed:"Velocidad",acceleration:"Aceleración",kicking_power:"Potencia de tiro",jump:"Salto",
  physical_contact:"Contacto físico",balance:"Equilibrio",stamina:"Resistencia",defensive_awareness:"Actitud defensiva",
  ball_winning:"Recuperación",aggression:"Agresividad",gk_awareness:"Actitud de portero",gk_catching:"Atrapadas",
  gk_clearing:"Despejes",gk_reflexes:"Reflejos de portero",gk_reach:"Cobertura de portero"
};
const POSITIONS = {
  GK:[50,91],CB:[50,77],LB:[20,72],RB:[80,72],DMF:[50,62],CMF:[50,50],LMF:[22,48],RMF:[78,48],
  AMF:[50,38],LWF:[22,25],RWF:[78,25],SS:[50,23],CF:[50,9]
};
const ROLE_NAMES = {
  GK:"Portero",CB:"Defensa central",LB:"Lateral izquierdo",RB:"Lateral derecho",DMF:"Mediocentro defensivo",
  CMF:"Mediocentro",LMF:"Medio izquierdo",RMF:"Medio derecho",AMF:"Mediapunta",LWF:"Extremo izquierdo",
  RWF:"Extremo derecho",SS:"Segundo delantero",CF:"Delantero centro"
};
const ROLE_SHORT = {
  GK:"Portero",CB:"Defensa",LB:"Lateral izq.",RB:"Lateral der.",DMF:"MCD",CMF:"MC",LMF:"Medio izq.",
  RMF:"Medio der.",AMF:"Mediapunta",LWF:"Extremo izq.",RWF:"Extremo der.",SS:"2.º delantero",CF:"Delantero"
};
function roleName(code,compact=false){return (compact?ROLE_SHORT:ROLE_NAMES)[code]||code}

async function request(path, options={}) {
  const response = await window.DFP.fetch(path, options);
  const type = response.headers.get("content-type") || "";
  if (!response.ok || type.includes("application/json")) {
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || "La operación no pudo completarse");
    return data;
  }
  return response;
}
async function post(path, payload) {
  return request(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
}
function busy(on, text="Procesando…") { $("#busy").classList.toggle("hidden",!on); $("#busyText").textContent=text; }
function toast(message, error=false) {
  const item=document.createElement("div"); item.className="toast"+(error?" error":""); item.textContent=message;
  $("#toastArea").append(item); setTimeout(()=>item.remove(),4300);
  $("#statusText").textContent=message; $("#statusDot").classList.toggle("error",error);
}
function initials(name="") { return name.split(/\s+/).filter(Boolean).slice(0,2).map(x=>x[0]).join("").toUpperCase() || "--"; }
function escapeText(value) { const d=document.createElement("div"); d.textContent=String(value??""); return d.innerHTML; }
function markDirty(value=true) {
  state.formDirty=value;
  $("#dirtyBadge").textContent=value?"CAMBIOS SIN GUARDAR":"SIN CAMBIOS";
  $("#dirtyBadge").classList.toggle("changed",value);
}
function updateSummary(summary) {
  if (!summary) return;
  if (state.meta) state.meta.summary=summary;
  $("#summaryText").textContent=`${summary.players.toLocaleString("es")} jugadores · ${summary.teams.toLocaleString("es")} equipos · ${summary.undo} operaciones`;
  $("#undoBtn").disabled=!summary.undo;
  $("#exportBtn").disabled=false;
}
function setActions(enabled) { ["saveBtn","createBtn","replaceBtn"].forEach(id=>$("#"+id).disabled=!enabled);$("#lineupBtn").disabled=!state.loaded;$("#teamsBtn").disabled=!state.loaded;$("#importTeamBtn").disabled=!state.loaded;$("#exportBtn").disabled=!state.loaded; }

function refreshTeamLists(meta){
  const selected=$("#teamFilter").value;
  $("#teamFilter").innerHTML='<option value="">Todos los equipos</option>'+meta.teams.map(x=>`<option value="${x.id}">${escapeText(x.name)} · ${x.id}</option>`).join("");
  $("#teamFilter").value=selected;
  $("#transferTeamLabel").textContent=`Nuevo club · ${meta.club_teams.length} disponibles`;
  $("#newTeamLabel").textContent=`Club inicial · ${meta.club_teams.length} disponibles`;
}
function buildEditors(meta) {
  const countries=$("#countrySelect"); countries.innerHTML=meta.countries.map(x=>`<option value="${x.id}">${x.id} · ${escapeText(x.name)}</option>`).join("");
  $("#positionSelect").innerHTML=meta.positions.map(x=>`<option value="${x.id}">${x.name} · ${x.code}</option>`).join("");
  refreshTeamLists(meta);
  clearTeam("transfer"); clearTeam("new"); clearTeam("lineup"); clearTeam("admin"); clearTeam("importTarget");
  $("#lineupFormation").innerHTML='<option value="">Conservar formación actual</option>'+Object.keys(meta.formations).map(name=>`<option value="${escapeText(name)}">${escapeText(name)}</option>`).join("");
  $("#statsGrid").innerHTML=meta.stats.map(key=>`<div class="stat-row"><label for="stat-${key}">${escapeText(STAT_LABELS[key]||key)}</label><input id="stat-${key}" name="stat-${key}" type="number" min="40" max="99"><div class="meter"><i></i></div></div>`).join("");
  const parent=$("#positionNodes"); parent.innerHTML="";
  Object.entries(POSITIONS).forEach(([code,[left,top]])=>{
    const node=document.createElement("label"); node.className="position-node"; node.style.left=left+"%"; node.style.top=top+"%";
    node.innerHTML=`<b>${code}</b><select name="pos-${code}" aria-label="Aptitud ${code}"><option value="0">C</option><option value="1">B</option><option value="2">A</option></select>`; parent.append(node);
  });
}

function foldText(value){return String(value??"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase()}
function teamParts(prefix){return {search:$("#"+prefix+"TeamSearch"),hidden:$("#"+prefix+"Team"),results:$("#"+prefix+"TeamResults")}}
function teamSource(prefix){if(prefix==="importSource")return state.importSourceTeams||[];return prefix==="lineup"?(state.meta?.teams||[]):(state.meta?.club_teams||[])}
function clearTeam(prefix){const p=teamParts(prefix);p.hidden.value="";p.search.value="";p.results.classList.add("hidden")}
function chooseTeam(prefix,id){
  const p=teamParts(prefix),team=teamSource(prefix).find(x=>String(x.id)===String(id));if(!team)return;
  p.hidden.value=team.id;p.search.value=`${team.name} · ${team.id}`;p.results.classList.add("hidden")
}
function showTeamResults(prefix){
  const p=teamParts(prefix),query=foldText(p.search.value.trim());
  const found=teamSource(prefix).filter(team=>!query||foldText(team.name).includes(query)||String(team.id).includes(query));
  const shown=found.slice(0,40);
  p.results.innerHTML=shown.length?shown.map(team=>`<button type="button" class="team-option" data-id="${team.id}"><b>${escapeText(team.name)}</b><small>${team.kind==="selection"?"SELECCIÓN · ":"CLUB · "}ID ${team.id}</small></button>`).join("")+(found.length>shown.length?`<div class="team-more">${found.length-shown.length} más · escribe para afinar</div>`:""):'<div class="team-empty">No se encontró ese equipo o ID.</div>';
  p.results.classList.remove("hidden");
}

async function loadFile(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".cpk")) { toast("Selecciona un archivo .cpk",true); return; }
  if (file.size>64*1024*1024) { toast("El archivo supera el límite de 64 MB",true); return; }
  busy(true,"Analizando y validando el CPK…");
  try {
    const data=await request("api/load",{method:"POST",headers:{"Content-Type":"application/octet-stream","X-File-Name":encodeURIComponent(file.name)},body:file});
    state.loaded=true; state.meta=data; state.current=null; state.page=1; state.formDirty=false;state.importSourceTeams=[];state.importDbSummary=null;state.importPreview=null;
    buildEditors(data);clearTeam("importSource");$("#importDbName").textContent="Ninguna database externa cargada";$("#importDbSummary").textContent="Carga el Resource_02 del otro parche; el archivo original no se modificará.";$("#clearImportDbBtn").disabled=true;resetImportPreview(); updateSummary(data.summary); setActions(false); $("#exportBtn").disabled=false;
    $("#emptyState").classList.remove("hidden"); $("#editor").classList.add("hidden");
    await searchPlayers(); toast(`CPK validado: ${data.summary.players.toLocaleString("es")} jugadores encontrados`);
  } catch(e) { toast(e.message,true); }
  finally { busy(false); $("#fileInput").value=""; }
}

async function searchPlayers() {
  if (!state.loaded) return;
  const params=new URLSearchParams({q:state.query,team:state.team,table:state.table,page:state.page,limit:80});
  try {
    const data=await request("api/players?"+params); state.pages=data.pages;
    $("#resultCount").textContent=data.total.toLocaleString("es"); $("#pageLabel").textContent=`Página ${data.page} / ${data.pages}`;
    $("#prevPage").disabled=data.page<=1; $("#nextPage").disabled=data.page>=data.pages;
    const list=$("#playerList");
    list.innerHTML=data.items.length?data.items.map(p=>{const affiliation=p.club_names[0]||(`Sin club${p.selection_names[0]?" · Selección "+p.selection_names[0]:""}`);return `<button class="player-item ${state.current?.key===p.key?"active":""}" data-key="${p.key}" role="option"><span class="mini-avatar">${escapeText(initials(p.name))}</span><span><b class="player-name">${escapeText(p.name)}</b><small class="player-team">${escapeText((p.game_name&&p.game_name!==p.name?p.game_name+" · ":"")+affiliation)}</small></span><span class="player-id"><b>${p.position}</b><small>#${p.id}</small></span></button>`}).join(""):'<div class="no-results">No hay jugadores que coincidan.<br>Prueba otro nombre, ID o equipo.</div>';
    $$(".player-item",list).forEach(button=>button.addEventListener("click",()=>selectPlayer(button.dataset.key)));
  } catch(e) { toast(e.message,true); }
}

async function selectPlayer(key, force=false) {
  if (state.formDirty && !force && !confirm("Hay cambios sin guardar. ¿Quieres descartarlos y cambiar de jugador?")) return;
  try {
    const data=await request("api/player?key="+encodeURIComponent(key)); renderPlayer(data.player);
    await searchPlayers();
  } catch(e) { toast(e.message,true); }
}

function renderPlayer(player) {
  state.current=player; state.original=JSON.parse(JSON.stringify(player)); markDirty(false); setActions(true);
  $("#emptyState").classList.add("hidden"); $("#editor").classList.remove("hidden");
  $("#avatarInitials").textContent=initials(player.display_name); $("#positionBadge").textContent=player.position_name;
  $("#heroName").textContent=player.full_name||player.display_name; $("#heroId").textContent=`ID ${player.id}`;
  const clubAssignment=player.assignments.find(x=>x.team_kind==="club"),selectionAssignment=player.assignments.find(x=>x.team_kind==="selection");
  $("#heroNation").textContent=player.nationality_name; $("#heroTeam").textContent=clubAssignment?.team_name||(`Sin club${selectionAssignment?" · Selección: "+selectionAssignment.team_name:""}`);
  $("#recordType").textContent=player.table.toUpperCase()+".BIN";
  const avg=Math.round(Object.values(player.stats).filter((_,i)=>i<20).reduce((a,b)=>a+b,0)/20); $("#overallValue").textContent=avg;
  ["display_name","shirt_name","full_name","nationality","position","age","height","weight","strong_foot","form","weak_use","weak_accuracy","injury_resistance"].forEach(key=>{
    const el=$(`[name="${key}"]`); if(el) el.value=player[key];
  });
  Object.entries(player.stats).forEach(([key,value])=>{const input=$(`#stat-${key}`);if(input){input.value=value;updateMeter(input)}});
  Object.entries(player.playable).forEach(([key,value])=>{const input=$(`[name="pos-${key}"]`);if(input)input.value=value});
  renderAssignments(player.assignments);
  $(".workspace").classList.add("show-editor");
}

function renderAssignments(rows) {
  const clubRows=rows.filter(row=>row.team_kind==="club"),firstClub=clubRows[0];
  $("#assignmentList").innerHTML=rows.length?rows.map(row=>`<button type="button" class="assignment-card ${row===firstClub?"selected":""} ${row.team_kind==="selection"?"protected":""}" data-key="${row.key}" data-kind="${row.team_kind}"><span class="shirt">${row.shirt_number}</span><span><strong>${escapeText(row.team_name)}</strong><small>${row.team_kind==="selection"?"SELECCIÓN PROTEGIDA · ":"CLUB · "}ID ${row.team_id} · orden ${row.squad_order}</small></span></button>`).join(""):'<div class="no-results">Este jugador no tiene inscripción. Puedes crear una con “Traspasar / inscribir”.</div>';
  $("#assignmentSelect").innerHTML='<option value="">Crear nueva inscripción de club</option>'+clubRows.map(row=>`<option value="${row.key}">${escapeText(row.team_name)} · #${row.shirt_number}</option>`).join("");
  if(firstClub){$("#assignmentSelect").value=firstClub.key;fillTransfer(firstClub)} else {$("#assignmentSelect").value="";clearTeam("transfer");$("#transferTitle").textContent="Inscribir en un club"}
  $$(".assignment-card").forEach(card=>card.addEventListener("click",()=>{
    if(card.dataset.kind==="selection"){toast("La selección se conserva protegida. Crea una inscripción de club aparte.");return}
    $$(".assignment-card").forEach(x=>x.classList.toggle("selected",x===card)); $("#assignmentSelect").value=card.dataset.key;
    fillTransfer(state.current.assignments.find(x=>x.key===card.dataset.key));
  }));
}
function fillTransfer(row) { if(!row)return; chooseTeam("transfer",row.team_id);$("#transferShirt").value=row.shirt_number;$("#transferOrder").value=row.squad_order;$("#transferTitle").textContent="Editar inscripción seleccionada"; }
function updateMeter(input){const n=Math.max(40,Math.min(99,Number(input.value)||40));$(".meter i",input.closest(".stat-row")).style.width=((n-40)/59*100)+"%"}

function collectValues() {
  const form=$("#playerForm"); const fd=new FormData(form); const values={};
  ["display_name","shirt_name","full_name"].forEach(k=>values[k]=String(fd.get(k)||"").trim());
  ["nationality","position","age","height","weight","strong_foot","form","weak_use","weak_accuracy","injury_resistance"].forEach(k=>values[k]=Number(fd.get(k)));
  values.stats={}; Object.keys(STAT_LABELS).forEach(k=>values.stats[k]=Number($(`#stat-${k}`).value));
  values.playable={}; Object.keys(POSITIONS).forEach(k=>values.playable[k]=Number(fd.get("pos-"+k)));
  return values;
}

async function saveCurrent(){
  if(!state.current)return; busy(true,"Guardando y validando el jugador…");
  try{const data=await post("api/save",{key:state.current.key,values:collectValues()});renderPlayer(data.player);updateSummary(data.summary);await searchPlayers();toast("Jugador guardado correctamente")}catch(e){toast(e.message,true)}finally{busy(false)}
}
async function applyTransfer(){
  if(!state.current)return; const team=$("#transferTeam").value;if(!team){toast("Selecciona el equipo de destino",true);return}
  busy(true,"Aplicando traspaso…");
  try{const data=await post("api/transfer",{key:state.current.key,assignment_key:$("#assignmentSelect").value||null,team_id:Number(team),shirt_number:Number($("#transferShirt").value),squad_order:Number($("#transferOrder").value)});renderPlayer(data.player);updateSummary(data.summary);await searchPlayers();toast("Traspaso e inscripción aplicados")}catch(e){toast(e.message,true)}finally{busy(false)}
}

async function releasePlayer(){
  if(!state.current)return;
  const assignmentKey=$("#assignmentSelect").value;
  const row=state.current.assignments.find(x=>x.key===assignmentKey&&x.team_kind==="club");
  if(!row){toast("Selecciona la inscripción de club que quieres liberar",true);return}
  const name=state.current.full_name||state.current.display_name;
  if(!confirm(`¿Mover a ${name} a jugadores libres?\n\nSe eliminará su inscripción en ${row.team_name}. Su selección (si tiene) no cambia.`))return;
  await sendRelease({key:state.current.key,assignment_key:assignmentKey},async data=>{renderPlayer(data.player);await searchPlayers()});
}
async function releaseFromLineup(assignmentKey,playerKey){
  if(!state.lineup)return;
  if(state.lineupDirty){toast("Guarda o descarta primero los cambios de alineación",true);return}
  const player=orderedLineupRoster().find(item=>item.assignment_key===assignmentKey);if(!player)return;
  if(!confirm(`¿Mover a ${player.name} a jugadores libres?\n\nSe eliminará su inscripción en ${state.lineup.team.name}.`))return;
  await sendRelease({key:playerKey,assignment_key:assignmentKey,team_id:state.lineup.team.id},async data=>{
    if(data.lineup){state.lineup=data.lineup;state.lineupOrder=data.lineup.roster.map(item=>item.assignment_key);state.lineupFormation=data.lineup.formation;state.swapIndex=null;setLineupDirty(false);renderLineup()}
    if(state.current&&state.current.key===playerKey){try{renderPlayer((await request("api/player?key="+encodeURIComponent(playerKey))).player)}catch(_){}}
    await searchPlayers();
  });
}
async function sendRelease(payload,onDone,force=false){
  busy(true,"Moviendo a jugadores libres…");
  try{
    const data=await post("api/release",{...payload,allow_below_minimum:force});
    updateSummary(data.summary);await onDone(data);toast("Jugador movido a jugadores libres");
  }catch(e){
    if(e.message.startsWith("EQUIPO_MINIMO|")){
      const message=e.message.split("|").slice(1).join("|");busy(false);
      if(confirm(message+".\n\n¿Quieres liberarlo de todos modos?"))return await sendRelease(payload,onDone,true);
      return;
    }
    toast(e.message,true);
  }finally{busy(false)}
}

async function openCreate(){
  if(!state.current){toast("Selecciona primero un jugador plantilla",true);return}
  try{const ids=await request("api/available-ids");$("#recommendedId").textContent=ids.recommended;$("#newId").value=ids.recommended;$("#idNote").textContent=ids.note;
    $("#templateName").value=`${state.current.display_name} · ID ${state.current.id}`;$("#newDisplayName").value="NUEVO JUGADOR";$("#newShirtName").value="NUEVO";$("#newFullName").value="Nuevo Jugador";
    const currentClub=state.current.assignments.find(x=>x.team_kind==="club");if(currentClub)chooseTeam("new",currentClub.team_id);else clearTeam("new");showModal("createModal");
  }catch(e){toast(e.message,true)}
}
async function createPlayer(){
  const team=$("#newTeam").value;if(!team){toast("Selecciona un equipo inicial",true);return}
  busy(true,"Creando jugador y comprobando referencias…");
  try{const data=await post("api/create",{new_id:Number($("#newId").value),template_key:state.current.key,team_id:Number(team),shirt_number:Number($("#newShirtNumber").value),values:{display_name:$("#newDisplayName").value,shirt_name:$("#newShirtName").value,full_name:$("#newFullName").value}});hideModal("createModal");renderPlayer(data.player);updateSummary(data.summary);await searchPlayers();toast(`Jugador creado con ID ${data.player.id}`)}catch(e){toast(e.message,true)}finally{busy(false)}
}

function openReplace(){if(!state.current)return;state.replaceChoice=null;$("#replaceTarget").textContent=`${state.current.display_name} · ${state.current.id}`;$("#replaceSource").textContent="Selecciona uno";$("#replaceSearch").value="";$("#replaceResults").innerHTML='<div class="no-results">Escribe un nombre o ID para buscar la plantilla.</div>';$("#confirmReplace").disabled=true;showModal("replaceModal");setTimeout(()=>$("#replaceSearch").focus(),100)}
let replaceTimer;
async function searchReplacement(){clearTimeout(replaceTimer);replaceTimer=setTimeout(async()=>{const q=$("#replaceSearch").value.trim();if(!q)return;try{const data=await request("api/players?"+new URLSearchParams({q,page:1,limit:30}));$("#replaceResults").innerHTML=data.items.filter(p=>p.key!==state.current.key).map(p=>`<button class="replace-option" data-key="${p.key}" data-name="${escapeText(p.name)}"><b>${escapeText(p.name)}</b><small>${p.table} · ID ${p.id}</small></button>`).join("")||'<div class="no-results">Sin coincidencias</div>';
  $$(".replace-option").forEach(b=>b.addEventListener("click",()=>{$$(".replace-option").forEach(x=>x.classList.toggle("selected",x===b));state.replaceChoice=b.dataset.key;$("#replaceSource").textContent=b.dataset.name+" · "+b.dataset.key.split(":")[1];$("#confirmReplace").disabled=false}))}catch(e){toast(e.message,true)}},220)}
async function replaceSlot(){if(!state.replaceChoice)return;if(!confirm("¿Confirmas el reemplazo? Podrás deshacerlo antes de cerrar el programa."))return;busy(true,"Reemplazando slot y validando…");try{const data=await post("api/replace",{target_key:state.current.key,template_key:state.replaceChoice,copy_appearance:$("#copyAppearance").checked,values:{}});hideModal("replaceModal");renderPlayer(data.player);updateSummary(data.summary);await searchPlayers();toast("Slot reemplazado. ID e inscripciones conservados.")}catch(e){toast(e.message,true)}finally{busy(false)}}

function setLineupDirty(value=true){state.lineupDirty=value;$("#lineupDirty").textContent=value?"CAMBIOS SIN GUARDAR":"SIN CAMBIOS";$("#lineupDirty").classList.toggle("changed",value)}
function orderedLineupRoster(){if(!state.lineup)return[];const byKey=new Map(state.lineup.roster.map(item=>[item.assignment_key,item]));return state.lineupOrder.map(key=>byKey.get(key)).filter(Boolean)}
function renderLineup(){
  if(!state.lineup)return;
  const roster=orderedLineupRoster(),formation=state.lineupFormation.length?state.lineupFormation:state.lineup.formation;
  const shirtCounts=new Map();roster.forEach(player=>shirtCounts.set(player.shirt_number,(shirtCounts.get(player.shirt_number)||0)+1));
  $("#lineupTeamName").textContent=state.lineup.team.name;$("#lineupKind").textContent=state.lineup.team.kind==="selection"?"SELECCIÓN NACIONAL":"CLUB";
  $("#lineupFormationName").textContent=$("#lineupFormation").value||state.lineup.formation_name;$("#lineupCount").textContent=`${roster.length} jugadores`;
  const pitch=$("#lineupPitch");pitch.innerHTML='<div class="pitch-lines"></div>'+formation.slice(0,11).map((slot,index)=>{const player=roster[index];if(!player)return"";const left=Math.max(5,Math.min(95,slot.x/104*100)),top=Math.max(6,Math.min(94,(46-slot.y)/46*100)),duplicate=shirtCounts.get(player.shirt_number)>1;return `<button type="button" class="pitch-player ${state.swapIndex===index?"selected":""} ${duplicate?"duplicate-shirt":""}" data-lineup-index="${index}" style="left:${left}%;top:${top}%" title="${duplicate?`Dorsal ${player.shirt_number} duplicado · `:""}${escapeText(roleName(slot.code))}"><b>${player.shirt_number}</b><span>${escapeText(player.game_name||player.name)}</span><small>${escapeText(roleName(slot.code,true))} · ${player.rating}</small></button>`}).join("");
  $("#lineupRoster").innerHTML=roster.length?roster.map((player,index)=>{const duplicate=shirtCounts.get(player.shirt_number)>1;return `<div class="lineup-row ${index<11?"starter":"bench"} ${state.swapIndex===index?"selected":""} ${duplicate?"duplicate-shirt":""}"><button type="button" class="shirt-edit ${duplicate?"duplicate":""}" data-shirt-key="${player.assignment_key}" title="${duplicate?"Dorsal duplicado · ":""}Cambiar dorsal de ${escapeText(player.name)}">${player.shirt_number}</button><button type="button" class="lineup-player-select" data-lineup-index="${index}"><i>${index+1}</i><span><strong>${escapeText(player.name)}</strong><small>${escapeText(roleName(player.position_code))} · MEDIA ${player.rating} · ID ${player.id}</small></span><em>${index<11?"XI":"BANCA"}</em></button>${state.lineup.team.kind==="selection"?`<button type="button" class="remove-callup" data-assignment-key="${player.assignment_key}" title="Desconvocar a ${escapeText(player.name)}">×</button>`:`<button type="button" class="release-free" data-release-key="${player.assignment_key}" data-player-key="${player.player_key}" title="Mover a ${escapeText(player.name)} a jugadores libres">LIBRE</button>`}</div>`}).join(""):'<div class="callup-empty">Este equipo no tiene jugadores inscritos.</div>';
  $$('[data-lineup-index]').forEach(button=>button.addEventListener("click",()=>swapLineupPlayer(Number(button.dataset.lineupIndex))));
  $$('[data-shirt-key]').forEach(button=>button.addEventListener("click",()=>editLineupShirt(button.dataset.shirtKey)));
  $$('.remove-callup').forEach(button=>button.addEventListener("click",e=>{e.stopPropagation();removeCallup(button.dataset.assignmentKey)}));
  $$('.release-free').forEach(button=>button.addEventListener("click",e=>{e.stopPropagation();releaseFromLineup(button.dataset.releaseKey,button.dataset.playerKey)}));
  $("#callupPanel").classList.toggle("hidden",state.lineup.team.kind!=="selection");
}
function swapLineupPlayer(index){
  if(state.swapIndex===null){state.swapIndex=index;$("#swapHint").textContent="ELIGE EL SEGUNDO JUGADOR";renderLineup();return}
  if(state.swapIndex===index){state.swapIndex=null;$("#swapHint").textContent="ELIGE DOS JUGADORES";renderLineup();return}
  [state.lineupOrder[state.swapIndex],state.lineupOrder[index]]=[state.lineupOrder[index],state.lineupOrder[state.swapIndex]];state.swapIndex=null;$("#swapHint").textContent="ORDEN MODIFICADO";setLineupDirty();renderLineup()
}
async function loadTeamLineup(teamId){
  if(!teamId)return;busy(true,"Cargando plantilla y formación…");
  try{const data=await request("api/team?"+new URLSearchParams({team_id:teamId}));state.lineup=data.lineup;state.lineupOrder=data.lineup.roster.map(item=>item.assignment_key);state.lineupFormation=data.lineup.formation;state.swapIndex=null;$("#lineupFormation").value="";$("#swapHint").textContent="ELIGE DOS JUGADORES";setLineupDirty(false);$("#callupSearch").value="";$("#callupResults").innerHTML='<div class="callup-empty">Escribe un nombre, ID o club para buscar candidatos.</div>';renderLineup()}catch(e){toast(e.message,true)}finally{busy(false)}
}
async function openLineups(){
  if(!state.loaded)return;showModal("lineupModal");
  const preferred=state.current?.assignments.find(item=>item.team_kind==="club")||state.current?.assignments.find(item=>item.team_kind==="selection");
  const teamId=preferred?.team_id||state.lineup?.team?.id||state.meta.teams[0]?.id;if(teamId){chooseTeam("lineup",teamId);await loadTeamLineup(teamId)}
}
function closeLineups(){if(state.lineupDirty&&!confirm("Hay cambios de alineación sin guardar. ¿Quieres descartarlos?"))return;hideModal("lineupModal");state.swapIndex=null}
async function autoSortLineup(){
  if(!state.lineup)return;busy(true,"Evaluando cada jugador en su mejor posición…");
  try{const data=await post("api/team/autosort",{team_id:state.lineup.team.id,preset_name:$("#lineupFormation").value});state.lineupOrder=data.ordered_assignment_keys;state.lineupFormation=data.formation;state.swapIndex=null;setLineupDirty();$("#swapHint").textContent="AUTOSORT PREPARADO";renderLineup();toast("AutoSort completado. Revisa el XI y pulsa Guardar.")}catch(e){toast(e.message,true)}finally{busy(false)}
}
async function saveLineup(){
  if(!state.lineup)return;busy(true,"Guardando orden y táctica…");
  try{const data=await post("api/team/save",{team_id:state.lineup.team.id,ordered_assignment_keys:state.lineupOrder,preset_name:$("#lineupFormation").value});state.lineup=data.lineup;state.lineupOrder=data.lineup.roster.map(item=>item.assignment_key);state.lineupFormation=data.lineup.formation;$("#lineupFormation").value="";setLineupDirty(false);updateSummary(data.summary);renderLineup();toast("Alineación y formación guardadas")}catch(e){toast(e.message,true)}finally{busy(false)}
}
async function editLineupShirt(assignmentKey){
  if(!state.lineup)return;if(state.lineupDirty){toast("Guarda o descarta primero los cambios de alineación",true);return}
  const player=state.lineup.roster.find(item=>item.assignment_key===assignmentKey);if(!player)return;
  const answer=prompt(`Nuevo dorsal para ${player.name} (1–99):`,String(player.shirt_number));if(answer===null)return;const shirt=Number(answer);
  if(!Number.isInteger(shirt)||shirt<1||shirt>99){toast("El dorsal debe estar entre 1 y 99",true);return editLineupShirt(assignmentKey)}
  busy(true,"Actualizando dorsal…");
  try{const data=await post("api/team/shirt",{team_id:state.lineup.team.id,assignment_key:assignmentKey,shirt_number:shirt});state.lineup=data.lineup;state.lineupOrder=data.lineup.roster.map(item=>item.assignment_key);state.lineupFormation=data.lineup.formation;updateSummary(data.summary);renderLineup();toast(`Dorsal de ${player.name} actualizado a ${shirt}`)}
  catch(e){if(e.message.startsWith("DORSAL_OCUPADO|")){alert(e.message.split("|").slice(1).join("|")+". Elige otro número.");busy(false);return await editLineupShirt(assignmentKey)}toast(e.message,true)}finally{busy(false)}
}
let callupTimer;
function debounceCallupSearch(){clearTimeout(callupTimer);callupTimer=setTimeout(searchCallupCandidates,220)}
async function searchCallupCandidates(){
  if(!state.lineup||state.lineup.team.kind!=="selection")return;const q=$("#callupSearch").value.trim();if(!q){$("#callupResults").innerHTML='<div class="callup-empty">Escribe un nombre, ID o club para buscar candidatos.</div>';return}
  try{const data=await request("api/callup-candidates?"+new URLSearchParams({team_id:state.lineup.team.id,q,limit:80}));$("#callupResults").innerHTML=data.items.length?data.items.map(player=>`<article class="callup-card ${!player.eligible?"mismatch":""}"><span class="candidate-rating">${player.rating}</span><div><strong>${escapeText(player.name)}</strong><small>${escapeText(roleName(player.position_code))} · ID ${player.id} · ${escapeText(player.nationality_name)}</small><em>${escapeText(player.clubs.join(", ")||"Sin club")}${player.called_up?" · Ya convocado":player.other_selections.length?" · Ya en "+escapeText(player.other_selections.join(", ")):""}</em></div><button type="button" data-callup-key="${player.player_key}" ${(player.called_up||player.other_selections.length)?"disabled":""}>${player.called_up?"YA ESTÁ":player.eligible?"CONVOCAR":"REVISAR"}</button></article>`).join(""):`<div class="callup-empty">No se encontraron candidatos para “${escapeText(q)}”.</div>`;$$('[data-callup-key]:not([disabled])').forEach(button=>button.addEventListener("click",()=>callUpPlayer(button.dataset.callupKey)))}catch(e){toast(e.message,true)}
}
function nextSelectionShirt(){const used=new Set((state.lineup?.roster||[]).map(player=>player.shirt_number));for(let number=1;number<=99;number++)if(!used.has(number))return number;return 1}
async function callUpPlayer(playerKey,allowMismatch=false,chosenShirt=null){
  if(state.lineupDirty){toast("Guarda o descarta primero los cambios de alineación",true);return}
  const suggested=nextSelectionShirt(),answer=chosenShirt===null?prompt("Dorsal para esta convocatoria (1–99):",String(suggested)):String(chosenShirt);if(answer===null)return;const shirt=Number(answer);if(!Number.isInteger(shirt)||shirt<1||shirt>99){toast("El dorsal debe estar entre 1 y 99",true);return}
  busy(true,"Añadiendo a la convocatoria…");
  try{const data=await post("api/callup",{team_id:state.lineup.team.id,player_key:playerKey,shirt_number:shirt,allow_mismatch:allowMismatch});state.lineup=data.lineup;state.lineupOrder=data.lineup.roster.map(item=>item.assignment_key);state.lineupFormation=data.lineup.formation;setLineupDirty(false);updateSummary(data.summary);renderLineup();await searchCallupCandidates();toast("Jugador convocado; su club se ha conservado")}
  catch(e){if(e.message.startsWith("NACIONALIDAD_INCOMPATIBLE|")){const message=e.message.split("|").slice(1).join("|");if(confirm(message+".\n\n¿Quieres convocarlo de todos modos?")){busy(false);return await callUpPlayer(playerKey,true,shirt)}}if(e.message.startsWith("DORSAL_OCUPADO|")){alert(e.message.split("|").slice(1).join("|")+". Elige otro dorsal para la convocatoria.");busy(false);return await callUpPlayer(playerKey,allowMismatch)}toast(e.message,true)}finally{busy(false)}
}
async function removeCallup(assignmentKey){
  if(state.lineupDirty){toast("Guarda o descarta primero los cambios de alineación",true);return}
  const player=orderedLineupRoster().find(item=>item.assignment_key===assignmentKey);if(!player||!confirm(`¿Desconvocar a ${player.name}? Su inscripción de club no cambiará.`))return;busy(true,"Retirando de la convocatoria…");
  try{const data=await post("api/callup/remove",{team_id:state.lineup.team.id,assignment_key:assignmentKey});state.lineup=data.lineup;state.lineupOrder=data.lineup.roster.map(item=>item.assignment_key);state.lineupFormation=data.lineup.formation;setLineupDirty(false);updateSummary(data.summary);renderLineup();await searchCallupCandidates();toast("Jugador retirado de la selección") }catch(e){toast(e.message,true)}finally{busy(false)}
}

function formatBytes(value){const n=Number(value)||0;if(n<1024)return n+" B";if(n<1024**2)return (n/1024).toFixed(1)+" KB";return (n/1024**2).toFixed(1)+" MB"}
function renderAssetStatus(status){
  state.assetsStatus=status||{};const slots=status?.slots||{},wanted=["p1","p2","p3","g1","g2"];
  $("#kitSlotChips").innerHTML=wanted.map(slot=>`<span class="${slots[slot]?"ready":""}">${slot.toUpperCase()} · ${slots[slot]||0}</span>`).join("");
  $("#kitSourceSummary").textContent=`${status?.source_files||0} archivos · ${formatBytes(status?.source_bytes||0)}${status?.ignored?` · ${status.ignored} sin slot detectable`:""}`;
  $("#kitCpkLoaded").classList.toggle("hidden",!status?.target_cpk);$("#kitCpkName").textContent=status?.target_cpk||"—";
  $("#extractedKitFolderLoaded").classList.toggle("hidden",!status?.target_folder);$("#extractedKitFolderName").textContent=status?.target_folder||"—";
  $("#teamLogoStatus").textContent=(status?.logo_variants||[]).length?`Variantes listas: ${status.logo_variants.join(", ")}`:"Sin logo cargado";
}
async function loadAssetStatus(){try{const data=await request("api/team-assets/status");renderAssetStatus(data.status)}catch(e){toast(e.message,true)}}
async function loadAdminTeam(teamId){
  if(!teamId)return;busy(true,"Cargando slot de equipo…");
  try{const data=await request("api/team/details?"+new URLSearchParams({team_id:teamId}));state.adminTeam=data.team;$("#adminTeamId").textContent=data.team.id;$("#adminTeamTable").textContent=`${data.team.table} · ${data.team.kind==="club"?"CLUB":"SELECCIÓN"}`;$("#adminTeamName").value=data.team.name;$("#adminTeamAbbr").value=data.team.abbreviation||"";$("#adminRosterCount").value=`${data.team.roster_count} jugadores`;$("#adminSlotNote").textContent=data.team.slot_note;$("#teamPackStatus").textContent=`Slot ${data.team.id} preparado. Puedes cambiar nombre, cargar kits y añadir el escudo.`}
  catch(e){state.adminTeam=null;toast(e.message,true)}finally{busy(false)}
}
async function openTeamManager(){
  if(!state.loaded)return;showModal("teamManagerModal");await loadAssetStatus();
  const preferred=state.adminTeam?.id||state.current?.assignments.find(x=>x.team_kind==="club")?.team_id||state.meta.club_teams[0]?.id;
  if(preferred){chooseTeam("admin",preferred);await loadAdminTeam(preferred)}
}
async function saveTeamSlot(silent=false){
  const teamId=Number($("#adminTeam").value);if(!teamId){if(!silent)toast("Selecciona el club que vas a sustituir",true);return false}
  const name=$("#adminTeamName").value.trim(),abbreviation=$("#adminTeamAbbr").value.trim();
  if(!name||abbreviation.length<2){if(!silent)toast("Completa el nombre y una abreviatura de 2–3 caracteres",true);return false}
  if(!silent&&!confirm(`Se conservará el Team ID ${teamId} y se sustituirá la identidad del club. ¿Continuar?`))return false;
  busy(true,"Guardando identidad del equipo…");
  try{const data=await post("api/team/replace-slot",{team_id:teamId,name,abbreviation});state.meta=data;state.adminTeam=data.team;refreshTeamLists(data);updateSummary(data.summary);$("#adminTeamName").value=data.team.name;$("#adminTeamAbbr").value=data.team.abbreviation;$("#adminRosterCount").value=`${data.team.roster_count} jugadores`;chooseTeam("admin",teamId);$("#teamPackStatus").textContent=`${data.team.name} guardado en el slot ${teamId}.`;if(!silent)toast("Equipo guardado; liga, región y Team ID conservados");return true}
  catch(e){toast(e.message,true);return false}finally{busy(false)}
}
async function uploadKitFolder(files){
  const list=[...files];if(!list.length)return;busy(true,`Preparando ${list.length} archivos de kits…`);
  try{await request("api/team-assets/source/reset",{method:"POST",body:""});
    for(let i=0;i<list.length;i+=4){const batch=list.slice(i,i+4);await Promise.all(batch.map(file=>request("api/team-assets/source/file",{method:"POST",headers:{"Content-Type":"application/octet-stream","X-Relative-Path":encodeURIComponent(file.webkitRelativePath||file.name)},body:file})));$("#busyText").textContent=`Analizando kits… ${Math.min(i+4,list.length)} / ${list.length}`}
    await loadAssetStatus();const found=state.assetsStatus?.slots||{};const detected=["p1","p2","p3","g1","g2"].filter(x=>found[x]);toast(`Carpeta cargada: ${detected.join(", ").toUpperCase()||"sin slots reconocidos"}`)
  }catch(e){toast(e.message,true)}finally{busy(false);$("#kitSourceInput").value=""}
}
async function uploadKitCpk(file){
  if(!file)return;if(!file.name.toLowerCase().endsWith(".cpk")){toast("Selecciona un CPK de uniformes",true);return}if(file.size>1024**3){toast("El CPK supera 1 GB",true);return}
  busy(true,"Validando el CPK de uniformes…");try{const data=await request("api/team-assets/target-cpk",{method:"POST",headers:{"Content-Type":"application/octet-stream","X-File-Name":encodeURIComponent(file.name)},body:file});renderAssetStatus(data.status);toast("CPK de kits cargado sin modificar el original")}catch(e){toast(e.message,true)}finally{busy(false);$("#kitTargetInput").value=""}
}
function imageFromFile(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onerror=()=>reject(new Error("No se pudo leer el PNG"));reader.onload=()=>{const img=new Image();img.onload=()=>resolve({img,url:reader.result});img.onerror=()=>reject(new Error("PNG no válido"));img.src=reader.result};reader.readAsDataURL(file)})}
function canvasPng(img,size){return new Promise((resolve,reject)=>{const canvas=document.createElement("canvas");canvas.width=size;canvas.height=size;const ctx=canvas.getContext("2d");ctx.clearRect(0,0,size,size);const available=size*.88,scale=Math.min(available/img.naturalWidth,available/img.naturalHeight),w=Math.max(1,Math.round(img.naturalWidth*scale)),h=Math.max(1,Math.round(img.naturalHeight*scale));ctx.drawImage(img,(size-w)/2,(size-h)/2,w,h);canvas.toBlob(blob=>blob?resolve(blob):reject(new Error("No se pudo generar el logo")),"image/png")})}
async function uploadTeamLogo(file){
  if(!file)return;if(file.type!=="image/png"&&!file.name.toLowerCase().endsWith(".png")){toast("El escudo debe ser PNG",true);return}busy(true,"Generando logos 128, 256 y 512…");
  try{const {img,url}=await imageFromFile(file);$("#teamLogoPreview").innerHTML=`<img alt="Vista previa del escudo">`;$("#teamLogoPreview img").src=url;for(const [variant,size] of [["r",128],["r_l",256],["r_ll",512]]){const blob=await canvasPng(img,size);const data=await request("api/team-assets/logo",{method:"POST",headers:{"Content-Type":"image/png","X-Logo-Variant":variant},body:blob});renderAssetStatus(data.status)}toast("Escudo preparado en 128, 256 y 512 px")}
  catch(e){toast(e.message,true)}finally{busy(false);$("#teamLogoInput").value=""}
}
async function exportTeamPackage(){
  const teamId=Number($("#adminTeam").value);if(!teamId){toast("Selecciona un equipo",true);return}const saved=await saveTeamSlot(true);if(!saved)return;
  if(state.assetsStatus?.target_folder&&!confirm("Se insertarán los kits directamente en la carpeta extraída seleccionada. Los archivos reemplazados tendrán backup. ¿Continuar?"))return;
  busy(true,"Relinkeando kits, reuniendo archivos y verificando el paquete…");try{const response=await request("api/team-assets/export?"+new URLSearchParams({team_id:teamId}));const blob=await response.blob(),disposition=response.headers.get("Content-Disposition")||"",found=disposition.match(/filename="([^"]+)"/),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=found?found[1]:`DFP_TEAM_${teamId}.zip`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);toast("Paquete de equipo, kits y logo exportado")}
  catch(e){toast(e.message,true)}finally{busy(false)}
}

function resetImportPreview(message="Aquí aparecerá el cruce de jugadores e IDs antes de realizar cualquier cambio."){
  state.importPreview=null;$("#applyTeamImportBtn").disabled=true;$("#importPreviewTitle").textContent="Carga una database y selecciona ambos equipos";$("#importMetrics").innerHTML="<span>Sin analizar</span>";$("#importRoster").innerHTML=`<div class="callup-empty">${escapeText(message)}</div>`;updateImportButtons()
}
function updateImportButtons(){
  const ready=state.loaded&&state.importSourceTeams.length&&Number($("#importSourceTeam").value)&&Number($("#importTargetTeam").value);
  $("#previewTeamImportBtn").disabled=!ready;
  if(!state.importPreview)$("#applyTeamImportBtn").disabled=true
}
function renderImportDatabase(data){
  state.importSourceTeams=data.club_teams||[];state.importDbSummary=data.summary||null;
  $("#importDbName").textContent=data.summary?.source_name||"Database externa";
  $("#importDbSummary").textContent=`${(data.summary?.players||0).toLocaleString("es")} jugadores · ${state.importSourceTeams.length.toLocaleString("es")} clubes disponibles`;
  $("#clearImportDbBtn").disabled=false;clearTeam("importSource");resetImportPreview("Busca y selecciona el club que deseas importar.")
}
async function openTeamImporter(){
  if(!state.loaded)return;showModal("teamImportModal");
  const preferred=state.current?.assignments.find(item=>item.team_kind==="club")?.team_id||state.meta.club_teams[0]?.id;
  if(preferred&&!$("#importTargetTeam").value)chooseTeam("importTarget",preferred);
  updateImportButtons();setTimeout(()=>state.importSourceTeams.length?$("#importSourceTeamSearch").focus():$("#loadImportDbBtn").focus(),80)
}
async function loadImportDatabase(file){
  if(!file)return;if(!file.name.toLowerCase().endsWith(".cpk")){toast("Selecciona el Resource_02.cpk del otro parche",true);return}if(file.size>64*1024*1024){toast("La database externa supera el límite de 64 MB",true);return}
  busy(true,"Leyendo equipos y jugadores de la database externa…");
  try{const data=await request("api/team-import/load",{method:"POST",headers:{"Content-Type":"application/octet-stream","X-File-Name":encodeURIComponent(file.name)},body:file});renderImportDatabase(data);toast(`Database externa lista: ${data.club_teams.length} clubes encontrados`)}
  catch(e){toast(e.message,true)}finally{busy(false);$("#importDbInput").value=""}
}
function importActionText(player){
  if(player.action==="reuse")return player.current_clubs?.length?`REUTILIZAR ID ${player.target_id} · mover desde ${player.current_clubs.join(", ")}`:`REUTILIZAR EXISTENTE · ID ${player.target_id}`;
  if(player.action==="create_same_id")return `CREAR · CONSERVAR ID ${player.target_id}`;
  return `CREAR · ID ${player.source_id} → ${player.target_id}`
}
function renderImportPreview(preview){
  state.importPreview=preview;const s=preview.summary;
  $("#importPreviewTitle").textContent=`${preview.source_team.name} → slot ${preview.target_team.id} (${preview.target_team.name})`;
  $("#importMetrics").innerHTML=`<span>${s.players} jugadores</span><span>${s.reuse} existentes</span><span>${s.create_same_id+s.create_new_id} nuevos</span><span>${escapeText(preview.formation_name)}</span>`;
  $("#importRoster").innerHTML=preview.players.map(player=>`<article class="import-player-row ${player.action}"><div><strong>${escapeText(player.name)}</strong><small>ID externo ${player.source_id} · ${escapeText(player.nationality_name)}</small></div><div><b>${escapeText(roleName(player.position_code,true))}</b><small>Dorsal ${player.shirt_number} · orden ${player.squad_order}</small></div><div><strong>${escapeText(importActionText(player))}</strong><small>${player.action==="reuse"?"Se conserva el jugador de Destiny":"Se copiarán sus datos y apariencia de database"}</small></div></article>`).join("");
  const duplicateNote=preview.duplicate_shirts?.length?` Atención: dorsales duplicados ${preview.duplicate_shirts.join(", ")}.`:"";
  $("#teamImportStatus").textContent=`Análisis listo: ${s.reuse} se reutilizan, ${s.create_same_id} conservan ID y ${s.create_new_id} reciben ID libre.${duplicateNote}`;
  $("#applyTeamImportBtn").disabled=false
}
async function previewTeamImport(){
  const sourceTeam=Number($("#importSourceTeam").value),targetTeam=Number($("#importTargetTeam").value);if(!sourceTeam||!targetTeam){toast("Selecciona el club externo y el slot de Destiny",true);return}
  busy(true,"Cruzando nombres, nacionalidades, IDs y plantillas…");
  try{const data=await request("api/team-import/preview?"+new URLSearchParams({source_team_id:sourceTeam,target_team_id:targetTeam}));renderImportPreview(data.preview);toast("Cruce completado; revisa la plantilla antes de importar")}
  catch(e){resetImportPreview(e.message);toast(e.message,true)}finally{busy(false)}
}
async function applyTeamImport(){
  if(!state.importPreview)return;const sourceTeam=Number($("#importSourceTeam").value),targetTeam=Number($("#importTargetTeam").value),preview=state.importPreview;
  if(!confirm(`Se sustituirá la identidad y plantilla de ${preview.target_team.name} por ${preview.source_team.name}.\n\nSe conservarán el Team ID ${targetTeam}, la liga y la región del slot. ¿Continuar?`))return;
  busy(true,"Importando equipo, reasignando IDs y verificando referencias…");
  try{const data=await post("api/team-import/apply",{source_team_id:sourceTeam,target_team_id:targetTeam});state.meta=data;refreshTeamLists(data);updateSummary(data.summary);chooseTeam("importTarget",targetTeam);state.importPreview=null;$("#applyTeamImportBtn").disabled=true;$("#importPreviewTitle").textContent=`${data.team.name} importado correctamente en el Team ID ${targetTeam}`;$("#teamImportStatus").textContent=`Importación completa: ${data.plan.summary.players} jugadores y formación ${data.plan.formation_name}. Puedes usar Deshacer mientras el programa siga abierto.`;await searchPlayers();if(state.current){try{const fresh=await request("api/player?key="+encodeURIComponent(state.current.key));renderPlayer(fresh.player)}catch(_){}}toast(`${data.team.name} importado con ${data.plan.summary.players} jugadores`)}
  catch(e){toast(e.message,true)}finally{busy(false)}
}

async function undo(){if(!confirm("¿Deshacer la última operación guardada?"))return;busy(true,"Deshaciendo…");try{const data=await post("api/undo",{}),pickerIds=Object.fromEntries(["transfer","new","lineup","admin","importTarget"].map(prefix=>[prefix,teamParts(prefix).hidden.value]));const meta=await request("api/meta");state.meta=meta;refreshTeamLists(meta);Object.entries(pickerIds).forEach(([prefix,id])=>{if(id)chooseTeam(prefix,id)});updateSummary(meta.summary);const key=state.current?.key;state.current=null;markDirty(false);await searchPlayers();if(key){try{const fresh=await request("api/player?key="+encodeURIComponent(key));renderPlayer(fresh.player)}catch(_){$(".workspace").classList.remove("show-editor");$("#editor").classList.add("hidden");$("#emptyState").classList.remove("hidden");setActions(false);$("#exportBtn").disabled=false}}toast(data.message)}catch(e){toast(e.message,true)}finally{busy(false)}}
async function exportCpk(){busy(true,"Reconstruyendo y verificando el CPK…");try{const response=await request("api/export");const blob=await response.blob();const disposition=response.headers.get("Content-Disposition")||"";const found=disposition.match(/filename="([^"]+)"/);const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download=found?found[1]:"Resource_02_EDITADO.cpk";document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);toast("CPK exportado y verificado correctamente")}catch(e){toast(e.message,true)}finally{busy(false)}}
async function shutdownApp(){if(!confirm("¿Cerrar y limpiar los datos cargados? Exporta el CPK antes si quieres conservar tus cambios."))return;try{await post("api/shutdown",{})}catch(_){}location.reload()}

function showModal(id){$("#"+id).classList.remove("hidden")}function hideModal(id){$("#"+id).classList.add("hidden")}
function switchTab(name){$$('[data-tab]').forEach(x=>x.classList.toggle("active",x.dataset.tab===name));$$('[data-page]').forEach(x=>x.classList.toggle("active",x.dataset.page===name))}
function debounceSearch(){clearTimeout(debounceSearch.timer);debounceSearch.timer=setTimeout(()=>{state.query=$("#searchInput").value;state.page=1;searchPlayers()},180)}

$("#loadBtn").addEventListener("click",()=>$("#fileInput").click());$("#emptyLoadBtn").addEventListener("click",()=>$("#fileInput").click());$("#fileInput").addEventListener("change",e=>loadFile(e.target.files[0]));
$("#saveBtn").addEventListener("click",saveCurrent);$("#createBtn").addEventListener("click",openCreate);$("#lineupBtn").addEventListener("click",openLineups);$("#teamsBtn").addEventListener("click",openTeamManager);$("#importTeamBtn").addEventListener("click",openTeamImporter);$("#replaceBtn").addEventListener("click",openReplace);$("#undoBtn").addEventListener("click",undo);$("#exportBtn").addEventListener("click",exportCpk);$("#helpBtn").addEventListener("click",()=>showModal("helpModal"));
$("#shutdownBtn").addEventListener("click",shutdownApp);
$("#searchInput").addEventListener("input",debounceSearch);$("#teamFilter").addEventListener("change",e=>{state.team=e.target.value;state.page=1;searchPlayers()});$("#tableFilter").addEventListener("change",e=>{state.table=e.target.value;state.page=1;searchPlayers()});
$("#prevPage").addEventListener("click",()=>{if(state.page>1){state.page--;searchPlayers()}});$("#nextPage").addEventListener("click",()=>{if(state.page<state.pages){state.page++;searchPlayers()}});
$$('[data-tab]').forEach(x=>x.addEventListener("click",()=>switchTab(x.dataset.tab)));$("#playerForm").addEventListener("input",e=>{if(state.current){markDirty();if(e.target.matches('[id^="stat-"]'))updateMeter(e.target)}});
$("#mobileBack").addEventListener("click",()=>$(".workspace").classList.remove("show-editor"));
$("#assignmentSelect").addEventListener("change",e=>{const row=state.current?.assignments.find(x=>x.key===e.target.value);if(row)fillTransfer(row);else{clearTeam("transfer");$("#transferTitle").textContent="Crear inscripción nueva de club"}});$("#transferBtn").addEventListener("click",applyTransfer);$("#releaseBtn").addEventListener("click",releasePlayer);$("#addTransferBtn").addEventListener("click",()=>{$("#assignmentSelect").value="";$("#transferTitle").textContent="Crear inscripción nueva de club";clearTeam("transfer");$("#transferTeamSearch").focus()});
[["transfer","transferTeamPicker"],["new","newTeamPicker"],["lineup","lineupTeamPicker"],["admin","adminTeamPicker"],["importSource","importSourceTeamPicker"],["importTarget","importTargetTeamPicker"]].forEach(([prefix,pickerId])=>{const p=teamParts(prefix);const select=id=>{if(prefix==="lineup"&&state.lineupDirty&&!confirm("Hay cambios de alineación sin guardar. ¿Quieres descartarlos y cambiar de equipo?")){chooseTeam("lineup",state.lineup.team.id);return}chooseTeam(prefix,id);if(prefix==="lineup")loadTeamLineup(id);if(prefix==="admin")loadAdminTeam(id);if(prefix.startsWith("import"))resetImportPreview("Pulsa Analizar importación para cruzar ambas plantillas.")};p.search.addEventListener("focus",()=>showTeamResults(prefix));p.search.addEventListener("input",()=>{p.hidden.value="";showTeamResults(prefix);if(prefix.startsWith("import"))resetImportPreview("Selecciona un resultado de búsqueda para continuar.")});p.search.addEventListener("keydown",e=>{if(e.key==="Enter"){const first=$(".team-option",p.results);if(first){e.preventDefault();select(first.dataset.id)}}});p.results.addEventListener("click",e=>{const option=e.target.closest(".team-option");if(option)select(option.dataset.id)});document.addEventListener("click",e=>{if(!e.target.closest("#"+pickerId))p.results.classList.add("hidden")})});
$$('[data-preset]').forEach(button=>button.addEventListener("click",()=>{if(!state.current)return;const preset=button.dataset.preset;Object.keys(STAT_LABELS).forEach(key=>{const input=$("#stat-"+key);if(preset==="reset")input.value=state.original.stats[key];else if(preset==="elite")input.value=Math.max(Number(input.value),80);else input.value=Math.max(40,Math.min(99,Number(input.value)+(preset==="all+1"?1:-1)));updateMeter(input)});markDirty()}));
$("#lineupFormation").addEventListener("change",e=>{if(!state.lineup)return;state.lineupFormation=e.target.value?(state.meta.formations[e.target.value]||state.lineup.formation):state.lineup.formation;setLineupDirty();renderLineup()});$("#autoSortBtn").addEventListener("click",autoSortLineup);$("#saveLineupBtn").addEventListener("click",saveLineup);$("#closeLineupBtn").addEventListener("click",closeLineups);$("#callupSearch").addEventListener("input",debounceCallupSearch);
$("#confirmCreate").addEventListener("click",createPlayer);$("#replaceSearch").addEventListener("input",searchReplacement);$("#confirmReplace").addEventListener("click",replaceSlot);$$('[data-close]').forEach(b=>b.addEventListener("click",()=>hideModal(b.dataset.close)));$$('.modal-backdrop').forEach(m=>m.addEventListener("click",e=>{if(e.target===m){if(m.id==="lineupModal")closeLineups();else hideModal(m.id)}}));
$("#saveTeamBtn").addEventListener("click",()=>saveTeamSlot(false));$("#exportTeamPackBtn").addEventListener("click",exportTeamPackage);$("#closeTeamManagerBtn").addEventListener("click",()=>hideModal("teamManagerModal"));$("#pickKitFolderBtn").addEventListener("click",()=>$("#kitSourceInput").click());$("#kitSourceInput").addEventListener("change",e=>uploadKitFolder(e.target.files));$("#pickKitCpkBtn").addEventListener("click",()=>$("#kitTargetInput").click());$("#kitTargetInput").addEventListener("change",e=>uploadKitCpk(e.target.files[0]));$("#clearKitCpkBtn").addEventListener("click",async()=>{try{const data=await request("api/team-assets/target-clear",{method:"POST",body:""});renderAssetStatus(data.status);toast("CPK de kits retirado") }catch(e){toast(e.message,true)}});$("#pickTeamLogoBtn").addEventListener("click",()=>$("#teamLogoInput").click());$("#teamLogoInput").addEventListener("change",e=>uploadTeamLogo(e.target.files[0]));
$("#pickExtractedKitFolderBtn").addEventListener("click",async()=>{busy(true,"Abriendo selector de carpeta extraída…");try{const data=await request("api/team-assets/target-folder",{method:"POST",body:""});renderAssetStatus(data.status);toast("Carpeta CPK extraída preparada") }catch(e){if(!e.message.includes("No se seleccionó"))toast(e.message,true)}finally{busy(false)}});$("#clearExtractedKitFolderBtn").addEventListener("click",async()=>{try{const data=await request("api/team-assets/target-folder-clear",{method:"POST",body:""});renderAssetStatus(data.status);toast("Carpeta extraída retirada") }catch(e){toast(e.message,true)}});
$("#loadImportDbBtn").addEventListener("click",()=>$("#importDbInput").click());$("#importDbInput").addEventListener("change",e=>loadImportDatabase(e.target.files[0]));$("#previewTeamImportBtn").addEventListener("click",previewTeamImport);$("#applyTeamImportBtn").addEventListener("click",applyTeamImport);$("#closeTeamImportBtn").addEventListener("click",()=>hideModal("teamImportModal"));$("#clearImportDbBtn").addEventListener("click",async()=>{try{await request("api/team-import/clear",{method:"POST",body:""});state.importSourceTeams=[];state.importDbSummary=null;clearTeam("importSource");$("#importDbName").textContent="Ninguna database externa cargada";$("#importDbSummary").textContent="Carga el Resource_02 del otro parche; el archivo original no se modificará.";$("#clearImportDbBtn").disabled=true;resetImportPreview();toast("Database externa retirada") }catch(e){toast(e.message,true)}});
window.addEventListener("beforeunload",e=>{if(state.loaded&&state.meta?.summary?.dirty){e.preventDefault();e.returnValue=""}});
document.addEventListener("keydown",e=>{if(e.key==="Escape")$$('.modal-backdrop:not(.hidden)').forEach(m=>m.id==="lineupModal"?closeLineups():hideModal(m.id));if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="s"){e.preventDefault();if(!$("#teamManagerModal").classList.contains("hidden"))saveTeamSlot(false);else if(!$("#lineupModal").classList.contains("hidden"))saveLineup();else saveCurrent()}});

async function restoreSession(){
  try{const status=await request("api/status");if(!status.loaded)return;const meta=await request("api/meta");state.loaded=true;state.meta=meta;buildEditors(meta);updateSummary(meta.summary);setActions(false);$("#exportBtn").disabled=false;await searchPlayers();const imported=await request("api/team-import/status");if(imported.loaded)renderImportDatabase(imported);toast("Sesión de database recuperada")}
  catch(e){toast("No se pudo recuperar la sesión: "+e.message,true)}
}
restoreSession();
