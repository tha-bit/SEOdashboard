type Option={value:string;label:string}

export function CheckboxFilter({label,options,values,onChange,onToggle}:{label:string;options:Option[];values:string[];onChange:(values:string[])=>void;onToggle?:(event:React.SyntheticEvent<HTMLDetailsElement>)=>void}){
  const allValues=options.map(option=>option.value)
  const selected=values.length?values:allValues
  function toggle(value:string,checked:boolean){
    const next=checked?[...new Set([...selected,value])]:selected.filter(item=>item!==value)
    if(!next.length)return
    onChange(next.length===allValues.length?[]:next)
  }
  return <details className="filter-picker" onToggle={onToggle}><summary>{label} <b>{values.length||'All'}</b></summary><div><header><strong>{label}</strong><button type="button" onClick={()=>onChange([])}>Select all</button></header><div className="filter-option-list">{options.map(option=><label className="filter-option-row" key={option.value}><input type="checkbox" checked={selected.includes(option.value)} onChange={event=>toggle(option.value,event.target.checked)}/><span>{option.label}</span></label>)}</div></div></details>
}
