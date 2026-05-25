import { NavLink } from 'react-router-dom'

const links = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/upload', label: 'Upload Data' },
  { to: '/records', label: 'Records' },
  { to: '/batches', label: 'Batches' },
]

export default function Navbar() {
  return (
    <nav className="bg-white border-b border-gray-200 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-8">
            <span className="text-green-700 font-bold text-lg tracking-tight">
              Breathe<span className="text-gray-900">ESG</span>
            </span>
            <div className="flex gap-1">
              {links.map(l => (
                <NavLink
                  key={l.to}
                  to={l.to}
                  className={({ isActive }) =>
                    `px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-green-50 text-green-700'
                        : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                    }`
                  }
                >
                  {l.label}
                </NavLink>
              ))}
            </div>
          </div>
          <div className="text-xs text-gray-400">analyst@acme.com</div>
        </div>
      </div>
    </nav>
  )
}
