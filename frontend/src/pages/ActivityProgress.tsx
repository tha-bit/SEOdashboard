import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, postJson } from '../api'
import { SummaryActionCard } from '../components/SummaryActionCard'
import type { ActivityCategory, MonthlyComparison, Project, SEOActivity } from '../types'

const statuses=['in_progress','ignored','completed','resolved','changed']
const sections=['pages','site_architecture','on_page','keyword','performance']
const labels:Record<string,string>={pages:'Pages',site_architecture:'Site Architecture',on_page:'On-Page SEO',keyword:'Keyword',performance:'Performance',in_progress:'In Progress',ignored:'Ignored',completed:'Completed',resolved:'Resolved',changed:'Changed'}
const label=(value:string)=>labels[value]||value.replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase())
const currentMonth=()=>new Date().toISOString().slice(0,7)
const priorMonth=(month:string)=>{const [year,value]=month.split('-').map(Number);return new Date(Date.UTC(year,value-2,1)).toISOString().slice(0,7)}

export function ActivityProgress({project}:{project:Project}){
  const [params]=useSearchParams()
  const [items,setItems]=useState<SEOActivity[]>([]),[total,setTotal]=useState(0),[categories,setCategories]=useState<ActivityCategory[]>([]),[months,setMonths]=useState<string[]>([])
  const [summary,setSummary]=useState<MonthlyComparison|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState(''),[showAdd,setShowAdd]=useState(false),[showCategories,setShowCategories]=useState(false)
  const [search,setSearch]=useState(''),[section,setSection]=useState('all'),[status,setStatus]=useState('all'),[category,setCategory]=useState('all'),[month,setMonth]=useState(currentMonth()),[compare,setCompare]=useState(priorMonth(currentMonth()))
  const issueKey=params.get('issue_key')||''
  async function refresh(){setLoading(true);setError('');try{const [activity,categoryRows,monthRows]=await Promise.all([loadAllActivity(project.id,issueKey),api<ActivityCategory[]>(`/api/projects/${project.id}/activity/categories`),api<string[]>(`/api/projects/${project.id}/activity/months`)]);setItems(activity.items);setTotal(activity.total);setCategories(categoryRows);setMonths(monthRows);const available=monthRows.includes(month)?month:(monthRows[0]||month);if(available!==month)setMonth(available);const comparison=monthRows.includes(compare)&&compare!==available?compare:(monthRows.find(item=>item!==available)||priorMonth(available));if(comparison!==compare)setCompare(comparison);setSummary(await api<MonthlyComparison>(`/api/projects/${project.id}/activity/monthly?month=${available}&compare=${comparison}`))}catch(e){setError((e as Error).message)}finally{setLoading(false)}}
  useEffect(()=>{refresh()},[project.id,issueKey])
  useEffect(()=>{api<MonthlyComparison>(`/api/projects/${project.id}/activity/monthly?month=${month}&compare=${compare}`).then(setSummary).catch(e=>setError(e.message))},[project.id,month,compare])
  const exportQuery=new URLSearchParams();if(search)exportQuery.set('search',search);if(section!=='all')exportQuery.set('section',section);if(status!=='all')exportQuery.set('status',status);if(category!=='all')exportQuery.set('category_id',category);if(issueKey)exportQuery.set('issue_key',issueKey)
  const activeStatus=(value:string)=>setStatus(current=>current===value?'all':value)
  const current=summary?.current
  const groups=useMemo(()=>groupActivities(items),[items])
  const visibleGroups=useMemo(()=>groups.filter(group=>group.entries.some(item=>activityMatches(item,{search,section,status,category}))),[groups,search,section,status,category])
  return <div className="page activity-page">
    <div className="page-heading"><div><p className="eyebrow">ACCOUNTABLE SEO WORK</p><h1>SEO Tracker</h1><p>See what changed, what improved, and what still needs attention without losing earlier evidence.</p></div><div className="actions"><a className="secondary" href={`/api/projects/${project.id}/activity/export.csv?${exportQuery}`}>Export log</a><button className="secondary" onClick={()=>setShowCategories(true)}>Categories</button><button className="primary" onClick={()=>setShowAdd(true)}>Add activity</button></div></div>
    {error&&<div className="error-box">{error}</div>}
    <div className="activity-month-controls"><label>Progress month<select value={month} onChange={e=>setMonth(e.target.value)}>{monthOptions(months,month)}</select></label><span>compared with</span><label>Comparison month<select value={compare} onChange={e=>setCompare(e.target.value)}>{monthOptions(months,compare)}</select></label><a href={`/api/projects/${project.id}/activity/monthly.csv?month=${month}&compare=${compare}`}>Export comparison</a></div>
    <div className="metric-grid activity-metrics">
      <SummaryActionCard label="Resolved issues" value={current?.issues_resolved??0} detail={delta(summary,'issues_resolved',true)} action="Show resolved" active={status==='resolved'} onClick={()=>activeStatus('resolved')}/>
      <SummaryActionCard label="New issues" value={current?.new_issues??0} detail={delta(summary,'new_issues',false)} action="Show in progress" active={status==='in_progress'} attention={Boolean(current?.new_issues)} onClick={()=>activeStatus('in_progress')}/>
      <SummaryActionCard label="Outstanding issues" value={current?.outstanding_issues??'—'} detail={current?.issue_snapshot_date?`Latest crawl: ${fmtDate(current.issue_snapshot_date)}`:'No crawl snapshot this month'} action="Open Issues" onClick={()=>location.assign('/issues')}/>
      <SummaryActionCard label="Completed recommendations" value={current?.recommendations_completed??0} detail={`${current?.recommendations_created??0} created this month`} action="Show completed" active={status==='completed'} onClick={()=>activeStatus('completed')}/>
    </div>
    <section className="panel progress-panel"><div className="panel-title"><div><h2>Monthly performance evidence</h2><p>Values appear only when a dated GSC, GA4, ranking, or crawl snapshot is available.</p></div></div><div className="progress-evidence">{metric('Organic clicks',current?.organic_clicks,summary?.comparison?.organic_clicks)}{metric('Impressions',current?.organic_impressions,summary?.comparison?.organic_impressions)}{metric('Organic sessions',current?.organic_sessions,summary?.comparison?.organic_sessions)}{metric('Average position',current?.average_position,summary?.comparison?.average_position,true)}{metric('Ranking keywords',current?.ranking_keywords,summary?.comparison?.ranking_keywords)}{metric('Top 10 keywords',current?.top_10_keywords,summary?.comparison?.top_10_keywords)}</div></section>
    <section className="panel activity-log"><div className="panel-title"><div><h2>Activity timeline</h2><p>{issueKey?'Filtered to the selected issue · ':''}{total} record{total===1?'':'s'} grouped into {visibleGroups.length} expandable {visibleGroups.length===1?'entry':'entries'} · append-only history</p></div>{(search||section!=='all'||status!=='all'||category!=='all'||issueKey)&&<button className="text-button" onClick={()=>{setSearch('');setSection('all');setStatus('all');setCategory('all');if(issueKey)location.assign('/activity')}}>Clear filters</button>}</div>
      <div className="activity-filters"><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search activity, URL, or issue"/><select value={section} onChange={e=>setSection(e.target.value)}><option value="all">All sections</option>{sections.map(item=><option key={item} value={item}>{label(item)}</option>)}</select><select value={status} onChange={e=>setStatus(e.target.value)}><option value="all">All statuses</option>{statuses.map(item=><option key={item} value={item}>{label(item)}</option>)}</select><select value={category} onChange={e=>setCategory(e.target.value)}><option value="all">All categories</option>{categories.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></div>
      {loading?<div className="loading-panel"><div className="spinner"/>Loading activity…</div>:visibleGroups.length?<div className="timeline">{visibleGroups.map(group=><ActivityGroupRow key={group.key} group={group} project={project} onChanged={refresh}/>)}</div>:<div className="empty small-empty"><h3>No activity matches these filters</h3><p>Add a manual record or import a later crawl to start measuring change.</p></div>}
    </section>
    {showAdd&&<ActivityModal project={project} categories={categories} onClose={()=>setShowAdd(false)} onSaved={()=>{setShowAdd(false);refresh()}}/>}
    {showCategories&&<CategoryModal project={project} categories={categories} onClose={()=>setShowCategories(false)} onSaved={async()=>{setCategories(await api<ActivityCategory[]>(`/api/projects/${project.id}/activity/categories`))}}/>}
  </div>
}

type ActivityGroup={key:string;url?:string;entries:SEOActivity[];latest:SEOActivity}

function ActivityGroupRow({group,project,onChanged}:{group:ActivityGroup;project:Project;onChanged:()=>void|Promise<void>}){
  const [open,setOpen]=useState(false),[saving,setSaving]=useState(false),[pendingStatus,setPendingStatus]=useState<string|null>(null),[updateError,setUpdateError]=useState('')
  const item=group.latest
  async function update(){
    if(!pendingStatus||pendingStatus===item.status)return setPendingStatus(null)
    setSaving(true);setUpdateError('')
    try{await postJson(`/api/projects/${project.id}/activity/${item.id}/status`,{status:pendingStatus});setPendingStatus(null);await onChanged()}
    catch(error){setUpdateError((error as Error).message)}finally{setSaving(false)}
  }
  const title=activityGroupTitle(group)
  const context=group.url?`${compactUrlLabel(group.url)} · ${group.entries.length} ${group.entries.length===1?'record':'records'} · Latest ${fmtDate(item.occurred_at)}`:`${label(item.section)} · ${group.entries.length} ${group.entries.length===1?'record':'records'} · Latest ${fmtDate(item.occurred_at)}`
  return <article className={`timeline-item status-${item.status}`}>
    <button className="timeline-main" onClick={()=>setOpen(value=>!value)} aria-expanded={open}>
      <span className="timeline-dot"/><span><b title={title}>{title}</b><small title={group.url}>{context}</small></span><em>{label(item.status)}</em><i>{open?'−':'+'}</i>
    </button>
    {open&&<div className="timeline-detail">
      {group.url&&<a href={group.url} target="_blank" rel="noreferrer">{group.url}</a>}
      <div className="activity-history" aria-label={`Complete change history for ${group.url||item.title}`}>
        {group.entries.map(entry=><ActivityHistoryEntry key={entry.id} item={entry}/>) }
      </div>
      {updateError&&<div className="error-box">{updateError}</div>}
      <div className="timeline-actions"><span>Update status</span>{statuses.map(nextStatus=><button key={nextStatus} disabled={saving||nextStatus===item.status} onClick={()=>setPendingStatus(nextStatus)}>{label(nextStatus)}</button>)}</div>
    </div>}
    {pendingStatus&&<div className="overlay"><div className="modal status-confirm-modal" role="dialog" aria-modal="true" aria-labelledby={`status-confirm-${item.id}`}>
      <button className="close" onClick={()=>setPendingStatus(null)} aria-label="Close">×</button>
      <p className="eyebrow">CONFIRM STATUS UPDATE</p><h2 id={`status-confirm-${item.id}`}>Update activity status?</h2>
      <p>This creates a new append-only status record for <strong title={group.url}>{group.url?compactUrlLabel(group.url):cleanActivityTitle(item)}</strong>.</p>
      <div className="status-confirm-values"><div><span>Current status</span><strong>{label(item.status)}</strong></div><div aria-hidden="true">→</div><div><span>New status</span><strong>{label(pendingStatus)}</strong></div></div>
      {updateError&&<div className="error-box">{updateError}</div>}
      <div className="modal-actions"><button className="secondary" disabled={saving} onClick={()=>setPendingStatus(null)}>Cancel</button><button className="primary" disabled={saving||pendingStatus===item.status} onClick={update}>{saving?'Updating…':'Confirm'}</button></div>
    </div></div>}
  </article>
}

function ActivityHistoryEntry({item}:{item:SEOActivity}){const hasData=Object.keys(item.before_data).length>0||Object.keys(item.after_data).length>0,title=cleanActivityTitle(item);return <article className="activity-history-entry"><header><div><b title={title}>{title}</b><small>{fmtDateTime(item.occurred_at)} · {label(item.section)}{item.category?` · ${item.category}`:''}</small></div><em>{label(item.status)}</em></header>{item.notes&&<p>{item.notes}</p>}{item.issue_type&&<dl><div><dt>Issue type</dt><dd>{label(item.issue_type)}</dd></div><div><dt>Action</dt><dd>{label(item.action_type)}</dd></div></dl>}{hasData&&<div className="before-after"><div><strong>Previous value</strong><pre>{JSON.stringify(item.before_data,null,2)}</pre></div><div><strong>New value</strong><pre>{JSON.stringify(item.after_data,null,2)}</pre></div></div>}</article>}

function groupActivities(items:SEOActivity[]):ActivityGroup[]{
  const grouped=new Map<string,SEOActivity[]>()
  for(const item of items){const key=item.url?`url:${normaliseActivityUrl(item.url)}`:item.page_id?`page:${item.page_id}`:`activity:${item.id}`;grouped.set(key,[...(grouped.get(key)||[]),item])}
  return Array.from(grouped.entries()).map(([key,entries])=>{entries.sort((left,right)=>new Date(right.occurred_at).getTime()-new Date(left.occurred_at).getTime()||new Date(right.created_at).getTime()-new Date(left.created_at).getTime());return {key,url:entries.find(item=>item.url)?.url,entries,latest:entries[0]}}).sort((left,right)=>new Date(right.latest.occurred_at).getTime()-new Date(left.latest.occurred_at).getTime())
}

async function loadAllActivity(projectId:string,issueKey:string){const limit=5000,items:SEOActivity[]=[];let offset=0,total=0;do{const query=new URLSearchParams({limit:String(limit),offset:String(offset)});if(issueKey)query.set('issue_key',issueKey);const response=await api<{items:SEOActivity[];total:number}>(`/api/projects/${projectId}/activity?${query}`);items.push(...response.items);total=response.total;offset+=response.items.length;if(!response.items.length)break}while(offset<total);return {items,total}}
function activityMatches(item:SEOActivity,filters:{search:string;section:string;status:string;category:string}){const needle=filters.search.trim().toLocaleLowerCase();if(filters.section!=='all'&&item.section!==filters.section)return false;if(filters.status!=='all'&&item.status!==filters.status)return false;if(filters.category!=='all'&&item.category_id!==filters.category)return false;if(!needle)return true;return [item.title,item.notes,item.url,item.issue_type,item.action_type,item.category,label(item.section),label(item.status)].some(value=>String(value||'').toLocaleLowerCase().includes(needle))}

function normaliseActivityUrl(value:string){try{const parsed=new URL(value);const path=parsed.pathname==='/'?'/':parsed.pathname.replace(/\/+$/,'');return `${parsed.origin.toLowerCase()}${path}${parsed.search}`}catch{return value.trim().replace(/\/+$/,'')}}
function shortUrl(value:string){try{const parsed=new URL(value);return `${parsed.pathname||'/'}${parsed.search}`}catch{return value}}
function compactUrlLabel(value:string,maxLength=76){let display=value;try{const parsed=new URL(value);display=`${parsed.hostname}${parsed.pathname||'/'}${parsed.search}`}catch{/* Keep the imported value. */}if(display.length<=maxLength)return display;const tailLength=28,headLength=maxLength-tailLength-1;return `${display.slice(0,headLength)}…${display.slice(-tailLength)}`}
function cleanActivityTitle(item:SEOActivity){let title=item.title.trim();if(item.url){for(const candidate of [item.url,shortUrl(item.url)]){const suffix=` · ${candidate}`;if(title.endsWith(suffix))title=title.slice(0,-suffix.length).trim()}if(title===item.url||title===shortUrl(item.url))title=label(item.issue_type||item.action_type)}return title||label(item.issue_type||item.action_type)}
function activityGroupTitle(group:ActivityGroup){const titles=Array.from(new Set(group.entries.map(cleanActivityTitle)));if(titles.length===1)return titles[0];return `${titles[0]} + ${titles.length-1} more ${titles.length===2?'change':'changes'}`}

function ActivityModal({project,categories,onClose,onSaved}:{project:Project;categories:ActivityCategory[];onClose:()=>void;onSaved:()=>void}){const [title,setTitle]=useState(''),[notes,setNotes]=useState(''),[url,setUrl]=useState(''),[section,setSection]=useState('pages'),[status,setStatus]=useState('completed'),[category,setCategory]=useState(''),[issueType,setIssueType]=useState(''),[date,setDate]=useState(new Date().toISOString().slice(0,10)),[error,setError]=useState('');async function submit(e:React.FormEvent){e.preventDefault();try{await postJson(`/api/projects/${project.id}/activity`,{title,notes:notes||null,url:url||null,section,status,category_id:category||null,issue_type:issueType||null,occurred_at:`${date}T12:00:00Z`});onSaved()}catch(e){setError((e as Error).message)}}return <div className="overlay"><form className="modal activity-modal" onSubmit={submit}><button type="button" className="close" onClick={onClose}>×</button><p className="eyebrow">MANUAL RECORD</p><h2>Add SEO activity</h2><label>Activity title<input required autoFocus value={title} onChange={e=>setTitle(e.target.value)} placeholder="Updated category meta descriptions"/></label><div className="two-col"><label>Date<input type="date" value={date} onChange={e=>setDate(e.target.value)}/></label><label>Section<select value={section} onChange={e=>setSection(e.target.value)}>{sections.map(item=><option key={item} value={item}>{label(item)}</option>)}</select></label><label>Status<select value={status} onChange={e=>setStatus(e.target.value)}>{statuses.map(item=><option key={item} value={item}>{label(item)}</option>)}</select></label><label>Category<select value={category} onChange={e=>setCategory(e.target.value)}><option value="">No custom category</option>{categories.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></label></div><label>Related URL<input type="url" value={url} onChange={e=>setUrl(e.target.value)} placeholder="https://example.com/page"/></label><label>Issue type<input value={issueType} onChange={e=>setIssueType(e.target.value)} placeholder="Optional issue type"/></label><label>Notes<textarea value={notes} onChange={e=>setNotes(e.target.value)} placeholder="What was changed, why, and any verification evidence"/></label>{error&&<div className="error-box">{error}</div>}<div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Cancel</button><button className="primary">Save activity</button></div></form></div>}

function CategoryModal({project,categories,onClose,onSaved}:{project:Project;categories:ActivityCategory[];onClose:()=>void;onSaved:()=>void}){const [name,setName]=useState(''),[error,setError]=useState('');async function submit(e:React.FormEvent){e.preventDefault();try{await postJson(`/api/projects/${project.id}/activity/categories`,{name,color:'blue'});setName('');onSaved()}catch(e){setError((e as Error).message)}}return <div className="overlay"><div className="modal"><button className="close" onClick={onClose}>×</button><p className="eyebrow">ORGANISATION</p><h2>Activity categories</h2><form onSubmit={submit}><label>New category<input required value={name} onChange={e=>setName(e.target.value)} placeholder="Q4 technical fixes"/></label><button className="primary small" style={{marginTop:10}}>Add category</button></form>{error&&<div className="error-box">{error}</div>}<div className="category-list">{categories.map(item=><div key={item.id}><b>{item.name}</b><span>{item.activity_count} records</span></div>)}{!categories.length&&<p className="hint">No custom categories yet.</p>}</div><div className="modal-actions"><button className="secondary" onClick={onClose}>Done</button></div></div></div>}

function monthOptions(months:string[],selected:string){return Array.from(new Set([selected,...months])).map(item=><option key={item} value={item}>{new Date(`${item}-02T00:00:00Z`).toLocaleDateString(undefined,{month:'long',year:'numeric',timeZone:'UTC'})}</option>)}
function fmtDate(value:string){return new Date(value).toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric'})}
function fmtDateTime(value:string){return new Date(value).toLocaleString(undefined,{day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'})}
function metric(name:string,value:number|null|undefined,compare:number|null|undefined,inverse=false){const available=value!==null&&value!==undefined;const changed=available&&compare!==null&&compare!==undefined?value-compare:null;return <div><span>{name}</span><strong>{available?value.toLocaleString(undefined,{maximumFractionDigits:1}):'Data not available'}</strong><small>{changed===null?'No comparable data':`${changed>0?'+':''}${changed.toLocaleString(undefined,{maximumFractionDigits:1})} vs comparison${inverse?' · lower is usually better':''}`}</small></div>}
function delta(summary:MonthlyComparison|null,key:string,positive:boolean){const value=summary?.deltas?.[key];if(value===null||value===undefined)return 'No comparable month';const good=positive?value>=0:value<=0;return `${value>0?'+':''}${value} vs comparison${good?' · favourable':''}`}
