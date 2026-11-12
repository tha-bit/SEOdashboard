import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { DashboardData, Project } from '../types'
import { Icon } from '../components/Icons'

export function Dashboard({project}:{project:Project}){
  const [data,setData]=useState<DashboardData>(); const [error,setError]=useState('')
  useEffect(()=>{setData(undefined);api<DashboardData>(`/api/projects/${project.id}/dashboard`).then(setData).catch(e=>setError(e.message))},[project.id])
  if(error)return <div className="error-box">{error}</div>
  if(!data)return <div className="loading-panel"><div className="spinner"/>Calculating inventory…</div>
  const hasOrganicPerformance=[data.organic_sessions,data.organic_clicks,data.organic_impressions,data.average_position].some(value=>value!==null)
  return <div className="page dashboard dashboard-overview"><div className="page-heading"><div><p className="eyebrow">SEO OVERVIEW</p><h1>{project.name}</h1><p>The essential health and organic search signals available in this workspace.</p></div><Link className="primary button" to="/imports"><Icon name="upload"/>Import data</Link></div>
    <section className="dashboard-health-grid" aria-label="Website SEO health">
      <Link className="dashboard-health-card" to="/pages"><span>Total pages</span><strong>{data.total_pages.toLocaleString()}</strong><small>Live pages in the current inventory</small><b>View pages →</b></Link>
      {data.indexability_observed_pages>0&&<Link className="dashboard-health-card indexability-card" to="/pages"><span>Indexability</span><div className="indexability-values"><div><strong>{data.indexable_pages.toLocaleString()}</strong><small>Indexable</small></div><div><strong>{data.non_indexable_pages.toLocaleString()}</strong><small>Non-indexable</small></div></div>{data.indexability_observed_pages<data.total_pages&&<em>{(data.total_pages-data.indexability_observed_pages).toLocaleString()} without indexability evidence</em>}<b>Review inventory →</b></Link>}
      {data.total_pages>0&&<Link className={`dashboard-health-card issue-card ${data.critical_issue_count>0?'has-critical':'is-clear'}`} to="/issues"><span>Critical SEO issues</span><strong>{data.critical_issue_count.toLocaleString()}</strong><small>{data.critical_issue_count>0?`${data.critical_architecture_issues} architecture · ${data.critical_on_page_issues} on-page`:'No critical issues detected in stored evidence'}</small><b>Open issues →</b></Link>}
      {data.unique_keywords>0&&<Link className="dashboard-health-card" to="/keywords"><span>Keyword performance</span><strong>{data.unique_keywords.toLocaleString()}</strong><small>Tracked keywords · {data.keyword_quick_wins.toLocaleString()} quick wins</small><b>Review keywords →</b></Link>}
    </section>
    {data.total_pages===0&&<Empty/>}
    {hasOrganicPerformance?<section className="panel dashboard-performance"><header><div><p className="eyebrow">ORGANIC PERFORMANCE</p><h2>Latest imported search signals</h2><p>Only metrics supplied by the latest relevant GA4 or GSC import are shown.</p></div><Link to="/keywords">Explore performance →</Link></header><div className="performance-metrics">
      {data.organic_sessions!==null&&<PerformanceMetric label="Organic sessions" value={formatMetric(data.organic_sessions)} source="GA4" period={dateRange(data.ga4_period_start,data.ga4_period_end)}/>}
      {data.organic_clicks!==null&&<PerformanceMetric label="Organic clicks" value={formatMetric(data.organic_clicks)} source="GSC" period={dateRange(data.gsc_period_start,data.gsc_period_end)}/>}
      {data.organic_impressions!==null&&<PerformanceMetric label="Organic impressions" value={formatMetric(data.organic_impressions)} source="GSC" period={dateRange(data.gsc_period_start,data.gsc_period_end)}/>}
      {data.average_position!==null&&<PerformanceMetric label="Average position" value={data.average_position.toFixed(1)} source="GSC" period={dateRange(data.gsc_period_start,data.gsc_period_end)}/>}
    </div></section>:<section className="dashboard-data-note"><div><Icon name="grid"/><span><strong>Organic performance data is not available yet</strong><small>Import GA4 with an Organic channel value or GSC performance data to add these metrics.</small></span></div><Link to="/imports">Import performance data →</Link></section>}
  </div>
}
function PerformanceMetric({label,value,source,period}:{label:string;value:string;source:string;period:string}){return <Link className="performance-metric-card" to="/keywords"><span>{label}</span><strong>{value}</strong><small>{source}{period?` · ${period}`:''}</small><b>Explore performance →</b></Link>}
function formatMetric(value:number){return value.toLocaleString(undefined,{maximumFractionDigits:1})}
function dateRange(start:string|null,end:string|null){if(!start&&!end)return ''; const format=(value:string)=>new Date(`${value}T00:00:00`).toLocaleDateString(undefined,{month:'short',year:'numeric'}); if(start&&end)return start===end?format(start):`${format(start)}–${format(end)}`; return format((start||end)!)}
function Empty(){return <section className="panel dashboard-empty"><div className="empty-icon"><Icon name="pages"/></div><div><h2>No pages in this project yet</h2><p>Import a Screaming Frog export or a URL list to begin building this overview.</p></div><Link className="secondary button" to="/imports">Import pages</Link></section>}
