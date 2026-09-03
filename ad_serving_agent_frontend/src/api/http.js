import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({ baseURL: '/api/v1' })

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  ({ data, config }) => {
    if (data.code === 0) return data.data
    const error = new Error(data.message || '请求失败')
    if (!config.silent) ElMessage.error(error.message)
    return Promise.reject(error)
  },
  (error) => {
    if (!error.config?.silent) ElMessage.error(error.response?.data?.message || error.message || '网络异常')
    return Promise.reject(error)
  },
)

export default http
