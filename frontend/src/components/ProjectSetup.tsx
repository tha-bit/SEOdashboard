import { useState } from 'react'
import { postJson } from '../api'
import type { Project } from '../types'

export function ProjectSetup({onCreated}:{onCreated:(project:Project)=>void}) {
  const [name,setName]=useState(''); const [site,setSite]=useState('https://'); const [locale,setLocale]=useState('en-GB'); const [error,setError]=useState(''); const [busy,setBusy]=useState(false)
  async function submit(e:React.FormEvent){e.preventDefault();setBusy(true);setError('');try{onCreated(await postJson<Project>('/api/projects',{name,site_url:site,locale}))}catch(err){setError((err as Error).message)}finally{setBusy(false)}}
  return <div className="setup-screen"><div className="setup-card"><div className="brand-mark large">S</div><p className="eyebrow">SEO DATA WORKSPACE</p><h1>Create your first project</h1><p>Set the site boundary for your page inventory. Everything stays in a local SQLite database on this machine.</p><form onSubmit={submit}><label>Project name<input autoFocus required value={name} onChange={e=>setName(e.target.value)} placeholder="Spring catalogue audit"/></label><label>Site URL<input required type="url" value={site} onChange={e=>setSite(e.target.value)} placeholder="https://example.com"/></label><label>Locale <span className="optional">Optional</span><input value={locale} onChange={e=>setLocale(e.target.value)} placeholder="en-GB"/></label>{error&&<div className="error-box">{error}</div>}<button className="primary full" disabled={busy}>{busy?'Creating…':'Create project'}</button></form></div></div>
}

