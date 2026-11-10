import { useEffect, useMemo, useRef, useState } from 'react'
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import type { ColumnSizingState, VisibilityState } from '@tanstack/react-table'
import { api, deleteJson, patchJson, postJson, putJson } from '../api'
import { CheckboxFilter } from '../components/CheckboxFilter'
import { Icon } from '../components/Icons'
import type { CannibalizationCase, KeywordOpportunity, Page, Project, StrategyGroup, StrategyMember, StrategySummary } from '../types'

type View = 'groups' | 'mapping' | 'cannibalization'
type HistoryItem = { id:string; entity_type:string; action:string; reviewer?:string; before:Record<string,unknown>; after:Record<string,unknown>; reason?:string; created_at:string }

const groupHelper = createColumnHelper<StrategyGroup>()
const caseHelper = createColumnHelper<CannibalizationCase>()
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

  useEffect(() => {
    try {
      localStorage.setItem(`page-mapper:strategy:${project.id}:${view}`, JSON.stringify({ visibility, sizing }))
    } catch {
      // Layout remains usable without persistence.
    }
  }, [project.id, view, visibility, sizing])

  const visibleGroups = useMemo(() => groups.filter(group => {
    const haystack = `${group.name} ${group.members.map(item => item.keyword).join(' ')} ${group.target?.url || ''}`.toLowerCase()
    return (view !== 'groups' || group.members.some(member => member.best_semrush_position !== null))
      && (!search || haystack.includes(search.toLowerCase()))
      && (!statuses.length || statuses.includes(group.status))
      && (!intents.length || intents.includes(group.intent || 'Unclassified'))
      && (!readiness.length || readiness.includes(group.readiness))
  }), [groups, search, statuses, intents, readiness, view])

  const visibleCases = useMemo(() => cases.filter(item => (!search || `${item.title} ${item.case_type}`.toLowerCase().includes(search.toLowerCase())) && (!statuses.length || statuses.includes(item.status))), [cases, search, statuses])

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
    groupHelper.accessor('intent', { header:'Intent', size:115, cell:info => <span className="intent-pill">{info.getValue() || 'Unclassified'}</span> }),
    groupHelper.display({ id:'ranking_keywords', header:'Current ranking keywords', size:145, cell:info => <strong>{info.row.original.members.filter(member => member.best_semrush_position !== null).length}</strong> }),
    groupHelper.accessor('unique_volume', { header:'Unique volume', size:115, cell:info => fmt(info.getValue()) }),
    groupHelper.accessor('status', { header:'Group status', size:120, cell:info => <span className={`strategy-status status-${info.getValue()}`}>{title(info.getValue())}</span> }),
    groupHelper.accessor('observed_urls', { header:'Current ranking URLs', size:300, minSize:180, maxSize:600, cell:info => <UrlStack urls={info.getValue()}/> }),
  ], [selected])

  const caseColumns = useMemo(() => [
    caseHelper.accessor('title', { header:'Case', size:330, minSize:190, maxSize:620, cell:info => <button className="strategy-link" onClick={() => setOpenCase(info.row.original.id)}><strong>{info.getValue()}</strong><small>View evidence and decision log</small></button> }),
    caseHelper.accessor('case_type', { header:'Signal', size:190, cell:info => title(info.getValue()) }),
    caseHelper.accessor('priority', { header:'Priority', size:100, cell:info => title(info.getValue()) }),
    caseHelper.accessor('status', { header:'Status', size:155, cell:info => <span className={`strategy-status status-${info.getValue()}`}>{title(info.getValue())}</span> }),
    caseHelper.accessor('last_seen_at', { header:'Last seen', size:150, cell:info => new Date(info.getValue()).toLocaleDateString() }),
  ], [])

  const groupTable = useReactTable({ data:visibleGroups, columns:groupColumns, state:{ columnVisibility:visibility, columnSizing:sizing }, onColumnVisibilityChange:setVisibility, onColumnSizingChange:setSizing, columnResizeMode:'onChange', getCoreRowModel:getCoreRowModel() })
  const caseTable = useReactTable({ data:visibleCases, columns:caseColumns, state:{ columnVisibility:visibility, columnSizing:sizing }, onColumnVisibilityChange:setVisibility, onColumnSizingChange:setSizing, columnResizeMode:'onChange', getCoreRowModel:getCoreRowModel() })
  const statusOptions = useMemo(() => [...new Set((view === 'cannibalization' ? cases : groups).map(item => item.status))].sort().map(value => ({ value, label:title(value) })), [groups, cases, view])
  const intentOptions = useMemo(() => [...new Set(groups.map(item => item.intent || 'Unclassified'))].sort().map(value => ({ value, label:value })), [groups])
  const readinessOptions = useMemo(() => [...new Set(groups.map(item => item.readiness))].sort().map(value => ({ value, label:value })), [groups])
  const heading = view === 'groups' ? 'Keyword Groups' : view === 'mapping' ? 'Page Mapping' : 'Cannibalization Audit'
  const intro = view === 'groups' ? 'Review imported ranking keywords and deterministic group suggestions.' : view === 'mapping' ? 'Choose a target URL, focus keyword, supporting terms and planned action for every page.' : 'Investigate evidence-based overlap signals; no case is automatically labelled harmful.'
  const table = view === 'cannibalization' ? caseTable : groupTable

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
      <article><span>Mapped keywords</span><strong>{summary?.mapped_keywords ?? '—'}</strong><small>{summary?.unmapped_keywords ?? '—'} awaiting approval</small></article>
      <article><span>Keyword groups</span><strong>{summary?.groups ?? '—'}</strong><small>Suggested and approved</small></article>
      <article><span>Approved targets</span><strong>{summary?.approved_targets ?? '—'}</strong><small>Protected from import overwrite</small></article>
      <article className={summary?.cases_needing_review ? 'attention' : ''}><span>Cases needing review</span><strong>{summary?.cases_needing_review ?? '—'}</strong><small>{summary?.resolved_cases ?? '—'} resolved</small></article>
    </section>
    {view === 'mapping'
      ? <PageMappingWorkspace project={project} groups={visibleGroups} allGroups={groups} loading={loading} error={error} search={search} setSearch={setSearch} onSaved={() => setRefresh(value => value + 1)}/>
      : <section className="table-panel strategy-table-panel">
          <div ref={toolbar} className="workspace-filter-bar strategy-filter-bar">
            <div className="filter-search-row">
              <div className="search"><Icon name="search"/><input value={search} onChange={event => setSearch(event.target.value)} placeholder={`Search ${heading.toLowerCase()}…`}/></div>
              <strong>{(view === 'cannibalization' ? visibleCases : visibleGroups).length} results</strong>
              <details className="column-picker" onToggle={keepOne}><summary><Icon name="settings"/>Columns</summary><div><header><strong>Visible columns</strong><button onClick={() => table.toggleAllColumnsVisible(true)}>Show all</button></header>{table.getAllLeafColumns().filter(column => column.getCanHide()).map(column => <label key={column.id}><input type="checkbox" checked={column.getIsVisible()} onChange={column.getToggleVisibilityHandler()}/><span>{typeof column.columnDef.header === 'string' ? column.columnDef.header : column.id}</span></label>)}<button className="reset-columns" onClick={() => { table.resetColumnSizing(); table.resetColumnVisibility() }}>Reset layout</button></div></details>
            </div>
            <div className="filter-controls-row strategy-filter-controls">
              <CheckboxFilter label="Status" options={statusOptions} values={statuses} onChange={setStatuses} onToggle={keepOne}/>
              {view !== 'cannibalization' && <CheckboxFilter label="Intent" options={intentOptions} values={intents} onChange={setIntents} onToggle={keepOne}/>}
              {view !== 'cannibalization' && <CheckboxFilter label="Readiness" options={readinessOptions} values={readiness} onChange={setReadiness} onToggle={keepOne}/>}
            </div>
          </div>
          {selected.length > 0 && <div className="bulk-bar"><strong>{selected.length} groups selected</strong><button className="primary" disabled={busy} onClick={approveSelected}>Approve groups and memberships</button><button className="secondary" onClick={() => setSelected([])}>Clear</button></div>}
          {error && <div className="error-box">{error}</div>}
          <StrategyTable table={table} loading={loading} empty={view === 'cannibalization' ? 'Run the evidence scan after importing rankings.' : 'Generate suggestions after importing Semrush rankings.'}/>
        </section>}
    {openGroup && <GroupDrawer project={project} group={groups.find(item => item.id === openGroup)!} onClose={() => setOpenGroup(undefined)} onSaved={() => setRefresh(value => value + 1)}/>}
    {openCase && <CaseDrawer project={project} item={cases.find(caseItem => caseItem.id === openCase)!} onClose={() => setOpenCase(undefined)} onSaved={() => setRefresh(value => value + 1)}/>}
  </div>
}

function StrategyTable({ table, loading, empty }:{ table:any; loading:boolean; empty:string }) {
  return <div className="table-scroll resizable-table"><table style={{ width:table.getTotalSize(), minWidth:'100%' }}><thead>{table.getHeaderGroups().map((group:any) => <tr key={group.id}>{group.headers.map((header:any) => <th key={header.id} style={{ width:header.getSize() }}>{flexRender(header.column.columnDef.header, header.getContext())}{header.column.getCanResize() && <button className={`column-resizer ${header.column.getIsResizing() ? 'active' : ''}`} onMouseDown={header.getResizeHandler()} onTouchStart={header.getResizeHandler()} onDoubleClick={() => header.column.resetSize()} aria-label="Resize column"/>}</th>)}</tr>)}</thead><tbody>{loading ? <tr><td colSpan={table.getVisibleLeafColumns().length}><div className="loading-panel"><div className="spinner"/>Loading strategy evidence…</div></td></tr> : table.getRowModel().rows.length ? table.getRowModel().rows.map((row:any) => <tr key={row.id}>{row.getVisibleCells().map((cell:any) => <td key={cell.id} style={{ width:cell.column.getSize() }}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}</tr>) : <tr><td colSpan={table.getVisibleLeafColumns().length}><div className="empty small-empty"><h3>No results yet</h3><p>{empty}</p></div></td></tr>}</tbody></table></div>
}

type PageMapBucket = { key:string; url?:string; groups:StrategyGroup[] }
type PageMapMember = { member:StrategyMember; group:StrategyGroup; groups:StrategyGroup[] }

function PageMappingWorkspace({ project, groups, allGroups, loading, error, search, setSearch, onSaved }:{ project:Project; groups:StrategyGroup[]; allGroups:StrategyGroup[]; loading:boolean; error:string; search:string; setSearch:(value:string)=>void; onSaved:()=>void }) {
  const [actions, setActions] = useState<string[]>([])
  const [keywords, setKeywords] = useState<KeywordOpportunity[]>([])
  const [keywordError, setKeywordError] = useState('')
  const actionOptions = [{ value:'create_new', label:'Create new' }, { value:'optimize_existing', label:'Optimize existing' }, { value:'leave_as_is', label:'Leave as is' }]
  function refreshKeywords() {
    api<KeywordOpportunity[]>(`/api/projects/${project.id}/keywords`).then(rows => setKeywords(rows.filter(item => item.volume !== null || item.keyword_difficulty !== null || item.best_semrush_position !== null))).catch(err => setKeywordError(err.message))
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
      <div className="filter-search-row"><div className="search"><Icon name="search"/><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search target URL or keyword…"/></div><strong>{buckets.length} target URLs</strong></div>
      <div className="filter-controls-row strategy-filter-controls"><CheckboxFilter label="Planned action" options={actionOptions} values={actions} onChange={setActions}/></div>
    </div>
    <div className="mapping-guidance"><strong>URL-first keyword map</strong><p>One target URL per row. Keyword metrics are read-only Semrush evidence; mapping roles and planned actions can be edited here.</p></div>
    {(error || keywordError) && <div className="error-box">{error || keywordError}</div>}
    {loading ? <div className="loading-panel"><div className="spinner"/>Loading page map…</div> : buckets.length ? <div className="page-map-table-scroll"><table className="page-map-table"><thead><tr><th>Target URL</th><th>Primary Keyword</th><th>Search Volume</th><th>Search Volume of Secondary KWs</th><th>Search Intent</th><th>Planned Action</th></tr></thead><tbody>{buckets.map(bucket => <PageMappingRow key={bucket.key} project={project} bucket={bucket} keywords={keywords} onSaved={onSaved} onKeywordsChanged={refreshKeywords}/>)}</tbody></table></div> : <div className="empty small-empty"><h3>No matching target URLs</h3><p>{allGroups.length ? 'Adjust the filters or search.' : 'Generate assignments after importing Semrush rankings.'}</p></div>}
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
        planned_action:group.target?.page_id ? value : 'create_new',
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
    <td><div className="page-map-target"><div className="page-map-target-heading"><button className="row-expand-button" aria-expanded={expanded} aria-label={expanded ? 'Collapse mapping tools' : 'Expand mapping tools'} onClick={() => setExpanded(value => !value)}>{expanded ? '−' : '+'}</button><a href={bucket.url || undefined} target={bucket.url ? '_blank' : undefined} rel="noreferrer">{bucket.url || 'Target URL not assigned'}</a></div><button className="mapping-tools-toggle" onClick={() => setExpanded(value => !value)}>{expanded ? 'Hide mapping tools' : 'Manage mapping'}</button>{error && <small className="inline-error">{error}</small>}</div></td>
    <td onDragOver={event => { if (draggedKeywordId) event.preventDefault() }} onDrop={promoteDroppedKeyword}><div className={`primary-keyword-cell ${draggedKeywordId ? 'drop-ready' : ''}`}>{primary ? <span className="primary-keyword-chip"><strong>{primary.member.keyword}</strong><button disabled={busy} title="Remove primary keyword" onClick={() => removeKeyword(primary)}>×</button></span> : <span className="cell-placeholder">Drop or add a primary keyword</span>}<KeywordPicker label={primary ? 'Change keyword' : 'Add Keyword'} keywords={keywords} assignedIds={assignedIds} disabled={busy} onSelect={item => addKeyword(item, 'primary')}/></div></td>
    <td><strong className="metric-number">{fmt(primary?.member.volume)}</strong></td>
    <td><div className="secondary-keyword-cell combined">{secondary.map(item => <span className="secondary-keyword-chip" draggable key={item.member.id} onDragStart={event => { setDraggedKeywordId(item.member.id); event.dataTransfer.effectAllowed = 'move' }} onDragEnd={() => setDraggedKeywordId(undefined)}><i aria-hidden="true">⋮⋮</i><strong>{item.member.keyword}</strong><b>{fmt(item.member.volume)}</b><button disabled={busy} title="Make primary" onClick={() => addKeyword(item.member, 'primary')}>Make primary</button><button disabled={busy} title="Remove secondary keyword" onClick={() => removeKeyword(item)}>×</button></span>)}<KeywordPicker label="Add Secondary Keyword" keywords={keywords} assignedIds={assignedIds} disabled={busy} onSelect={item => addKeyword(item, 'supporting')}/></div></td>
    <td><span className="intent-pill">{primary?.member.intent || owner?.intent || 'Unclassified'}</span></td>
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
  const [query, setQuery] = useState('')
  const [pages, setPages] = useState<Page[]>([])
  const [pageId, setPageId] = useState(bucket.groups[0]?.target?.page_id || '')
  const [url, setUrl] = useState(bucket.groups[0]?.target?.page_id ? '' : bucket.url || '')
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
        planned_action:pageId ? (group.target?.planned_action === 'leave_as_is' ? 'leave_as_is' : 'optimize_existing') : 'create_new',
        focus_keyword_id:group.primary_keyword_id || null,
      })))
      details.current?.removeAttribute('open'); onSaved()
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  return <details className="target-editor" ref={details}><summary aria-disabled={disabled}>Edit target</summary><div className="target-editor-popover"><label>Find existing page<input value={query} onChange={event => setQuery(event.target.value)} placeholder="Type at least two characters…"/></label>{pages.length > 0 && <div className="page-search-results">{pages.map(page => <button className={pageId === page.id ? 'active' : ''} key={page.id} onClick={() => { setPageId(page.id); setUrl('') }}><strong>{page.original_url}</strong><small>{page.page_type} · {page.indexability || 'Indexability unknown'}</small></button>)}</div>}<label>Or proposed URL<input value={url} disabled={Boolean(pageId)} onChange={event => { setUrl(event.target.value); setPageId('') }} placeholder="https://example.com/planned-page"/></label>{pageId && <button className="text-button" onClick={() => setPageId('')}>Clear selected page</button>}{error && <small className="inline-error">{error}</small>}<button className="primary" disabled={busy || (!pageId && !url)} onClick={save}>{busy ? 'Saving…' : 'Save target'}</button></div></details>
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
    {tab === 'Rankings' && <><div className="strategy-form-grid"><label>Group name<input value={name} onChange={event => setName(event.target.value)}/></label><label>Intent<input value={intent} onChange={event => setIntent(event.target.value)}/></label></div><div className="member-list">{rankingMembers.length ? rankingMembers.map(member => <article key={member.id}><div><strong>{member.keyword}</strong><small>Position {fmt(member.best_semrush_position)} · Volume {fmt(member.volume)} · KD {fmt(member.keyword_difficulty)} · {member.ranking_urls[0] || 'No ranking URL supplied'}</small></div><span className="intent-pill">{member.intent || 'Unclassified'}</span></article>) : <div className="metadata-empty">No current Semrush ranking observations are available in this group.</div>}</div><label className="strategy-field">Reviewer<input value={reviewer} onChange={event => setReviewer(event.target.value)} placeholder="Optional reviewer name"/></label><div className="drawer-actions"><button className="secondary" disabled={busy} onClick={saveGroup}>Save group details</button><button className="primary" disabled={busy} onClick={approve}>Approve group</button></div></>}
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

  return <div className="overlay" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}><aside className="drawer strategy-drawer"><button className="close" onClick={onClose}>×</button><p className="eyebrow">CANNIBALIZATION REVIEW</p><h2>{item.title}</h2><span className={`strategy-status status-${item.status}`}>{title(item.status)}</span><div className="evidence-box"><strong>Detection evidence</strong><pre>{JSON.stringify(item.evidence, null, 2)}</pre></div>{item.unknowns.length > 0 && <div className="unknown-box"><strong>What this evidence cannot prove</strong>{item.unknowns.map(value => <p key={value}>{value}</p>)}</div>}<div className="strategy-form-grid"><label>Status<select value={status} onChange={event => setStatus(event.target.value)}>{['new', 'needs_investigation', 'harmless_overlap', 'likely_cannibalization', 'confirmed', 'resolved'].map(value => <option value={value} key={value}>{title(value)}</option>)}</select></label><label>Reviewer<input value={reviewer} onChange={event => setReviewer(event.target.value)}/></label></div><label className="strategy-field">Action<input value={action} onChange={event => setAction(event.target.value)}/></label><label className="strategy-field">Preferred URL<input value={preferredUrl} onChange={event => setPreferredUrl(event.target.value)}/></label><label className="strategy-field">Decision notes<textarea rows={3} value={notes} onChange={event => setNotes(event.target.value)}/></label>{error && <div className="error-box">{error}</div>}<button className="primary" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Record decision'}</button><h3 className="history-heading">Decision history</h3><div className="strategy-history">{item.decision_history.map((decision, index) => <article key={`${decision.decided_at}-${index}`}><header><strong>{title(decision.status)}</strong><time>{new Date(decision.decided_at).toLocaleString()}</time></header><p>{decision.action} · {decision.reviewer || 'No reviewer'}</p>{decision.notes && <small>{decision.notes}</small>}</article>)}</div></aside></div>
}
