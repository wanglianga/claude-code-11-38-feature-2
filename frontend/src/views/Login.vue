<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { setAuth } from '../store'

const router = useRouter()
const form = reactive({ username: '', password: '' })
const loading = ref(false)

async function submit() {
  loading.value = true
  try {
    const r = await api.post<{ token: string; username: string; display_name: string; role: string }>(
      '/api/auth/login', form)
    setAuth(r.token, r.username, r.display_name, r.role)
    router.push('/dashboard')
  } catch (e: any) {
    ElMessage.error(e.message || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <h2>公共建筑改造范围与能耗绩效数据核验平台</h2>
      <p class="sub">证据受理 · 范围册 · 计量边界 · 绩效事实 · 引用簿</p>
      <el-form :model="form" @keyup.enter="submit">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password />
        </el-form-item>
        <el-button type="primary" size="large" :loading="loading" style="width: 100%" @click="submit">
          登录
        </el-button>
      </el-form>
      <div class="accounts">
        <p>测试账号：admin / admin123（管理员）</p>
        <p>analyst / analyst123（分析员）· auditor / auditor123（审计只读）</p>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.login-wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #f0f4f8; }
.login-card { width: 460px; }
h2 { font-size: 19px; margin: 0 0 6px; }
.sub { color: #888; font-size: 13px; margin-bottom: 22px; }
.accounts { margin-top: 18px; font-size: 12px; color: #999; }
.accounts p { margin: 2px 0; }
</style>
