import { createRouter, createWebHashHistory } from 'vue-router'
import { auth } from './store'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', component: () => import('./views/Login.vue') },
    {
      path: '/',
      component: () => import('./views/Layout.vue'),
      children: [
        { path: '', redirect: '/dashboard' },
        { path: 'dashboard', component: () => import('./views/Dashboard.vue') },
        { path: 'evidence', component: () => import('./views/Evidence.vue') },
        { path: 'scope', component: () => import('./views/Scope.vue') },
        { path: 'boundaries', component: () => import('./views/Boundaries.vue') },
        { path: 'facts', component: () => import('./views/Facts.vue') },
        { path: 'facts/:id', component: () => import('./views/FactDetail.vue') },
        { path: 'comparisons', component: () => import('./views/Comparisons.vue') },
        { path: 'citations', component: () => import('./views/Citations.vue') },
      ],
    },
  ],
})

router.beforeEach((to) => {
  if (to.path !== '/login' && !auth.loggedIn) return '/login'
})

export default router
