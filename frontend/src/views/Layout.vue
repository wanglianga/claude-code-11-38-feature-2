<script setup lang="ts">
import { useRouter } from 'vue-router'
import { auth, clearAuth } from '../store'

const router = useRouter()

function logout() {
  clearAuth()
  router.push('/login')
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="230px">
      <div class="brand">
        <div class="brand-title">能耗绩效核验平台</div>
        <div class="brand-sub">范围 · 边界 · 事实 · 引用</div>
      </div>
      <el-menu :default-active="$route.path" router background-color="#1f2d3d" text-color="#b8c4d0"
               active-text-color="#ffffff">
        <el-menu-item index="/dashboard">工作台</el-menu-item>
        <el-menu-item index="/evidence">证据受理库</el-menu-item>
        <el-menu-item index="/scope">改造范围册</el-menu-item>
        <el-menu-item index="/boundaries">计量边界册</el-menu-item>
        <el-menu-item index="/facts">绩效事实</el-menu-item>
        <el-menu-item index="/comparisons">跨项目比较</el-menu-item>
        <el-menu-item index="/citations">引用簿</el-menu-item>
      </el-menu>
      <div class="disclaimer">本平台不替代项目审批、预算调剂、拨款、施工安排或设备采购</div>
    </el-aside>
    <el-container>
      <el-header class="topbar">
        <span />
        <div class="user">
          <el-tag size="small" effect="plain">{{ auth.role }}</el-tag>
          <span>{{ auth.displayName }}（{{ auth.username }}）</span>
          <el-button link type="primary" @click="logout">退出</el-button>
        </div>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout { min-height: 100vh; }
.el-aside { background: #1f2d3d; display: flex; flex-direction: column; }
.brand { padding: 18px 16px 12px; color: #fff; }
.brand-title { font-size: 15px; font-weight: 600; }
.brand-sub { font-size: 11px; color: #7f96ab; margin-top: 4px; }
.el-menu { border-right: none; flex: 1; }
.disclaimer { padding: 12px 14px; font-size: 11px; color: #5f7488; line-height: 1.6; }
.topbar { display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #e8e8e8; background: #fff; }
.user { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.el-main { background: #f5f7fa; }
</style>
