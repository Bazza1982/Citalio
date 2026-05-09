"""FastAPI GUI backend for Citalio — serves the local web UI and REST API."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from citalio.db.connection import open_and_migrate
from citalio.db.project_repository import DocumentCitationRepository
from citalio.db.repository import CitationRepository
from citalio.validation.citation_validator import validate_project as _validate_project

# ---------------------------------------------------------------------------
# Inline SPA HTML
# ---------------------------------------------------------------------------

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Citalio</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;font-size:14px;color:#1a1a1a;background:#f5f5f5}
header{background:#2c3e50;color:#fff;padding:12px 24px;display:flex;align-items:center;gap:24px}
header h1{font-size:18px;font-weight:600;letter-spacing:.5px}
nav button{background:transparent;border:none;color:rgba(255,255,255,.7);cursor:pointer;padding:4px 12px;border-radius:4px;font-size:14px}
nav button.active,nav button:hover{background:rgba(255,255,255,.15);color:#fff}
.panel{display:none;padding:20px 24px;height:calc(100vh - 52px);overflow:hidden}
.panel.active{display:flex;gap:20px}
.panel-col{display:flex;flex-direction:column;gap:12px}
.sidebar{width:300px;flex-shrink:0}.main{flex:1;overflow:auto}
input[type=search]{width:100%;padding:8px 12px;border:1px solid #ddd;border-radius:6px;font-size:14px}
.list{background:#fff;border-radius:8px;overflow:auto;max-height:calc(100vh - 160px);border:1px solid #e0e0e0}
.list-item{padding:10px 14px;border-bottom:1px solid #f0f0f0;cursor:pointer}
.list-item:last-child{border-bottom:none}
.list-item:hover,.list-item.selected{background:#eef2ff}
.list-item .title{font-weight:500}
.list-item .meta{font-size:12px;color:#666;margin-top:2px}
.detail{background:#fff;border-radius:8px;padding:20px;border:1px solid #e0e0e0;overflow:auto;max-height:calc(100vh - 60px)}
.detail h2{font-size:16px;font-weight:600;margin-bottom:10px;line-height:1.4}
.field{margin-bottom:6px;font-size:13px}
.field strong{display:inline-block;min-width:100px;color:#555}
section{margin-top:16px}
section h3{font-size:13px;font-weight:600;color:#444;border-bottom:1px solid #eee;padding-bottom:4px;margin-bottom:8px}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:500}
.badge-candidate{background:#fef3c7;color:#92400e}
.badge-approved{background:#d1fae5;color:#065f46}
.badge-rejected{background:#fee2e2;color:#991b1b}
.badge-needs_repair{background:#fde8d8;color:#c2410c}
.badge-inserted,.badge-rendered,.badge-validated{background:#dbeafe;color:#1e40af}
.badge-repaired{background:#ede9fe;color:#5b21b6}
.btn{padding:5px 14px;border:none;border-radius:5px;cursor:pointer;font-size:13px;font-weight:500}
.btn-approve{background:#d1fae5;color:#065f46}.btn-approve:hover{background:#a7f3d0}
.btn-reject{background:#fee2e2;color:#991b1b}.btn-reject:hover{background:#fecaca}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:10px;margin-bottom:16px}
.stat-card{background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:10px 14px;text-align:center}
.stat-card .num{font-size:22px;font-weight:700;color:#2c3e50}
.stat-card .label{font-size:11px;color:#666;margin-top:2px}
.issue{background:#fff8f0;border-left:3px solid #f59e0b;border-radius:4px;padding:8px 12px;margin-bottom:8px;font-size:13px}
.issue .type{font-size:11px;font-weight:600;color:#b45309;margin-bottom:2px}
.empty{text-align:center;padding:40px 20px;color:#999;font-size:13px}
.filter-bar{display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
.filter-bar label{font-size:13px;color:#555}
select{padding:6px 10px;border:1px solid #ddd;border-radius:5px;font-size:13px}
.dr{background:#fff;border:1px solid #e0e0e0;border-radius:6px;padding:12px 16px;margin-bottom:10px}
.dr-header{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.dr-body{font-size:12px;color:#555}
.dr-actions{margin-top:8px;display:flex;gap:8px}
</style>
</head>
<body>
<header>
  <h1>&#128218; Citalio</h1>
  <nav>
    <button class="active" onclick="showPanel('library',this)">Library</button>
    <button onclick="showPanel('projects',this)">Projects</button>
    <button onclick="showPanel('review',this)">Review</button>
  </nav>
</header>

<div id="panel-library" class="panel active">
  <div class="sidebar panel-col">
    <input type="search" id="lib-search" placeholder="Search references..." oninput="debounceSearch()">
    <div id="lib-list" class="list"></div>
  </div>
  <div class="main">
    <div id="lib-detail" class="detail"><div class="empty">Select a reference to view details.</div></div>
  </div>
</div>

<div id="panel-projects" class="panel">
  <div class="sidebar panel-col">
    <div id="proj-list" class="list"></div>
  </div>
  <div class="main">
    <div id="proj-detail" class="detail"><div class="empty">Select a project to view its dashboard.</div></div>
  </div>
</div>

<div id="panel-review" class="panel" style="flex-direction:column;overflow:auto">
  <div class="filter-bar">
    <label>Project:</label>
    <select id="rev-project" onchange="loadReview()"><option value="">&#8212; select project &#8212;</option></select>
    <label>State:</label>
    <select id="rev-state" onchange="loadReview()">
      <option value="">All</option>
      <option value="candidate">Candidate</option>
      <option value="approved">Approved</option>
      <option value="rejected">Rejected</option>
      <option value="needs_repair">Needs Repair</option>
    </select>
  </div>
  <div id="rev-content" style="overflow:auto;flex:1"></div>
</div>

<script>
var _projects=[];

function showPanel(name,btn){
  document.querySelectorAll('.panel').forEach(function(p){p.classList.remove('active')});
  document.querySelectorAll('nav button').forEach(function(b){b.classList.remove('active')});
  document.getElementById('panel-'+name).classList.add('active');
  btn.classList.add('active');
  if(name==='projects')loadProjects();
  if(name==='review')loadReviewProjects();
}

// Library
var _searchTimer;
function debounceSearch(){clearTimeout(_searchTimer);_searchTimer=setTimeout(searchRefs,300)}

function searchRefs(){
  var q=document.getElementById('lib-search').value.trim();
  var url=q?'/api/refs?q='+encodeURIComponent(q)+'&limit=50':'/api/refs?limit=50';
  fetch(url).then(function(r){return r.json()}).then(function(refs){
    var list=document.getElementById('lib-list');
    if(!refs.length){list.innerHTML='<div class="empty">No references found.</div>';return}
    list.innerHTML=refs.map(function(r){
      var auth=r.authors.map(function(a){return a.literal||(a.family+(a.given?', '+a.given[0]+'.':''))}).join('; ');
      return '<div class="list-item" onclick="showRef(\''+r.id+'\',this)"><div class="title">'+esc(r.title)+'</div><div class="meta">'+(r.year||'')+(auth?' &middot; '+esc(auth.substring(0,50))+(auth.length>50?'&hellip;':''):'' )+'</div></div>';
    }).join('');
  });
}

function showRef(id,el){
  document.querySelectorAll('#lib-list .list-item').forEach(function(e){e.classList.remove('selected')});
  el.classList.add('selected');
  fetch('/api/refs/'+id).then(function(r){return r.json()}).then(function(r){
    var auth=r.authors.map(function(a){return a.literal||[a.family,a.given].filter(Boolean).join(', ')}).join('; ');
    var ed=r.editors.map(function(a){return a.literal||[a.family,a.given].filter(Boolean).join(', ')}).join('; ');
    var html='<h2>'+esc(r.title)+'</h2>';
    html+='<div class="field"><strong>Type</strong>'+r.item_type+'</div>';
    html+='<div class="field"><strong>Year</strong>'+(r.year||'&mdash;')+'</div>';
    html+='<div class="field"><strong>Authors</strong>'+esc(auth||'&mdash;')+'</div>';
    if(ed)html+='<div class="field"><strong>Editors</strong>'+esc(ed)+'</div>';
    if(r.publication_title)html+='<div class="field"><strong>Publication</strong>'+esc(r.publication_title)+'</div>';
    if(r.volume)html+='<div class="field"><strong>Volume</strong>'+r.volume+(r.issue?' ('+r.issue+')':'')+(r.pages?', pp.&nbsp;'+r.pages:'')+'</div>';
    if(r.doi)html+='<div class="field"><strong>DOI</strong><a href="https://doi.org/'+r.doi+'" target="_blank">'+r.doi+'</a></div>';
    if(r.url)html+='<div class="field"><strong>URL</strong><a href="'+r.url+'" target="_blank">'+esc(r.url.substring(0,60))+'&hellip;</a></div>';
    if(r.citekey)html+='<div class="field"><strong>Citekey</strong><code>'+r.citekey+'</code></div>';
    html+='<div class="field"><strong>Confidence</strong>'+(r.confidence_score*100).toFixed(0)+'%</div>';
    if(r.abstract)html+='<section><h3>Abstract</h3><p style="font-size:13px;color:#444;line-height:1.5">'+esc(r.abstract.substring(0,600))+(r.abstract.length>600?'&hellip;':'')+'</p></section>';
    if(r.notes&&r.notes.length)html+='<section><h3>Notes ('+r.notes.length+')</h3>'+r.notes.map(function(n){return'<div style="margin-bottom:6px;font-size:13px"><span class="badge badge-candidate">'+n.kind+'</span> '+esc(n.text.substring(0,200))+'</div>'}).join('')+'</section>';
    if(r.attachments&&r.attachments.length)html+='<section><h3>Attachments</h3>'+r.attachments.map(function(a){return'<div style="font-size:13px"><code>'+a.kind+'</code> &mdash; '+esc(a.path)+'</div>'}).join('')+'</section>';
    document.getElementById('lib-detail').innerHTML=html;
  });
}

// Projects
function loadProjects(){
  fetch('/api/projects').then(function(r){return r.json()}).then(function(projects){
    _projects=projects;
    var list=document.getElementById('proj-list');
    if(!projects.length){list.innerHTML='<div class="empty">No projects yet.</div>';return}
    list.innerHTML=projects.map(function(p){
      return '<div class="list-item" onclick="showProject(\''+p.id+'\',this)"><div class="title">'+esc(p.name)+'</div><div class="meta">'+p.created_at.substring(0,10)+'</div></div>';
    }).join('');
  });
}

function showProject(id,el){
  document.querySelectorAll('#proj-list .list-item').forEach(function(e){e.classList.remove('selected')});
  el.classList.add('selected');
  fetch('/api/projects/'+id).then(function(r){return r.json()}).then(function(p){
    var s=p.stats||{};
    var states=['candidate','approved','rejected','needs_repair','repaired','inserted','rendered','validated'];
    var cards=states.map(function(st){return'<div class="stat-card"><div class="num">'+(s[st]||0)+'</div><div class="label">'+st+'</div></div>'}).join('');
    var anchors=Object.entries(s.anchors||{}).map(function(e){return'<div class="stat-card"><div class="num">'+e[1]+'</div><div class="label">anchor:'+e[0]+'</div></div>'}).join('');
    var html='<h2>'+esc(p.name)+'</h2>';
    if(p.docx_path)html+='<div class="field"><strong>DOCX</strong><code style="font-size:12px">'+esc(p.docx_path)+'</code></div>';
    if(p.markdown_path)html+='<div class="field"><strong>Markdown</strong><code style="font-size:12px">'+esc(p.markdown_path)+'</code></div>';
    html+='<section><h3>Decision Counts</h3><div class="stat-grid">'+cards+anchors+'</div></section>';
    html+='<section><h3>Validation Report</h3><div id="val-'+id+'">Loading&hellip;</div></section>';
    document.getElementById('proj-detail').innerHTML=html;
    fetch('/api/projects/'+id+'/validation').then(function(r){return r.json()}).then(function(v){
      var vEl=document.getElementById('val-'+id);
      if(!vEl)return;
      if(!v.issues.length){vEl.innerHTML='<div style="font-size:13px;color:#059669">&#10003; No validation issues detected.</div>';return}
      vEl.innerHTML=v.issues.map(function(i){return'<div class="issue"><div class="type">'+i.issue_type+'</div>'+esc(i.description)+'</div>'}).join('');
    });
  });
}

// Review
function loadReviewProjects(){
  if(_projects.length){_populateReviewSelect();return}
  fetch('/api/projects').then(function(r){return r.json()}).then(function(ps){_projects=ps;_populateReviewSelect()});
}
function _populateReviewSelect(){
  var sel=document.getElementById('rev-project');
  var cur=sel.value;
  sel.innerHTML='<option value="">&#8212; select project &#8212;</option>'+_projects.map(function(p){return'<option value="'+p.id+'"'+(p.id===cur?' selected':'')+'>'+esc(p.name)+'</option>'}).join('');
  if(cur)loadReview();
}

function loadReview(){
  var pid=document.getElementById('rev-project').value;
  var state=document.getElementById('rev-state').value;
  var content=document.getElementById('rev-content');
  if(!pid){content.innerHTML='';return}
  var url='/api/projects/'+pid+'/decisions'+(state?'?state='+state:'');
  fetch(url).then(function(r){return r.json()}).then(function(decisions){
    if(!decisions.length){content.innerHTML='<div class="empty">No decisions match the filter.</div>';return}
    content.innerHTML=decisions.map(function(d){
      var marker=d.citation_marker?'[@'+esc(d.citation_marker)+']':'(no marker)';
      var html='<div class="dr" id="dr-'+d.id+'">';
      html+='<div class="dr-header"><span class="badge badge-'+d.decision_state+'">'+d.decision_state+'</span><strong>'+marker+'</strong><span style="font-size:12px;color:#666">'+(d.confidence*100).toFixed(0)+'% conf</span></div>';
      html+='<div class="dr-body">';
      if(d.cited_for)html+='<div><strong>Cited for:</strong> '+esc(d.cited_for.substring(0,200))+'</div>';
      if(d.selected_reason)html+='<div><strong>Reason:</strong> '+esc(d.selected_reason.substring(0,200))+'</div>';
      if(d.reference_id)html+='<div style="margin-top:4px;color:#888">Ref: <code>'+d.reference_id.substring(0,12)+'&hellip;</code></div>';
      html+='</div>';
      if(d.decision_state==='candidate'||d.decision_state==='needs_repair'){
        html+='<div class="dr-actions"><button class="btn btn-approve" onclick="approveD(\''+pid+'\',\''+d.id+'\')">Approve</button><button class="btn btn-reject" onclick="rejectD(\''+pid+'\',\''+d.id+'\')">Reject</button></div>';
      }
      html+='</div>';
      return html;
    }).join('');
  });
}

function approveD(pid,did){
  fetch('/api/projects/'+pid+'/decisions/'+did+'/approve',{method:'POST'}).then(function(){
    var row=document.getElementById('dr-'+did);
    if(!row)return;
    row.querySelector('.badge').className='badge badge-approved';
    row.querySelector('.badge').textContent='approved';
    var acts=row.querySelector('.dr-actions');if(acts)acts.remove();
  });
}
function rejectD(pid,did){
  fetch('/api/projects/'+pid+'/decisions/'+did+'/reject',{method:'POST'}).then(function(){
    var row=document.getElementById('dr-'+did);
    if(!row)return;
    row.querySelector('.badge').className='badge badge-rejected';
    row.querySelector('.badge').textContent='rejected';
    var acts=row.querySelector('.dr-actions');if(acts)acts.remove();
  });
}

function esc(s){if(!s)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

searchRefs();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(library: Optional[Path] = None) -> FastAPI:
    """Create and return the Citalio FastAPI application.

    *library* is the path to the Citalio library directory (default ~/.citalio).
    """
    app = FastAPI(title="Citalio", docs_url="/api/docs", redoc_url=None)

    def _conn():
        return open_and_migrate(library)

    # ---- HTML shell -------------------------------------------------------

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index() -> str:
        return _HTML

    # ---- References -------------------------------------------------------

    @app.get("/api/refs")
    async def search_refs(
        q: str = Query(""),
        limit: int = Query(50, ge=1, le=200),
    ):
        conn = _conn()
        try:
            repo = CitationRepository(conn)
            if q:
                refs = repo.search_references(q, limit=limit)
            else:
                rows = conn.execute(
                    'SELECT * FROM "references" ORDER BY year DESC, title ASC LIMIT ?',
                    (limit,),
                ).fetchall()
                refs = [repo._row_to_reference(r) for r in rows]
            return [
                {
                    "id": r.id,
                    "citekey": r.citekey,
                    "title": r.title,
                    "year": r.year,
                    "item_type": r.item_type,
                    "doi": r.doi,
                    "authors": [
                        {"family": a.family, "given": a.given, "literal": a.literal}
                        for a in r.authors
                    ],
                }
                for r in refs
            ]
        finally:
            conn.close()

    @app.get("/api/refs/{ref_id}")
    async def get_ref(ref_id: str):
        conn = _conn()
        try:
            repo = CitationRepository(conn)
            ref = repo.get_reference(ref_id)
            if ref is None:
                raise HTTPException(status_code=404, detail="Reference not found")
            notes = repo.list_notes(ref_id)
            attachments = repo.list_attachments(ref_id)
            return {
                "id": ref.id,
                "citekey": ref.citekey,
                "title": ref.title,
                "year": ref.year,
                "item_type": ref.item_type,
                "doi": ref.doi,
                "isbn": ref.isbn,
                "url": ref.url,
                "abstract": ref.abstract,
                "publication_title": ref.publication_title,
                "volume": ref.volume,
                "issue": ref.issue,
                "pages": ref.pages,
                "publisher": ref.publisher,
                "confidence_score": ref.confidence_score,
                "authors": [
                    {"family": a.family, "given": a.given, "literal": a.literal}
                    for a in ref.authors
                ],
                "editors": [
                    {"family": e.family, "given": e.given, "literal": e.literal}
                    for e in ref.editors
                ],
                "notes": [
                    {"kind": n.kind, "text": n.text, "source": n.source}
                    for n in notes
                ],
                "attachments": [
                    {"kind": a.kind, "path": a.path} for a in attachments
                ],
            }
        finally:
            conn.close()

    # ---- Projects ---------------------------------------------------------

    @app.get("/api/projects")
    async def list_projects():
        conn = _conn()
        try:
            repo = DocumentCitationRepository(conn)
            projects = repo.list_projects()
            return [
                {"id": p.id, "name": p.name, "created_at": p.created_at}
                for p in projects
            ]
        finally:
            conn.close()

    @app.get("/api/projects/{project_id}")
    async def get_project(project_id: str):
        conn = _conn()
        try:
            repo = DocumentCitationRepository(conn)
            project = repo.get_project(project_id)
            if project is None:
                raise HTTPException(status_code=404, detail="Project not found")
            stats = repo.project_stats(project_id)
            return {
                "id": project.id,
                "name": project.name,
                "docx_path": project.docx_path,
                "markdown_path": project.markdown_path,
                "sidecar_path": project.sidecar_path,
                "created_at": project.created_at,
                "stats": stats,
            }
        finally:
            conn.close()

    # ---- Decisions --------------------------------------------------------

    @app.get("/api/projects/{project_id}/decisions")
    async def list_decisions(
        project_id: str,
        state: Optional[str] = Query(None),
    ):
        conn = _conn()
        try:
            repo = DocumentCitationRepository(conn)
            states = [state] if state else None
            decisions = repo.list_candidates(project_id, states=states)
            return [
                {
                    "id": d.id,
                    "decision_state": d.decision_state,
                    "citation_marker": d.citation_marker,
                    "cited_for": d.cited_for,
                    "selected_reason": d.selected_reason,
                    "confidence": d.confidence,
                    "reference_id": d.reference_id,
                    "anchor_id": d.anchor_id,
                }
                for d in decisions
            ]
        finally:
            conn.close()

    @app.post("/api/projects/{project_id}/decisions/{decision_id}/approve")
    async def approve_decision(project_id: str, decision_id: str):
        conn = _conn()
        try:
            repo = DocumentCitationRepository(conn)
            ok = repo.approve_decision(decision_id)
            if not ok:
                raise HTTPException(status_code=404, detail="Decision not found")
            return {"status": "approved"}
        finally:
            conn.close()

    @app.post("/api/projects/{project_id}/decisions/{decision_id}/reject")
    async def reject_decision(
        project_id: str,
        decision_id: str,
        reason: str = Query(""),
    ):
        conn = _conn()
        try:
            repo = DocumentCitationRepository(conn)
            ok = repo.reject_decision(decision_id, reason=reason or None)
            if not ok:
                raise HTTPException(status_code=404, detail="Decision not found")
            return {"status": "rejected"}
        finally:
            conn.close()

    # ---- Validation -------------------------------------------------------

    @app.get("/api/projects/{project_id}/validation")
    async def run_validation(project_id: str):
        conn = _conn()
        try:
            report = _validate_project(conn, project_id)
            return {
                "project_id": report.project_id,
                "issue_count": len(report.issues),
                "issues": [
                    {
                        "issue_type": i.issue_type,
                        "description": i.description,
                        "decision_id": i.decision_id,
                        "reference_id": i.reference_id,
                        "marker": i.marker,
                    }
                    for i in report.issues
                ],
            }
        finally:
            conn.close()

    return app
