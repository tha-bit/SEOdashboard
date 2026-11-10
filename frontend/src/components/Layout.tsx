import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import type { Project } from '../types'
import { Icon } from './Icons'

export function Layout({projects, activeProject, onProject, onNewProject, children}:{projects:Project[]; activeProject?:Project; onProject:(id:string)=>void; onNewProject:()=>void; children:React.ReactNode}) {
  const beforeKeywords = [['/','Dashboard','grid'],['/projects','Projects','folder'],['/pages','Pages','pages'],['/architecture','Site Architecture','tree'],['/on-page','On-Page SEO','edit']] as const
  const keywordNav = [['/keywords','Keyword Research','search'],['/keyword-groups','Keyword Groups','folder'],['/page-mapping','Page Mapping','pages'],['/cannibalization','Cannibalization','alert']] as const
  const afterKeywords = [['/issues','Issues','alert'],['/imports','Imports','upload'],['/settings','Settings','settings']] as const
  const location=useLocation()
  const [collapsed,setCollapsed]=useState(()=>{try{return localStorage.getItem('page-mapper:sidebar-collapsed')==='true'}catch{return false}})
  const [keywordOpen,setKeywordOpen]=useState(()=>{try{return localStorage.getItem('page-mapper:keyword-nav-open')!=='false'}catch{return true}})
  const keywordActive=keywordNav.some(([to])=>location.pathname===to)
  useEffect(()=>{try{localStorage.setItem('page-mapper:sidebar-collapsed',String(collapsed))}catch{/* The toggle still works for this session. */}},[collapsed])
  useEffect(()=>{try{localStorage.setItem('page-mapper:keyword-nav-open',String(keywordOpen))}catch{/* The dropdown still works for this session. */}},[keywordOpen])
  useEffect(()=>{if(keywordActive)setKeywordOpen(true)},[keywordActive])
  function keywordToggle(){if(collapsed){setCollapsed(false);setKeywordOpen(true)}else setKeywordOpen(value=>!value)}
  const links=(items:typeof beforeKeywords|typeof afterKeywords)=>items.map(([to,label,icon])=><NavLink key={to} to={to} end={to==='/' } title={collapsed?label:undefined}><Icon name={icon}/><span className="nav-label">{label}</span></NavLink>)
  return <div className={`app-shell ${collapsed?'sidebar-collapsed':''}`}>
    <aside className="sidebar">
      <button className="sidebar-toggle" type="button" onClick={()=>setCollapsed(value=>!value)} aria-label={collapsed?'Expand sidebar':'Collapse sidebar'} title={collapsed?'Expand sidebar':'Collapse sidebar'}>{collapsed?'›':'‹'}</button>
      <div className="brand"><div className="brand-mark">S</div><div className="brand-copy"><strong>SEO Data</strong><span>Workspace</span></div></div>
      <nav aria-label="Primary">{links(beforeKeywords)}<div className={`keyword-nav-group ${keywordOpen?'open':''} ${keywordActive?'active':''}`}><button className="keyword-nav-toggle" type="button" onClick={keywordToggle} aria-expanded={!collapsed&&keywordOpen} title={collapsed?'Keyword':undefined}><Icon name="search"/><span className="nav-label">Keyword</span><span className="keyword-nav-chevron" aria-hidden="true">⌄</span></button>{keywordOpen&&!collapsed&&<div className="keyword-nav-submenu">{keywordNav.map(([to,label,icon])=><NavLink key={to} to={to}><Icon name={icon}/><span>{label}</span></NavLink>)}</div>}</div>{links(afterKeywords)}</nav>
      <div className="local-note" title={collapsed?'Local workspace':undefined}><span className="status-dot"/><span className="local-label">Local workspace</span></div>
    </aside>
    <div className="main-wrap">
      <header className="topbar"><div className="project-switcher"><Icon name="folder"/><label><span>Active project</span><select value={activeProject?.id||''} onChange={e=>onProject(e.target.value)}><option value="" disabled>{projects.length?'Select a project':'No active projects'}</option>{projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label><button className="new-project" onClick={onNewProject} title="Create project" aria-label="Create project"><Icon name="plus"/></button></div><div className="site-chip">{activeProject?.site_url.replace(/^https?:\/\//,'') || 'Open Projects to restore one'}</div></header>
      <main>{children}</main>
    </div>
  </div>
}
