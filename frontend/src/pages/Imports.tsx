import { useEffect, useMemo, useState } from 'react'
import { api, postJson } from '../api'
import type { ImportBatch, Project } from '../types'
import { Icon } from '../components/Icons'

type HeaderRecognition={source_header:string;semantic_key:string|null;display_name:string|null;confidence:'exact'|'possible'|'unrecognized';matched_alias:string|null}
type SemanticField={key:string;label:string}
type StageResult={batch:ImportBatch;columns:string[];sample_rows:Record<string,unknown>[];suggested_mapping:Record<string,string>;detection:Record<string,string>;warnings:string[];header_recognition:HeaderRecognition[];semantic_fields:SemanticField[];requires_header_verification:boolean}

const SOURCE_FIELDS:Record<string,string[][]>={
  screaming_frog:[['address','URL *'],['http_status','HTTP status'],['indexability','Indexability'],['content_type','Content type'],['url_path','URL path'],['page_type','Page type']],
  url_list:[['address','URL *']],
  semrush:[['keyword','Keyword *'],['volume','Volume'],['keyword_difficulty','KD %'],['position','Position'],['intent','Intent'],['ranking_url','Ranking URL'],['serp_features','SERP features'],['market','Market / database'],['device','Device'],['snapshot_date','Snapshot date']],
  gsc:[['keyword','Query *'],['page_url','Page URL (query × page only)'],['clicks','Clicks'],['impressions','Impressions'],['ctr','CTR'],['average_position','Average position'],['search_type','Search type'],['country','Country'],['device','Device'],['period_start','Period start'],['period_end','Period end']],
  ga4:[['landing_page','Landing page / path *'],['sessions','Sessions'],['engaged_sessions','Engaged sessions'],['conversions','Conversions / key events'],['purchases','Purchases'],['revenue','Revenue'],['period_start','Period start'],['period_end','Period end'],['attribution_scope','Attribution / report scope'],['channel_filter','Channel filter']],
}

const CATEGORY_ORDER=['URL & response','Content & metadata','Headings','Canonicals & indexing','Links & architecture','International','Other columns']

function columnCategory(semanticKey:string|null,sourceHeader:string){
  const value=`${semanticKey||''} ${sourceHeader}`.toLowerCase()
  if(/hreflang|language|region/.test(value))return 'International'
  if(/canonical|robots|indexab|noindex/.test(value))return 'Canonicals & indexing'
  if(/\bh[1-6]\b|heading/.test(value))return 'Headings'
  if(/title|description|meta|word count|content/.test(value))return 'Content & metadata'
  if(/inlink|outlink|link score|crawl depth|folder|path/.test(value))return 'Links & architecture'
  if(/address|\burl\b|status|response|content type|mime|page type/.test(value))return 'URL & response'
  return 'Other columns'
}

export function Imports({project}:{project:Project}){
  const [imports,setImports]=useState<ImportBatch[]>([])
  const [file,setFile]=useState<File>()
  const [source,setSource]=useState('screaming_frog')
  const [reportingDate,setReportingDate]=useState('')
  const [stage,setStage]=useState<StageResult>()
  const [mapping,setMapping]=useState<Record<string,string>>({})
  const [strategy,setStrategy]=useState('update_observations')
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [report,setReport]=useState<ImportBatch>()
  const [reviewOpen,setReviewOpen]=useState(false)
  const [headersVerified,setHeadersVerified]=useState(false)
  const [columnSearch,setColumnSearch]=useState('')
  const load=()=>api<ImportBatch[]>(`/api/projects/${project.id}/imports`).then(setImports)
  useEffect(()=>{load();setStage(undefined);setReport(undefined)},[project.id])

  async function upload(){
    if(!file)return
    setBusy(true);setError('');setHeadersVerified(false);setColumnSearch('')
    const form=new FormData();form.append('file',file);form.append('source',source);if(reportingDate)form.append('reporting_date',reportingDate)
    try{
      const response=await fetch(`/api/projects/${project.id}/imports/stage`,{method:'POST',body:form})
      if(!response.ok){const result=await response.json();throw new Error(result.detail||'Upload failed')}
      const result=await response.json() as StageResult
      setStage(result);setMapping(result.suggested_mapping)
    }catch(caught){setError((caught as Error).message)}finally{setBusy(false)}
  }

  async function confirm(){
    if(!stage)return
    setBusy(true);setError('')
    try{
      const done=await postJson<ImportBatch>(`/api/projects/${project.id}/imports/${stage.batch.id}/confirm`,{mapping,duplicate_strategy:strategy,headers_verified:headersVerified})
      setReport(done);setStage(undefined);setFile(undefined);setReviewOpen(false);load()
    }catch(caught){setError((caught as Error).message);setReviewOpen(false)}finally{setBusy(false)}
  }

  function setHeaderMeaning(sourceHeader:string,semanticKey:string){
    setMapping(current=>{
      const next=Object.fromEntries(Object.entries(current).filter(([,header])=>header!==sourceHeader))
      if(semanticKey)next[semanticKey]=sourceHeader
      return next
    })
  }

  const requiredField=source==='ga4'?'landing_page':source==='semrush'||source==='gsc'?'keyword':'address'
  const performanceSource=['semrush','gsc','ga4'].includes(source)
  const mappedCount=Object.values(mapping).filter(Boolean).length

  return <div className="page imports-page">
    <div className="page-heading compact"><div><p className="eyebrow">SOURCE EVIDENCE</p><h1>Imports</h1><p>Bring URL evidence into a reviewable, auditable pipeline.</p></div></div>
    <div className="import-grid">
      <section className="panel import-flow">
        <div className="steps"><span className={!stage&&!report?'active':'done'}>1 <b>Upload</b></span><i/><span className={stage?'active':report?'done':''}>2 <b>Map & validate</b></span><i/><span className={report?'active':''}>3 <b>Report</b></span></div>
        {!stage&&!report&&<div className="upload-step"><div className="guidance"><strong>Uploaded evidence only</strong><p>Import Screaming Frog, Semrush, Google Search Console, GA4, or URL-list exports. Every source remains separate, dated and auditable; no live provider connection is used.</p></div><label>Source preset<select value={source} onChange={event=>setSource(event.target.value)}><option value="screaming_frog">Screaming Frog — inventory / metadata / hreflang</option><option value="url_list">Simple URL list</option><option value="semrush">Semrush — keywords and organic positions</option><option value="gsc">Google Search Console — query or query × page</option><option value="ga4">Google Analytics 4 — landing pages</option></select></label><label>Optional crawl / report date<input type="date" value={reportingDate} onChange={event=>setReportingDate(event.target.value)}/></label><label className={`dropzone ${file?'has-file':''}`}><input type="file" accept=".csv,.xlsx,.xlsm,text/csv" onChange={event=>setFile(event.target.files?.[0])}/><Icon name="upload"/><strong>{file?file.name:'Choose a CSV or XLSX file'}</strong><span>{file?`${(file.size/1024).toFixed(1)} KB — ready to preview`:'or drag it here · files remain on this machine'}</span></label>{error&&<div className="error-box">{error}</div>}<button className="primary" disabled={!file||busy} onClick={upload}>{busy?'Reading file…':'Preview and map columns'}</button></div>}
        {stage&&<div className="mapping-step"><div className="mapping-summary"><div><span>File</span><strong title={stage.batch.file_name}>{stage.batch.file_name}</strong></div><div><span>Rows staged</span><strong>{stage.batch.row_count.toLocaleString()}</strong></div><div><span>Detected</span><strong>{stage.detection.format?.toUpperCase()} {stage.detection.encoding}</strong></div></div>{stage.warnings.map(warning=><div className="warning-box" key={warning}>{warning}</div>)}<section className="import-mapping-section"><header><div><h2>Map source fields</h2><p>{performanceSource?'Map only dimensions and metrics genuinely present in the file. Missing values remain unknown, not zero.':'URL is required. All imported columns remain staged until final confirmation.'}</p></div><span>{mappedCount} mapped</span></header><div className="mapping-grid semantic-mapping-grid">{(SOURCE_FIELDS[source]||[]).map(([key,label])=><MappingField key={key} label={label} value={mapping[key]||''} columns={stage.columns} recognised={stage.suggested_mapping[key]===mapping[key]&&Boolean(mapping[key])} onChange={value=>setMapping(current=>({...current,[key]:value}))}/>)}</div></section>{stage.header_recognition.length>0&&<ColumnRecognitionPanel stage={stage} mapping={mapping} search={columnSearch} setSearch={setColumnSearch} onMeaning={setHeaderMeaning}/>}<section className="import-preview-section"><header><div><h2>Source preview</h2><p>Original imported names and sample values are shown exactly as supplied.</p></div><span>First {Math.min(stage.sample_rows.length,5)} rows</span></header><div className="preview-table"><table><thead><tr>{stage.columns.slice(0,8).map(column=><th key={column} title={column}>{column}</th>)}</tr></thead><tbody>{stage.sample_rows.slice(0,5).map((row,index)=><tr key={index}>{stage.columns.slice(0,8).map(column=><td key={column} title={String(row[column]??'')}>{String(row[column]??'')}</td>)}</tr>)}</tbody></table></div></section>{!performanceSource&&<label>When a URL identity already exists<select value={strategy} onChange={event=>setStrategy(event.target.value)}><option value="update_observations">Update imported observation fields (recommended)</option><option value="skip">Skip existing URL</option></select></label>}{error&&<div className="error-box">{error}</div>}<div className="flow-actions"><button className="secondary" onClick={()=>setStage(undefined)}>Back</button><button className="primary" disabled={!mapping[requiredField]||busy} onClick={()=>setReviewOpen(true)}>Review final import</button></div></div>}
        {report&&<div className="report-step"><div className={`report-icon ${report.error_count?'warning':''}`}>{report.error_count?'!':'✓'}</div><p className="eyebrow">IMPORT COMPLETE</p><h2>{report.file_name}</h2><p>{report.error_count?'The valid rows were committed. Invalid source rows remain available for audit.':'All valid rows were committed as a dated, non-destructive snapshot.'}</p><div className="report-metrics"><div><strong>{report.row_count}</strong><span>Source rows</span></div><div><strong>{report.imported_count}</strong><span>Imported / updated</span></div><div><strong>{report.skipped_count}</strong><span>Duplicates skipped</span></div><div><strong>{report.error_count}</strong><span>Errors</span></div></div><div className="flow-actions centered"><button className="secondary" onClick={()=>setReport(undefined)}>Import another file</button><a className="primary button" href={performanceSource?'/keywords':'/on-page'}>{performanceSource?'Review keyword performance':'Review on-page metadata'}</a></div></div>}
      </section><ImportHistory imports={imports}/>
    </div>
    {reviewOpen&&stage&&<div className="overlay"><div className="modal final-review"><button type="button" className="close" onClick={()=>setReviewOpen(false)}>×</button><p className="eyebrow">FINAL CONFIRMATION</p><h2>Import {stage.batch.row_count.toLocaleString()} source rows?</h2><p>No observations are added to the dashboard until you confirm. Original rows, mapping, dates and source semantics remain auditable.</p><dl><div><dt>Required identity</dt><dd>{mapping[requiredField]}</dd></div><div><dt>Mapped fields</dt><dd>{mappedCount}</dd></div><div><dt>Import behaviour</dt><dd>{performanceSource?'Append dated observations; preserve history':strategy==='skip'?'Skip existing URLs':'Update observations'}</dd></div></dl>{stage.requires_header_verification&&<label className="verification-check"><input type="checkbox" checked={headersVerified} onChange={event=>setHeadersVerified(event.target.checked)}/><span><strong>I reviewed the non-exact headers</strong><small>I verified or corrected the possible matches and accept unmapped columns as raw source data.</small></span></label>}{error&&<div className="error-box">{error}</div>}<div className="modal-actions"><button className="secondary" onClick={()=>setReviewOpen(false)}>Go back</button><button className="primary" disabled={busy||(stage.requires_header_verification&&!headersVerified)} onClick={confirm}>{busy?'Importing…':`Confirm and import ${stage.batch.row_count.toLocaleString()} rows`}</button></div></div></div>}
  </div>
}

function MappingField({label,value,columns,recognised,onChange}:{label:string;value:string;columns:string[];recognised:boolean;onChange:(value:string)=>void}){
  const required=label.endsWith('*')
  return <label className={`mapping-field-card ${value?'is-mapped':'is-unmapped'}`}><span className="mapping-field-heading"><strong>{label.replace(/ \*$/,'')}</strong><small className={recognised?'recognised':value?'selected':required?'required':''}>{recognised?'Recognised':value?'Selected':required?'Required':'Optional'}</small></span><select aria-label={`Map ${label}`} value={value} onChange={event=>onChange(event.target.value)}><option value="">Not mapped</option>{columns.map(column=><option key={column} value={column}>{column}</option>)}</select>{value&&<code title={value}>{value}</code>}</label>
}

function ColumnRecognitionPanel({stage,mapping,search,setSearch,onMeaning}:{stage:StageResult;mapping:Record<string,string>;search:string;setSearch:(value:string)=>void;onMeaning:(header:string,key:string)=>void}){
  const labels=useMemo(()=>Object.fromEntries(stage.semantic_fields.map(field=>[field.key,field.label])),[stage.semantic_fields])
  const filtered=useMemo(()=>stage.header_recognition.filter(item=>`${item.source_header} ${item.display_name||''} ${item.matched_alias||''} ${labels[item.semantic_key||'']||''}`.toLowerCase().includes(search.trim().toLowerCase())),[stage.header_recognition,labels,search])
  const groups=useMemo(()=>CATEGORY_ORDER.map(category=>({category,items:filtered.filter(item=>{const selected=Object.entries(mapping).find(([,header])=>header===item.source_header)?.[0]||item.semantic_key;return columnCategory(selected,item.source_header)===category})})).filter(group=>group.items.length),[filtered,mapping])
  const exact=stage.header_recognition.filter(item=>item.confidence==='exact').length
  const possible=stage.header_recognition.filter(item=>item.confidence==='possible').length
  const unknown=stage.header_recognition.filter(item=>item.confidence==='unrecognized').length
  return <section className="import-mapping-section recognition-workspace"><header><div><h2>Screaming Frog columns</h2><p>Human-readable meanings are shown alongside the original export headers. Verify possible or unrecognised columns before importing.</p></div><span>{stage.header_recognition.length} columns</span></header><div className="import-column-toolbar"><div className="import-column-search"><Icon name="search"/><input value={search} onChange={event=>setSearch(event.target.value)} placeholder="Search imported columns…" aria-label="Search imported columns"/></div><div className="recognition-summary"><span className="exact">{exact} exact</span><span className="possible">{possible} verify</span><span>{unknown} unrecognised</span></div></div>{groups.length?<div className="recognition-groups">{groups.map(group=><section key={group.category}><header><strong>{group.category}</strong><span>{group.items.length}</span></header><div className="recognition-card-grid">{group.items.map(item=>{const selected=Object.entries(mapping).find(([,header])=>header===item.source_header)?.[0]||'';return <article className={`recognition-card recognition-card-${item.confidence} ${selected?'is-selected':''}`} key={item.source_header}><div className="recognition-card-copy"><span className={`recognition recognition-${item.confidence}`}>{item.confidence==='exact'?'Exact':item.confidence==='possible'?'Verify':'Unrecognised'}</span><strong title={item.display_name||item.source_header}>{item.display_name||'Imported column'}</strong><code title={item.source_header}>{item.source_header}</code></div><label><span>Use as</span><select aria-label={`Meaning for ${item.source_header}`} value={selected} onChange={event=>onMeaning(item.source_header,event.target.value)}><option value="">Keep as unmapped raw data</option>{stage.semantic_fields.map(field=><option key={field.key} value={field.key}>{field.label}</option>)}</select></label></article>})}</div></section>)}</div>:<div className="column-search-empty"><strong>No columns match “{search}”</strong><button className="text-button" onClick={()=>setSearch('')}>Clear search</button></div>}</section>
}

function ImportHistory({imports}:{imports:ImportBatch[]}){return <section className="panel history"><div className="panel-title"><div><h2>Import history</h2><p>Checksums, counts and warnings are retained.</p></div></div>{imports.length===0?<div className="mini-empty"><p>No source files have been staged.</p></div>:<div className="history-list">{imports.map(item=><article key={item.id}><div className="file-badge small"><Icon name="pages"/></div><div><strong>{item.file_name}</strong><span>{item.source.replace('_',' ')} · {new Date(item.imported_at).toLocaleString()}</span><small>{item.checksum.slice(0,12)}…</small></div><div><span className={`batch-status ${item.error_count?'warn':''}`}>{item.status.replaceAll('_',' ')}</span><small>{item.imported_count}/{item.row_count} written</small></div></article>)}</div>}</section>}
