import { useEffect, useMemo, useRef, useState } from 'react'
import { createColumnHelper, flexRender, getCoreRowModel, getSortedRowModel, useReactTable } from '@tanstack/react-table'
import type { ColumnOrderState, ColumnSizingState, SortingState, VisibilityState } from '@tanstack/react-table'
import { api, deleteJson, patchJson, postJson } from '../api'
import { CheckboxFilter } from '../components/CheckboxFilter'
import { Icon } from '../components/Icons'
import { IntentPills, SEARCH_INTENTS } from '../components/IntentPills'
import { SummaryActionCard } from '../components/SummaryActionCard'
import type { KeywordOpportunity, Project } from '../types'

type SaveResult = { created:number; updated:number; keyword_ids:string[] }

const columnHelper = createColumnHelper<KeywordOpportunity>()
const DEFAULT_COLUMN_ORDER = ['keyword','volume','keyword_difficulty','intents','url_associations']
const COLUMN_LABELS:Record<string,string> = {
  keyword:'Keyword',
  volume:'Volume',
  keyword_difficulty:'KD',
  intents:'Intent',
  url_associations:'URL coverage',
}

function savedTableLayout(projectId:string) {
  try {
    const saved = JSON.parse(localStorage.getItem(`page-mapper:saved-keywords-table:${projectId}`)||'{}')
    return {
      sizing:(saved.sizing||{}) as ColumnSizingState,
      visibility:(saved.visibility||{}) as VisibilityState,
      order:(Array.isArray(saved.order)&&saved.order.length?saved.order:DEFAULT_COLUMN_ORDER) as ColumnOrderState,
    }
  } catch {
    return { sizing:{}, visibility:{}, order:DEFAULT_COLUMN_ORDER as ColumnOrderState }
  }
}

export function SavedKeywords({ project }:{ project:Project }) {
  const initialLayout = useMemo(()=>savedTableLayout(project.id),[project.id])
  const filterToolbar = useRef<HTMLDivElement>(null)
  const [items, setItems] = useState<KeywordOpportunity[]>([])
  const [search, setSearch] = useState('')
  const [coverage, setCoverage] = useState<string[]>([])
  const [intents, setIntents] = useState<string[]>([])
  const [volumeMin, setVolumeMin] = useState('')
  const [volumeMax, setVolumeMax] = useState('')
  const [difficultyMin, setDifficultyMin] = useState('')
  const [difficultyMax, setDifficultyMax] = useState('')
  const [value, setValue] = useState('')
  const [editing, setEditing] = useState<KeywordOpportunity>()
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>(initialLayout.sizing)
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(initialLayout.visibility)
  const [columnOrder, setColumnOrder] = useState<ColumnOrderState>(initialLayout.order)
  const [sorting, setSorting] = useState<SortingState>([])
  const [draggedColumn, setDraggedColumn] = useState<string>()

  function load() {
    setLoading(true)
    api<KeywordOpportunity[]>(`/api/projects/${project.id}/keywords`).then(setItems).catch(err=>setError(err.message)).finally(()=>setLoading(false))
  }
  useEffect(load, [project.id])
  useEffect(()=>{
    localStorage.setItem(`page-mapper:saved-keywords-table:${project.id}`,JSON.stringify({sizing:columnSizing,visibility:columnVisibility,order:columnOrder}))
  },[project.id,columnSizing,columnVisibility,columnOrder])

  const visible = useMemo(()=>items.filter(item=>{
    if (search && !`${item.keyword} ${item.market} ${item.url_associations.map(url=>url.url).join(' ')}`.toLowerCase().includes(search.toLowerCase())) return false
    if (coverage.length) {
      const state = item.assigned_url_count ? 'mapped' : item.associated_url_count ? 'observed' : 'unassigned'
      if (!coverage.includes(state)) return false
    }
    if (intents.length&&!item.intents.some(intent=>intents.some(selected=>selected.toLowerCase()===intent.toLowerCase()))) return false
    if (volumeMin!==''&&(item.volume===null||item.volume<Number(volumeMin))) return false
    if (volumeMax!==''&&(item.volume===null||item.volume>Number(volumeMax))) return false
    if (difficultyMin!==''&&(item.keyword_difficulty===null||item.keyword_difficulty<Number(difficultyMin))) return false
    if (difficultyMax!==''&&(item.keyword_difficulty===null||item.keyword_difficulty>Number(difficultyMax))) return false
    return true
  }), [items, search, coverage, intents, volumeMin, volumeMax, difficultyMin, difficultyMax])

  const columns = useMemo(()=>[
    columnHelper.accessor('keyword',{header:'Keyword',size:280,minSize:170,sortUndefined:'last',cell:({row})=><button className="saved-keyword-link" onClick={()=>setEditing(row.original)}><strong>{row.original.keyword}</strong><small>{row.original.market||'Default market'} · Edit details</small></button>}),
    columnHelper.accessor('volume',{header:'Volume',size:110,minSize:80,sortDescFirst:true,sortUndefined:'last',cell:info=>info.getValue()?.toLocaleString()??'—'}),
    columnHelper.accessor('keyword_difficulty',{header:'KD',size:90,minSize:65,sortDescFirst:true,sortUndefined:'last',cell:info=>info.getValue()??'—'}),
    columnHelper.accessor(row=>row.intents.join(', '),{id:'intents',header:'Intent',size:160,minSize:110,sortUndefined:'last',cell:({row})=><IntentPills value={row.original.intents} empty="?"/>}),
    columnHelper.accessor(row=>row.associated_url_count,{id:'url_associations',header:'URL coverage',size:330,minSize:180,sortDescFirst:true,cell:({row})=>row.original.url_associations.length?<details className="saved-keyword-urls"><summary>{row.original.assigned_url_count} mapped · {row.original.associated_url_count} total</summary><div>{row.original.url_associations.map(association=><a key={association.url} href={association.url} target="_blank" rel="noreferrer"><strong>{association.url}</strong><small>{[association.mapped?'Mapped':null,association.semrush?'Semrush':null,association.gsc?'GSC':null].filter(Boolean).join(' · ')}</small></a>)}</div></details>:<span className="coverage-gap">Ready to map</span>}),
  ],[])

  const table = useReactTable({
    data:visible,
    columns,
    state:{columnSizing,columnVisibility,columnOrder,sorting},
    onColumnSizingChange:setColumnSizing,
    onColumnVisibilityChange:setColumnVisibility,
    onColumnOrderChange:setColumnOrder,
    onSortingChange:setSorting,
    columnResizeMode:'onChange',
    getCoreRowModel:getCoreRowModel(),
    getSortedRowModel:getSortedRowModel(),
  })

  function keepOneOpen(event:React.SyntheticEvent<HTMLDetailsElement>) {
    if (!event.currentTarget.open) return
    filterToolbar.current?.querySelectorAll('details[open]').forEach(item=>{if(item!==event.currentTarget)(item as HTMLDetailsElement).open=false})
  }

  function moveColumn(columnId:string, direction:-1|1) {
    setColumnOrder(current=>{
      const order = [...current]
      const from = order.indexOf(columnId)
      const to = from + direction
      if (from<0||to<0||to>=order.length) return current
      ;[order[from],order[to]]=[order[to],order[from]]
      return order
    })
  }

  function dropColumn(targetId:string) {
    if (!draggedColumn||draggedColumn===targetId) return setDraggedColumn(undefined)
    setColumnOrder(current=>{
      const order = current.filter(id=>id!==draggedColumn)
      const target = order.indexOf(targetId)
      order.splice(target<0?order.length:target,0,draggedColumn)
      return order
    })
    setDraggedColumn(undefined)
  }

  async function save() {
    const entries:{keyword:string;volume:number|null;keyword_difficulty:number|null}[] = []
    for (const [index, raw] of value.split(/\r?\n/).entries()) {
      const line = raw.trim()
      if (!line) continue
      const parts = line.split(',').map(part=>part.trim())
      const [keyword, volumeText='', difficultyText=''] = parts
      if (!keyword || parts.length>3 || (volumeText&&!/^\d+$/.test(volumeText)) || (difficultyText&&(!/^\d+(\.\d+)?$/.test(difficultyText)||Number(difficultyText)>100))) {
        setError(`Line ${index + 1} must use “keyword, volume, KD” with KD between 0 and 100.`)
        return
      }
      entries.push({ keyword, volume:volumeText?Number(volumeText):null, keyword_difficulty:difficultyText?Number(difficultyText):null })
    }
    if (!entries.length) { setError('Add at least one keyword.'); return }
    setBusy(true); setError(''); setMessage('')
    try {
      const result = await postJson<SaveResult>(`/api/projects/${project.id}/keywords`, { entries })
      setValue('')
      setMessage(`${result.created} new keyword${result.created===1?'':'s'} saved; ${result.updated} existing keyword${result.updated===1?'':'s'} updated.`)
      load()
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }

  const mapped = items.filter(item=>item.assigned_url_count>0).length
  const observedOnly = items.filter(item=>item.assigned_url_count===0&&item.associated_url_count>0).length
  const noUrl = items.filter(item=>item.associated_url_count===0).length
  function clearSummaryFilters(){setSearch('');setCoverage([]);setIntents([]);setVolumeMin('');setVolumeMax('');setDifficultyMin('');setDifficultyMax('')}
  function filterCoverage(value:string){const active=coverage.length===1&&coverage[0]===value;clearSummaryFilters();if(!active)setCoverage([value])}
  return <div className="page keyword-workspace saved-keywords-page">
    <div className="page-heading compact"><div><p className="eyebrow">DURABLE KEYWORD LIBRARY</p><h1>Saved Keywords</h1><p>Every imported or manually added keyword remains here whether it is mapped, observed, or still waiting for a target URL.</p></div><div className="actions"><a className="secondary button" href={`/api/projects/${project.id}/keywords/export`}><Icon name="download"/>Export</a><a className="primary button" href="/page-mapping"><Icon name="pages"/>Open Page Mapping</a></div></div>
    <section className="metric-grid keyword-metrics"><SummaryActionCard label="Saved keywords" value={items.length.toLocaleString()} detail="Imported and manual keywords" action="Show all keywords" onClick={clearSummaryFilters}/><SummaryActionCard label="Mapped" value={mapped.toLocaleString()} detail="Assigned to target URLs" action={coverage.length===1&&coverage[0]==='mapped'?'Clear filter':'Show mapped'} active={coverage.length===1&&coverage[0]==='mapped'} onClick={()=>filterCoverage('mapped')}/><SummaryActionCard label="Observed only" value={observedOnly.toLocaleString()} detail="Ranking or GSC URLs without a mapped target" action={coverage.length===1&&coverage[0]==='observed'?'Clear filter':'Show observed'} active={coverage.length===1&&coverage[0]==='observed'} onClick={()=>filterCoverage('observed')}/><SummaryActionCard label="No URL yet" value={noUrl.toLocaleString()} detail="Ready for a future target assignment" action={coverage.length===1&&coverage[0]==='unassigned'?'Clear filter':'Show without URLs'} active={coverage.length===1&&coverage[0]==='unassigned'} onClick={()=>filterCoverage('unassigned')}/></section>
    <section className="panel saved-keyword-entry"><div><h2>Add Keywords</h2><p>Add one keyword per line using <code>keyword, volume, KD</code>. Volume and KD are optional; existing terms are updated without deleting their history.</p></div><textarea rows={4} value={value} onChange={event=>setValue(event.target.value)} placeholder={'asda mobile bundles, 720, 34\nasda mobile upgrade, 390, 28\nasda sim only'} /><button className="primary" disabled={busy||!value.trim()} onClick={save}>{busy?'Saving…':'Add Keywords'}</button>{message&&<div className="success-box">{message}</div>}{error&&<div className="error-box">{error}</div>}</section>
    <section className="table-panel saved-keyword-table-panel">
      <div ref={filterToolbar} className="workspace-filter-bar">
        <div className="filter-search-row">
          <div className="search"><Icon name="search"/><input value={search} onChange={event=>setSearch(event.target.value)} placeholder="Search saved keywords or URLs…"/></div>
          <strong>{visible.length.toLocaleString()} keywords</strong>
          <details className="column-picker saved-column-picker" onToggle={keepOneOpen}><summary><Icon name="settings"/>Columns</summary><div><header><strong>Columns and order</strong><button type="button" onClick={()=>table.toggleAllColumnsVisible(true)}>Show all</button></header>{columnOrder.map((columnId,index)=>{const column=table.getColumn(columnId);return column?<div className="saved-column-control" key={columnId}><label><input type="checkbox" checked={column.getIsVisible()} onChange={column.getToggleVisibilityHandler()}/><span>{COLUMN_LABELS[columnId]||columnId}</span></label><span className="column-move-actions"><button type="button" disabled={index===0} onClick={()=>moveColumn(columnId,-1)} aria-label={`Move ${COLUMN_LABELS[columnId]} left`}>←</button><button type="button" disabled={index===columnOrder.length-1} onClick={()=>moveColumn(columnId,1)} aria-label={`Move ${COLUMN_LABELS[columnId]} right`}>→</button></span></div>:null})}<button className="reset-columns" type="button" onClick={()=>{table.resetColumnSizing();table.resetColumnVisibility();setColumnOrder([...DEFAULT_COLUMN_ORDER])}}>Reset layout and order</button></div></details>
        </div>
        <div className="filter-controls-row saved-keyword-filter-controls">
          <CheckboxFilter label="Assignment" options={[{value:'mapped',label:'Mapped target'},{value:'observed',label:'Observed URL only'},{value:'unassigned',label:'No URL yet'}]} values={coverage} onChange={setCoverage} onToggle={keepOneOpen}/>
          <RangeFilter label="Volume" min={volumeMin} max={volumeMax} setMin={setVolumeMin} setMax={setVolumeMax} onToggle={keepOneOpen}/>
          <RangeFilter label="KD" min={difficultyMin} max={difficultyMax} setMin={setDifficultyMin} setMax={setDifficultyMax} maxLimit={100} onToggle={keepOneOpen}/>
          <CheckboxFilter label="Intent" options={SEARCH_INTENTS.map(intent=>({value:intent,label:intent}))} values={intents} onChange={setIntents} onToggle={keepOneOpen}/>
        </div>
      </div>
      <div className="table-scroll resizable-table"><table style={{width:table.getTotalSize(),minWidth:'100%'}}><thead>{table.getHeaderGroups().map(group=><tr key={group.id}>{group.headers.map(header=>{const direction=header.column.getIsSorted();return <th key={header.id} aria-sort={direction?(direction==='asc'?'ascending':'descending'):'none'} draggable onDragStart={()=>setDraggedColumn(header.column.id)} onDragEnd={()=>setDraggedColumn(undefined)} onDragOver={event=>event.preventDefault()} onDrop={()=>dropColumn(header.column.id)} className={draggedColumn===header.column.id?'dragging-column':''} style={{width:header.getSize()}}><span className="header-label"><button type="button" className="saved-sort-button" draggable={false} onDragStart={event=>{event.preventDefault();event.stopPropagation()}} onMouseDown={event=>event.stopPropagation()} onClick={header.column.getToggleSortingHandler()} title={`Sort by ${COLUMN_LABELS[header.column.id]||header.column.id}`}>{flexRender(header.column.columnDef.header,header.getContext())}<span aria-hidden="true" className="sort-direction">{direction==='asc'?'↑':direction==='desc'?'↓':'↕'}</span></button></span>{header.column.getCanResize()&&<button type="button" className={`column-resizer ${header.column.getIsResizing()?'active':''}`} onMouseDown={header.getResizeHandler()} onTouchStart={header.getResizeHandler()} onDoubleClick={()=>header.column.resetSize()} draggable={false} aria-label={`Resize ${COLUMN_LABELS[header.column.id]||header.column.id} column`}/>}</th>})}</tr>)}</thead><tbody>{loading?<tr><td colSpan={table.getVisibleLeafColumns().length}><div className="loading-panel"><div className="spinner"/>Loading saved keywords…</div></td></tr>:table.getRowModel().rows.length?table.getRowModel().rows.map(row=><tr key={row.id}>{row.getVisibleCells().map(cell=><td key={cell.id} style={{width:cell.column.getSize()}}>{flexRender(cell.column.columnDef.cell,cell.getContext())}</td>)}</tr>):<tr><td colSpan={table.getVisibleLeafColumns().length}><div className="empty small-empty"><h3>No matching saved keywords</h3><p>Adjust the filter or add a new keyword.</p></div></td></tr>}</tbody></table></div>
    </section>
    {editing&&<KeywordEditor project={project} item={editing} onClose={()=>setEditing(undefined)} onSaved={()=>{setEditing(undefined);load()}}/>}
  </div>
}

function RangeFilter({ label, min, max, setMin, setMax, maxLimit, onToggle }:{ label:string; min:string; max:string; setMin:(value:string)=>void; setMax:(value:string)=>void; maxLimit?:number; onToggle:(event:React.SyntheticEvent<HTMLDetailsElement>)=>void }) {
  const active = min!==''||max!==''
  return <details className="filter-picker range-filter-picker" onToggle={onToggle}><summary>{label} <b>{active?'Set':'All'}</b></summary><div><header><strong>{label} range</strong><button type="button" onClick={()=>{setMin('');setMax('')}}>Clear</button></header><div className="range-filter-fields"><label><span>Minimum</span><input type="number" min="0" max={maxLimit} value={min} onChange={event=>setMin(event.target.value)} placeholder="No minimum"/></label><label><span>Maximum</span><input type="number" min="0" max={maxLimit} value={max} onChange={event=>setMax(event.target.value)} placeholder="No maximum"/></label></div></div></details>
}

function KeywordEditor({ project, item, onClose, onSaved }:{ project:Project; item:KeywordOpportunity; onClose:()=>void; onSaved:()=>void }) {
  const [keyword, setKeyword] = useState(item.keyword)
  const [volume, setVolume] = useState(item.volume===null?'':String(item.volume))
  const [difficulty, setDifficulty] = useState(item.keyword_difficulty===null?'':String(item.keyword_difficulty))
  const [intents, setIntents] = useState(item.intents)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  function toggleIntent(intent:string) { setIntents(current=>current.includes(intent)?current.filter(item=>item!==intent):[...current,intent]) }
  async function save() {
    setBusy(true); setError('')
    try {
      await patchJson(`/api/projects/${project.id}/keywords/${item.id}/details`, { keyword, volume:volume===''?null:Number(volume), keyword_difficulty:difficulty===''?null:Number(difficulty), intents })
      onSaved()
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  async function remove() {
    if (!window.confirm(`Delete “${item.keyword}” and its imported metrics, rankings, group memberships and mappings? This cannot be undone.`)) return
    setBusy(true); setError('')
    try { await deleteJson(`/api/projects/${project.id}/keywords/${item.id}`); onSaved() } catch (err) { setError((err as Error).message); setBusy(false) }
  }
  return <div className="overlay" onMouseDown={event=>{if(event.target===event.currentTarget)onClose()}}><div className="modal saved-keyword-editor"><button className="close" onClick={onClose}>×</button><p className="eyebrow">SAVED KEYWORD</p><h2>Edit keyword details</h2><label>Keyword<input value={keyword} onChange={event=>setKeyword(event.target.value)}/></label><div className="two-col"><label>Search volume<input type="number" min="0" value={volume} onChange={event=>setVolume(event.target.value)}/></label><label>Keyword difficulty<input type="number" min="0" max="100" step="0.1" value={difficulty} onChange={event=>setDifficulty(event.target.value)}/></label></div><fieldset className="intent-selector"><legend>Search intent</legend><p>Select every intent that applies.</p><div>{SEARCH_INTENTS.map(intent=><button type="button" key={intent} className={intents.includes(intent)?'selected':''} onClick={()=>toggleIntent(intent)}><IntentPills value={[intent]}/><span>{intent}</span></button>)}</div></fieldset><section className="keyword-editor-urls"><strong>Associated URLs</strong>{item.url_associations.length?item.url_associations.map(association=><a key={association.url} href={association.url} target="_blank" rel="noreferrer">{association.url}</a>):<span>No URL associations yet.</span>}</section>{error&&<div className="error-box">{error}</div>}<div className="modal-actions split-actions"><button className="danger-outline" disabled={busy} onClick={remove}>Delete keyword</button><span/><button className="secondary" disabled={busy} onClick={onClose}>Cancel</button><button className="primary" disabled={busy||!keyword.trim()} onClick={save}>{busy?'Saving…':'Save changes'}</button></div></div></div>
}
