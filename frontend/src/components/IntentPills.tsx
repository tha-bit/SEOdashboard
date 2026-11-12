const INTENT_META:Record<string,{short:string;label:string}> = {
  informational:{short:'I',label:'Informational'},
  navigational:{short:'N',label:'Navigational'},
  commercial:{short:'C',label:'Commercial'},
  transactional:{short:'T',label:'Transactional'},
}

export const SEARCH_INTENTS = Object.values(INTENT_META).map(item=>item.label)

export function intentValues(value?:string|string[]) {
  const raw = Array.isArray(value) ? value : (value || '').split(/[,;|/]/)
  return [...new Set(raw.map(item=>item.trim()).filter(Boolean).map(item=>item.charAt(0).toUpperCase()+item.slice(1).toLowerCase()))]
}

export function IntentPills({ value, empty='—' }:{ value?:string|string[]; empty?:string }) {
  const intents = intentValues(value)
  if (!intents.length) return <span className="intent-pill intent-unclassified" title="Unclassified">{empty}</span>
  return <span className="intent-pills">{intents.map(intent=>{const meta=INTENT_META[intent.toLowerCase()]||{short:intent.charAt(0).toUpperCase(),label:intent};return <span key={intent} className={`intent-pill intent-${intent.toLowerCase()}`} title={meta.label} aria-label={meta.label}>{meta.short}</span>})}</span>
}
