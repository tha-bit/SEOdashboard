import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { patchJson } from '../api'
import type { Project } from '../types'
import { Icon } from '../components/Icons'
import { DeleteProjectModal, ProjectBundleUpload } from '../components/ProjectManagement'

export function Projects({projects,activeId,onSelect,onNew,onChanged}:{projects:Project[];activeId?:string;onSelect:(id:string)=>void;onNew:()=>void;onChanged:(preferredId?:string)=>void}){
  const [deleting,setDeleting]=useState<Project>(),[status,setStatus]=useState('All');const navigate=useNavigate()
  const visible=projects.filter(project=>status==='All'||(status==='Archived'?project.archived:!project.archived))
  async function toggleArchive(project:Project){const restored=project.archived;await patchJson<Project>(`/api/projects/${project.id}`,{archived:!project.archived});onChanged(restored?project.id:undefined)}
  function openProject(project:Project){if(project.archived)return;onSelect(project.id);navigate('/')}
  return <div className="page projects-page"><div className="page-heading compact"><div><p className="eyebrow">WORKSPACES</p><h1>Projects</h1><p>Manage active and archived site inventories in one place.</p></div><div className="actions"><ProjectBundleUpload onImported={project=>onChanged(project.id)}/><button className="primary" onClick={onNew}><Icon name="plus"/>New project</button></div></div>
    <section className="project-summary"><article><strong>{projects.filter(p=>!p.archived).length}</strong><span>Active</span></article><article><strong>{projects.filter(p=>p.archived).length}</strong><span>Archived</span></article><article><strong>{projects.length}</strong><span>Total projects</span></article></section>
    <div className="tabs" role="tablist">{['All','Active','Archived'].map(item=><button role="tab" aria-selected={status===item} className={status===item?'active':''} onClick={()=>setStatus(item)} key={item}>{item}</button>)}</div>
    <section className="project-list">{visible.length===0?<div className="panel empty small-empty"><h3>No {status.toLowerCase()} projects</h3><p>Projects you archive will remain available here.</p></div>:visible.map(project=><article className={`project-card ${project.archived?'archived':''}`} key={project.id}><div className="project-initial">{project.name.slice(0,1).toUpperCase()}</div><div className="project-info"><div><h2>{project.name}</h2><span className={`project-state ${project.archived?'archived':''}`}>{project.archived?'Archived':'Active'}</span>{project.id===activeId&&<span className="current-state">Current</span>}</div><p>{project.site_url}</p><small>{[project.locale,project.market].filter(Boolean).join(' · ')||'No locale or market'} · Created {new Date(project.created_at).toLocaleDateString()}</small></div><div className="project-actions">{!project.archived&&<button className="secondary" onClick={()=>openProject(project)}>Open</button>}<a className="secondary button" href={`/api/projects/${project.id}/export`}><Icon name="download"/>Download</a><button className="secondary" onClick={()=>toggleArchive(project)}>{project.archived?'Restore':'Archive'}</button><button className="danger-outline" onClick={()=>setDeleting(project)}>Delete</button></div></article>)}</section>
    {deleting&&<DeleteProjectModal project={deleting} onClose={()=>setDeleting(undefined)} onDeleted={()=>{setDeleting(undefined);onChanged()}}/>}
  </div>
}
