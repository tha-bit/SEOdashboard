import { useEffect, useMemo, useRef, useState } from 'react'
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import type { ColumnSizingState, VisibilityState } from '@tanstack/react-table'
import { api, deleteJson, patchJson, postJson, putJson } from '../api'
import { CheckboxFilter } from '../components/CheckboxFilter'
import { Icon } from '../components/Icons'
import { IntentPills } from '../components/IntentPills'
import { SummaryActionCard } from '../components/SummaryActionCard'
import type { CannibalizationCase, CannibalizationFinding, CannibalizationUrlMetric, KeywordOpportunity, Page, Project, StrategyGroup, StrategyMember, StrategySummary } from '../types'

type View = 'groups' | 'mapping' | 'cannibalization'
type HistoryItem = { id:string; entity_type:string; action:string; reviewer?:string; before:Record<string,unknown>; after:Record<string,unknown>; reason?:string; created_at:string }

const groupHelper = createColumnHelper<StrategyGroup>()
const fmt = (value:number|null|undefined) => value === null || value === undefined ? '—' : value.toLocaleString(undefined, { maximumFractionDigits:1 })
const title = (value:string) => value.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase())
const normalizedUrl = (value?:string) => (value || '').replace(/\/$/, '').toLowerCase()

function saved(projectId:string, view:View) {
  try {
    return JSON.parse(localStorage.getItem(`page-mapper:strategy:${projectId}:${view}`) || '{}') as { visibility?:VisibilityState; sizing?:ColumnSizingState }
  } catch {
    return {}
  }
}

export function KeywordStrategy({ project, view }:{ project:Project; view:View }) {
  const initial = useMemo(() => saved(project.id, view), [project.id, view])
  const toolbar = useRef<HTMLDivElement>(null)
  const [groups, setGroups] = useState<StrategyGroup[]>([])
  const [cases, setCases] = useState<CannibalizationCase[]>([])
  const [summary, setSummary] = useState<StrategySummary>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [search, setSearch] = useState('')
  const [statuses, setStatuses] = useState<string[]>([])
  const [intents, setIntents] = useState<string[]>([])
  const [readiness, setReadiness] = useState<string[]>([])
  const [cardFilter, setCardFilter] = useState('all')
  const [selected, setSelected] = useState<string[]>([])
  const [openGroup, setOpenGroup] = useState<string>()
  const [openCase, setOpenCase] = useState<string>()
  const [visibility, setVisibility] = useState<VisibilityState>(initial.visibility || {})
  const [sizing, setSizing] = useState<ColumnSizingState>(initial.sizing || {})

  useEffect(() => {
    setLoading(true)
    setError('')
    Promise.all([
      api<StrategyGroup[]>(`/api/projects/${project.id}/strategy/groups`),
      api<StrategySummary>(`/api/projects/${project.id}/strategy/summary`),
      view === 'cannibalization' ? api<CannibalizationCase[]>(`/api/projects/${project.id}/strategy/cannibalization/cases`) : Promise.resolve([]),
    ]).then(([groupRows, totals, caseRows]) => {
      setGroups(groupRows)
      setSummary(totals)
      setCases(caseRows)
    }).catch(err => setError(err.message)).finally(() => setLoading(false))
  }, [project.id, view, refresh])

  useEffect(() => { setCardFilter('all');setSearch('');setStatuses([]);setIntents([]);setReadiness([]) }, [view])

  useEffect(() => {
    try {
      localStorage.setItem(`page-mapper:strategy:${project.id}:${view}`, JSON.stringify({ visibility, sizing }))
    } catch {
      // Layout remains usable without persistence.
    }
  }, [project.id, view, visibility, sizing])

  const visibleGroups = useMemo(() => groups.filter(group => {
    const haystack = `${group.name} ${group.members.map(item => item.keyword).join(' ')} ${group.target?.url || ''}`.toLowerCase()
    const cardMatch = cardFilter==='all'
      || cardFilter==='approved_groups'&&group.status==='approved'
      || cardFilter==='suggested_groups'&&group.status==='suggested'
      || cardFilter==='missing_target'&&!group.target
      || cardFilter==='mapped_keywords'&&group.members.length>0
      || cardFilter==='needs_keywords'&&Boolean(group.target)&&group.members.length===0
      || cardFilter==='planned_new'&&group.target?.planned_action==='create_new'
    return (view !== 'groups' || group.members.some(member => member.best_semrush_position !== null))
      && cardMatch
      && (!search || haystack.includes(search.toLowerCase()))
      && (!statuses.length || statuses.includes(group.status))
      && (!intents.length || intents.includes(group.intent || 'Unclassified'))
      && (!readiness.length || readiness.includes(group.readiness))
  }), [groups, search, statuses, intents, readiness, view, cardFilter])
  const filteredCases=useMemo(()=>cases.filter(item=>cardFilter==='all'||cardFilter==='review_cases'&&['new','needs_investigation','reopened'].includes(item.status)||cardFilter==='resolved_cases'&&item.status==='resolved'||cardFilter==='exact_overlaps'&&item.case_type==='exact_query_multi_url'),[cases,cardFilter])

  async function automate() {
    setBusy(true)
    setError('')
    try {
      await postJson(`/api/projects/${project.id}/strategy/suggestions/generate`, {})
      setRefresh(value => value + 1)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function scan() {
    setBusy(true)
    setError('')
    try {
      await postJson(`/api/projects/${project.id}/strategy/cannibalization/scan`, {})
      setRefresh(value => value + 1)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function approveSelected() {
    setBusy(true)
    try {
      await Promise.all(selected.map(id => postJson(`/api/projects/${project.id}/strategy/groups/${id}/approve`, {})))
      setSelected([])
      setRefresh(value => value + 1)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const groupColumns = useMemo(() => [
    groupHelper.display({ id:'select', header:'', size:44, minSize:44, maxSize:44, cell:info => <input aria-label={`Select ${info.row.original.name}`} type="checkbox" checked={selected.includes(info.row.original.id)} onChange={event => setSelected(items => event.target.checked ? [...items, info.row.original.id] : items.filter(id => id !== info.row.original.id))}/> }),
    groupHelper.accessor('name', { header:'Keyword group', size:260, minSize:170, maxSize:520, cell:info => <button className="strategy-link" onClick={() => setOpenGroup(info.row.original.id)}><strong>{info.getValue()}</strong><small>{info.row.original.members.filter(member => member.best_semrush_position !== null).slice(0, 3).map(item => item.keyword).join(' · ') || 'No imported ranking keywords'}</small></button> }),
    groupHelper.accessor('intent', { header:'Intent', size:115, cell:info => <IntentPills value={info.getValue()} empty="?"/> }),
    groupHelper.display({ id:'ranking_keywords', header:'Current ranking keywords', size:145, cell:info => <strong>{info.row.original.members.filter(member => member.best_semrush_position !== null).length}</strong> }),
    groupHelper.accessor('unique_volume', { header:'Unique volume', size:115, cell:info => fmt(info.getValue()) }),
    groupHelper.accessor('status', { header:'Group status', size:120, cell:info => <span className={`strategy-status status-${info.getValue()}`}>{title(info.getValue())}</span> }),
    groupHelper.accessor('observed_urls', { header:'Current ranking URLs', size:300, minSize:180, maxSize:600, cell:info => <UrlStack urls={info.getValue()}/> }),
  ], [selected])

  const groupTable = useReactTable({ data:visibleGroups, columns:groupColumns, state:{ columnVisibility:visibility, columnSizing:sizing }, onColumnVisibilityChange:setVisibility, onColumnSizingChange:setSizing, columnResizeMode:'onChange', getCoreRowModel:getCoreRowModel() })
  const statusOptions = useMemo(() => [...new Set(groups.map(item => item.status))].sort().map(value => ({ value, label:title(value) })), [groups])
  const intentOptions = useMemo(() => [...new Set(groups.map(item => item.intent || 'Unclassified'))].sort().map(value => ({ value, label:value })), [groups])
  const readinessOptions = useMemo(() => [...new Set(groups.map(item => item.readiness))].sort().map(value => ({ value, label:value })), [groups])
  const heading = view === 'groups' ? 'Keyword Groups' : view === 'mapping' ? 'Page Mapping' : 'Cannibalization Audit'
  const intro = view === 'groups' ? 'Review imported ranking keywords and deterministic group suggestions.' : view === 'mapping' ? 'Choose a target URL, focus keyword, supporting terms and planned action for every page.' : 'Investigate evidence-based overlap signals; no case is automatically labelled harmful.'
  const table = groupTable
  const rankingGroups=groups.filter(group=>group.members.some(member=>member.best_semrush_position!==null))
  const targetUrlCount=new Set(groups.map(group=>group.target?.url&&normalizedUrl(group.target.url)).filter(Boolean)).size
  function applyCardFilter(value:string){const active=cardFilter===value;setCardFilter(active?'all':value);setSearch('');setStatuses([]);setIntents([]);setReadiness([])}

  function keepOne(event:React.SyntheticEvent<HTMLDetailsElement>) {
    if (!event.currentTarget.open) return
    toolbar.current?.querySelectorAll<HTMLDetailsElement>('details[open]').forEach(item => {
      if (item !== event.currentTarget) item.removeAttribute('open')
    })
  }

  return <div className="page keyword-workspace strategy-workspace">
    <div className="page-heading compact">
      <div><p className="eyebrow">KEYWORD STRATEGY</p><h1>{heading}</h1><p>{intro}</p></div>
      <div className="actions">
        {view === 'cannibalization'
          ? <button className="primary" disabled={busy} onClick={scan}><Icon name="search"/>{busy ? 'Scanning…' : 'Scan evidence'}</button>
          : <button className="primary" disabled={busy} onClick={automate}><Icon name="grid"/>{busy ? 'Generating…' : 'Generate assignments'}</button>}
        <a className="secondary button" href={`/api/projects/${project.id}/strategy/exports/${view === 'cannibalization' ? 'cannibalization' : view === 'mapping' ? 'page-map' : 'keyword-map'}`}><Icon name="download"/>Export</a>
      </div>
    </div>
    <section className="metric-grid strategy-metrics">
      {view==='groups'&&<><SummaryActionCard label="Ranking groups" value={rankingGroups.length.toLocaleString()} detail="Groups containing imported ranking keywords" action="Show all groups" onClick={()=>applyCardFilter('all')}/><SummaryActionCard label="Approved groups" value={rankingGroups.filter(group=>group.status==='approved').length.toLocaleString()} detail="Reviewed keyword groupings" action={cardFilter==='approved_groups'?'Clear filter':'Show approved'} active={cardFilter==='approved_groups'} onClick={()=>applyCardFilter('approved_groups')}/><SummaryActionCard label="Suggested groups" value={rankingGroups.filter(group=>group.status==='suggested').length.toLocaleString()} detail="Automated suggestions awaiting review" action={cardFilter==='suggested_groups'?'Clear filter':'Show suggestions'} active={cardFilter==='suggested_groups'} onClick={()=>applyCardFilter('suggested_groups')}/><SummaryActionCard label="Without target" value={rankingGroups.filter(group=>!group.target).length.toLocaleString()} detail="Ranking groups needing a target page" action={cardFilter==='missing_target'?'Clear filter':'Show target gaps'} active={cardFilter==='missing_target'} onClick={()=>applyCardFilter('missing_target')}/></>}
      {view==='mapping'&&<><SummaryActionCard label="Target URLs" value={targetUrlCount.toLocaleString()} detail="Existing and proposed mapped pages" action="Show all targets" onClick={()=>applyCardFilter('all')}/><SummaryActionCard label="Mapped keywords" value={summary?.mapped_keywords.toLocaleString()??'—'} detail="Approved keyword assignments" action={cardFilter==='mapped_keywords'?'Clear filter':'Show mapped'} active={cardFilter==='mapped_keywords'} onClick={()=>applyCardFilter('mapped_keywords')}/><SummaryActionCard label="Needs keywords" value={groups.filter(group=>group.target&&group.members.length===0).length.toLocaleString()} detail="Target pages without an assigned keyword" action={cardFilter==='needs_keywords'?'Clear filter':'Show gaps'} active={cardFilter==='needs_keywords'} onClick={()=>applyCardFilter('needs_keywords')}/><SummaryActionCard label="Planned new pages" value={groups.filter(group=>group.target?.planned_action==='create_new').length.toLocaleString()} detail="Targets marked Create new" action={cardFilter==='planned_new'?'Clear filter':'Show planned pages'} active={cardFilter==='planned_new'} onClick={()=>applyCardFilter('planned_new')}/></>}
      {view==='cannibalization'&&<><SummaryActionCard label="Overlapping keywords" value={cannibalizationRows(cases).length.toLocaleString()} detail="Keywords with more than one associated URL" action="Show all overlaps" onClick={()=>applyCardFilter('all')}/><SummaryActionCard label="Needs review" value={summary?.cases_needing_review.toLocaleString()??'—'} detail="Open evidence cases requiring a decision" action={cardFilter==='review_cases'?'Clear filter':'Show review queue'} active={cardFilter==='review_cases'} attention={Boolean(summary?.cases_needing_review)} onClick={()=>applyCardFilter('review_cases')}/><SummaryActionCard label="Exact multi-URL signals" value={summary?.exact_overlaps.toLocaleString()??'—'} detail="Exact queries observed across URLs" action={cardFilter==='exact_overlaps'?'Clear filter':'Show exact overlaps'} active={cardFilter==='exact_overlaps'} onClick={()=>applyCardFilter('exact_overlaps')}/><SummaryActionCard label="Resolved cases" value={summary?.resolved_cases.toLocaleString()??'—'} detail="Reviewed decisions retained in history" action={cardFilter==='resolved_cases'?'Clear filter':'Show resolved'} active={cardFilter==='resolved_cases'} onClick={()=>applyCardFilter('resolved_cases')}/></>}
    </section>
    {view === 'mapping'
      ? <PageMappingWorkspace project={project} groups={visibleGroups} allGroups={groups} loading={loading} error={error} search={search} setSearch={setSearch} onSaved={() => setRefresh(value => value + 1)}/>
      : view === 'cannibalization'
        ? <CannibalizationWorkspace cases={filteredCases} loading={loading} error={error} search={search} setSearch={setSearch} onOpenCase={setOpenCase}/>
      : <section className="table-panel strategy-table-panel">
          <div ref={toolbar} className="workspace-filter-bar strategy-filter-bar">
            <div className="filter-search-row">
              <div className="search"><Icon name="search"/><input value={search} onChange={event => setSearch(event.target.value)} placeholder={`Search ${heading.toLowerCase()}…`}/></div>
              <strong>{visibleGroups.length} results</strong>
              <details className="column-picker" onToggle={keepOne}><summary><Icon name="settings"/>Columns</summary><div><header><strong>Visible columns</strong><button onClick={() => table.toggleAllColumnsVisible(true)}>Show all</button></header>{table.getAllLeafColumns().filter(column => column.getCanHide()).map(column => <label key={column.id}><input type="checkbox" checked={column.getIsVisible()} onChange={column.getToggleVisibilityHandler()}/><span>{typeof column.columnDef.header === 'string' ? column.columnDef.header : column.id}</span></label>)}<button className="reset-columns" onClick={() => { table.resetColumnSizing(); table.resetColumnVisibility() }}>Reset layout</button></div></details>
            </div>
            <div className="filter-controls-row strategy-filter-controls">
              <CheckboxFilter label="Status" options={statusOptions} values={statuses} onChange={setStatuses} onToggle={keepOne}/>
              <CheckboxFilter label="Intent" options={intentOptions} values={intents} onChange={setIntents} onToggle={keepOne}/>
              <CheckboxFilter label="Readiness" options={readinessOptions} values={readiness} onChange={setReadiness} onToggle={keepOne}/>
            </div>
          </div>
          {selected.length > 0 && <div className="bulk-bar"><strong>{selected.length} groups selected</strong><button className="primary" disabled={busy} onClick={approveSelected}>Approve groups and memberships</button><button className="secondary" onClick={() => setSelected([])}>Clear</button></div>}
          {error && <div className="error-box">{error}</div>}
          <StrategyTable table={table} loading={loading} empty="Generate suggestions after importing Semrush rankings."/>
        </section>}
    {openGroup && <GroupDrawer project={project} group={groups.find(item => item.id === openGroup)!} onClose={() => setOpenGroup(undefined)} onSaved={() => setRefresh(value => value + 1)}/>}
    {openCase && <CaseDrawer project={project} item={cases.find(caseItem => caseItem.id === openCase)!} onClose={() => setOpenCase(undefined)} onSaved={() => setRefresh(value => value + 1)}/>}
  </div>
}

function StrategyTable({ table, loading, empty }:{ table:any; loading:boolean; empty:string }) {
  return <div className="table-scroll resizable-table"><table style={{ width:table.getTotalSize(), minWidth:'100%' }}><thead>{table.getHeaderGroups().map((group:any) => <tr key={group.id}>{group.headers.map((header:any) => <th key={header.id} style={{ width:header.getSize() }}>{flexRender(header.column.columnDef.header, header.getContext())}{header.column.getCanResize() && <button className={`column-resizer ${header.column.getIsResizing() ? 'active' : ''}`} onMouseDown={header.getResizeHandler()} onTouchStart={header.getResizeHandler()} onDoubleClick={() => header.column.resetSize()} aria-label="Resize column"/>}</th>)}</tr>)}</thead><tbody>{loading ? <tr><td colSpan={table.getVisibleLeafColumns().length}><div className="loading-panel"><div className="spinner"/>Loading strategy evidence…</div></td></tr> : table.getRowModel().rows.length ? table.getRowModel().rows.map((row:any) => <tr key={row.id}>{row.getVisibleCells().map((cell:any) => <td key={cell.id} style={{ width:cell.column.getSize() }}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}</tr>) : <tr><td colSpan={table.getVisibleLeafColumns().length}><div className="empty small-empty"><h3>No results yet</h3><p>{empty}</p></div></td></tr>}</tbody></table></div>
}

type CannibalizationRow = { key:string;keyword:string;keywordId?:string;classification:CannibalizationFinding['classification'];searchVolume:number|null;urls:CannibalizationUrlMetric[];cases:CannibalizationCase[];totalClicks:number|null;totalImpressions:number|null;topPosition:number|null }
type CannibalizationSort = 'keyword'|'severity'|'urls'|'volume'|'clicks'|'impressions'|'position'

function metricSum(urls:CannibalizationUrlMetric[], key:'gsc_clicks'|'gsc_impressions') {
  const values = urls.map(item => item[key]).filter((value):value is number => value !== null && value !== undefined)
  return values.length ? values.reduce((total, value) => total + value, 0) : null
}

function bestPosition(item:CannibalizationUrlMetric) {
  return item.position ?? item.gsc_position ?? null
}

function mergeUrl(left:CannibalizationUrlMetric, right:CannibalizationUrlMetric):CannibalizationUrlMetric {
  const positionValues = [left.position, right.position].filter((value):value is number => value !== null && value !== undefined)
  const gscPositionValues = [left.gsc_position, right.gsc_position].filter((value):value is number => value !== null && value !== undefined)
  const maximum = (key:'gsc_clicks'|'gsc_impressions'|'ga4_sessions'|'ga4_engaged_sessions'|'ga4_conversions') => {
    const values = [left[key], right[key]].filter((value):value is number => value !== null && value !== undefined)
    return values.length ? Math.max(...values) : null
  }
  return {...left,...right,approved_target:left.approved_target||right.approved_target,position:positionValues.length?Math.min(...positionValues):null,gsc_position:gscPositionValues.length?Math.min(...gscPositionValues):null,gsc_clicks:maximum('gsc_clicks'),gsc_impressions:maximum('gsc_impressions'),ga4_sessions:maximum('ga4_sessions'),ga4_engaged_sessions:maximum('ga4_engaged_sessions'),ga4_conversions:maximum('ga4_conversions')}
}

function cannibalizationRows(cases:CannibalizationCase[]):CannibalizationRow[] {
  const grouped = new Map<string,{keyword:string;keywordId?:string;classification:CannibalizationFinding['classification'];searchVolume:number|null;urls:Map<string,CannibalizationUrlMetric>;cases:CannibalizationCase[]}>()
  cases.forEach(caseItem => caseItem.findings.forEach(finding => {
    const key = finding.keyword_id || finding.keyword.trim().toLowerCase()
    const current = grouped.get(key) || {keyword:finding.keyword,keywordId:finding.keyword_id,classification:finding.classification,searchVolume:finding.search_volume??null,urls:new Map<string,CannibalizationUrlMetric>(),cases:[]}
    if (finding.classification === 'potential_cannibalization') current.classification = finding.classification
    if (finding.search_volume !== null && finding.search_volume !== undefined) current.searchVolume = Math.max(current.searchVolume??0,finding.search_volume)
    if (!current.cases.some(item => item.id === caseItem.id)) current.cases.push(caseItem)
    finding.urls.filter(item => item.url).forEach(item => {
      const urlKey = normalizedUrl(item.url)
      current.urls.set(urlKey,current.urls.has(urlKey)?mergeUrl(current.urls.get(urlKey)!,item):item)
    })
    grouped.set(key,current)
  }))
  return [...grouped.entries()].map(([key,item])=>{
    const urls=[...item.urls.values()]
    const positions=urls.map(bestPosition).filter((value):value is number=>value!==null)
    return {key,keyword:item.keyword,keywordId:item.keywordId,classification:item.classification,searchVolume:item.searchVolume,urls,cases:item.cases,totalClicks:metricSum(urls,'gsc_clicks'),totalImpressions:metricSum(urls,'gsc_impressions'),topPosition:positions.length?Math.min(...positions):null}
  })
}

const statusWeight:Record<string,number> = {confirmed:7,likely_cannibalization:6,reopened:5,needs_investigation:4,new:3,harmless_overlap:2,resolved:1}
function strongestStatus(row:CannibalizationRow) { return [...row.cases].sort((left,right)=>(statusWeight[right.status]||0)-(statusWeight[left.status]||0))[0]?.status||'new' }
function rowSeverity(row:CannibalizationRow) { return (row.classification==='potential_cannibalization'?10:0)+(statusWeight[strongestStatus(row)]||0) }
function strongestUrl(urls:CannibalizationUrlMetric[]) {
  return [...urls].sort((left,right)=>(right.gsc_clicks??-1)-(left.gsc_clicks??-1)||(right.gsc_impressions??-1)-(left.gsc_impressions??-1)||(bestPosition(left)??999)-(bestPosition(right)??999)||(right.ga4_sessions??-1)-(left.ga4_sessions??-1))[0]
}

function CannibalizationWorkspace({ cases, loading, error, search, setSearch, onOpenCase }:{ cases:CannibalizationCase[];loading:boolean;error:string;search:string;setSearch:(value:string)=>void;onOpenCase:(id:string)=>void }) {
  const toolbar = useRef<HTMLDivElement>(null)
  const [statuses,setStatuses] = useState<string[]>([])
  const [classifications,setClassifications] = useState<string[]>([])
  const [expanded,setExpanded] = useState<string[]>([])
  const [sort,setSort] = useState<CannibalizationSort>('severity')
  const [descending,setDescending] = useState(true)
  const rows = useMemo(()=>cannibalizationRows(cases),[cases])
  const statusOptions = useMemo(()=>[...new Set(cases.map(item=>item.status))].sort().map(value=>({value,label:title(value)})),[cases])
  const visible = useMemo(()=>rows.filter(row=>(!search||`${row.keyword} ${row.urls.map(item=>item.url).join(' ')}`.toLowerCase().includes(search.toLowerCase()))&&(!statuses.length||row.cases.some(item=>statuses.includes(item.status)))&&(!classifications.length||classifications.includes(row.classification))).sort((left,right)=>{
    const leftValue = sort==='keyword'?left.keyword:sort==='severity'?rowSeverity(left):sort==='urls'?left.urls.length:sort==='volume'?left.searchVolume??-1:sort==='clicks'?left.totalClicks??-1:sort==='impressions'?left.totalImpressions??-1:left.topPosition??999
    const rightValue = sort==='keyword'?right.keyword:sort==='severity'?rowSeverity(right):sort==='urls'?right.urls.length:sort==='volume'?right.searchVolume??-1:sort==='clicks'?right.totalClicks??-1:sort==='impressions'?right.totalImpressions??-1:right.topPosition??999
    const comparison=typeof leftValue==='string'?leftValue.localeCompare(String(rightValue)):Number(leftValue)-Number(rightValue)
    return descending?-comparison:comparison
  }),[rows,search,statuses,classifications,sort,descending])
  function keepOne(event:React.SyntheticEvent<HTMLDetailsElement>) { if(event.currentTarget.open)toolbar.current?.querySelectorAll<HTMLDetailsElement>('details[open]').forEach(item=>{if(item!==event.currentTarget)item.removeAttribute('open')}) }
  function changeSort(next:CannibalizationSort) { if(sort===next)setDescending(value=>!value);else{setSort(next);setDescending(next!=='keyword'&&next!=='position')} }
  function toggle(key:string) { setExpanded(items=>items.includes(key)?items.filter(item=>item!==key):[...items,key]) }
  return <section className="table-panel cannibalization-workspace">
    <div ref={toolbar} className="workspace-filter-bar cannibalization-filter-bar"><div className="filter-search-row"><div className="search"><Icon name="search"/><input value={search} onChange={event=>setSearch(event.target.value)} placeholder="Search keyword or competing URL…"/></div><strong>{visible.length} keyword{visible.length===1?'':'s'}</strong></div><div className="filter-controls-row cannibalization-filter-controls"><CheckboxFilter label="Issue type" options={[{value:'potential_cannibalization',label:'Potential cannibalisation'},{value:'keyword_overlap',label:'Keyword overlap'}]} values={classifications} onChange={setClassifications} onToggle={keepOne}/>{statusOptions.length>0&&<CheckboxFilter label="Review status" options={statusOptions} values={statuses} onChange={setStatuses} onToggle={keepOne}/>}</div></div>
    <div className="cannibalization-guidance"><strong>One row per keyword</strong><p>Potential cannibalisation means multiple pages rank or conflict with an approved target. Keyword overlap means multiple approved mappings exist, but competition has not been demonstrated.</p></div>
    {error&&<div className="error-box">{error}</div>}
    {loading?<div className="loading-panel"><div className="spinner"/>Loading cannibalisation evidence…</div>:visible.length?<div className="table-scroll cannibalization-table-scroll"><table className="cannibalization-table"><thead><tr><SortHeading label="Keyword" field="keyword" active={sort} descending={descending} onSort={changeSort}/><SortHeading label="Issue type" field="severity" active={sort} descending={descending} onSort={changeSort}/><SortHeading label="Competing URLs" field="urls" active={sort} descending={descending} onSort={changeSort}/><SortHeading label="Search volume" field="volume" active={sort} descending={descending} onSort={changeSort}/><SortHeading label="Total clicks" field="clicks" active={sort} descending={descending} onSort={changeSort}/><SortHeading label="Total impressions" field="impressions" active={sort} descending={descending} onSort={changeSort}/><SortHeading label="Top position" field="position" active={sort} descending={descending} onSort={changeSort}/><th>Review status</th></tr></thead><tbody>{visible.map(row=><CannibalizationKeywordRows key={row.key} row={row} expanded={expanded.includes(row.key)} onToggle={()=>toggle(row.key)} onOpenCase={onOpenCase}/>)}</tbody></table></div>:<div className="empty small-empty"><h3>No matching keyword overlaps</h3><p>{cases.length?'Adjust the search or filters.':'Run the evidence scan after importing rankings or approving keyword mappings.'}</p></div>}
  </section>
}

function SortHeading({ label, field, active, descending, onSort }:{label:string;field:CannibalizationSort;active:CannibalizationSort;descending:boolean;onSort:(field:CannibalizationSort)=>void}) {
  return <th aria-sort={active===field?(descending?'descending':'ascending'):'none'}><button className="cannibalization-sort" onClick={()=>onSort(field)}>{label}<span aria-hidden="true">{active===field?(descending?'↓':'↑'):'↕'}</span></button></th>
}

function CannibalizationKeywordRows({ row, expanded, onToggle, onOpenCase }:{row:CannibalizationRow;expanded:boolean;onToggle:()=>void;onOpenCase:(id:string)=>void}) {
  const status=strongestStatus(row)
  const strongest=strongestUrl(row.urls)
  const recommendation=row.classification==='keyword_overlap'?'Review the search intent assigned to each mapped page. Keep both only when they serve clearly different intents; otherwise choose one primary target.':`Use ${strongest?.url||'the strongest-performing page'} as the evidence-led starting point. Confirm intent, content purpose, canonical signals and internal links before consolidating or redirecting anything.`
  return <><tr className={`cannibalization-keyword-row ${expanded?'is-expanded':''}`}><td><button className="cannibalization-keyword-toggle" onClick={onToggle} aria-expanded={expanded}><span>{expanded?'−':'+'}</span><strong>{row.keyword}</strong></button></td><td><span className={`cannibalization-kind ${row.classification}`}>{row.classification==='keyword_overlap'?'Keyword overlap':'Potential cannibalisation'}</span></td><td><strong>{row.urls.length}</strong></td><td>{fmt(row.searchVolume)}</td><td>{fmt(row.totalClicks)}</td><td>{fmt(row.totalImpressions)}</td><td>{fmt(row.topPosition)}</td><td><span className={`strategy-status status-${status}`}>{title(status)}</span></td></tr>{expanded&&<tr className="cannibalization-expanded-row"><td colSpan={8}><div className="cannibalization-expanded-content"><header><div><strong>{row.urls.length} competing URLs for “{row.keyword}”</strong><p>Performance values are shown only where matching imported GSC or GA4 page evidence is available.</p></div><button className="secondary compact-button" onClick={()=>onOpenCase(row.cases[0].id)}>Review decision</button></header><div className="cannibalization-url-scroll"><table><thead><tr><th>Target URL</th><th>Page type</th><th>Position</th><th>Impressions</th><th>Clicks</th><th>CTR</th><th>GA4 sessions</th><th>Conversions</th><th>Actions</th></tr></thead><tbody>{row.urls.map(item=><CannibalizationUrlRow key={item.url} item={item} strongest={item.url===strongest?.url}/>)}</tbody></table></div><div className="cannibalization-recommendation"><strong>Recommended review</strong><p>{recommendation}</p></div><details className="advanced-case-list"><summary>Advanced detection evidence · {row.cases.length} signal{row.cases.length===1?'':'s'}</summary>{row.cases.map(item=><article key={item.id}><div><strong>{title(item.case_type)}</strong><span>{title(item.status)} · last seen {new Date(item.last_seen_at).toLocaleDateString()}</span></div><button className="text-button" onClick={()=>onOpenCase(item.id)}>Open evidence and history</button></article>)}</details></div></td></tr>}</>
}

function CannibalizationUrlRow({ item, strongest }:{item:CannibalizationUrlMetric;strongest:boolean}) {
  const [copied,setCopied]=useState(false)
  async function copy() { if(!item.url)return;await navigator.clipboard.writeText(item.url);setCopied(true);window.setTimeout(()=>setCopied(false),1200) }
  return <tr className={strongest?'strongest-url':''}><td><div className="competing-url"><a href={item.url} target="_blank" rel="noreferrer">{item.url}</a><span>{strongest?'Strongest available evidence':item.approved_target?'Approved target':'Competing URL'}</span></div></td><td>{item.page_type||'—'}</td><td>{fmt(bestPosition(item))}</td><td>{fmt(item.gsc_impressions)}</td><td>{fmt(item.gsc_clicks)}</td><td>{item.gsc_ctr===null||item.gsc_ctr===undefined?'—':`${(item.gsc_ctr*100).toFixed(1)}%`}</td><td>{fmt(item.ga4_sessions)}</td><td>{fmt(item.ga4_conversions)}</td><td><div className="url-row-actions"><button onClick={copy}>{copied?'Copied':'Copy'}</button><a href={item.url} target="_blank" rel="noreferrer">Open ↗</a></div></td></tr>
}

type PageMapBucket = { key:string; url?:string; groups:StrategyGroup[] }
type PageMapMember = { member:StrategyMember; group:StrategyGroup; groups:StrategyGroup[] }

function PageMappingWorkspace({ project, groups, allGroups, loading, error, search, setSearch, onSaved }:{ project:Project; groups:StrategyGroup[]; allGroups:StrategyGroup[]; loading:boolean; error:string; search:string; setSearch:(value:string)=>void; onSaved:()=>void }) {
  const [actions, setActions] = useState<string[]>([])
  const [keywords, setKeywords] = useState<KeywordOpportunity[]>([])
  const [keywordError, setKeywordError] = useState('')
  const [showDraftForm, setShowDraftForm] = useState(false)
  const actionOptions = [{ value:'create_new', label:'Create new' }, { value:'optimize_existing', label:'Optimize existing' }, { value:'leave_as_is', label:'Leave as is' }]
  function refreshKeywords() {
    api<KeywordOpportunity[]>(`/api/projects/${project.id}/keywords`).then(setKeywords).catch(err => setKeywordError(err.message))
  }
  useEffect(() => { refreshKeywords() }, [project.id])
  const actionFiltered = groups.filter(group => !actions.length || actions.includes(group.target?.planned_action || (group.target?.planned_page ? 'create_new' : 'optimize_existing')))
  const buckets = [...actionFiltered.reduce((items, group) => {
    const key = group.target?.url ? normalizedUrl(group.target.url) : `unassigned:${group.id}`
    const bucket = items.get(key) || { key, url:group.target?.url, groups:[] as StrategyGroup[] }
    bucket.groups.push(group)
    items.set(key, bucket)
    return items
  }, new Map<string, PageMapBucket>()).values()].sort((left, right) => (left.url || 'zzzz').localeCompare(right.url || 'zzzz'))
  return <section className="page-map-workspace">
    <div className="workspace-filter-bar page-map-toolbar">
      <div className="filter-search-row"><div className="search"><Icon name="search"/><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search target URL or keyword…"/></div><strong>{buckets.length} target URLs</strong><button className="primary small" onClick={()=>setShowDraftForm(true)}><Icon name="plus"/>Add Draft URL</button></div>
      <div className="filter-controls-row strategy-filter-controls"><CheckboxFilter label="Planned action" options={actionOptions} values={actions} onChange={setActions}/></div>
    </div>
    <div className="mapping-guidance"><strong>URL-first keyword map</strong><p>One target URL per row. Add planned URLs as Drafts, then assign keywords and On-Page recommendations before launch. A successful HTML Screaming Frog crawl will connect to the same record automatically.</p></div>
    {(error || keywordError) && <div className="error-box">{error || keywordError}</div>}
    {loading ? <div className="loading-panel"><div className="spinner"/>Loading page map…</div> : buckets.length ? <div className="page-map-table-scroll"><table className="page-map-table"><thead><tr><th>Target URL</th><th>Primary Keyword</th><th>Search Volume</th><th>Search Volume of Secondary KWs</th><th>Search Intent</th><th>Planned Action</th></tr></thead><tbody>{buckets.map(bucket => <PageMappingRow key={bucket.key} project={project} bucket={bucket} keywords={keywords} onSaved={onSaved} onKeywordsChanged={refreshKeywords}/>)}</tbody></table></div> : <div className="empty small-empty"><h3>No target URLs yet</h3><p>Add a Draft URL for a planned page, or generate assignments after importing Semrush rankings.</p></div>}
    {showDraftForm&&<DraftPageModal project={project} onClose={()=>setShowDraftForm(false)} onSaved={()=>{setShowDraftForm(false);onSaved()}}/>}
  </section>
}

function PageMappingRow({ project, bucket, keywords, onSaved, onKeywordsChanged }:{ project:Project; bucket:PageMapBucket; keywords:KeywordOpportunity[]; onSaved:()=>void; onKeywordsChanged:()=>void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [draggedKeywordId, setDraggedKeywordId] = useState<string>()
  const owner = bucket.groups.find(group => group.members.length) || bucket.groups[0]
  const references = bucket.groups.flatMap(group => group.members.map(member => ({ member, group })))
  const unique = [...references.reduce((items, reference) => {
    const current = items.get(reference.member.id)
    if (current) current.groups.push(reference.group)
    else items.set(reference.member.id, { ...reference, groups:[reference.group] })
    return items
  }, new Map<string, PageMapMember>()).values()]
  const primaryId = owner?.primary_keyword_id || owner?.members.find(item => item.role === 'primary')?.id || owner?.members[0]?.id
  const primary = unique.find(item => item.member.id === primaryId) || unique[0]
  const secondary = unique.filter(item => item.member.id !== primary?.member.id)
  const assignedIds = new Set(unique.map(item => item.member.id))
  const currentAction = bucket.groups[0]?.target?.planned_action || (bucket.groups[0]?.target?.planned_page ? 'create_new' : 'optimize_existing')

  async function addKeyword(keyword:KeywordOpportunity, role:'primary'|'supporting') {
    if (!owner) return
    setBusy(true); setError('')
    try {
      await postJson(`/api/projects/${project.id}/strategy/groups/${owner.id}/members`, { keyword_ids:[keyword.id], role, status:'approved' })
      onSaved()
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }

  async function removeKeyword(item:PageMapMember) {
    setBusy(true); setError('')
    try {
      await Promise.all(item.groups.map(group => deleteJson(`/api/projects/${project.id}/strategy/groups/${group.id}/members/${item.member.id}`)))
      onSaved()
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }

  async function updateAction(value:string) {
    setBusy(true); setError('')
    try {
      await Promise.all(bucket.groups.filter(group => group.target).map(group => putJson(`/api/projects/${project.id}/strategy/groups/${group.id}/target`, {
        page_id:group.target?.page_id || null,
        proposed_url:group.target?.page_id ? null : group.target?.url,
        status:group.target?.status || 'approved',
        rationale:group.target?.rationale || null,
        planned_action:value,
        focus_keyword_id:group.primary_keyword_id || null,
      })))
      onSaved()
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }

  function promoteDroppedKeyword(event:React.DragEvent) {
    event.preventDefault()
    const item = unique.find(reference => reference.member.id === draggedKeywordId)
    setDraggedKeywordId(undefined)
    if (item && item.member.id !== primary?.member.id) addKeyword(item.member, 'primary')
  }

  return <>
  <tr className={`${error ? 'has-error' : ''} ${expanded ? 'is-expanded' : ''}`}>
    <td><div className="page-map-target"><div className="page-map-target-heading"><button className="row-expand-button" aria-expanded={expanded} aria-label={expanded ? 'Collapse mapping tools' : 'Expand mapping tools'} onClick={() => setExpanded(value => !value)}>{expanded ? '−' : '+'}</button><a href={bucket.url || undefined} target={bucket.url ? '_blank' : undefined} rel="noreferrer">{bucket.url || 'Target URL not assigned'}</a>{bucket.groups[0]?.target?.page_type==='Draft'&&<span className="type-pill type-draft">Draft</span>}</div><button className="mapping-tools-toggle" onClick={() => setExpanded(value => !value)}>{expanded ? 'Hide mapping tools' : 'Manage mapping'}</button>{error && <small className="inline-error">{error}</small>}</div></td>
    <td onDragOver={event => { if (draggedKeywordId) event.preventDefault() }} onDrop={promoteDroppedKeyword}><div className={`primary-keyword-cell ${draggedKeywordId ? 'drop-ready' : ''}`}>{primary ? <span className="primary-keyword-chip"><strong>{primary.member.keyword}</strong><button disabled={busy} title="Remove primary keyword" onClick={() => removeKeyword(primary)}>×</button></span> : <span className="cell-placeholder">Drop or add a primary keyword</span>}<KeywordPicker label={primary ? 'Change keyword' : 'Add Keyword'} keywords={keywords} assignedIds={assignedIds} disabled={busy} onSelect={item => addKeyword(item, 'primary')}/></div></td>
    <td><strong className="metric-number">{fmt(primary?.member.volume)}</strong></td>
    <td><div className="secondary-keyword-cell combined">{secondary.map(item => <span className="secondary-keyword-chip" draggable key={item.member.id} onDragStart={event => { setDraggedKeywordId(item.member.id); event.dataTransfer.effectAllowed = 'move' }} onDragEnd={() => setDraggedKeywordId(undefined)}><i aria-hidden="true" title="Drag to the primary keyword column">⋮⋮</i><strong>{item.member.keyword}</strong><b>{fmt(item.member.volume)}</b><button disabled={busy} title="Remove secondary keyword" onClick={() => removeKeyword(item)}>×</button></span>)}<KeywordPicker label="Add Secondary Keyword" keywords={keywords} assignedIds={assignedIds} disabled={busy} onSelect={item => addKeyword(item, 'supporting')}/></div></td>
    <td><IntentPills value={primary?.member.intents || owner?.intent} empty="?"/></td>
    <td><select className="planned-action-select" value={currentAction} disabled={busy || !bucket.groups.some(group => group.target)} onChange={event => updateAction(event.target.value)}><option value="create_new">Create new</option><option value="optimize_existing">Optimize existing</option><option value="leave_as_is">Leave as is</option></select></td>
  </tr>
  {expanded && <tr className="page-map-expanded-row"><td colSpan={6}><div className="page-map-expanded-content"><section><span className="expanded-label">Target page</span><p>Change the existing or proposed URL for all keyword groups shown in this row.</p><TargetEditor project={project} bucket={bucket} disabled={busy} onSaved={onSaved}/></section><section><span className="expanded-label">Bulk keyword entry</span><p>Add one <code>keyword, search volume</code> pair per line. Existing keywords are reused safely.</p><BulkManualKeywordEditor project={project} group={owner} disabled={busy} onSaved={() => { onSaved(); onKeywordsChanged() }}/></section><section><span className="expanded-label">Quick role editing</span><p>Drag a secondary keyword onto the Primary Keyword cell, or use “Make primary”. Imported keyword evidence is never deleted.</p><div className="mapping-row-summary"><strong>{unique.length}</strong><span>Total keywords</span><strong>{bucket.groups.length}</strong><span>Keyword groups</span></div></section></div></td></tr>}
  </>
}

function BulkManualKeywordEditor({ project, group, disabled, onSaved }:{ project:Project; group?:StrategyGroup; disabled:boolean; onSaved:()=>void }) {
  const [value, setValue] = useState('')
  const [firstAsPrimary, setFirstAsPrimary] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function save() {
    if (!group) return
    const entries:{keyword:string;volume:number|null}[] = []
    for (const [index, raw] of value.split(/\r?\n/).entries()) {
      const line = raw.trim()
      if (!line) continue
      const separator = line.lastIndexOf(',')
      const keyword = (separator >= 0 ? line.slice(0, separator) : line).trim()
      const volumeText = separator >= 0 ? line.slice(separator + 1).trim().replaceAll(',', '') : ''
      if (!keyword || separator < 0 || !/^\d+$/.test(volumeText)) {
        setError(`Line ${index + 1} must use: keyword, search volume`)
        return
      }
      entries.push({ keyword, volume:Number(volumeText) })
    }
    if (!entries.length) { setError('Add at least one keyword and search volume.'); return }
    setBusy(true); setError('')
    try {
      await postJson(`/api/projects/${project.id}/strategy/groups/${group.id}/members/manual`, { entries, first_as_primary:firstAsPrimary })
      setValue(''); setFirstAsPrimary(false); onSaved()
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  return <div className="bulk-keyword-editor"><textarea rows={4} value={value} disabled={disabled || busy} onChange={event => setValue(event.target.value)} placeholder={'asda mobile deals, 720\nsim only plans, 1900'}/><label><input type="checkbox" checked={firstAsPrimary} onChange={event => setFirstAsPrimary(event.target.checked)}/><span>Use the first keyword as primary</span></label>{error && <small className="inline-error">{error}</small>}<button className="primary" disabled={disabled || busy || !value.trim()} onClick={save}>{busy ? 'Adding…' : 'Add bulk keywords'}</button></div>
}

function KeywordPicker({ label, keywords, assignedIds, disabled, onSelect }:{ label:string; keywords:KeywordOpportunity[]; assignedIds:Set<string>; disabled:boolean; onSelect:(keyword:KeywordOpportunity)=>void }) {
  const [query, setQuery] = useState('')
  const details = useRef<HTMLDetailsElement>(null)
  const options = keywords.filter(item => !assignedIds.has(item.id) && (!query || item.keyword.toLowerCase().includes(query.toLowerCase()))).slice(0, 50)
  return <details className="keyword-picker" ref={details}><summary aria-disabled={disabled}>{label}</summary><div className="keyword-picker-popover"><input autoFocus value={query} onChange={event => setQuery(event.target.value)} placeholder="Search imported Semrush keywords…"/><div>{options.length ? options.map(item => <button key={item.id} disabled={disabled} onClick={() => { onSelect(item); details.current?.removeAttribute('open'); setQuery('') }}><strong>{item.keyword}</strong><small>Volume {fmt(item.volume)} · KD {fmt(item.keyword_difficulty)} · {item.intent || 'Intent unknown'}</small></button>) : <p>No available imported keywords.</p>}</div></div></details>
}

function TargetEditor({ project, bucket, disabled, onSaved }:{ project:Project; bucket:PageMapBucket; disabled:boolean; onSaved:()=>void }) {
  const currentTarget=bucket.groups[0]?.target
  const currentIsDraft=currentTarget?.page_type==='Draft'
  const [query, setQuery] = useState('')
  const [pages, setPages] = useState<Page[]>([])
  const [pageId, setPageId] = useState(currentIsDraft?'':currentTarget?.page_id || '')
  const [url, setUrl] = useState(currentIsDraft?bucket.url || '':currentTarget?.page_id?'':bucket.url || '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const details = useRef<HTMLDetailsElement>(null)
  useEffect(() => {
    if (query.length < 2) { setPages([]); return }
    const timer = setTimeout(() => api<{ items:Page[] }>(`/api/projects/${project.id}/pages?search=${encodeURIComponent(query)}&page_size=20`).then(result => setPages(result.items)).catch(err => setError(err.message)), 250)
    return () => clearTimeout(timer)
  }, [query, project.id])
  async function save() {
    setBusy(true); setError('')
    try {
      await Promise.all(bucket.groups.map(group => putJson(`/api/projects/${project.id}/strategy/groups/${group.id}/target`, {
        page_id:pageId || null,
        proposed_url:pageId ? null : url,
        status:'approved',
        planned_action:pageId ? (group.target?.planned_action === 'leave_as_is' ? 'leave_as_is' : 'optimize_existing') : group.target?.planned_action || 'create_new',
        focus_keyword_id:group.primary_keyword_id || null,
      })))
      details.current?.removeAttribute('open'); onSaved()
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  return <details className="target-editor" ref={details}><summary aria-disabled={disabled}>Edit target</summary><div className="target-editor-popover"><label>Find existing live page<input value={query} onChange={event => setQuery(event.target.value)} placeholder="Type at least two characters…"/></label>{pages.length > 0 && <div className="page-search-results">{pages.map(page => <button className={pageId === page.id ? 'active' : ''} key={page.id} onClick={() => { setPageId(page.id); setUrl('') }}><strong>{page.original_url}</strong><small>{page.page_type} · {page.indexability || 'Indexability unknown'}</small></button>)}</div>}<label>Or use a Draft URL<input value={url} disabled={Boolean(pageId)} onChange={event => { setUrl(event.target.value); setPageId('') }} placeholder="https://example.com/planned-page"/></label><small className="target-editor-hint">New URLs are saved as Draft Page records and remain outside Pages and Site Architecture until a successful HTML crawl is imported.</small>{pageId && <button className="text-button" onClick={() => setPageId('')}>Clear selected page</button>}{error && <small className="inline-error">{error}</small>}<button className="primary" disabled={busy || (!pageId && !url)} onClick={save}>{busy ? 'Saving…' : 'Save target'}</button></div></details>
}

function DraftPageModal({project,onClose,onSaved}:{project:Project;onClose:()=>void;onSaved:()=>void}){
  const [url,setUrl]=useState(`${project.site_url.replace(/\/$/,'')}/`)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  async function submit(event:React.FormEvent){
    event.preventDefault();setBusy(true);setError('')
    try{await postJson(`/api/projects/${project.id}/strategy/draft-pages`,{url});onSaved()}catch(caught){setError((caught as Error).message)}finally{setBusy(false)}
  }
  return <div className="overlay"><form className="modal draft-page-modal" onSubmit={submit}><button type="button" className="close" onClick={onClose}>×</button><p className="eyebrow">PLANNED PAGE</p><h2>Add a Draft URL</h2><p className="modal-intro">The URL will appear in Page Mapping and On-Page SEO. It will stay out of the live inventory and architecture until Screaming Frog reports status 200 with HTML content.</p><label>Full planned URL<input type="url" required value={url} onChange={event=>setUrl(event.target.value)} placeholder="https://example.com/new-page"/></label>{error&&<div className="error-box">{error}</div>}<div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy?'Adding Draft…':'Add Draft URL'}</button></div></form></div>
}

function UrlStack({ urls }:{ urls:string[] }) {
  return urls.length ? <div className="ranking-url-stack"><strong>{urls.length} observed URL{urls.length === 1 ? '' : 's'}</strong><span title={urls.join('\n')}>{urls[0]}</span></div> : <span className="coverage-gap">No observed URL</span>
}

function GroupDrawer({ project, group, onClose, onSaved }:{ project:Project; group:StrategyGroup; onClose:()=>void; onSaved:()=>void }) {
  const [tab, setTab] = useState('Rankings')
  const [name, setName] = useState(group.name)
  const [intent, setIntent] = useState(group.intent || '')
  const [reviewer, setReviewer] = useState('')
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const rankingMembers = group.members.filter(member => member.best_semrush_position !== null)

  useEffect(() => {
    if (tab === 'History') api<HistoryItem[]>(`/api/projects/${project.id}/strategy/groups/${group.id}/history`).then(setHistory).catch(err => setError(err.message))
  }, [tab, project.id, group.id])

  async function saveGroup() {
    setBusy(true)
    try {
      await patchJson(`/api/projects/${project.id}/strategy/groups/${group.id}`, { name, intent:intent || null })
      onSaved()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function approve() {
    setBusy(true)
    try {
      await postJson(`/api/projects/${project.id}/strategy/groups/${group.id}/approve?reviewer=${encodeURIComponent(reviewer)}`, {})
      onSaved()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return <div className="overlay" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}><aside className="drawer strategy-drawer"><button className="close" onClick={onClose}>×</button><p className="eyebrow">KEYWORD GROUP</p><h2>{group.name}</h2><p className="keyword-scope">{rankingMembers.length} current ranking keywords · {group.status}</p><div className="drawer-tabs">{['Rankings', 'History'].map(item => <button className={tab === item ? 'active' : ''} onClick={() => setTab(item)} key={item}>{item}</button>)}</div>
    {tab === 'Rankings' && <><div className="strategy-form-grid"><label>Group name<input value={name} onChange={event => setName(event.target.value)}/></label><label>Intent<input value={intent} onChange={event => setIntent(event.target.value)}/></label></div><div className="member-list">{rankingMembers.length ? rankingMembers.map(member => <article key={member.id}><div><strong>{member.keyword}</strong><small>Position {fmt(member.best_semrush_position)} · Volume {fmt(member.volume)} · KD {fmt(member.keyword_difficulty)} · {member.ranking_urls[0] || 'No ranking URL supplied'}</small></div><IntentPills value={member.intents} empty="?"/></article>) : <div className="metadata-empty">No current Semrush ranking observations are available in this group.</div>}</div><label className="strategy-field">Reviewer<input value={reviewer} onChange={event => setReviewer(event.target.value)} placeholder="Optional reviewer name"/></label><div className="drawer-actions"><button className="secondary" disabled={busy} onClick={saveGroup}>Save group details</button><button className="primary" disabled={busy} onClick={approve}>Approve group</button></div></>}
    {tab === 'History' && <div className="strategy-history">{history.length ? history.map(item => <article key={item.id}><header><strong>{title(item.action)}</strong><time>{new Date(item.created_at).toLocaleString()}</time></header><p>{item.reviewer || 'No reviewer recorded'}{item.reason ? ` · ${item.reason}` : ''}</p><pre>{JSON.stringify(item.after, null, 2)}</pre></article>) : <div className="history-empty">No review decisions have been logged yet.</div>}</div>}
    {error && <div className="error-box">{error}</div>}
  </aside></div>
}

function CaseDrawer({ project, item, onClose, onSaved }:{ project:Project; item:CannibalizationCase; onClose:()=>void; onSaved:()=>void }) {
  const [status, setStatus] = useState(item.status)
  const [action, setAction] = useState(item.latest_decision?.action || 'Investigate intent and ranking trend')
  const [preferredUrl, setPreferredUrl] = useState(item.latest_decision?.preferred_url || '')
  const [reviewer, setReviewer] = useState(item.latest_decision?.reviewer || '')
  const [notes, setNotes] = useState(item.latest_decision?.notes || '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function save() {
    setBusy(true)
    try {
      await postJson(`/api/projects/${project.id}/strategy/cannibalization/cases/${item.id}/decision`, { status, action, preferred_url:preferredUrl || null, reviewer:reviewer || null, notes:notes || null })
      onSaved()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return <div className="overlay" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}><aside className="drawer strategy-drawer"><button className="close" onClick={onClose}>×</button><p className="eyebrow">CANNIBALIZATION REVIEW</p><h2>{item.findings[0]?.keyword||item.title}</h2><span className={`strategy-status status-${item.status}`}>{title(item.status)}</span><div className="case-review-summary"><strong>{item.findings[0]?.classification==='keyword_overlap'?'Keyword overlap':'Potential cannibalisation'}</strong><p>{item.case_type==='approved_keyword_multi_target'?'This keyword has more than one approved target. That overlap needs intent review, but is not proof of ranking competition.':'Multiple ranking or target signals involve this keyword. Compare the URLs before choosing a preferred page or consolidation action.'}</p></div>{item.unknowns.length > 0 && <div className="unknown-box"><strong>What this evidence cannot prove</strong>{item.unknowns.map(value => <p key={value}>{value}</p>)}</div>}<details className="evidence-box advanced-evidence"><summary>Advanced detection evidence</summary><pre>{JSON.stringify(item.evidence, null, 2)}</pre></details><div className="strategy-form-grid"><label>Status<select value={status} onChange={event => setStatus(event.target.value)}>{['new', 'needs_investigation', 'harmless_overlap', 'likely_cannibalization', 'confirmed', 'resolved'].map(value => <option value={value} key={value}>{title(value)}</option>)}</select></label><label>Reviewer<input value={reviewer} onChange={event => setReviewer(event.target.value)}/></label></div><label className="strategy-field">Action<input value={action} onChange={event => setAction(event.target.value)}/></label><label className="strategy-field">Preferred URL<input value={preferredUrl} onChange={event => setPreferredUrl(event.target.value)}/></label><label className="strategy-field">Decision notes<textarea rows={3} value={notes} onChange={event => setNotes(event.target.value)}/></label>{error && <div className="error-box">{error}</div>}<button className="primary" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Record decision'}</button><h3 className="history-heading">Decision history</h3><div className="strategy-history">{item.decision_history.map((decision, index) => <article key={`${decision.decided_at}-${index}`}><header><strong>{title(decision.status)}</strong><time>{new Date(decision.decided_at).toLocaleString()}</time></header><p>{decision.action} · {decision.reviewer || 'No reviewer'}</p>{decision.notes && <small>{decision.notes}</small>}</article>)}</div></aside></div>
}
