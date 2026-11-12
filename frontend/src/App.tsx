import { useEffect, useState } from 'react'
import { Link, Route, Routes } from 'react-router-dom'
import { api, postJson } from './api'
import type { Project } from './types'
import { Layout } from './components/Layout'
import { ProjectSetup } from './components/ProjectSetup'
import { Dashboard } from './pages/Dashboard'
import { Pages } from './pages/Pages'
import { Imports } from './pages/Imports'
import { Settings } from './pages/Settings'
import { Projects } from './pages/Projects'
import { SiteArchitecture } from './pages/SiteArchitecture'
import { Issues } from './pages/Issues'
import { OnPageSEO } from './pages/OnPageSEO'
import { KeywordResearch } from './pages/KeywordResearch'
import { SavedKeywords } from './pages/SavedKeywords'
import { KeywordStrategy } from './pages/KeywordStrategy'
import { ActivityProgress } from './pages/ActivityProgress'

export default function App(){
  const [projects,setProjects]=useState<Project[]>([]); const [activeId,setActiveId]=useState(localStorage.getItem('seo-project')||''); const [loading,setLoading]=useState(true); const [error,setError]=useState(''); const [showNew,setShowNew]=useState(false)
  async function refreshProjects(preferredId?:string){const items=await api<Project[]>('/api/projects?include_archived=true');setProjects(items);const active=items.filter(p=>!p.archived);const wanted=preferredId||activeId;if(!active.some(p=>p.id===wanted))setActiveId(active[0]?.id||'')}
  useEffect(()=>{refreshProjects().catch(e=>setError(e.message)).finally(()=>setLoading(false))},[])
  useEffect(()=>{if(activeId)localStorage.setItem('seo-project',activeId)},[activeId])
  if(loading)return <div className="center-state"><div className="spinner"/>Opening local workspace…</div>
  if(error)return <div className="center-state error-box">Could not connect to the local API: {error}</div>
  if(!projects.length)return <ProjectSetup onCreated={p=>{setProjects([p]);setActiveId(p.id)}}/>
  const activeProjects=projects.filter(p=>!p.archived);const project=activeProjects.find(p=>p.id===activeId)||activeProjects[0]
  function updateProject(updated:Project){setProjects(items=>items.map(p=>p.id===updated.id?updated:p));if(updated.archived&&updated.id===activeId){const next=activeProjects.find(p=>p.id!==updated.id);setActiveId(next?.id||'')}}
  const unavailable=<NoActiveProject/>
  return <Layout projects={activeProjects} activeProject={project} onProject={setActiveId} onNewProject={()=>setShowNew(true)}><Routes><Route path="/" element={project?<Dashboard project={project}/>:unavailable}/><Route path="/projects" element={<Projects projects={projects} activeId={project?.id} onSelect={setActiveId} onNew={()=>setShowNew(true)} onChanged={()=>refreshProjects()}/>}/><Route path="/pages" element={project?<Pages project={project}/>:unavailable}/><Route path="/architecture" element={project?<SiteArchitecture project={project}/>:unavailable}/><Route path="/on-page" element={project?<OnPageSEO project={project}/>:unavailable}/><Route path="/keywords" element={project?<KeywordResearch project={project}/>:unavailable}/><Route path="/saved-keywords" element={project?<SavedKeywords project={project}/>:unavailable}/><Route path="/keyword-groups" element={project?<KeywordStrategy project={project} view="groups"/>:unavailable}/><Route path="/page-mapping" element={project?<KeywordStrategy project={project} view="mapping"/>:unavailable}/><Route path="/cannibalization" element={project?<KeywordStrategy project={project} view="cannibalization"/>:unavailable}/><Route path="/activity" element={project?<ActivityProgress project={project}/>:unavailable}/><Route path="/issues" element={project?<Issues project={project}/>:unavailable}/><Route path="/imports" element={project?<Imports project={project}/>:unavailable}/><Route path="/settings" element={project?<Settings project={project} onChange={updateProject} onProjectsChanged={(preferred)=>refreshProjects(preferred)}/>:unavailable}/></Routes>{showNew&&<NewProject onClose={()=>setShowNew(false)} onCreated={p=>{setProjects(items=>[...items,p]);setActiveId(p.id);setShowNew(false)}}/>}</Layout>
}

function NoActiveProject(){return <div className="page"><div className="panel empty"><div className="empty-icon">A</div><h3>No active project selected</h3><p>Open Projects to restore an archived project, upload a project bundle, or create a new project.</p><Link className="primary button" to="/projects">Open Projects</Link></div></div>}

function NewProject({onClose,onCreated}:{onClose:()=>void;onCreated:(p:Project)=>void}){const [name,setName]=useState(''),[site,setSite]=useState('https://'),[locale,setLocale]=useState('en-GB'),[market,setMarket]=useState(''),[error,setError]=useState('');async function submit(e:React.FormEvent){e.preventDefault();try{onCreated(await postJson<Project>('/api/projects',{name,site_url:site,locale,market:market||null}))}catch(err){setError((err as Error).message)}}return <div className="overlay"><form className="modal" onSubmit={submit}><button type="button" className="close" onClick={onClose}>×</button><p className="eyebrow">NEW PROJECT</p><h2>Create another site workspace</h2><label>Project name<input autoFocus required value={name} onChange={e=>setName(e.target.value)} placeholder="UK store audit"/></label><label>Site URL<input type="url" required value={site} onChange={e=>setSite(e.target.value)}/></label><div className="two-col"><label>Locale<input value={locale} onChange={e=>setLocale(e.target.value)} placeholder="en-GB"/></label><label>Market<input value={market} onChange={e=>setMarket(e.target.value)} placeholder="United Kingdom"/></label></div>{error&&<div className="error-box">{error}</div>}<div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Cancel</button><button className="primary">Create project</button></div></form></div>}
