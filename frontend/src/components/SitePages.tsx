import {
  ABOUT_MISSION,
  HELP_ITEMS,
  HOME_PRODUCT_CARDS,
  PROBLEM_POINTS,
  SITE_CONTACT,
  SUSTAINABILITY_PILLARS,
  TEAM,
  type SiteView,
} from "../content/siteContent";
import SectionHeader from "./layout/SectionHeader";
import Button from "./ui/Button";
import CircuitPlannerPage from "./circuits/CircuitPlannerPage";
import ExplorerPage from "../pages/ExplorerPage";
import SessionsPage from "../pages/SessionsPage";
import type { ChatSession } from "../types";

interface SitePagesProps {
  view: SiteView;
  onNavigate: (view: SiteView) => void;
  onOpenChat: () => void;
  onAskGuide: (question: string) => void;
  chat: ChatSession | null;
  chats: ChatSession[];
  activeChatId: string | null;
  onNewChat: () => void;
  onSelectChat: (chatId: string) => void;
  onDeleteChat: (chatId: string) => void;
  onEnsureChat: () => string;
  onAppendMessage: (
    chatId: string,
    message: {
      role: "user" | "assistant";
      content: string;
      sources?: ChatSession["messages"][number]["sources"];
      memory?: ChatSession["messages"][number]["memory"];
      actions?: string[];
      elapsedMs?: number;
      latencyMs?: number;
      latencyDebug?: ChatSession["messages"][number]["latencyDebug"];
    },
  ) => void;
}

function HomeView({ onNavigate }: Pick<SitePagesProps, "onNavigate">) {
  return (
    <section className="content-panel home-panel">
      <div className="hero-section">
        <div className="hero-copy">
          <p className="hero-eyebrow">Dourbia · Carthage</p>
          <h1 className="hero-title">Découvrez Carthage avec un guide intelligent</h1>
          <p className="hero-subtitle">
            Explorez les monuments, obtenez des explications historiques sourcées et créez des
            circuits personnalisés selon votre temps, votre budget et vos préférences.
          </p>
          <div className="hero-actions">
            <Button variant="primary" onClick={() => onNavigate("explorer")}>
              Explorer Carthage
            </Button>
            <Button variant="secondary" onClick={() => onNavigate("circuit")}>
              Créer mon circuit
            </Button>
          </div>
        </div>
        <div className="hero-visual">
          <img src="/dourbia-banner.png" alt="" className="hero-banner" />
          <img src="/dourbia-logo.png" alt="Dourbia" className="hero-logo" />
        </div>
      </div>

      <section className="agent-features" aria-labelledby="product-cards-title">
        <h2 id="product-cards-title" className="section-title">
          Fonctionnalités
        </h2>
        <div className="agent-card-grid agent-card-grid-3">
          {HOME_PRODUCT_CARDS.map((feature) => (
            <article key={feature.title} className="agent-card">
              <h3>{feature.title}</h3>
              <p>{feature.description}</p>
            </article>
          ))}
        </div>
      </section>
    </section>
  );
}

function AboutView() {
  return (
    <section className="content-panel">
      <SectionHeader
        title="À propos de Dourbia"
        subtitle="Plateforme numérique intelligente pour découvrir le patrimoine culturel tunisien."
      />

      <div className="mission-card">
        <h3>Notre mission</h3>
        <p>{ABOUT_MISSION}</p>
      </div>

      <h3 className="section-title">Un tourisme durable</h3>
      <div className="card-grid">
        {SUSTAINABILITY_PILLARS.map((pillar) => (
          <article key={pillar.title} className="info-card">
            <h4>{pillar.title}</h4>
            <p>{pillar.description}</p>
          </article>
        ))}
      </div>

      <h3 className="section-title">Le problème que nous adressons</h3>
      <ul className="bullet-list">
        {PROBLEM_POINTS.map((point) => (
          <li key={point}>{point}</li>
        ))}
      </ul>

      <h3 className="section-title">Notre équipe</h3>
      <div className="team-grid">
        {TEAM.map((member) => (
          <article key={member.name} className="team-card">
            <strong>{member.name}</strong>
            <span>{member.role}</span>
          </article>
        ))}
      </div>

      <h3 className="section-title">Contact</h3>
      <div className="contact-grid">
        <article className="contact-card">
          <h4>Site web</h4>
          <a href={SITE_CONTACT.website} target="_blank" rel="noopener noreferrer">
            {SITE_CONTACT.website}
          </a>
        </article>
        <article className="contact-card">
          <h4>Email</h4>
          <a href={`mailto:${SITE_CONTACT.email}`}>{SITE_CONTACT.email}</a>
        </article>
      </div>

      <h3 className="section-title">Aide</h3>
      <div className="faq-list">
        {HELP_ITEMS.map((item) => (
          <article key={item.question} className="faq-card">
            <h4>{item.question}</h4>
            <p>{item.answer}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

export default function SitePages(props: SitePagesProps) {
  switch (props.view) {
    case "explorer":
      return (
        <ExplorerPage
          onNavigate={props.onNavigate}
          chat={props.chat}
          chats={props.chats}
          activeChatId={props.activeChatId}
          onNewChat={props.onNewChat}
          onSelectChat={props.onSelectChat}
          onDeleteChat={props.onDeleteChat}
          onEnsureChat={props.onEnsureChat}
          onAppendMessage={props.onAppendMessage}
        />
      );
    case "circuit":
      return <CircuitPlannerPage onAskGuide={props.onAskGuide} />;
    case "sessions":
      return (
        <SessionsPage
          chats={props.chats}
          activeChatId={props.activeChatId}
          onSelectChat={props.onSelectChat}
          onDeleteChat={props.onDeleteChat}
          onNewChat={props.onNewChat}
          onOpenChat={props.onOpenChat}
        />
      );
    case "about":
      return <AboutView />;
    default:
      return <HomeView onNavigate={props.onNavigate} />;
  }
}
