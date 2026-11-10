const jsonHeaders = { 'Content-Type': 'application/json' }

export async function api<T>(path:string, init?:RequestInit):Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try { const body = await response.json(); message = body.detail || message } catch { /* response was not JSON */ }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export const postJson = <T,>(path:string, data:unknown) => api<T>(path, {method:'POST', headers:jsonHeaders, body:JSON.stringify(data)})
export const patchJson = <T,>(path:string, data:unknown) => api<T>(path, {method:'PATCH', headers:jsonHeaders, body:JSON.stringify(data)})
export const putJson = <T,>(path:string, data:unknown) => api<T>(path, {method:'PUT', headers:jsonHeaders, body:JSON.stringify(data)})
export const deleteJson = <T,>(path:string) => api<T>(path, {method:'DELETE'})
