import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, patchJson, postJson } from '../api'
import { Icon } from '../components/Icons'
import { PageDetailsDrawer } from '../components/PageDetailsDrawer'
import { CheckboxFilter } from '../components/CheckboxFilter'
import { SummaryActionCard } from '../components/SummaryActionCard'
import { PAGE_TYPES, type IssuePriority, type OnPageDetail, type Project } from '../types'
import { downloadCsv } from '../csv'

type IssueSource='all'|'site_architecture'|'on_page'
type IssueSeverity='error'|'warning'|'info'
type IssueView='issues'|'solutions'|'priorities'
type SolutionStage='proposed'|'ignored'|'in_progress'|'implemented'|'verified'
type IssueSolution={id:string;project_id:string;page_id?:string;issue_key:string;source:Exclude<IssueSource,'all'>;issue_type:string;issue_label:string;workflow_status:SolutionStage;action:string;summary:string;owner?:string;target_date?:string;verification_notes?:string;issue_snapshot:Record<string,unknown>;data:Record<string,unknown>;created_at:string}
type UnifiedIssue={issue_key:string;source:Exclude<IssueSource,'all'>;source_label:string;source_severity:string;category:string;severity:IssueSeverity;priority:IssuePriority;status:string;type:string;page_id?:string;url?:string;label:string;detail:string;solution_count:number;latest_solution?:IssueSolution;recommendation?:string;recommended_solution?:string;page_type?:string;content_type?:string;http_status?:number|string;http_status_text?:string;indexability?:string;indexability_status?:string;canonical_url?:string;canonical_status?:string;redirect_uri?:string;redirect_type?:string;sitemap_included?:boolean|null;in_imported_sitemap?:boolean;imported_sitemap_occurrences?:number;sitemap_name?:string;source_url?:string;destination_url?:string;anchor?:string;link_position?:string;affected_link_count?:number;evidence?:Record<string,unknown>}
type PrioritySetting={source:Exclude<IssueSource,'all'>;type:string;label:string;category:string;default_priority:IssuePriority;priority:IssuePriority;customized:boolean;detected_count:number;disabled:boolean}
type OnPageEvidence={current:Record<string,unknown>;field_states:Record<string,string>;last_observed_at?:string}

const categoryOrder=['Broken & Invalid Links','Orphan & Weakly Linked Pages','Architecture & Crawl Depth','Anchor Text Issues','Indexability & Canonical Conflicts','Internal Linking Opportunities','Link Distribution & Structural Patterns','Technical SEO','Sitemap','Hierarchy','Page classification','Inventory evidence','Content metadata','Canonical & robots','Hreflang','Metadata evidence']
const categoryNotes:Record<string,string>={'Broken & Invalid Links':'Observed internal links to errors, redirects, or invalid destinations','Orphan & Weakly Linked Pages':'Potential orphans and pages with limited unique linking sources','Architecture & Crawl Depth':'Observed link coverage compared with crawl depth and approved hierarchy','Anchor Text Issues':'Missing, generic, or inconsistent link labels found in imported evidence','Indexability & Canonical Conflicts':'Observed links whose destinations require indexing or canonical review','Internal Linking Opportunities':'Evidence-led proposals for important pages with weak link support','Link Distribution & Structural Patterns':'Unusual volume, repetition, position, or origin patterns','Technical SEO':'HTTP responses, redirects, canonical conflicts, and indexability signals',Sitemap:'Eligibility, imported XML, and proposed sitemap membership',Hierarchy:'Approved parents, orphans, depth, and parent proposals','Page classification':'Pages that need a reliable type before structural review','Inventory evidence':'Imported architecture observations that need verification','Content metadata':'H1, title, and description evidence that needs review','Canonical & robots':'Canonical targets, robots directives, and indexability conflicts',Hreflang:'Language codes, targets, self-references, and reciprocal evidence','Metadata evidence':'Expected on-page fields that were not supplied by an import'}
const sourceTabs:{value:IssueSource;label:string}[]=[{value:'all',label:'All sources'},{value:'site_architecture',label:'Site Architecture'},{value:'on_page',label:'On-Page SEO'}]
const stageLabels:Record<SolutionStage,string>={proposed:'Proposed',ignored:'Ignored',in_progress:'In progress',implemented:'Implemented',verified:'Verified'}
const actionLabels:Record<string,string>={sitemap_change:'Sitemap change',hierarchy_change:'Hierarchy / parent change',classification_change:'Page classification',response_remediation:'URL / response remediation',sitemap_evidence:'Sitemap evidence update',content_update:'Content metadata update',canonical_robots_update:'Canonical / robots update',hreflang_update:'Hreflang update',technical_review:'Technical review',other:'Other solution'}
const priorityOptions=[{value:'critical',label:'Critical'},{value:'high',label:'High'},{value:'medium',label:'Medium'},{value:'low',label:'Low'}]

function shortRoute(url:string){try{return new URL(url).pathname||'/'}catch{return url}}
function sourceRoute(issue:UnifiedIssue){if(issue.source==='on_page')return '/on-page?view=issues';return issue.issue_key.startsWith('architecture:internal_link:')?'/architecture?view=internal-links':'/architecture?view=issues'}
function readable(value:string){return value.replaceAll('_',' ').replace(/^./,letter=>letter.toUpperCase())}
function formatDate(value:string){return new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short'}).format(new Date(value))}
function issueFromSolution(item:IssueSolution):UnifiedIssue{const snapshot=item.issue_snapshot;return {issue_key:item.issue_key,source:item.source,source_label:String(snapshot.source_label||(item.source==='on_page'?'On-Page SEO':'Site Architecture')),source_severity:String(snapshot.source_severity||'info'),category:String(snapshot.category||'Metadata evidence'),severity:(snapshot.severity as IssueSeverity)||'info',priority:(snapshot.priority as UnifiedIssue['priority'])||'low',status:String(snapshot.status||'historical'),type:item.issue_type,page_id:item.page_id,url:snapshot.url?String(snapshot.url):undefined,label:item.issue_label,detail:String(snapshot.detail||'Historical issue retained through its solution log.'),solution_count:1,latest_solution:item}}

export function Issues({project}:{project:Project}){
  const [searchParams]=useSearchParams()
  const filterToolbar=useRef<HTMLDivElement>(null)
  const requestedSource=searchParams.get('source')
  const initialSource:IssueSource=requestedSource==='site_architecture'||requestedSource==='on_page'?requestedSource:'all'
  const [issues,setIssues]=useState<UnifiedIssue[]>([]),[solutions,setSolutions]=useState<IssueSolution[]>([]),[prioritySettings,setPrioritySettings]=useState<PrioritySetting[]>([]),[view,setView]=useState<IssueView>('issues'),[source,setSource]=useState<IssueSource>(initialSource),[selectedCategories,setSelectedCategories]=useState<string[]>([]),[selectedPriorities,setSelectedPriorities]=useState<string[]>([]),[selectedStages,setSelectedStages]=useState<string[]>([]),[search,setSearch]=useState(searchParams.get('search')||''),[selectedIssue,setSelectedIssue]=useState<UnifiedIssue>(),[selectedPage,setSelectedPage]=useState<UnifiedIssue>(),[loading,setLoading]=useState(true),[error,setError]=useState(''),[refresh,setRefresh]=useState(0)
  useEffect(()=>{setLoading(true);setError('');Promise.all([api<UnifiedIssue[]>(`/api/projects/${project.id}/issues`),api<IssueSolution[]>(`/api/projects/${project.id}/issue-solutions`),api<PrioritySetting[]>(`/api/projects/${project.id}/issues/priority-settings`)]).then(([issueRows,solutionRows,settings])=>{setIssues(issueRows);setSolutions(solutionRows);setPrioritySettings(settings)}).catch(err=>setError(err.message)).finally(()=>setLoading(false))},[project.id,refresh])
  const sourceIssues=useMemo(()=>issues.filter(issue=>source==='all'||issue.source===source),[issues,source])
  const sourceSolutions=useMemo(()=>solutions.filter(item=>source==='all'||item.source===source),[solutions,source])
  const orderedCategories=useMemo(()=>{const discovered=[...new Set(sourceIssues.map(issue=>issue.category))].filter(name=>!categoryOrder.includes(name)).sort();return [...categoryOrder,...discovered]},[sourceIssues])
  const categories=useMemo(()=>orderedCategories.filter(name=>sourceIssues.some(issue=>issue.category===name)),[sourceIssues,orderedCategories])
  const visibleIssues=useMemo(()=>sourceIssues.filter(issue=>(!selectedCategories.length||selectedCategories.includes(issue.category))&&(!selectedPriorities.length||selectedPriorities.includes(issue.priority))&&(!search||`${issue.source_label} ${issue.category} ${issue.label} ${issue.type} ${issue.url||''} ${issue.detail} ${issue.latest_solution?.summary||''}`.toLowerCase().includes(search.toLowerCase()))),[sourceIssues,selectedCategories,selectedPriorities,search])
  const visibleSolutions=useMemo(()=>sourceSolutions.filter(item=>(!selectedStages.length||selectedStages.includes(item.workflow_status))&&(!search||`${item.issue_label} ${item.issue_type} ${item.summary} ${item.owner||''} ${(item.issue_snapshot.url as string)||''}`.toLowerCase().includes(search.toLowerCase()))),[sourceSolutions,selectedStages,search])
  const grouped=useMemo(()=>orderedCategories.map(name=>({name,issues:visibleIssues.filter(issue=>issue.category===name)})).filter(group=>group.issues.length),[visibleIssues,orderedCategories])
  const count=(value:IssuePriority)=>sourceIssues.filter(issue=>issue.priority===value).length
  function changeSource(value:IssueSource){setSource(value);setSelectedCategories([])}
  function filterPriority(value:IssuePriority){setView('issues');setSelectedCategories([]);setSearch('');setSelectedPriorities(current=>current.length===1&&current[0]===value?[]:[value])}
  function keepOnePickerOpen(event:React.SyntheticEvent<HTMLDetailsElement>){if(!event.currentTarget.open)return;filterToolbar.current?.querySelectorAll<HTMLDetailsElement>('details[open]').forEach(item=>{if(item!==event.currentTarget)item.removeAttribute('open')})}
  function saved(){setSelectedIssue(undefined);setRefresh(value=>value+1)}
  async function changePriority(issue:UnifiedIssue,priority:string){try{await patchJson(`/api/projects/${project.id}/issues/${encodeURIComponent(issue.issue_key)}/priority`,{priority:priority==='automatic'?null:priority});setRefresh(value=>value+1)}catch(err){setError((err as Error).message)}}
  async function createTask(issue:UnifiedIssue){try{const result=await postJson<{duplicate?:boolean}>(`/api/projects/${project.id}/task-manager/tasks`,{title:issue.label,description:issue.detail,category:issue.category,priority:issue.priority,status:'to_do',related_urls:issue.url?[issue.url]:[],supporting_links:[],source_issue_key:issue.issue_key,source_issue_type:issue.type,source_section:issue.source,source_url:issue.url||null});window.alert(result.duplicate?'An open task is already linked to this issue.':'Task added to Task Manager.')}catch(err){setError((err as Error).message)}}
  function allIssuesExportUrl(){const params=new URLSearchParams();if(source!=='all')params.set('source',source);if(search.trim())params.set('search',search.trim());selectedCategories.forEach(item=>params.append('categories',item));selectedPriorities.forEach(item=>params.append('priorities',item));return `/api/projects/${project.id}/issues.csv?${params}`}
  return <div className="page issues-page"><div className="page-heading compact"><div><p className="eyebrow">CENTRAL REVIEW & SOLUTION LOG</p><h1>Issues</h1><p>Review findings, record source-specific solutions, and retain implementation evidence for reporting.</p></div><div className="actions"><a className="secondary button" href={`/api/projects/${project.id}/issue-solutions.csv`}><Icon name="download"/>Solution log CSV</a><a className="primary button" href={allIssuesExportUrl()}><Icon name="download"/>Issues CSV</a></div></div>
    <div className="tabs issue-view-tabs" role="tablist"><button role="tab" aria-selected={view==='issues'} className={view==='issues'?'active':''} onClick={()=>setView('issues')}>Current issues <span>{issues.length.toLocaleString()}</span></button><button role="tab" aria-selected={view==='solutions'} className={view==='solutions'?'active':''} onClick={()=>setView('solutions')}>Solution log <span>{solutions.length.toLocaleString()}</span></button><button role="tab" aria-selected={view==='priorities'} className={view==='priorities'?'active':''} onClick={()=>setView('priorities')}>Priority Management <span>{prioritySettings.length.toLocaleString()}</span></button></div>
    <div className="tabs issue-source-tabs" role="tablist">{sourceTabs.map(tab=>{const items=view==='issues'?issues:view==='solutions'?solutions:prioritySettings;const tabCount=items.filter(item=>tab.value==='all'||item.source===tab.value).length;return <button key={tab.value} role="tab" aria-selected={source===tab.value} className={source===tab.value?'active':''} onClick={()=>changeSource(tab.value)}>{tab.label}<span>{tabCount.toLocaleString()}</span></button>})}</div>
    {view==='issues'?<><section className="metric-grid issue-metrics"><SummaryActionCard label="Critical" value={count('critical').toLocaleString()} detail="Immediate attention recommended" action={selectedPriorities.length===1&&selectedPriorities[0]==='critical'?'Clear filter':'Show critical'} active={selectedPriorities.length===1&&selectedPriorities[0]==='critical'} attention={count('critical')>0} onClick={()=>filterPriority('critical')}/><SummaryActionCard label="High" value={count('high').toLocaleString()} detail="High-impact review items" action={selectedPriorities.length===1&&selectedPriorities[0]==='high'?'Clear filter':'Show high'} active={selectedPriorities.length===1&&selectedPriorities[0]==='high'} attention={count('high')>0} onClick={()=>filterPriority('high')}/><SummaryActionCard label="Medium" value={count('medium').toLocaleString()} detail="Planned review work" action={selectedPriorities.length===1&&selectedPriorities[0]==='medium'?'Clear filter':'Show medium'} active={selectedPriorities.length===1&&selectedPriorities[0]==='medium'} onClick={()=>filterPriority('medium')}/><SummaryActionCard label="Low" value={count('low').toLocaleString()} detail="Lower-impact observations" action={selectedPriorities.length===1&&selectedPriorities[0]==='low'?'Clear filter':'Show low'} active={selectedPriorities.length===1&&selectedPriorities[0]==='low'} onClick={()=>filterPriority('low')}/></section>
      <section className="panel issues-catalog"><div ref={filterToolbar} className="architecture-toolbar issues-filter-toolbar"><div className="search"><Icon name="search"/><input value={search} onChange={event=>setSearch(event.target.value)} placeholder="Search issues, URLs, or solutions"/></div><CheckboxFilter label="Category" options={categories.map(item=>({value:item,label:item}))} values={selectedCategories} onChange={setSelectedCategories} onToggle={keepOnePickerOpen}/><CheckboxFilter label="Priority" options={priorityOptions} values={selectedPriorities} onChange={setSelectedPriorities} onToggle={keepOnePickerOpen}/><span>{visibleIssues.length.toLocaleString()} affected entries</span></div>
        {error&&<div className="error-box">{error}</div>}{loading?<div className="loading-panel"><div className="spinner"/>Loading issues…</div>:grouped.length?<div className="issue-category-list">{grouped.map(group=><IssueCategory key={group.name} category={group.name} issues={group.issues} onSolution={setSelectedIssue} onPage={setSelectedPage} onPriority={changePriority} onTask={createTask}/>)}</div>:<div className="empty small-empty"><h3>No matching issues</h3><p>The current source and filters have no review items.</p></div>}
      </section></>:view==='solutions'?<SolutionLog items={visibleSolutions} loading={loading} error={error} search={search} setSearch={setSearch} stages={selectedStages} setStages={setSelectedStages} onFollowUp={item=>setSelectedIssue(issueFromSolution(item))} onPage={item=>setSelectedPage(issueFromSolution(item))}/>:<PriorityManagement key={source} project={project} items={prioritySettings.filter(item=>source==='all'||item.source===source)} loading={loading} error={error} onChanged={()=>setRefresh(value=>value+1)}/>}
    {selectedIssue&&<SolutionDrawer project={project} issue={selectedIssue} history={solutions.filter(item=>item.source===selectedIssue.source&&item.issue_key===selectedIssue.issue_key)} onClose={()=>setSelectedIssue(undefined)} onSaved={saved} onPage={()=>{setSelectedIssue(undefined);setSelectedPage(selectedIssue)}}/>}
    {selectedPage?.page_id&&<PageDetailsDrawer project={project} pageId={selectedPage.page_id} context={{label:selectedPage.label,detail:selectedPage.detail,source:selectedPage.source_label}} onClose={()=>setSelectedPage(undefined)}/>}
  </div>
}

function IssueCategory({category,issues,onSolution,onPage,onPriority,onTask}:{category:string;issues:UnifiedIssue[];onSolution:(issue:UnifiedIssue)=>void;onPage:(issue:UnifiedIssue)=>void;onPriority:(issue:UnifiedIssue,priority:string)=>void;onTask:(issue:UnifiedIssue)=>void}){
  const groups=useMemo(()=>{const map=new Map<string,{label:string;severity:IssueSeverity;source:UnifiedIssue['source'];sourceLabel:string;sourceSeverity:string;items:UnifiedIssue[]}>();const order={error:0,warning:1,info:2};for(const issue of issues){const key=`${issue.source}:${issue.type}`;const current=map.get(key);if(current)current.items.push(issue);else map.set(key,{label:issue.label,severity:issue.severity,source:issue.source,sourceLabel:issue.source_label,sourceSeverity:issue.source_severity,items:[issue]})}return [...map.entries()].sort((a,b)=>order[a[1].severity]-order[b[1].severity]||b[1].items.length-a[1].items.length)},[issues])
  function download(label:string,items:UnifiedIssue[]){
    const isStatus = category === 'Technical SEO' || items.some(i => i.type.startsWith('http_') || i.type.startsWith('redirect_'))
    const isSitemapOrCanonical = category === 'Sitemap' || category === 'Canonical & robots' || items.some(i => i.type.startsWith('sitemap_') || i.type.startsWith('canonical_') || i.type.startsWith('robots_'))
    const isInternalLink = category.includes('Links') || category.includes('Linking') || items.some(i => Boolean(i.source_url || i.destination_url || i.anchor || (i.evidence && 'source_url' in i.evidence)))

    const rows = items.map(issue => {
      const ev = issue.evidence || {}
      if (isInternalLink) {
        return {
          'Source URL': issue.source_url || (ev.source_url as string) || '',
          'Destination URL': issue.destination_url || (ev.destination_url as string) || issue.url || '',
          'HTTP Status Code': issue.http_status ?? (ev.status_code as number) ?? '',
          'Anchor Text': issue.anchor || (ev.anchor as string) || '',
          'Link Position': issue.link_position || (ev.link_position as string) || '',
          'Indexability': issue.indexability || '',
          'Canonical Status': issue.canonical_status || '',
          'Canonical URL': issue.canonical_url || '',
          'Page Type': issue.page_type || '',
          'Affected Link Count': issue.affected_link_count ?? (ev.affected_link_count as number) ?? '',
          'Issue': issue.label,
          'Priority': issue.priority,
          'Status': issue.status,
          'Detail': issue.detail,
          'Recommendation': issue.recommendation || issue.recommended_solution || '',
        }
      }
      if (isStatus) {
        return {
          'Affected URL': issue.url || '',
          'HTTP Status Code': issue.http_status ?? '',
          'Status': issue.http_status_text || '',
          'Content Type': issue.content_type || '',
          'Page Type': issue.page_type || '',
          'Redirect Destination': issue.redirect_uri || '',
          'Redirect Type': issue.redirect_type || '',
          'Issue': issue.label,
          'Priority': issue.priority,
          'Workflow Status': issue.status,
          'Detail': issue.detail,
          'Recommendation': issue.recommendation || issue.recommended_solution || '',
        }
      }
      if (isSitemapOrCanonical) {
        return {
          'Affected URL': issue.url || '',
          'Sitemap URL or Name': issue.sitemap_name || (issue.sitemap_included === true ? 'Proposed Sitemap' : issue.in_imported_sitemap ? 'Imported Sitemap' : ''),
          'Indexability': issue.indexability || '',
          'Indexability Status': issue.indexability_status || '',
          'Canonical URL': issue.canonical_url || '',
          'Canonical Status': issue.canonical_status || '',
          'Content Type': issue.content_type || '',
          'Page Type': issue.page_type || '',
          'Proposed Sitemap': issue.sitemap_included === true ? 'Included' : issue.sitemap_included === false ? 'Excluded' : issue.page_type ? 'Unreviewed' : '',
          'Imported Sitemap Occurrences': issue.imported_sitemap_occurrences ?? '',
          'Issue': issue.label,
          'Priority': issue.priority,
          'Status': issue.status,
          'Detail': issue.detail,
          'Recommendation': issue.recommendation || issue.recommended_solution || '',
        }
      }
      return {
        'Affected URL': issue.url || '',
        'Issue': issue.label,
        'Category': issue.category,
        'Priority': issue.priority,
        'Status': issue.status,
        'Page Type': issue.page_type || '',
        'Content Type': issue.content_type || '',
        'HTTP Status Code': issue.http_status ?? '',
        'Indexability': issue.indexability || '',
        'Canonical URL': issue.canonical_url || '',
        'Detail': issue.detail,
        'Recommendation': issue.recommendation || issue.recommended_solution || '',
        'Solution Log Entries': issue.solution_count,
      }
    })
    downloadCsv(`${category}-${label}`, rows)
  }
  return <section className="issue-category">
    <header><div><p className="eyebrow">{category.toUpperCase()}</p><h2>{category}</h2><p>{categoryNotes[category]||'Issues grouped by source and rule.'}</p></div><span className="count-chip">{issues.length.toLocaleString()}</span></header>
    <div className="issue-groups">{groups.map(([key,group],index)=><IssueGroupCard
      key={key}
      groupKey={key}
      group={group}
      index={index}
      onDownload={()=>download(group.label,group.items)}
      onPage={onPage}
      onSolution={onSolution}
      onTask={onTask}
      onPriority={onPriority}
    />)}</div>
  </section>
}

function IssueGroupCard({
  groupKey,
  group,
  index,
  onDownload,
  onPage,
  onSolution,
  onTask,
  onPriority,
}: {
  groupKey: string
  group: { label: string; severity: IssueSeverity; source: UnifiedIssue['source']; sourceLabel: string; sourceSeverity: string; items: UnifiedIssue[] }
  index: number
  onDownload: () => void
  onPage: (issue: UnifiedIssue) => void
  onSolution: (issue: UnifiedIssue) => void
  onTask: (issue: UnifiedIssue) => void
  onPriority: (issue: UnifiedIssue, priority: string) => void
}) {
  const [visibleCount, setVisibleCount] = useState(50)
  const visibleItems = group.items.slice(0, visibleCount)

  return (
    <details className={`issue-group ${group.severity}`} open={index === 0}>
      <summary>
        <span className="severity-dot" />
        <div>
          <strong>{group.label}</strong>
          <small>
            <span className={`issue-source-badge ${group.source}`}>{group.sourceLabel}</span>
            {groupKey.split(':').slice(1).join(':').replaceAll('_', ' ')} · {group.sourceSeverity}
          </small>
        </div>
        <b>{group.items.length.toLocaleString()}</b>
        <span className="disclosure">⌄</span>
      </summary>
      <div className="issue-group-tools">
        <button className="secondary compact-button" onClick={onDownload}>
          <Icon name="download" />Download this issue CSV
        </button>
      </div>
      <div className="issue-pages">
        {visibleItems.map((issue, itemIndex) => (
          <article key={`${issue.issue_key}-${itemIndex}`}>
            <div>
              {issue.url && issue.page_id ? (
                <button className="issue-url-button" onClick={() => onPage(issue)}>
                  <strong>{shortRoute(issue.url)}</strong>
                  <small>{issue.url}</small>
                  <span>View page details →</span>
                </button>
              ) : (
                <strong>{issue.url ? shortRoute(issue.url) : 'Project-level issue'}</strong>
              )}
              {issue.url && !issue.page_id && <small>{issue.url}</small>}
              {issue.latest_solution && (
                <span className={`solution-stage ${issue.latest_solution.workflow_status}`}>
                  {stageLabels[issue.latest_solution.workflow_status]} · {issue.solution_count} log{issue.solution_count === 1 ? '' : 's'}
                </span>
              )}
            </div>
            <p>{issue.detail}</p>
            <div className="issue-item-actions">
              <button className="secondary compact-button" onClick={() => onSolution(issue)}>
                {issue.solution_count ? 'View / update solution' : 'View solution'}
              </button>
              <button className="secondary compact-button" onClick={() => onTask(issue)}>
                Create task
              </button>
              <label className="priority-control">
                Priority
                <select value={issue.priority} onChange={event => onPriority(issue, event.target.value)}>
                  <option value="critical">Critical</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                  <option value="automatic">Automatic</option>
                </select>
              </label>
              <Link className="issue-source-link" to={`/activity?issue_key=${encodeURIComponent(issue.issue_key)}`}>Activity →</Link>
              <Link className="issue-source-link" to={sourceRoute(issue)}>Open source →</Link>
            </div>
          </article>
        ))}
        {group.items.length > visibleCount && (
          <div className="issue-pages-more">
            <span>Showing {visibleCount} of {group.items.length.toLocaleString()} affected pages</span>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button className="secondary compact-button" onClick={() => setVisibleCount(c => c + 50)}>Show 50 more</button>
              <button className="secondary compact-button" onClick={() => setVisibleCount(group.items.length)}>Show all ({group.items.length})</button>
            </div>
          </div>
        )}
      </div>
    </details>
  )
}

function PriorityManagement({project,items,loading,error,onChanged}:{project:Project;items:PrioritySetting[];loading:boolean;error:string;onChanged:()=>void}){
  const toolbar=useRef<HTMLDivElement>(null)
  const [search,setSearch]=useState(''),[priorities,setPriorities]=useState<string[]>([]),[categories,setCategories]=useState<string[]>([]),[showDisabled,setShowDisabled]=useState(true),[saving,setSaving]=useState(''),[localError,setLocalError]=useState('')
  const categoryOptions=useMemo(()=>[...new Set(items.map(item=>item.category))].sort().map(value=>({value,label:value})),[items])
  const disabledCount=useMemo(()=>items.filter(item=>item.disabled).length,[items])
  const visible=useMemo(()=>items.filter(item=>{
    if(!showDisabled&&item.disabled)return false
    return (!priorities.length||priorities.includes(item.priority))&&(!categories.length||categories.includes(item.category))&&(!search||`${item.label} ${item.type} ${item.category} ${item.source}`.toLowerCase().includes(search.toLowerCase()))
  }),[items,priorities,categories,search,showDisabled])
  function keepOneOpen(event:React.SyntheticEvent<HTMLDetailsElement>){if(!event.currentTarget.open)return;toolbar.current?.querySelectorAll<HTMLDetailsElement>('details[open]').forEach(item=>{if(item!==event.currentTarget)item.removeAttribute('open')})}
  async function update(item:PrioritySetting,priority:string|null){setSaving(`${item.source}:${item.type}`);setLocalError('');try{await patchJson(`/api/projects/${project.id}/issues/priority-settings/${item.source}/${encodeURIComponent(item.type)}`,{priority});onChanged()}catch(err){setLocalError((err as Error).message)}finally{setSaving('')}}
  async function toggleDisabled(item:PrioritySetting){setSaving(`${item.source}:${item.type}`);setLocalError('');try{await patchJson(`/api/projects/${project.id}/issues/priority-settings/${item.source}/${encodeURIComponent(item.type)}`,{disabled:!item.disabled});onChanged()}catch(err){setLocalError((err as Error).message)}finally{setSaving('')}}
  async function resetAll(){if(!window.confirm('Restore every issue type to its built-in default priority? Page-specific priority overrides and historical records will be preserved.'))return;setSaving('all');setLocalError('');try{await api(`/api/projects/${project.id}/issues/priority-settings`,{method:'DELETE'});onChanged()}catch(err){setLocalError((err as Error).message)}finally{setSaving('')}}
  return <section className="panel priority-management"><div className="panel-title"><div><h2>Priority Management</h2><p>Configure project-wide defaults and enable or disable individual issue types. Disabled issue types are excluded from detection while preserving history.</p></div><button className="secondary" disabled={Boolean(saving)} onClick={resetAll}>Restore all defaults</button></div><div ref={toolbar} className="architecture-toolbar issues-filter-toolbar priority-management-toolbar"><div className="search"><Icon name="search"/><input value={search} onChange={event=>setSearch(event.target.value)} placeholder="Search issue types"/></div><CheckboxFilter label="Priority" options={priorityOptions} values={priorities} onChange={setPriorities} onToggle={keepOneOpen}/><CheckboxFilter label="Category" options={categoryOptions} values={categories} onChange={setCategories} onToggle={keepOneOpen}/><label className="inline-toggle"><input type="checkbox" checked={showDisabled} onChange={event=>setShowDisabled(event.target.checked)}/><span>Show disabled ({disabledCount})</span></label><span>{visible.length.toLocaleString()} issue types</span></div>{(error||localError)&&<div className="error-box">{localError||error}</div>}{loading?<div className="loading-panel"><div className="spinner"/>Loading priority settings…</div>:<div className="table-scroll priority-settings-table"><table><thead><tr><th>Issue type</th><th>Source</th><th>Category</th><th>Current default</th><th>Detected</th><th>Status</th><th>Actions</th></tr></thead><tbody>{visible.map(item=>{const key=`${item.source}:${item.type}`,busy=saving===key;return <tr key={key} className={item.disabled?'disabled-issue-row':''}><td><strong>{item.label}</strong><small>{item.type.replaceAll('_',' ')}</small></td><td><span className={`issue-source-badge ${item.source}`}>{item.source==='on_page'?'On-Page SEO':'Site Architecture'}</span></td><td>{item.category}</td><td><select className={`priority-select priority-${item.priority}`} value={item.priority} disabled={busy||item.disabled} onChange={event=>update(item,event.target.value)}>{priorityOptions.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select>{item.customized&&!item.disabled&&<small>Custom project default</small>}</td><td>{item.disabled?<span className="muted-cell">Disabled</span>:item.detected_count.toLocaleString()}</td><td><button className={`issue-toggle-btn ${item.disabled?'disabled':'enabled'}`} disabled={busy} onClick={()=>toggleDisabled(item)} title={item.disabled?'Click to enable this issue type':'Click to disable this issue type'}>{item.disabled?'Disabled':'Active'}</button></td><td><button className="text-button" disabled={!item.customized||busy||item.disabled} onClick={()=>update(item,null)}>Restore default</button></td></tr>})}</tbody></table></div>}</section>
}

function SolutionLog({items,loading,error,search,setSearch,stages,setStages,onFollowUp,onPage}:{items:IssueSolution[];loading:boolean;error:string;search:string;setSearch:(value:string)=>void;stages:string[];setStages:(values:string[])=>void;onFollowUp:(item:IssueSolution)=>void;onPage:(item:IssueSolution)=>void}){
  const filterToolbar=useRef<HTMLDivElement>(null)
  function keepOnePickerOpen(event:React.SyntheticEvent<HTMLDetailsElement>){if(!event.currentTarget.open)return;filterToolbar.current?.querySelectorAll<HTMLDetailsElement>('details[open]').forEach(item=>{if(item!==event.currentTarget)item.removeAttribute('open')})}
  return <section className="panel solution-log-panel"><div ref={filterToolbar} className="architecture-toolbar issues-filter-toolbar"><div className="search"><Icon name="search"/><input value={search} onChange={event=>setSearch(event.target.value)} placeholder="Search solution history"/></div><CheckboxFilter label="Workflow Stage" options={Object.entries(stageLabels).map(([value,label])=>({value,label}))} values={stages} onChange={setStages} onToggle={keepOnePickerOpen}/><span>{items.length.toLocaleString()} log entries</span></div>{error&&<div className="error-box">{error}</div>}{loading?<div className="loading-panel"><div className="spinner"/>Loading solution history…</div>:items.length?<div className="solution-log-list">{items.map(item=><article key={item.id}><header><div><span className={`issue-source-badge ${item.source}`}>{item.source==='on_page'?'On-Page SEO':'Site Architecture'}</span><span className={`solution-stage ${item.workflow_status}`}>{stageLabels[item.workflow_status]}</span></div><time>{formatDate(item.created_at)}</time></header><h2>{item.issue_label}</h2>{item.page_id&&item.issue_snapshot.url?<button className="issue-url-button compact" onClick={()=>onPage(item)}><span>{String(item.issue_snapshot.url)}</span><small>View page details →</small></button>:<span className="muted-cell">Project-level issue</span>}<p>{item.summary}</p><dl><div><dt>Action</dt><dd>{actionLabels[item.action]||readable(item.action)}</dd></div><div><dt>Owner</dt><dd>{item.owner||'Unassigned'}</dd></div><div><dt>Target</dt><dd>{item.target_date||'Not set'}</dd></div></dl>{item.verification_notes&&<div className="solution-verification"><strong>Verification</strong><p>{item.verification_notes}</p></div>}<details><summary>Recorded source-specific data</summary><SolutionData data={item.data}/></details><button className="secondary compact-button solution-follow-up" onClick={()=>onFollowUp(item)}>Add follow-up</button></article>)}</div>:<div className="empty small-empty"><h3>No solution history yet</h3><p>Add a solution from a current issue to begin the reporting log.</p></div>}</section>
}

function SolutionData({data}:{data:Record<string,unknown>}){const entries=Object.entries(data).filter(([,value])=>value!==''&&value!=null);return entries.length?<dl className="solution-data">{entries.map(([key,value])=><div key={key}><dt>{readable(key)}</dt><dd>{String(value)}</dd></div>)}</dl>:<p className="hint">No optional source fields were recorded.</p>}

function defaultAction(issue:UnifiedIssue){if(issue.source==='site_architecture'){if(issue.type.startsWith('sitemap_')||issue.type.includes('sitemap'))return 'sitemap_change';if(issue.type.includes('parent')||issue.type.includes('orphan')||issue.type.includes('circular'))return 'hierarchy_change';if(issue.type==='unknown_page_type')return 'classification_change';return 'response_remediation'}if(issue.type.startsWith('hreflang_'))return 'hreflang_update';if(issue.type.startsWith('canonical_')||issue.type.startsWith('robots_')||issue.type.startsWith('noindex_'))return 'canonical_robots_update';if(['h1','title','description'].some(value=>issue.type.includes(value)))return 'content_update';return 'technical_review'}

function recommendationData(data:Record<string,unknown>){
  const h1=Array.isArray(data.h1)?data.h1.join('\n'):String(data.h1||'')
  const hreflang=Array.isArray(data.hreflang)?data.hreflang.map(item=>{const row=item as Record<string,unknown>;return `${row.language||''}, ${row.target||''}`.trim()}).join('\n'):String(data.hreflang||'')
  return {recommended_h1:h1,recommended_title:String(data.title||''),recommended_meta_description:String(data.meta_description||''),recommended_canonical_url:String(data.canonical_url||''),recommended_robots:String(data.meta_robots||''),recommended_hreflang:hreflang}
}

function SolutionDrawer({project,issue,history,onClose,onSaved,onPage}:{project:Project;issue:UnifiedIssue;history:IssueSolution[];onClose:()=>void;onSaved:()=>void;onPage:()=>void}){
  const previousData=history[0]?.data||{}
  const [workflowStatus,setWorkflowStatus]=useState<SolutionStage>('proposed'),[action,setAction]=useState(defaultAction(issue)),[summary,setSummary]=useState(''),[owner,setOwner]=useState(''),[targetDate,setTargetDate]=useState(''),[verification,setVerification]=useState(''),[data,setData]=useState<Record<string,string>>(()=>Object.fromEntries(Object.entries(previousData).map(([key,value])=>[key,String(value??'')]))),[saving,setSaving]=useState(false),[error,setError]=useState(''),[pageDetail,setPageDetail]=useState<OnPageDetail>(),[evidenceError,setEvidenceError]=useState(''),[evidenceLoading,setEvidenceLoading]=useState(issue.source==='on_page'&&Boolean(issue.page_id))
  const setField=(key:string,value:string)=>setData(current=>({...current,[key]:value}))
  const actions=issue.source==='site_architecture'?[['sitemap_change','Sitemap change'],['hierarchy_change','Hierarchy / parent change'],['classification_change','Page classification'],['response_remediation','URL / response remediation'],['sitemap_evidence','Sitemap evidence update'],['other','Other solution']]:[['content_update','Content metadata update'],['canonical_robots_update','Canonical / robots update'],['hreflang_update','Hreflang update'],['technical_review','Technical review'],['other','Other solution']]
  useEffect(()=>{
    if(issue.source!=='on_page'||!issue.page_id)return
    setEvidenceLoading(true);setEvidenceError('')
    api<OnPageDetail>(`/api/projects/${project.id}/on-page/pages/${issue.page_id}`).then(detail=>{setPageDetail(detail);setData(current=>Object.values(current).some(Boolean)?current:{...current,...recommendationData(detail.recommendation?.data||{})})}).catch(err=>setEvidenceError(err.message)).finally(()=>setEvidenceLoading(false))
  },[project.id,issue.page_id,issue.source])
  const savedEvidence=history[0]?.issue_snapshot?.on_page_current as OnPageEvidence|undefined
  const evidence:OnPageEvidence|undefined=pageDetail?{current:pageDetail.current,field_states:pageDetail.field_states,last_observed_at:pageDetail.last_observed_at}:savedEvidence
  async function submit(event:React.FormEvent){event.preventDefault();setSaving(true);setError('');try{await postJson(`/api/projects/${project.id}/issue-solutions`,{issue_key:issue.issue_key,source:issue.source,workflow_status:workflowStatus,action,summary,owner:owner||null,target_date:targetDate||null,verification_notes:verification||null,data:Object.fromEntries(Object.entries(data).filter(([,value])=>value!==''))});onSaved()}catch(err){setError((err as Error).message)}finally{setSaving(false)}}
  return <div className="overlay"><aside className="drawer solution-drawer"><button className="close" onClick={onClose} aria-label="Close">×</button><p className="eyebrow">{issue.source_label.toUpperCase()} SOLUTION</p><h2>{issue.label}</h2>{issue.url&&issue.page_id?<button className="issue-url-button compact" onClick={onPage}><span>{issue.url}</span><small>View page details →</small></button>:issue.url&&<a href={issue.url} target="_blank" rel="noreferrer">{issue.url} ↗</a>}<p className="solution-issue-detail">{issue.detail}</p>
    <form onSubmit={submit}><div className="solution-form-grid"><label>Workflow stage<select value={workflowStatus} onChange={event=>setWorkflowStatus(event.target.value as SolutionStage)}>{Object.entries(stageLabels).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label>Solution type<select value={action} onChange={event=>setAction(event.target.value)}>{actions.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label>Owner<input value={owner} onChange={event=>setOwner(event.target.value)} placeholder="Person or team"/></label><label>Target date<input type="date" value={targetDate} onChange={event=>setTargetDate(event.target.value)}/></label></div><label>Solution summary<textarea required rows={4} value={summary} onChange={event=>setSummary(event.target.value)} placeholder="Describe the proposed or completed solution and why it addresses this issue."/></label>
      {issue.source==='site_architecture'?<ArchitectureSolutionFields data={data} setField={setField}/>:<OnPageSolutionFields issue={issue} evidence={evidence} loading={evidenceLoading} evidenceError={evidenceError} data={data} setField={setField}/>}<label>Verification and outcome notes<textarea rows={3} value={verification} onChange={event=>setVerification(event.target.value)} placeholder="Record QA evidence, crawl results, approvals, or remaining risks."/></label>{error&&<div className="error-box">{error}</div>}<div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Cancel</button><button className="primary" disabled={saving||!summary.trim()}>{saving?'Saving…':'Save log entry'}</button></div></form>
    <section className="detail-section solution-history"><h3>Solution history</h3><p>Entries are append-only so earlier decisions remain available for reporting.</p>{history.length?history.map(item=><article key={item.id}><header><span className={`solution-stage ${item.workflow_status}`}>{stageLabels[item.workflow_status]}</span><time>{formatDate(item.created_at)}</time></header><strong>{actionLabels[item.action]||readable(item.action)}</strong><p>{item.summary}</p><small>{item.owner||'Unassigned'}{item.target_date?` · target ${item.target_date}`:''}</small></article>):<p className="history-empty">No solution has been recorded for this issue.</p>}</section>
  </aside></div>
}

function ArchitectureSolutionFields({data,setField}:{data:Record<string,string>;setField:(key:string,value:string)=>void}){return <fieldset className="source-solution-fields"><legend>Architecture solution data</legend><p>Complete the fields relevant to this issue. These values are stored with the log entry, not applied automatically.</p><div className="solution-form-grid"><label>Proposed page type<select value={data.proposed_page_type||''} onChange={event=>setField('proposed_page_type',event.target.value)}><option value="">No classification change</option>{PAGE_TYPES.map(type=><option key={type}>{type}</option>)}</select></label><label>Sitemap decision<select value={data.sitemap_decision||''} onChange={event=>setField('sitemap_decision',event.target.value)}><option value="">No decision recorded</option><option value="include">Include</option><option value="exclude">Exclude</option><option value="review">Needs review</option></select></label><label>Proposed parent URL<input value={data.proposed_parent_url||''} onChange={event=>setField('proposed_parent_url',event.target.value)} placeholder="https://example.com/parent"/></label><label>Architecture section<input value={data.architecture_section||''} onChange={event=>setField('architecture_section',event.target.value)} placeholder="Section or directory"/></label><label>Expected status code<input inputMode="numeric" value={data.expected_status_code||''} onChange={event=>setField('expected_status_code',event.target.value)} placeholder="200"/></label><label>Expected indexability<select value={data.expected_indexability||''} onChange={event=>setField('expected_indexability',event.target.value)}><option value="">Not specified</option><option>Indexable</option><option>Non-Indexable</option></select></label></div><label>Architecture evidence<textarea rows={3} value={data.architecture_evidence||''} onChange={event=>setField('architecture_evidence',event.target.value)} placeholder="Parent rationale, sitemap source, redirect target, or structural evidence."/></label></fieldset>}

type ComparisonGroup={key:string;label:string;fields:string[];recommendation:string}
const allComparisonGroups:ComparisonGroup[]=[
  {key:'h1',label:'H1 headings',fields:['h1'],recommendation:'recommended_h1'},
  {key:'title',label:'Meta title',fields:['title'],recommendation:'recommended_title'},
  {key:'description',label:'Meta description',fields:['meta_description'],recommendation:'recommended_meta_description'},
  {key:'canonical',label:'Canonical',fields:['canonical_url'],recommendation:'recommended_canonical_url'},
  {key:'robots',label:'Robots directives',fields:['meta_robots','x_robots_tag'],recommendation:'recommended_robots'},
  {key:'hreflang',label:'Hreflang',fields:['hreflang'],recommendation:'recommended_hreflang'},
]

function relevantComparisonGroups(issue:UnifiedIssue){
  const type=issue.type
  if(type==='metadata_not_collected')return allComparisonGroups.filter(group=>['h1','title','description'].includes(group.key))
  if(type.includes('h1'))return allComparisonGroups.filter(group=>group.key==='h1')
  if(type.includes('title'))return allComparisonGroups.filter(group=>group.key==='title')
  if(type.includes('description'))return allComparisonGroups.filter(group=>group.key==='description')
  if(type.includes('canonical'))return allComparisonGroups.filter(group=>group.key==='canonical')
  if(type.includes('robots')||type.includes('noindex'))return allComparisonGroups.filter(group=>group.key==='robots')
  if(type.includes('hreflang'))return allComparisonGroups.filter(group=>group.key==='hreflang')
  return allComparisonGroups
}

function suggestedActions(issue:UnifiedIssue){
  if(issue.type==='multiple_h1')return ['Keep one primary H1 for the page.','Replace the primary H1 with the recommendation where appropriate.','Convert unnecessary H1s to H2s or another suitable heading level.']
  if(issue.type==='missing_h1')return ['Add one descriptive primary H1 that reflects the page topic and search intent.']
  if(issue.type.includes('title'))return [issue.type.startsWith('missing_')?'Add a descriptive, unique title.':'Replace or update the current title to address the identified issue.','Re-crawl the page and confirm the rendered title.']
  if(issue.type.includes('description'))return [issue.type.startsWith('missing_')?'Add a useful meta description.':'Replace or update the current description to address the identified issue.','Re-crawl the page and confirm the rendered description.']
  if(issue.type.includes('canonical'))return ['Update the canonical element only after confirming the preferred indexable URL.','Re-crawl and verify that the canonical resolves successfully.']
  if(issue.type.includes('robots')||issue.type.includes('noindex'))return ['Update the robots directive to match the intended indexing state.','Check both HTML meta robots and HTTP X-Robots-Tag evidence before implementation.']
  if(issue.type.includes('hreflang'))return ['Correct the affected language and target pair.','Validate self-references, reciprocal links, language codes, and indexable targets after deployment.']
  return ['Review the imported evidence, record the intended change, and verify it in a new crawl.']
}

function formatEvidenceValue(field:string,value:unknown){
  if(field==='hreflang'&&Array.isArray(value))return value.map(item=>{const row=item as Record<string,unknown>;return `${row.language||'(no language)'} → ${row.target||'(no target)'}`})
  if(Array.isArray(value))return value.map(item=>String(item))
  return [String(value??'')]
}

function CurrentEvidence({group,evidence,issue}:{group:ComparisonGroup;evidence?:OnPageEvidence;issue:UnifiedIssue}){
  if(!evidence)return <p className="comparison-unavailable">Data not available</p>
  const rows=group.fields.flatMap(field=>{
    const state=evidence.field_states?.[field]
    const value=evidence.current?.[field]
    if(state==='not_provided'||value===undefined)return [{field,value:'Data not available',unavailable:true}]
    if(state==='empty'||value===''||(Array.isArray(value)&&!value.length))return [{field,value:'Empty value collected',unavailable:false}]
    return formatEvidenceValue(field,value).map((item,index)=>({field,value:item,index,unavailable:false}))
  })
  const reported=issue.type==='multiple_h1'?Number(issue.detail.match(/contains (\d+) H1/)?.[1]||0):0
  const available=group.key==='h1'&&Array.isArray(evidence.current.h1)?evidence.current.h1.length:0
  return <><ul className={`current-evidence-list ${rows.length>1?'multiple':''}`}>{rows.map((row,index)=><li className={row.unavailable?'unavailable':''} key={`${row.field}-${index}`}><span>{row.field==='h1'?`H1-${index+1}`:row.field==='hreflang'?`Alternate ${index+1}`:readable(row.field)}</span><strong>{row.value}</strong></li>)}</ul>{reported>available&&<p className="evidence-subset-note">The issue reports {reported} H1 values, but only {available} {available===1?'is':'are'} available in the current snapshot. Only available values are shown.</p>}</>
}

function CopyButton({value}:{value:string}){
  const [copied,setCopied]=useState(false)
  async function copy(){
    if(!value)return
    try{await navigator.clipboard.writeText(value)}catch{const area=document.createElement('textarea');area.value=value;document.body.appendChild(area);area.select();document.execCommand('copy');area.remove()}
    setCopied(true);window.setTimeout(()=>setCopied(false),1400)
  }
  return <button type="button" className="copy-recommendation" disabled={!value} onClick={copy}>{copied?'Copied':'Copy'}</button>
}

function OnPageSolutionFields({issue,evidence,loading,evidenceError,data,setField}:{issue:UnifiedIssue;evidence?:OnPageEvidence;loading:boolean;evidenceError:string;data:Record<string,string>;setField:(key:string,value:string)=>void}){
  const groups=relevantComparisonGroups(issue)
  return <fieldset className="source-solution-fields on-page-solution-fields"><legend>On-page solution data</legend><p>Compare the latest imported page evidence with the issue and proposed optimisation. Recommendations remain editable and are not applied automatically.</p>
    <div className="on-page-comparison">
      <section className="comparison-column current"><header><span>1</span><div><strong>Current Data</strong><small>{evidence?.last_observed_at?`Latest evidence: ${formatDate(evidence.last_observed_at)}`:'Latest imported or crawled evidence'}</small></div></header>{loading?<p className="comparison-unavailable">Loading current page data…</p>:evidenceError&&!evidence?<p className="comparison-unavailable">Data not available</p>:groups.map(group=><article key={group.key}><h4>{group.label}</h4><CurrentEvidence group={group} evidence={evidence} issue={issue}/></article>)}</section>
      <section className="comparison-column identified"><header><span>2</span><div><strong>Identified Issue</strong><small>Why this page needs attention</small></div></header><article><h4>{issue.label}</h4><p>{issue.detail}</p><div className="suggested-action"><strong>Suggested action</strong><ul>{suggestedActions(issue).map(item=><li key={item}>{item}</li>)}</ul></div></article></section>
      <section className="comparison-column recommended"><header><span>3</span><div><strong>Recommended Solution</strong><small>Proposed values entered below</small></div></header>{groups.map(group=>{const value=data[group.recommendation]||'';return <article key={group.key}><div className="comparison-recommendation-heading"><h4>{group.label}</h4><CopyButton value={value}/></div>{value?<p className="recommended-preview">{value}</p>:<p className="comparison-unavailable">No recommendation entered yet</p>}</article>})}</section>
    </div>
    {evidenceError&&<p className="evidence-load-warning">Live evidence could not be refreshed: {evidenceError}{evidence?' Saved evidence from the latest solution is shown.':''}</p>}
    <div className="recommendation-editor-heading"><strong>Recommendation fields</strong><span>Enter only the values relevant to this issue.</span></div>
    <label><span className="recommendation-label">Recommended H1 <CopyButton value={data.recommended_h1||''}/></span><textarea rows={2} value={data.recommended_h1||''} onChange={event=>setField('recommended_h1',event.target.value)} placeholder="Recommended primary heading"/></label><label><span className="recommendation-label">Recommended title <small>{(data.recommended_title||'').length} characters</small><CopyButton value={data.recommended_title||''}/></span><input value={data.recommended_title||''} onChange={event=>{setField('recommended_title',event.target.value);setField('recommended_title_length',String(event.target.value.length))}} placeholder="Recommended title tag"/></label><label><span className="recommendation-label">Recommended meta description <small>{(data.recommended_meta_description||'').length} characters</small><CopyButton value={data.recommended_meta_description||''}/></span><textarea rows={3} value={data.recommended_meta_description||''} onChange={event=>{setField('recommended_meta_description',event.target.value);setField('recommended_description_length',String(event.target.value.length))}} placeholder="Recommended description"/></label><div className="solution-form-grid"><label><span className="recommendation-label">Canonical URL <CopyButton value={data.recommended_canonical_url||''}/></span><input value={data.recommended_canonical_url||''} onChange={event=>setField('recommended_canonical_url',event.target.value)} placeholder="https://example.com/canonical"/></label><label><span className="recommendation-label">Robots directive <CopyButton value={data.recommended_robots||''}/></span><input value={data.recommended_robots||''} onChange={event=>setField('recommended_robots',event.target.value)} placeholder="index, follow"/></label></div><label><span className="recommendation-label">Hreflang plan <CopyButton value={data.recommended_hreflang||''}/></span><textarea rows={3} value={data.recommended_hreflang||''} onChange={event=>setField('recommended_hreflang',event.target.value)} placeholder="One language and target URL per line"/></label><label>Expected validation metric or result<input value={data.expected_validation_result||''} onChange={event=>setField('expected_validation_result',event.target.value)} placeholder="For example: one H1, self-canonical, reciprocal hreflang"/></label>
  </fieldset>
}
