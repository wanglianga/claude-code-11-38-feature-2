import { reactive } from 'vue'

export const auth = reactive({
  token: localStorage.getItem('epv_token') || '',
  username: localStorage.getItem('epv_username') || '',
  displayName: localStorage.getItem('epv_display') || '',
  role: localStorage.getItem('epv_role') || '',
  get loggedIn() { return !!this.token },
  get canWrite() { return this.role === 'admin' || this.role === 'analyst' },
})

export function setAuth(token: string, username: string, displayName: string, role: string) {
  auth.token = token; auth.username = username; auth.displayName = displayName; auth.role = role
  localStorage.setItem('epv_token', token)
  localStorage.setItem('epv_username', username)
  localStorage.setItem('epv_display', displayName)
  localStorage.setItem('epv_role', role)
}

export function clearAuth() {
  auth.token = ''; auth.username = ''; auth.displayName = ''; auth.role = ''
  localStorage.removeItem('epv_token'); localStorage.removeItem('epv_username')
  localStorage.removeItem('epv_display'); localStorage.removeItem('epv_role')
}
