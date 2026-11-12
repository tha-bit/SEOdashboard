type Option={value:string;label:string}

export const FILTER_NONE='__filter_none__'

export function toggleFilterSelection(current:string[],value:string,checked:boolean){
  const selected=current.includes(FILTER_NONE)?[]:current
  const next=checked?[...new Set([...selected,value])]:selected.filter(item=>item!==value)
  return next.length?next:[FILTER_NONE]
}

export function filterSelectionCount(values:string[]){return values.includes(FILTER_NONE)?0:values.length}

export function CheckboxFilter({label,options,values,onChange,onToggle}:{label:string;options:Option[];values:string[];onChange:(values:string[])=>void;onToggle?:(event:React.SyntheticEvent<HTMLDetailsElement>)=>void}){
  const allValues=options.map(option=>option.value)
  const cleared=values.includes(FILTER_NONE)
  const selected=cleared?[]:values.length?values:allValues
  function toggle(value:string,checked:boolean){
    const next=checked?[...new Set([...selected,value])]:selected.filter(item=>item!==value)
    onChange(!next.length?[FILTER_NONE]:next.length===allValues.length?[]:next)
  }
  return <details className="filter-picker" onToggle={onToggle}><summary>{label} <b>{cleared?0:values.length||'All'}</b></summary><div><header><strong>{label}</strong><span className="filter-header-actions"><button type="button" onClick={()=>onChange([])}>Select all</button><button type="button" onClick={()=>onChange([FILTER_NONE])}>Clear</button></span></header><div className="filter-option-list">{options.map(option=><label className="filter-option-row" key={option.value}><input type="checkbox" checked={selected.includes(option.value)} onChange={event=>toggle(option.value,event.target.checked)}/><span>{option.label}</span></label>)}</div></div></details>
}
