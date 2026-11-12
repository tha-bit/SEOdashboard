import type { ReactNode } from 'react'

export function SummaryActionCard({label,value,detail,action,onClick,active=false,attention=false}:{label:string;value:ReactNode;detail:string;action:string;onClick:()=>void;active?:boolean;attention?:boolean}){
  return <button type="button" className={`summary-action-card${active?' is-active':''}${attention?' attention':''}`} aria-pressed={active} onClick={onClick}>
    <span>{label}</span>
    <strong>{value}</strong>
    <small>{detail}</small>
    <b>{action}</b>
  </button>
}
