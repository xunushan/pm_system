import { useEffect, useState } from 'react'
import { apiRoot } from './api/client'

/**
 * H5 页面骨架。
 * 页面设计暂不讨论；本文件仅验证与 Service 联通。
 * 实际页面（规划 / 调度 / 配置 / 轻量编辑）按 Story 实现，见 doc/01。
 */
export function App() {
  const [status, setStatus] = useState('检查中…')

  useEffect(() => {
    apiRoot
      .get<{ status: string }>('/health')
      .then((d) => setStatus(d.status === 'ok' ? 'Service 在线 ✅' : 'Service 异常'))
      .catch(() => setStatus('Service 离线（先启动 service）'))
  }, [])

  return (
    <div style={{ fontFamily: 'sans-serif', padding: 24 }}>
      <h1>目标管理系统</h1>
      <p>Service 状态：{status}</p>
      <p style={{ color: '#888' }}>页面按 Story 实现，见 doc/01_用户故事文档_v2.0.md</p>
    </div>
  )
}
