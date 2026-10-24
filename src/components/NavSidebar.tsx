import './NavSidebar.css';

interface Props {
  activePanel: string | null;
  onPanelChange: (panel: string | null) => void;
}

const ITEMS = [
  { id: 'history',  label: 'History',  d: 'M12 8v4l3 3m6-3a9 9 0 1 1-18 0 9 9 0 0 1 18 0z' },
  { id: 'memory',   label: 'Memory',   d: 'M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 1 1 7.072 0l-.548.547A3.374 3.374 0 0 0 14 18.469V19a2 2 0 1 1-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z' },
  { id: 'settings', label: 'Settings', d: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm7.94-2.06a1.5 1.5 0 0 0 .29-1.65l-.6-1.08a1.5 1.5 0 0 0-1.35-.82h-.2a7 7 0 0 0-.7-.41l-.08-.2a1.5 1.5 0 0 0-.58-1.47l-1-.72a1.5 1.5 0 0 0-1.67-.04 7 7 0 0 0-.8.17l-.17.1a1.5 1.5 0 0 0-1.57 0l-.17-.1a7 7 0 0 0-.8-.17 1.5 1.5 0 0 0-1.67.04l-1 .72a1.5 1.5 0 0 0-.58 1.47l-.08.2a7 7 0 0 0-.7.41h-.2a1.5 1.5 0 0 0-1.35.82l-.6 1.08a1.5 1.5 0 0 0 .29 1.65l.15.15a7 7 0 0 0 0 .82l-.15.15a1.5 1.5 0 0 0-.29 1.65l.6 1.08a1.5 1.5 0 0 0 1.35.82h.2a7 7 0 0 0 .7.41l.08.2a1.5 1.5 0 0 0 .58 1.47l1 .72a1.5 1.5 0 0 0 1.67.04 7 7 0 0 0 .8-.17l.17-.1a1.5 1.5 0 0 0 1.57 0l.17.1a7 7 0 0 0 .8.17 1.5 1.5 0 0 0 1.67-.04l1-.72a1.5 1.5 0 0 0 .58-1.47l.08-.2a7 7 0 0 0 .7-.41h.2a1.5 1.5 0 0 0 1.35-.82l.6-1.08a1.5 1.5 0 0 0-.29-1.65l-.15-.15a7 7 0 0 0 0-.82z' },
  { id: 'preview',  label: 'Preview',  d: 'M13 10V3L4 14h7v7l9-11h-7z' },
];

export function NavSidebar({ activePanel, onPanelChange }: Props) {
  return (
    <nav className="nav-sidebar" id="nav-sidebar">
      {ITEMS.map((it) => (
        <button
          key={it.id}
          className={`nav-btn ${activePanel === it.id ? 'nav-btn--active' : ''}`}
          id={`nav-${it.id}`}
          onClick={() => onPanelChange(it.id)}
          aria-label={it.label}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="1.5"
            strokeLinecap="round" strokeLinejoin="round"
          >
            <path d={it.d} />
          </svg>
          <span>{it.label}</span>
        </button>
      ))}
    </nav>
  );
}
