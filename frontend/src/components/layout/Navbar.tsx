import { useState } from "react";
import type { SiteView } from "../../content/siteContent";

interface NavbarProps {
  activeView: SiteView;
  onNavigate: (view: SiteView) => void;
  onNewChat: () => void;
}

const NAV_ITEMS: { id: SiteView; label: string }[] = [
  { id: "explorer", label: "Explorer" },
  { id: "circuit", label: "Créer un circuit" },
  { id: "sessions", label: "Mes sessions" },
  { id: "about", label: "À propos" },
];

export default function Navbar({ activeView, onNavigate, onNewChat }: NavbarProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  function handleNavigate(view: SiteView) {
    onNavigate(view);
    setMenuOpen(false);
  }

  function handleNewChat() {
    onNewChat();
    setMenuOpen(false);
  }

  return (
    <header className="top-nav">
      <button type="button" className="top-nav-brand" onClick={() => handleNavigate("home")}>
        <img src="/dourbia-icon.png" alt="" className="top-nav-icon" />
        <span className="top-nav-title">
          <span className="brand-dour">dour</span>
          <span className="brand-bia">bia</span>
        </span>
      </button>

      <button
        type="button"
        className="top-nav-menu-toggle"
        onClick={() => setMenuOpen((open) => !open)}
        aria-expanded={menuOpen}
        aria-controls="top-nav-mobile-menu"
        aria-label={menuOpen ? "Fermer le menu" : "Ouvrir le menu"}
      >
        <span className="top-nav-menu-bar" />
        <span className="top-nav-menu-bar" />
        <span className="top-nav-menu-bar" />
      </button>

      <nav className="top-nav-links" aria-label="Navigation principale">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={activeView === item.id ? "active" : undefined}
            onClick={() => handleNavigate(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div
        id="top-nav-mobile-menu"
        className={`top-nav-mobile-panel${menuOpen ? " open" : ""}`}
        aria-hidden={!menuOpen}
      >
        <nav className="top-nav-mobile-links" aria-label="Navigation mobile">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={activeView === item.id ? "active" : undefined}
              onClick={() => handleNavigate(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <button type="button" className="top-nav-mobile-chat" onClick={handleNewChat}>
          + Nouveau chat
        </button>
      </div>

      <button
        type="button"
        className="top-nav-new-chat"
        onClick={handleNewChat}
        aria-label="Démarrer une nouvelle conversation"
      >
        + Nouveau chat
      </button>
    </header>
  );
}
