import { useRef, useState } from 'react'
import { api } from '../api'
import type { Project } from '../types'
import { Icon } from './Icons'

export function ProjectBundleUpload({onImported}:{onImported:(project:Project)=>void}){
  const input=useRef<HTMLInputElement>(null);const [busy,setBusy]=useState(false),[error,setError]=useState('')
  async function upload(file?:File){if(!file)return;setBusy(true);setError('');const form=new FormData();form.append('file',file);try{const response=await fetch('/api/projects/import',{method:'POST',body:form});if(!response.ok){const body=await response.json();throw new Error(body.detail||'Project import failed')}onImported(await response.json() as Project)}catch(err){setError((err as Error).message)}finally{setBusy(false);if(input.current)input.current.value=''}}
  return <div className="bundle-upload"><input ref={input} type="file" accept=".json,.seo-project.json,application/json" onChange={e=>upload(e.target.files?.[0])}/><button type="button" className="secondary" disabled={busy} onClick={()=>input.current?.click()}><Icon name="upload"/>{busy?'Restoring project…':'Upload project bundle'}</button>{error&&<div className="error-box">{error}</div>}</div>
}

export function DeleteProjectModal({project,onClose,onDeleted}:{project:Project;onClose:()=>void;onDeleted:(id:string)=>void}){
  const [confirmation,setConfirmation]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('')
  async function remove(){setBusy(true);setError('');try{await api(`/api/projects/${project.id}?confirm_name=${encodeURIComponent(confirmation)}`,{method:'DELETE'});onDeleted(project.id)}catch(err){setError((err as Error).message);setBusy(false)}}
  return <div className="overlay"><div className="modal delete-modal"><button type="button" className="close" onClick={onClose}>×</button><p className="eyebrow danger-text">PERMANENT DELETION</p><h2>Delete “{project.name}”?</h2><p>This permanently removes the project, its pages, imports, raw audit rows, and future project-scoped records. Download a project bundle first if you may need it again.</p><a className="secondary button" href={`/api/projects/${project.id}/export`}><Icon name="download"/>Download project first</a><label>Type <strong>{project.name}</strong> to confirm<input autoFocus value={confirmation} onChange={e=>setConfirmation(e.target.value)} autoComplete="off"/></label>{error&&<div className="error-box">{error}</div>}<div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Cancel</button><button type="button" className="danger-button" disabled={busy||confirmation!==project.name} onClick={remove}>{busy?'Deleting…':'Permanently delete project'}</button></div></div></div>
}
