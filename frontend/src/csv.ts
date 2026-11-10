function safeCell(value:unknown){
  let text=value===null||value===undefined?'':String(value)
  if(/^[=+\-@]/.test(text))text=`'${text}`
  return `"${text.replaceAll('"','""')}"`
}

function safeName(value:string){return value.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,80)||'issues'}

export function downloadCsv(filename:string,rows:Array<Record<string,unknown>>){
  if(!rows.length)return
  const headers=[...new Set(rows.flatMap(row=>Object.keys(row)))]
  const csv=[headers.map(safeCell).join(','),...rows.map(row=>headers.map(header=>safeCell(row[header])).join(','))].join('\r\n')
  const url=URL.createObjectURL(new Blob([`\uFEFF${csv}`],{type:'text/csv;charset=utf-8'}))
  const link=document.createElement('a');link.href=url;link.download=`${safeName(filename)}.csv`;document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url)
}
