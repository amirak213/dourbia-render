import { SITE_CONTACT } from "../../content/siteContent";

export default function Footer() {
  return (
    <footer className="site-footer">
      <img src="/dourbia-icon.png" alt="" className="footer-icon" />
      <span>
        © Dourbia — {SITE_CONTACT.taglineFr} ·{" "}
        <a href={`mailto:${SITE_CONTACT.email}`}>{SITE_CONTACT.email}</a>
      </span>
    </footer>
  );
}
