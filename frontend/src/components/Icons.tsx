export function Icon({name}:{name:'grid'|'pages'|'upload'|'settings'|'search'|'plus'|'download'|'folder'|'tree'|'alert'|'edit'}) {
  const paths:Record<string,React.ReactNode> = {
    grid:<><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
    pages:<><path d="M6 2h9l4 4v16H6z"/><path d="M14 2v5h5M9 12h7M9 16h7"/></>,
    upload:<><path d="M12 16V3M7 8l5-5 5 5"/><path d="M4 14v7h16v-7"/></>,
    settings:<><circle cx="12" cy="12" r="3"/><path d="M19 13.5v-3l-2.1-.7-.5-1.2 1-2-2.1-2.1-2 1-1.2-.5L11.5 2h-3l-.7 2.1-1.2.5-2-1-2.1 2.1 1 2-.5 1.2-2 .6v3l2.1.7.5 1.2-1 2 2.1 2.1 2-1 1.2.5.6 2.1h3l.7-2.1 1.2-.5 2 1 2.1-2.1-1-2 .5-1.2z"/></>,
    search:<><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
    plus:<path d="M12 5v14M5 12h14"/>, download:<><path d="M12 3v13M7 11l5 5 5-5"/><path d="M4 20h16"/></>,
    folder:<><path d="M3 6h7l2 2h9v11H3z"/></>,
    tree:<><circle cx="12" cy="4" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="12" cy="19" r="2"/><circle cx="19" cy="19" r="2"/><path d="M12 6v6M5 17v-5h14v5M12 12v5"/></>,
    alert:<><path d="M12 3 2.8 20h18.4z"/><path d="M12 9v5M12 17.5h.01"/></>,
    edit:<><path d="M4 20h4l11-11-4-4L4 16z"/><path d="m13.5 6.5 4 4"/></>,
  }
  return <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}
