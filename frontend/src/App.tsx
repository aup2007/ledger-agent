import { BrowserRouter, Link, NavLink, Route, Routes } from 'react-router-dom'
import { UploadPage } from './pages/Upload'
import { RunDetailPage } from './pages/RunDetail'
import { QueuePage } from './pages/Queue'
import './styles.css'

export default function App() {
  return (
    <BrowserRouter>
      <div className="shell">
        <nav className="topnav">
          <Link to="/" className="brand">
            Aqua<span className="amp"> · </span>Doc Agent
            <span className="brand-sub">In-Good-Order Ledger</span>
          </Link>
          <div className="nav-links">
            <NavLink to="/" end>Upload</NavLink>
            <NavLink to="/queue">Queue</NavLink>
          </div>
        </nav>

        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
          <Route path="/queue" element={<QueuePage />} />
        </Routes>

        <footer className="foot">
          <span>Aqua · Doc Agent</span>
          <span className="orn">· · ·</span>
          <span>LangGraph · Groq · Neon</span>
        </footer>
      </div>
    </BrowserRouter>
  )
}
