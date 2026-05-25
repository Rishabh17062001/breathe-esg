import { useEffect, useState } from 'react'

const ICONS = {
  success: '✓',
  error: '✕',
  warning: '⚠',
  info: 'ℹ',
}

const STYLES = {
  success: 'bg-green-600 text-white',
  error: 'bg-red-600 text-white',
  warning: 'bg-yellow-500 text-white',
  info: 'bg-blue-600 text-white',
}

export function Toast({ message, type = 'success', onClose }) {
  useEffect(() => {
    const t = setTimeout(onClose, 3000)
    return () => clearTimeout(t)
  }, [onClose])

  return (
    <div className={`flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg text-sm font-medium min-w-[220px] max-w-sm ${STYLES[type]}`}>
      <span className="text-base leading-none">{ICONS[type]}</span>
      <span className="flex-1">{message}</span>
      <button onClick={onClose} className="opacity-70 hover:opacity-100 text-base leading-none ml-1">&times;</button>
    </div>
  )
}

export function ToastContainer({ toasts, onClose }) {
  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2">
      {toasts.map(t => (
        <Toast key={t.id} message={t.message} type={t.type} onClose={() => onClose(t.id)} />
      ))}
    </div>
  )
}

let _id = 0
export function useToast() {
  const [toasts, setToasts] = useState([])

  function show(message, type = 'success') {
    const id = ++_id
    setToasts(prev => [...prev, { id, message, type }])
  }

  function remove(id) {
    setToasts(prev => prev.filter(t => t.id !== id))
  }

  return { toasts, show, remove }
}
