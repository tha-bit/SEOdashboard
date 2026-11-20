import { useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import type { ColumnSizingState, VisibilityState } from '@tanstack/react-table'
import { api, patchJson, postJson } from '../api'
import { CheckboxFilter } from '../components/CheckboxFilter'
import { Icon } from '../components/Icons'
import type { Project } from '../types'

type Category = { key: string; label: string; count: number }
type Summary = {
  snapshot: null | {
    id: string
    observed_at: string
    complete: boolean
    internal_links: number
    external_links: number
    unmatched_links: number
  }
  total_findings: number
  critical: number
  broken_links: number
  redirect_destinations?: number
  error_destinations?: number
  potential_orphans: number
  weak_pages: number
  opportunities: number
  categories: Category[]
}
type Settings = { weak_inlinks: number; deep_crawl_depth: number }

export type LinkDetail = {
  source_url: string
  destination_url: string
  status_code?: number
  indexability?: string
  indexability_status?: string
  canonical_url?: string
  canonical_status?: string
  anchor?: string
  alt_text?: string
  link_position?: string
  follow?: string
  rel?: string
}

type Finding = {
  issue_key: string
  type: string
  category: string
  category_key: string
  label: string
  detail: string
  severity: string
  priority: string
  status: string
  solution_count: number
  page_id?: string
  url?: string
  page_type?: string
  inlinks?: number
  imported_inlinks?: number
  internal_inlinks?: number
  internal_inlinks_source?: 'screaming_frog' | 'calculated_relationships'
  unique_sources?: number
  crawl_depth?: number
  indexability?: string
  status_code?: number
  page_status_code?: number
  recommendation: string
  snapshot_complete: boolean
  evidence: Record<string, unknown>
  affected_link_count?: number
  links?: LinkDetail[]
}

type InlinkEvidence = {
  snapshot: null | { id: string; observed_at: string; complete: boolean }
  count: number
  unique_sources: number
  inlinks: {
    id: string
    source_url: string
    destination_url: string
    anchor?: string
    alt_text?: string
    status_code?: number
    follow?: string
    rel?: string
    link_position?: string
    link_origin?: string
  }[]
}

const PRIORITIES = [
  { value: 'critical', label: 'Critical' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
]
const PRIORITY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }
const findingHelper = createColumnHelper<Finding>()
const FINDING_COLUMNS: Record<string, string> = {
  issue: 'Issue',
  url: 'Affected URL',
  affected_link_count: 'Affected Links',
  page_type: 'Page Type',
  internal_inlinks: 'Internal Inlinks',
  unique_sources: 'Unique Linking Pages',
  crawl_depth: 'Crawl Depth',
  page_status_code: 'Status Code',
  priority: 'Priority',
  actions: 'Actions',
}

function savedFindingLayout(projectId: string) {
  if (typeof window === 'undefined') return { columnVisibility: {}, columnSizing: {} }
  try {
    return JSON.parse(localStorage.getItem(`page-mapper:internal-links-table:${projectId}`) || '{}') as {
      columnVisibility?: VisibilityState
      columnSizing?: ColumnSizingState
    }
  } catch {
    return { columnVisibility: {}, columnSizing: {} }
  }
}

export function InternalLinkingAnalysis({ project }: { project: Project }) {
  const saved = useMemo(() => savedFindingLayout(project.id), [project.id])
  const filterToolbar = useRef<HTMLDivElement>(null)
  const [summary, setSummary] = useState<Summary>()
  const [items, setItems] = useState<Finding[]>([])
  const [settings, setSettings] = useState<Settings>({ weak_inlinks: 3, deep_crawl_depth: 4 })
  const [search, setSearch] = useState('')
  const [categories, setCategories] = useState<string[]>([])
  const [priorities, setPriorities] = useState<string[]>([])
  const [pageTypes, setPageTypes] = useState<string[]>([])
  const [indexabilities, setIndexabilities] = useState<string[]>([])
  const [statuses, setStatuses] = useState<string[]>([])
  const [sort, setSort] = useState('priority')
  const [selected, setSelected] = useState<Finding>()
  const [inlinkPage, setInlinkPage] = useState<Finding>()
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [error, setError] = useState('')
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(saved.columnVisibility || {})
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>(saved.columnSizing || {})

  const load = async () => {
    try {
      const [nextSummary, nextItems, nextSettings] = await Promise.all([
        api<Summary>(`/api/projects/${project.id}/architecture/internal-links/summary`),
        api<{ items: Finding[] }>(`/api/projects/${project.id}/architecture/internal-links/findings`),
        api<Settings>(`/api/projects/${project.id}/architecture/internal-links/settings`),
      ])
      setSummary(nextSummary)
      setItems(nextItems.items)
      setSettings(nextSettings)
    } catch (err) {
      setError((err as Error).message)
    }
  }
  useEffect(() => {
    load()
  }, [project.id])
  useEffect(() => {
    try {
      localStorage.setItem(`page-mapper:internal-links-table:${project.id}`, JSON.stringify({ columnVisibility, columnSizing }))
    } catch {
      /* Session-only fallback */
    }
  }, [project.id, columnVisibility, columnSizing])

  const pageTypeOptions = useMemo(() => [...new Set(items.map(item => item.page_type).filter(Boolean) as string[])].sort().map(value => ({ value, label: value })), [items])
  const indexabilityOptions = useMemo(() => [...new Set(items.map(item => item.indexability || 'Unknown'))].sort().map(value => ({ value, label: value })), [items])
  const statusOptions = useMemo(() => [...new Set(items.map(item => (item.page_status_code === null || item.page_status_code === undefined ? 'Unknown' : String(item.page_status_code))))].sort().map(value => ({ value, label: value })), [items])
  const visible = useMemo(
    () =>
      items
        .filter(
          item =>
            (!categories.length || categories.includes(item.category_key)) &&
            (!priorities.length || priorities.includes(item.priority)) &&
            (!pageTypes.length || pageTypes.includes(item.page_type || '')) &&
            (!indexabilities.length || indexabilities.includes(item.indexability || 'Unknown')) &&
            (!statuses.length || statuses.includes(item.page_status_code === null || item.page_status_code === undefined ? 'Unknown' : String(item.page_status_code))) &&
            (!search || `${item.label} ${item.url || ''} ${item.detail} ${JSON.stringify(item.evidence)}`.toLowerCase().includes(search.toLowerCase())),
        )
        .sort((a, b) =>
          sort === 'internal_inlinks'
            ? (b.internal_inlinks ?? -1) - (a.internal_inlinks ?? -1)
            : sort === 'unique_sources'
              ? (b.unique_sources ?? -1) - (a.unique_sources ?? -1)
              : sort === 'crawl_depth'
                ? (b.crawl_depth ?? -1) - (a.crawl_depth ?? -1)
                : (PRIORITY_ORDER[a.priority] ?? 9) - (PRIORITY_ORDER[b.priority] ?? 9),
        ),
    [items, categories, priorities, pageTypes, indexabilities, statuses, search, sort],
  )
  const grouped = useMemo(() => {
    const result = new Map<string, Finding[]>()
    for (const item of visible) result.set(item.category, [...(result.get(item.category) || []), item])
    return [...result.entries()]
  }, [visible])

  function clear() {
    setCategories([])
    setPriorities([])
    setPageTypes([])
    setIndexabilities([])
    setStatuses([])
    setSearch('')
  }
  function keepOnePickerOpen(event: React.SyntheticEvent<HTMLDetailsElement>) {
    if (!event.currentTarget.open) return
    filterToolbar.current?.querySelectorAll<HTMLDetailsElement>('details[open]').forEach(item => {
      if (item !== event.currentTarget) item.removeAttribute('open')
    })
  }
  function exportUrl(category?: string) {
    const params = new URLSearchParams()
    if (category) params.set('category', category)
    if (priorities.length === 1) params.set('priority', priorities[0])
    if (search.trim()) params.set('search', search.trim())
    pageTypes.forEach(value => params.append('page_types', value))
    indexabilities.forEach(value => params.append('indexabilities', value))
    statuses.forEach(value => params.append('status_codes', value))
    return `/api/projects/${project.id}/architecture/internal-links/export.csv?${params}`
  }
  async function saveSettings() {
    try {
      await patchJson(`/api/projects/${project.id}/architecture/internal-links/settings`, settings)
      setSettingsOpen(false)
      await load()
    } catch (err) {
      setError((err as Error).message)
    }
  }
  async function createTask(item: Finding) {
    try {
      const result = await postJson<{ duplicate?: boolean }>(`/api/projects/${project.id}/task-manager/tasks`, {
        title: item.label,
        description: `${item.detail}\n\nRecommendation: ${item.recommendation}`,
        category: 'Internal Linking',
        priority: item.priority,
        status: 'to_do',
        related_urls: item.url ? [item.url] : [],
        supporting_links: [],
        source_issue_key: item.issue_key,
        source_issue_type: item.type,
        source_section: 'site_architecture',
        source_url: item.url || null,
      })
      window.alert(result.duplicate ? 'An open task is already linked to this finding.' : 'Task added to Task Manager.')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  if (!summary?.snapshot)
    return (
      <section className="panel internal-linking-empty">
        <div className="empty">
          <Icon name="tree" />
          <h2>No internal-link evidence yet</h2>
          <p>Import a Screaming Frog Inlinks CSV or XLSX file to analyse actual source-to-destination links for PDP and PLP commercial pages.</p>
          <a className="primary button" href="/imports">
            Import Screaming Frog Inlinks
          </a>
        </div>
      </section>
    )

  return (
    <div className="internal-linking-workspace">
      <section className="metric-grid internal-link-metrics">
        <button onClick={clear}>
          <span>Observed internal links</span>
          <strong>{summary.snapshot.internal_links.toLocaleString()}</strong>
          <small>{summary.snapshot.complete ? 'Complete snapshot' : 'Partial snapshot'}</small>
        </button>
        <button
          onClick={() => {
            clear()
            setCategories(['broken_invalid_links'])
          }}
        >
          <span>Broken internal links</span>
          <strong>{summary.broken_links.toLocaleString()}</strong>
          <small>4XX error destinations</small>
        </button>
        {summary.redirect_destinations !== undefined && (
          <button
            onClick={() => {
              clear()
              setCategories(['broken_invalid_links', 'indexability_canonical_conflicts'])
            }}
          >
            <span>Redirect links (3XX)</span>
            <strong>{summary.redirect_destinations.toLocaleString()}</strong>
            <small>3XX redirect destinations</small>
          </button>
        )}
        <button
          onClick={() => {
            clear()
            setCategories(['orphan_weak_pages'])
          }}
        >
          <span>Potential orphan pages</span>
          <strong>{summary.potential_orphans.toLocaleString()}</strong>
          <small>PDP/PLP without links</small>
        </button>
        <button
          onClick={() => {
            clear()
            setCategories(['orphan_weak_pages'])
            setSearch('Weakly linked')
          }}
        >
          <span>Weakly linked pages</span>
          <strong>{summary.weak_pages.toLocaleString()}</strong>
          <small>Below {settings.weak_inlinks} unique sources</small>
        </button>
        <button
          onClick={() => {
            clear()
            setCategories(['indexability_canonical_conflicts'])
          }}
        >
          <span>Indexability conflicts</span>
          <strong>{summary.categories.find(item => item.key === 'indexability_canonical_conflicts')?.count.toLocaleString() || '0'}</strong>
          <small>Non-indexable or non-canonical</small>
        </button>
        <button
          onClick={() => {
            clear()
            setCategories(['linking_opportunities'])
          }}
        >
          <span>Linking opportunities</span>
          <strong>{summary.opportunities.toLocaleString()}</strong>
          <small>Commercial recommendations</small>
        </button>
      </section>

      <section className="panel internal-link-findings">
        <div className="panel-title">
          <div>
            <p className="eyebrow">PDP &amp; PLP COMMERCIAL PAGES ONLY</p>
            <h2>Internal Linking Analysis</h2>
            <p>
              {new Date(summary.snapshot.observed_at).toLocaleString()} · issues restricted to PDP &amp; PLP commercial pages · asset pages excluded · grouped by affected destination
            </p>
          </div>
          <div className="actions">
            <button className="secondary" onClick={() => setSettingsOpen(true)}>
              <Icon name="settings" />
              Thresholds
            </button>
            <a className="secondary button" href={exportUrl()}>
              <Icon name="download" />
              Export filtered CSV
            </a>
          </div>
        </div>

        <div ref={filterToolbar} className="internal-link-controls">
          <div className="internal-link-search-row">
            <div className="search">
              <Icon name="search" />
              <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search issues, URLs, anchors, or evidence" />
            </div>
            <span>{visible.length.toLocaleString()} findings</span>
            <button className="text-button" onClick={clear}>
              Clear filters
            </button>
          </div>
          <div className="internal-link-filter-row">
            <CheckboxFilter label="Category" options={summary.categories.map(item => ({ value: item.key, label: `${item.label} (${item.count})` }))} values={categories} onChange={setCategories} onToggle={keepOnePickerOpen} />
            <CheckboxFilter label="Priority" options={PRIORITIES} values={priorities} onChange={setPriorities} onToggle={keepOnePickerOpen} />
            <CheckboxFilter label="Page Type" options={pageTypeOptions} values={pageTypes} onChange={setPageTypes} onToggle={keepOnePickerOpen} />
            <CheckboxFilter label="Indexability" options={indexabilityOptions} values={indexabilities} onChange={setIndexabilities} onToggle={keepOnePickerOpen} />
            <CheckboxFilter label="Status Code" options={statusOptions} values={statuses} onChange={setStatuses} onToggle={keepOnePickerOpen} />
            <label className="inline-sort">
              Sort
              <select value={sort} onChange={event => setSort(event.target.value)}>
                <option value="priority">Priority</option>
                <option value="internal_inlinks">Internal inlinks</option>
                <option value="unique_sources">Unique sources</option>
                <option value="crawl_depth">Crawl depth</option>
              </select>
            </label>
            <details className="column-picker" onToggle={keepOnePickerOpen}>
              <summary>
                <Icon name="settings" />
                Columns
              </summary>
              <div>
                <header>
                  <strong>Visible metrics</strong>
                  <button type="button" onClick={() => setColumnVisibility({})}>
                    Show all
                  </button>
                </header>
                <div className="filter-option-list">
                  {Object.entries(FINDING_COLUMNS).map(([id, label]) => (
                    <label className="filter-option-row" key={id}>
                      <input type="checkbox" checked={columnVisibility[id] !== false} onChange={event => setColumnVisibility(current => ({ ...current, [id]: event.target.checked }))} />
                      <span>{label}</span>
                    </label>
                  ))}
                </div>
                <button
                  type="button"
                  className="reset-columns"
                  onClick={() => {
                    setColumnVisibility({})
                    setColumnSizing({})
                  }}
                >
                  Reset widths and visibility
                </button>
              </div>
            </details>
          </div>
        </div>

        {error && <div className="error-box">{error}</div>}

        <div className="internal-link-groups">
          {grouped.map(([category, rows]) => (
            <details key={category} open>
              <summary>
                <div>
                  <strong>{category}</strong>
                  <small>{rows.length.toLocaleString()} affected records</small>
                </div>
                <span className="disclosure">⌄</span>
              </summary>
              <div className="issue-group-tools">
                <a className="secondary button compact-button" href={exportUrl(rows[0].category_key)}>
                  <Icon name="download" />
                  Export category CSV
                </a>
              </div>
              <FindingsTable rows={rows} visibility={columnVisibility} sizing={columnSizing} setVisibility={setColumnVisibility} setSizing={setColumnSizing} onDetails={setSelected} onInlinks={setInlinkPage} />
            </details>
          ))}
          {!grouped.length && (
            <div className="empty small-empty">
              <h3>No matching findings</h3>
              <p>Adjust the filters or import a newer Inlinks snapshot.</p>
            </div>
          )}
        </div>
      </section>

      {selected && <InternalLinkFindingDrawer finding={selected} onClose={() => setSelected(undefined)} onInspectInlinks={() => { if (selected.page_id) { setInlinkPage(selected); setSelected(undefined) } }} onCreateTask={() => createTask(selected)} />}
      {inlinkPage?.page_id && <PageIncomingLinksDrawer project={project} pageId={inlinkPage.page_id} url={inlinkPage.url} onClose={() => setInlinkPage(undefined)} />}

      {settingsOpen && (
        <div className="overlay" onMouseDown={event => { if (event.target === event.currentTarget) setSettingsOpen(false) }}>
          <aside className="drawer">
            <button className="close" onClick={() => setSettingsOpen(false)}>×</button>
            <p className="eyebrow">INTERNAL LINKING RULES</p>
            <h2>Analysis thresholds</h2>
            <p>These project settings apply to PDP and PLP commercial pages. They do not modify imported evidence.</p>
            <div className="edit-fields">
              <label>
                Weak page: fewer than unique sources
                <input type="number" min="1" max="100" value={settings.weak_inlinks} onChange={event => setSettings(value => ({ ...value, weak_inlinks: Number(event.target.value) }))} />
              </label>
              <label>
                Deep page: crawl depth at or above
                <input type="number" min="1" max="100" value={settings.deep_crawl_depth} onChange={event => setSettings(value => ({ ...value, deep_crawl_depth: Number(event.target.value) }))} />
              </label>
            </div>
            <div className="modal-actions">
              <button className="secondary" onClick={() => setSettingsOpen(false)}>Cancel</button>
              <button className="primary" onClick={saveSettings}>Save thresholds</button>
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}

function FindingsTable({
  rows,
  visibility,
  sizing,
  setVisibility,
  setSizing,
  onDetails,
  onInlinks,
}: {
  rows: Finding[]
  visibility: VisibilityState
  sizing: ColumnSizingState
  setVisibility: Dispatch<SetStateAction<VisibilityState>>
  setSizing: Dispatch<SetStateAction<ColumnSizingState>>
  onDetails: (item: Finding) => void
  onInlinks: (item: Finding) => void
}) {
  const columns = useMemo(
    () => [
      findingHelper.display({
        id: 'issue',
        header: 'Issue',
        size: 220,
        minSize: 170,
        maxSize: 340,
        cell: info => (
          <button className="finding-primary" onClick={() => onDetails(info.row.original)}>
            <strong>{info.row.original.label}</strong>
            <small>{info.row.original.detail}</small>
          </button>
        ),
      }),
      findingHelper.accessor('url', {
        id: 'url',
        header: 'Affected URL',
        size: 230,
        minSize: 170,
        maxSize: 380,
        cell: info =>
          info.getValue() ? (
            <div className="finding-url">
              <button className="issue-url-button" onClick={() => onDetails(info.row.original)} title={info.getValue()}>
                {shortUrl(info.getValue() || '')}
              </button>
              {info.row.original.page_id && (
                <button className="text-button" onClick={() => onInlinks(info.row.original)}>
                  Inspect inlinks
                </button>
              )}
            </div>
          ) : (
            <button className="text-button" onClick={() => onDetails(info.row.original)}>
              View project-level finding
            </button>
          ),
      }),
      findingHelper.accessor('affected_link_count', {
        id: 'affected_link_count',
        header: 'Affected Links',
        size: 110,
        minSize: 90,
        maxSize: 150,
        cell: info => {
          const count = info.getValue()
          if (count === null || count === undefined) return <span className="muted-cell">—</span>
          return <span className="count-chip">{count.toLocaleString()} link{count === 1 ? '' : 's'}</span>
        },
      }),
      findingHelper.accessor('page_type', { header: 'Page Type', size: 100, minSize: 85, maxSize: 150, cell: info => info.getValue() || 'N/A' }),
      findingHelper.accessor('internal_inlinks', {
        header: 'Internal Inlinks',
        size: 110,
        minSize: 95,
        maxSize: 160,
        cell: info => (
          <span title={info.row.original.internal_inlinks_source === 'screaming_frog' ? 'Imported from Screaming Frog' : 'Calculated from the latest Inlinks relationships'}>
            {metric(info.getValue())}
          </span>
        ),
      }),
      findingHelper.accessor('unique_sources', { header: 'Unique Sources', size: 105, minSize: 90, maxSize: 145, cell: info => metric(info.getValue()) }),
      findingHelper.accessor('crawl_depth', { header: 'Crawl Depth', size: 95, minSize: 80, maxSize: 135, cell: info => metric(info.getValue()) }),
      findingHelper.accessor('page_status_code', { header: 'Status Code', size: 95, minSize: 80, maxSize: 130, cell: info => metric(info.getValue()) }),
      findingHelper.accessor('priority', { header: 'Priority', size: 95, minSize: 85, maxSize: 140, cell: info => <span className={`priority-pill ${info.getValue()}`}>{info.getValue()}</span> }),
      findingHelper.display({
        id: 'actions',
        header: 'Actions',
        size: 100,
        minSize: 90,
        maxSize: 140,
        cell: info => (
          <button className="secondary compact-button" onClick={() => onDetails(info.row.original)}>
            View details
          </button>
        ),
      }),
    ],
    [onDetails, onInlinks],
  )
  const [page, setPage] = useState(1)
  const pageSize = 50
  useEffect(() => {
    setPage(1)
  }, [rows])
  const totalPages = Math.max(Math.ceil(rows.length / pageSize), 1)
  const currentPage = Math.min(page, totalPages)
  const pageRows = useMemo(() => rows.slice((currentPage - 1) * pageSize, currentPage * pageSize), [rows, currentPage, pageSize])

  const table = useReactTable({
    data: pageRows,
    columns,
    state: { columnVisibility: visibility, columnSizing: sizing },
    onColumnVisibilityChange: setVisibility,
    onColumnSizingChange: setSizing,
    columnResizeMode: 'onChange',
    getCoreRowModel: getCoreRowModel(),
  })
  return (
    <div>
      <div className="table-scroll resizable-table internal-link-table">
        <table style={{ width: table.getTotalSize(), minWidth: '100%' }}>
          <thead>
            {table.getHeaderGroups().map(group => (
              <tr key={group.id}>
                {group.headers.map(header => (
                  <th key={header.id} style={{ width: header.getSize() }}>
                    <span className="header-label">{flexRender(header.column.columnDef.header, header.getContext())}</span>
                    {header.column.getCanResize() && (
                      <button
                        type="button"
                        className={`column-resizer ${header.column.getIsResizing() ? 'active' : ''}`}
                        aria-label={`Resize ${FINDING_COLUMNS[header.column.id] || header.column.id} column`}
                        onDoubleClick={() => header.column.resetSize()}
                        onMouseDown={header.getResizeHandler()}
                        onTouchStart={header.getResizeHandler()}
                      />
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map(row => (
              <tr key={row.original.issue_key}>
                {row.getVisibleCells().map(cell => (
                  <td key={cell.id} style={{ width: cell.column.getSize() }}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > pageSize && (
        <div className="pagination">
          <span>Showing {(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, rows.length)} of {rows.length.toLocaleString()} findings</span>
          <div className="pagination-controls">
            <button disabled={currentPage === 1} onClick={() => setPage(p => Math.max(p - 1, 1))}>← Previous</button>
            <span>Page {currentPage} of {totalPages}</span>
            <button disabled={currentPage >= totalPages} onClick={() => setPage(p => Math.min(p + 1, totalPages))}>Next →</button>
          </div>
        </div>
      )}
    </div>
  )
}

function InternalLinkFindingDrawer({
  finding,
  onClose,
  onInspectInlinks,
  onCreateTask,
}: {
  finding: Finding
  onClose: () => void
  onInspectInlinks: () => void
  onCreateTask: () => void
}) {
  const [showAllLinks, setShowAllLinks] = useState(false)
  const links = finding.links || []
  const displayedLinks = showAllLinks ? links : links.slice(0, 10)
  const actions = suggestedActions(finding)
  const nonLinkEvidence = Object.entries(finding.evidence || {}).filter(
    ([key, value]) => key !== 'links' && value !== null && value !== undefined && value !== '',
  )

  return (
    <div className="overlay" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
      <aside className="drawer page-detail-drawer internal-link-finding-drawer" aria-label="Internal linking issue details">
        <button className="close" onClick={onClose} aria-label="Close issue details">×</button>
        <p className="eyebrow">INTERNAL LINKING ISSUE</p>
        <h2>{finding.label}</h2>
        {finding.url ? (
          <a href={finding.url} target="_blank" rel="noreferrer">
            {finding.url} ↗
          </a>
        ) : (
          <span className="muted-cell">Project-level finding</span>
        )}

        <section className="issue-context-card">
          <span>{finding.category}</span>
          <strong>Issue Summary</strong>
          <p>{finding.detail}</p>
          <div className="finding-drawer-badges">
            <span className={`priority-pill ${finding.priority}`}>{finding.priority}</span>
            <span className={`solution-stage ${finding.status}`}>{finding.status.replaceAll('_', ' ')}</span>
            {finding.affected_link_count ? (
              <span className="count-chip">{finding.affected_link_count.toLocaleString()} link{finding.affected_link_count === 1 ? '' : 's'} affected</span>
            ) : null}
          </div>
        </section>

        {/* Structured Affected Links Table / Cards */}
        {links.length > 0 && (
          <div className="detail-section affected-links-section">
            <div className="affected-links-header">
              <h3>Affected Internal Links ({finding.affected_link_count || links.length})</h3>
              <p>Individual links causing or affected by this issue. Click any URL to inspect.</p>
            </div>
            <div className="affected-links-list">
              {displayedLinks.map((link, idx) => {
                const sc = link.status_code
                const scClass = sc && sc >= 400 ? 'status-pill error' : sc && sc >= 300 ? 'status-pill redirect' : 'status-pill ok'
                return (
                  <article key={idx} className="affected-link-row">
                    <div className="affected-link-urls">
                      <div>
                        <span className="link-label">Source page:</span>
                        <a href={link.source_url} target="_blank" rel="noreferrer" title={link.source_url}>
                          {shortUrl(link.source_url)} ↗
                        </a>
                      </div>
                      <div>
                        <span className="link-label">Destination target:</span>
                        <a href={link.destination_url} target="_blank" rel="noreferrer" title={link.destination_url}>
                          {shortUrl(link.destination_url)} ↗
                        </a>
                      </div>
                    </div>
                    <dl className="affected-link-meta">
                      {sc !== undefined && (
                        <div>
                          <dt>HTTP Status</dt>
                          <dd><span className={scClass}>{sc}</span></dd>
                        </div>
                      )}
                      {link.indexability && (
                        <div>
                          <dt>Indexability</dt>
                          <dd>{link.indexability_status || link.indexability}</dd>
                        </div>
                      )}
                      {link.canonical_url && (
                        <div>
                          <dt>Canonical URL</dt>
                          <dd>
                            <span title={link.canonical_url}>{shortUrl(link.canonical_url)}</span>
                            {link.canonical_status && <small> ({link.canonical_status})</small>}
                          </dd>
                        </div>
                      )}
                      <div>
                        <dt>Anchor Text</dt>
                        <dd>{link.anchor || link.alt_text || <span className="muted-cell">Empty / No text</span>}</dd>
                      </div>
                      <div>
                        <dt>Link Position</dt>
                        <dd>{link.link_position || 'Content'}{link.follow ? ` · ${link.follow}` : ''}</dd>
                      </div>
                    </dl>
                  </article>
                )
              })}
            </div>
            {links.length > 10 && !showAllLinks && (
              <button type="button" className="text-button show-more-links" onClick={() => setShowAllLinks(true)}>
                Show all {links.length} affected links ↓
              </button>
            )}
          </div>
        )}

        <div className="detail-section">
          <h3>Current Data</h3>
          <p>The main metric uses mapped Screaming Frog Inlinks when supplied, otherwise it falls back to the latest imported relationship count.</p>
          <dl>
            <div>
              <dt>Internal Inlinks</dt>
              <dd>{metric(finding.internal_inlinks)}</dd>
            </div>
            <div>
              <dt>Metric source</dt>
              <dd>{inlinksSourceLabel(finding.internal_inlinks_source)}</dd>
            </div>
            <div>
              <dt>Unique linking pages</dt>
              <dd>{metric(finding.unique_sources)}</dd>
            </div>
            <div>
              <dt>Crawl Depth</dt>
              <dd>{metric(finding.crawl_depth)}</dd>
            </div>
            <div>
              <dt>Page type</dt>
              <dd>{finding.page_type || 'N/A'}</dd>
            </div>
            <div>
              <dt>Indexability</dt>
              <dd>{finding.indexability || 'N/A'}</dd>
            </div>
            <div>
              <dt>Status Code</dt>
              <dd>{metric(finding.page_status_code)}</dd>
            </div>
            <div>
              <dt>Snapshot coverage</dt>
              <dd>{finding.snapshot_complete ? 'Complete snapshot' : 'Partial snapshot'}</dd>
            </div>
          </dl>
        </div>

        {nonLinkEvidence.length > 0 && (
          <div className="detail-section">
            <h3>Detection Evidence</h3>
            <p>Additional imported values supporting this finding.</p>
            <dl>
              {nonLinkEvidence.map(([key, value]) => (
                <div key={key}>
                  <dt>{key.replaceAll('_', ' ')}</dt>
                  <dd>{evidenceValue(value)}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        <div className="detail-section recommendation-section">
          <h3>Recommended Solution</h3>
          <p>{finding.recommendation || 'Data not available'}</p>
        </div>

        <div className="detail-section">
          <h3>Suggested Actions</h3>
          <ul className="finding-action-list">
            {actions.map(action => (
              <li key={action}>{action}</li>
            ))}
          </ul>
        </div>

        <div className="drawer-actions">
          <a className="secondary button" href={`/issues?source=site_architecture&search=${encodeURIComponent(finding.type)}`}>
            {finding.solution_count ? `Open solution log (${finding.solution_count})` : 'Open solution'}
          </a>
          {finding.page_id && (
            <button className="secondary" onClick={onInspectInlinks}>
              Inspect incoming links
            </button>
          )}
          <button className="primary" onClick={onCreateTask}>
            Create task
          </button>
        </div>
      </aside>
    </div>
  )
}

function suggestedActions(finding: Finding) {
  const actions: Record<string, string[]> = {
    broken_internal_link: [
      'Replace or remove the broken destination link across all affected source pages.',
      'Re-crawl the affected source URLs and confirm the destination returns the intended successful response.',
    ],
    redirecting_internal_link: [
      'Update the source links to point directly to the final canonical destination.',
      'Verify the final URL is indexable and canonical before updating.',
    ],
    link_to_3xx: [
      'Update source links to point directly to the final redirect destination.',
      'Confirm the final destination returns HTTP 200 OK and is indexable.',
    ],
    link_to_4xx: [
      'Replace or remove all source links pointing to this error destination.',
      'Restore or redirect the destination URL if it represents valid content.',
    ],
    empty_anchor: [
      'Add concise anchor text or image alt text that explains the destination.',
      'Check the rendered link in its page context before publishing.',
    ],
    generic_anchor: [
      'Replace generic wording with descriptive, natural anchor text.',
      'Avoid forcing exact-match keywords where they do not help users.',
    ],
    link_to_non_indexable: [
      'Confirm whether the non-indexable destination is intentional.',
      'If not intentional, link to the appropriate indexable canonical page.',
    ],
    link_to_non_canonical: [
      'Update links to point directly to the canonical target URL.',
      'Confirm whether the canonical directive on the destination page is correct.',
    ],
    potential_orphan_page: [
      'Verify that the supplied Inlinks export is complete.',
      'Add useful contextual or navigational links from relevant PDP or PLP pages, then confirm them in a new crawl.',
    ],
    weakly_linked_page: [
      'Identify authoritative, contextually relevant source pages.',
      'Add useful links and compare link occurrences and unique sources in the next complete snapshot.',
    ],
    deep_important_page: [
      'Review the page hierarchy and approved parent relationship.',
      'Add relevant links from shallower pages where they improve navigation.',
    ],
    internal_link_opportunity: [
      'Review the proposed source and anchor against the page content.',
      'Implement only links that are useful and contextually appropriate.',
    ],
  }
  return [
    ...(actions[finding.type] || [
      'Review the supporting evidence and affected URLs.',
      'Implement the recommended change where it is appropriate for users and site structure.',
    ]),
    'Record the decision in the solution log and verify the result with a later complete crawl.',
  ]
}

function metric(value: unknown) {
  return value === null || value === undefined || value === '' ? 'N/A' : String(value)
}

function inlinksSourceLabel(value: Finding['internal_inlinks_source']) {
  return value === 'screaming_frog'
    ? 'Screaming Frog Internal crawl'
    : value === 'calculated_relationships'
      ? 'Calculated from imported Inlinks relationships'
      : 'N/A'
}

function evidenceValue(value: unknown) {
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'None'
  if (typeof value === 'object' && value !== null) return JSON.stringify(value)
  return metric(value)
}

export function PageIncomingLinksDrawer({ project, pageId, url, onClose }: { project: Project; pageId: string; url?: string; onClose: () => void }) {
  const [data, setData] = useState<InlinkEvidence>()
  const [error, setError] = useState('')
  useEffect(() => {
    api<InlinkEvidence>(`/api/projects/${project.id}/architecture/internal-links/pages/${pageId}`)
      .then(setData)
      .catch(err => setError(err.message))
  }, [project.id, pageId])
  return (
    <div className="overlay" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
      <aside className="drawer incoming-links-drawer">
        <button className="close" onClick={onClose}>×</button>
        <p className="eyebrow">OBSERVED INTERNAL LINKS</p>
        <h2>{url ? shortUrl(url) : 'Incoming links'}</h2>
        <p>{data ? `${data.count.toLocaleString()} occurrences from ${data.unique_sources.toLocaleString()} unique source pages` : 'Loading evidence…'}</p>
        {error && <div className="error-box">{error}</div>}
        <div className="incoming-link-list">
          {data?.inlinks.map(link => (
            <article key={link.id}>
              <a href={link.source_url} target="_blank" rel="noreferrer">
                {shortUrl(link.source_url)} ↗
              </a>
              <strong>{link.anchor || link.alt_text || 'No anchor or alt text'}</strong>
              <small>
                {link.link_position || 'Position unknown'} · {link.link_origin || 'Origin unknown'} · {link.follow || 'Follow state unknown'}
                {link.rel ? ` · ${link.rel}` : ''}
              </small>
            </article>
          ))}
        </div>
        {data && !data.inlinks.length && (
          <div className="mini-empty">
            <p>No incoming links were observed for this page in the latest snapshot.</p>
          </div>
        )}
      </aside>
    </div>
  )
}

function shortUrl(value: string) {
  try {
    const url = new URL(value)
    return `${url.pathname}${url.search}` || '/'
  } catch {
    return value
  }
}
