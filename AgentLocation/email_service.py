"""
email_service.py — DOURBIA
══════════════════════════════════════════════════════════════
Module email centralisé — réutilisable par tous les agents.

Usage depuis un autre module :
    from email_service import EmailService

    svc = EmailService(
        expediteur="dourbia.agence@gmail.com",
        mot_de_passe="app_password",
        proprietaire="amirakoumenji21@gmail.com",
        serveur_base_url: Optional[str] = None
        chatbot_url: Optional[str] = None
        delai_relance_h=24,
    )

    svc.proprietaire_attente(reservation, token)
    svc.confirmation_client(reservation)
    svc.rappel_client(reservation)
    svc.feedback_client(reservation)
    svc.refus_client(reservation, raison="Voiture non disponible.")
    svc.relance_proprietaire(reservation, token)
    svc.annulation_client(reservation, source="client")

Toutes les méthodes lancent l'envoi dans un thread daemon (non bloquant).
"""

import os
import re
import secrets
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

try:
    from core.config import settings as app_settings
except Exception:
    app_settings = None


# ══════════════════════════════════════════════════════════════
# CLASSE PRINCIPALE
# ══════════════════════════════════════════════════════════════

class EmailService:
    """
    Service d'envoi d'emails pour Dourbia.
    Instanciez-le une fois et passez-le à vos agents.
    """

    def __init__(
        self,
        expediteur: str = "",
        mot_de_passe: str = "",
        proprietaire: str = "",
        serveur_base_url: Optional[str] = None,
        chatbot_url: Optional[str] = None,
        delai_relance_h: int = 24,
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 465,
    ):
        self.expediteur = (
            expediteur
            or os.getenv("EMAIL_EXPEDITEUR", "")
            or getattr(app_settings, "email_expediteur", "")
        )
        self.mot_de_passe = (
            mot_de_passe
            or os.getenv("EMAIL_MOT_DE_PASSE", "")
            or getattr(app_settings, "email_mot_de_passe", "")
        )
        self.proprietaire = (
            proprietaire
            or os.getenv("EMAIL_PROPRIETAIRE", "")
            or getattr(app_settings, "email_proprietaire", "")
        )
        self.serveur_base_url = (
            serveur_base_url
            or os.getenv("SERVEUR_BASE_URL", "")
            or getattr(app_settings, "serveur_base_url", "")
            or "http://localhost:8000"
        )
        self.chatbot_url = (
            chatbot_url
            or os.getenv("CHATBOT_URL", "")
            or getattr(app_settings, "chatbot_url", "")
            or "http://localhost:3000"
        )
        self.delai_relance_h  = delai_relance_h
        self.smtp_host        = smtp_host
        self.smtp_port        = smtp_port

    # ──────────────────────────────────────────────────────────
    # ENVOI SMTP (privé, bloquant — appelé dans un thread)
    # ──────────────────────────────────────────────────────────

    def _smtp(self, sujet: str, html: str, dest: str) -> bool:
        if not self.mot_de_passe:
            print(f"  [EMAIL] Non configuré → non envoyé à {dest}")
            return False
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = sujet
            msg["From"]    = self.expediteur
            msg["To"]      = dest
            msg.attach(MIMEText(html, "html", "utf-8"))
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as s:
                s.login(self.expediteur, self.mot_de_passe)
                s.sendmail(self.expediteur, dest, msg.as_string())
            print(f"  [EMAIL] OK → {dest}")
            return True
        except Exception as e:
            print(f"  [EMAIL] Erreur : {e}")
            return False

    def _envoyer_async(self, sujet: str, html: str, dest: str):
        """Lance l'envoi dans un thread daemon (non bloquant)."""
        threading.Thread(
            target=self._smtp,
            args=(sujet, html, dest),
            daemon=True,
        ).start()

    # ──────────────────────────────────────────────────────────
    # HELPERS HTML
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _header(titre: str, couleur_bg: str = "#1a1a2e", couleur_texte: str = "#e8b86d") -> str:
        return (
            f'<div style="background:{couleur_bg};padding:20px;text-align:center">'
            f'<h2 style="color:{couleur_texte};margin:0">{titre}</h2></div>'
        )

    @staticmethod
    def _extras_row(extras: str) -> str:
        if not extras:
            return ""
        return (
            f"<tr><td style='padding:8px;font-weight:bold'>Extras</td>"
            f"<td style='padding:8px'>{extras}</td></tr>"
        )

    @staticmethod
    def _valider_email(email: str) -> bool:
        return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()))

    # ──────────────────────────────────────────────────────────
    # 1. EMAIL PROPRIÉTAIRE — NOUVELLE DEMANDE EN ATTENTE
    # ──────────────────────────────────────────────────────────

    def proprietaire_attente(self, reservation: dict, token: str):
        """
        Envoie au propriétaire un email avec boutons CONFIRMER / REFUSER.
        Appelé juste après la création d'une réservation EN_ATTENTE.
        """
        rid      = reservation.get("id", "")
        lien_ok  = f"{self.serveur_base_url}/confirmer/{token}"
        lien_non = f"{self.serveur_base_url}/refuser/{token}"
        extras   = self._extras_row(reservation.get("voiture_extras", ""))

        html = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto">
        {self._header("DOURBIA - Action Requise")}
        <div style="padding:24px">
          <h3>Demande #{rid}</h3>
          <table style="width:100%;border-collapse:collapse;margin-bottom:20px">
            <tr><td style="padding:8px;font-weight:bold">Client</td>
                <td style="padding:8px">{reservation.get('client_nom','')} — {reservation.get('client_tel','')}</td></tr>
            <tr><td style="padding:8px;font-weight:bold">Email</td>
                <td style="padding:8px">{reservation.get('client_email','Non fourni')}</td></tr>
            <tr><td style="padding:8px;font-weight:bold">Véhicule</td>
                <td style="padding:8px">{reservation.get('voiture_details','')}</td></tr>
            <tr><td style="padding:8px;font-weight:bold">Immatriculation</td>
                <td style="padding:8px">{reservation.get('voiture_immat','')}</td></tr>
            <tr><td style="padding:8px;font-weight:bold">Agence / Ville</td>
                <td style="padding:8px">{reservation.get('voiture_agence','')} — {reservation.get('voiture_ville','')}</td></tr>
            {extras}
            <tr><td style="padding:8px;font-weight:bold">Période</td>
                <td style="padding:8px">{reservation.get('date_debut','')} au {reservation.get('date_fin','')}</td></tr>
            <tr><td style="padding:8px;font-weight:bold">Durée</td>
                <td style="padding:8px">{reservation.get('nb_jours','')} jours</td></tr>
            <tr><td style="padding:8px;font-weight:bold">Caution</td>
                <td style="padding:8px">{reservation.get('caution','')} TND</td></tr>
            <tr style="background:#1a1a2e">
                <td style="padding:10px;color:#e8b86d;font-weight:bold">TOTAL</td>
                <td style="padding:10px;color:#e8b86d;font-weight:bold">{reservation.get('prix_total','')} TND</td></tr>
          </table>
          <div style="text-align:center;margin-top:24px">
            <a href="{lien_ok}"  style="background:#27ae60;color:white;padding:14px 32px;border-radius:6px;text-decoration:none;font-weight:bold;margin-right:12px">CONFIRMER</a>
            <a href="{lien_non}" style="background:#e74c3c;color:white;padding:14px 32px;border-radius:6px;text-decoration:none;font-weight:bold">REFUSER</a>
          </div>
        </div></body></html>"""

        self._envoyer_async(
            f"[DOURBIA] Demande voiture à valider - {rid}",
            html,
            self.proprietaire,
        )

    # ──────────────────────────────────────────────────────────
    # 2. EMAIL PROPRIÉTAIRE — RELANCE APRÈS N HEURES SANS RÉPONSE
    # ──────────────────────────────────────────────────────────

    def relance_proprietaire(self, reservation: dict, token: str):
        """
        Relance si la réservation est encore EN_ATTENTE après delai_relance_h heures.
        Réutilise le même token de confirmation/refus.
        """
        rid      = reservation.get("id", "")
        lien_ok  = f"{self.serveur_base_url}/confirmer/{token}"
        lien_non = f"{self.serveur_base_url}/refuser/{token}"
        extras   = self._extras_row(reservation.get("voiture_extras", ""))

        html = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto">
        {self._header(f"⏰ DOURBIA — Relance : Action Requise", couleur_bg="#8b1a1a", couleur_texte="#fff")}
        <div style="padding:24px">
          <div style="background:#fff3cd;border-left:4px solid #f9a825;padding:14px;border-radius:4px;margin-bottom:20px">
            <b>⚠️ Cette demande attend votre réponse depuis plus de {self.delai_relance_h}h.</b><br>
            Le client <b>{reservation.get('client_nom','')}</b> est en attente.
          </div>
          <h3>Rappel — Demande #{rid}</h3>
          <table style="width:100%;border-collapse:collapse;margin-bottom:20px">
            <tr><td style="padding:8px;font-weight:bold">Client</td>
                <td style="padding:8px">{reservation.get('client_nom','')} — {reservation.get('client_tel','')}</td></tr>
            <tr><td style="padding:8px;font-weight:bold">Email</td>
                <td style="padding:8px">{reservation.get('client_email','Non fourni')}</td></tr>
            <tr><td style="padding:8px;font-weight:bold">Véhicule</td>
                <td style="padding:8px">{reservation.get('voiture_details','')}</td></tr>
            <tr><td style="padding:8px;font-weight:bold">Agence / Ville</td>
                <td style="padding:8px">{reservation.get('voiture_agence','')} — {reservation.get('voiture_ville','')}</td></tr>
            {extras}
            <tr><td style="padding:8px;font-weight:bold">Période</td>
                <td style="padding:8px">{reservation.get('date_debut','')} au {reservation.get('date_fin','')}</td></tr>
            <tr><td style="padding:8px;font-weight:bold">Durée</td>
                <td style="padding:8px">{reservation.get('nb_jours','')} jours</td></tr>
            <tr style="background:#1a1a2e">
                <td style="padding:10px;color:#e8b86d;font-weight:bold">TOTAL</td>
                <td style="padding:10px;color:#e8b86d;font-weight:bold">{reservation.get('prix_total','')} TND</td></tr>
          </table>
          <div style="text-align:center;margin-top:24px">
            <a href="{lien_ok}"  style="background:#27ae60;color:white;padding:14px 32px;border-radius:6px;text-decoration:none;font-weight:bold;margin-right:12px">CONFIRMER</a>
            <a href="{lien_non}" style="background:#e74c3c;color:white;padding:14px 32px;border-radius:6px;text-decoration:none;font-weight:bold">REFUSER</a>
          </div>
          <p style="text-align:center;color:#888;font-size:13px;margin-top:16px">
            Les liens ci-dessus sont identiques à ceux de l'email initial — ils restent valides.
          </p>
        </div></body></html>"""

        self._envoyer_async(
            f"[DOURBIA] ⏰ Relance — demande non traitée depuis {self.delai_relance_h}h - {rid}",
            html,
            self.proprietaire,
        )
        print(f"  [RELANCE_PROP] Email de relance → {self.proprietaire} ({rid})")

    # ──────────────────────────────────────────────────────────
    # 3. EMAIL CLIENT — CONFIRMATION DE RÉSERVATION
    # ──────────────────────────────────────────────────────────

    def confirmation_client(
        self,
        reservation: dict,
        token_annulation: Optional[str] = None,
    ) -> bool:
        """
        Email de confirmation envoyé au client après validation du propriétaire.

        token_annulation (optionnel) : si fourni, un lien d'annulation est ajouté.
        Si None, aucun lien d'annulation n'est affiché.
        """
        email = reservation.get("client_email", "")
        if not email or not self._valider_email(email):
            return False

        rid    = reservation.get("id", "")
        extras = self._extras_row(reservation.get("voiture_extras", ""))

        elec_note = (
            '<p style="background:#e0f7fa;border-left:3px solid #00bcd4;padding:10px;">'
            'Véhicule électrique — recharge incluse.</p>'
        ) if reservation.get("voiture_electrique") else ""

        # Section annulation (optionnelle)
        section_annulation = ""
        if token_annulation:
            lien_annul = f"{self.serveur_base_url}/annuler_client/{token_annulation}"
            section_annulation = f"""
            <div style="margin-top:28px;padding:16px;background:#fff8f8;border:1px solid #f0c0c0;border-radius:8px">
              <p style="margin:0 0 10px 0;font-size:14px;color:#666">Vous souhaitez annuler cette réservation ?</p>
              <a href="{lien_annul}"
                 style="display:inline-block;background:#c0392b;color:white;padding:10px 22px;
                        border-radius:6px;text-decoration:none;font-size:13px;font-weight:bold">
                Annuler ma réservation
              </a>
              <p style="margin:10px 0 0 0;font-size:12px;color:#999">
                Ce lien est à usage unique et sera désactivé après utilisation.
              </p>
            </div>"""

        html = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto">
        {self._header("DOURBIA - Réservation Confirmée ✅")}
        <div style="padding:24px">
          {elec_note}
          <h3>Location #{rid}</h3>
          <table style="width:100%;border-collapse:collapse">
            <tr><td style="padding:8px;font-weight:bold">Client</td>
                <td style="padding:8px">{reservation.get('client_nom','')}</td></tr>
            <tr><td style="padding:8px;font-weight:bold">Véhicule</td>
                <td style="padding:8px">{reservation.get('voiture_details','')}</td></tr>
            <tr><td style="padding:8px;font-weight:bold">Immatriculation</td>
                <td style="padding:8px">{reservation.get('voiture_immat','')}</td></tr>
            <tr><td style="padding:8px;font-weight:bold">Agence</td>
                <td style="padding:8px">{reservation.get('voiture_agence','')} — {reservation.get('voiture_ville','')}</td></tr>
            {extras}
            <tr><td style="padding:8px;font-weight:bold">Période</td>
                <td style="padding:8px">{reservation.get('date_debut','')} au {reservation.get('date_fin','')}</td></tr>
            <tr><td style="padding:8px;font-weight:bold">Durée</td>
                <td style="padding:8px">{reservation.get('nb_jours','')} jours</td></tr>
            <tr><td style="padding:8px;font-weight:bold">Prix/jour</td>
                <td style="padding:8px">{reservation.get('prix_jour','')} TND</td></tr>
            <tr><td style="padding:8px;font-weight:bold">Caution</td>
                <td style="padding:8px">{reservation.get('caution','')} TND</td></tr>
            <tr style="background:#1a1a2e">
                <td style="padding:10px;color:#e8b86d;font-weight:bold">TOTAL</td>
                <td style="padding:10px;color:#e8b86d;font-weight:bold">{reservation.get('prix_total','')} TND</td></tr>
          </table>
          {section_annulation}
        </div></body></html>"""

        self._envoyer_async(f"[DOURBIA] Réservation confirmée - {rid}", html, email)
        return True

    # ──────────────────────────────────────────────────────────
    # 4. EMAIL CLIENT — RAPPEL J-1
    # ──────────────────────────────────────────────────────────

    def rappel_client(self, reservation: dict) -> bool:
        """Email de rappel envoyé la veille de la prise en charge."""
        email = reservation.get("client_email", "")
        if not email or not self._valider_email(email):
            return False

        rid      = reservation.get("id", "")
        nom      = reservation.get("client_nom", "")
        vehicule = reservation.get("voiture_details", "")
        agence   = reservation.get("voiture_agence", "")
        ville    = reservation.get("voiture_ville", "")
        d_debut  = reservation.get("date_debut", "")
        d_fin    = reservation.get("date_fin", "")
        nb_jours = reservation.get("nb_jours", "")
        extras   = reservation.get("voiture_extras", "")
        caution  = reservation.get("caution", "")

        extras_row = (
            f"<tr><td style='padding:10px;font-weight:bold;background:#f9f9f9'>🎁 Extras inclus</td>"
            f"<td style='padding:10px'>{extras}</td></tr>"
        ) if extras else ""

        elec_tip = (
            '<div style="background:#e0f7fa;border-left:4px solid #00bcd4;padding:12px;margin:16px 0;border-radius:4px">'
            '<b>⚡ Véhicule électrique</b> — La recharge est incluse. Pensez à brancher le véhicule chaque soir !'
            '</div>'
        ) if reservation.get("voiture_electrique") else ""

        html = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto">
        {self._header("DOURBIA — Rappel de Location 🚗")}
        <div style="padding:24px">
          <p>Bonjour <b>{nom}</b>,</p>
          <p style="font-size:16px">
            Votre location débute <b style="color:#27ae60">demain, le {d_debut}</b> !<br>
            Voici un récapitulatif de votre dossier :
          </p>
          {elec_tip}
          <table style="width:100%;border-collapse:collapse;margin:16px 0;border:1px solid #e0e0e0">
            <tr style="background:#1a1a2e">
              <td colspan="2" style="padding:10px;color:#e8b86d;font-weight:bold;font-size:15px">📋 Dossier #{rid}</td>
            </tr>
            <tr><td style="padding:10px;font-weight:bold;background:#f9f9f9">🚗 Véhicule</td>
                <td style="padding:10px">{vehicule}</td></tr>
            <tr><td style="padding:10px;font-weight:bold;background:#f9f9f9">📍 Agence</td>
                <td style="padding:10px">{agence} — {ville}</td></tr>
            <tr><td style="padding:10px;font-weight:bold;background:#f9f9f9">📅 Prise en charge</td>
                <td style="padding:10px"><b style="color:#27ae60">{d_debut}</b></td></tr>
            <tr><td style="padding:10px;font-weight:bold;background:#f9f9f9">📅 Retour prévu</td>
                <td style="padding:10px">{d_fin} ({nb_jours} jours)</td></tr>
            {extras_row}
            <tr><td style="padding:10px;font-weight:bold;background:#f9f9f9">💰 Caution</td>
                <td style="padding:10px">{caution} TND (remboursée au retour)</td></tr>
          </table>
          <div style="background:#fff8e1;border-left:4px solid #f9a825;padding:14px;border-radius:4px;margin:16px 0">
            <b>📌 À ne pas oublier demain :</b>
            <ul style="margin:8px 0;padding-left:20px;line-height:2">
              <li>Votre <b>pièce d'identité / passeport</b> en cours de validité</li>
              <li>Votre <b>permis de conduire</b></li>
              <li>La <b>caution</b> de {caution} TND</li>
              <li>Ce <b>numéro de dossier</b> : <code style="background:#eee;padding:2px 6px;border-radius:3px">{rid}</code></li>
            </ul>
          </div>
          <p>Questions ? Notre assistante Yasmine est disponible :<br>
             <a href="{self.chatbot_url}" style="color:#e8b86d;font-weight:bold">{self.chatbot_url}</a></p>
          <p>Nous vous souhaitons un excellent voyage ! 🌟</p>
          <p>Cordialement,<br><b>L'équipe Dourbia</b></p>
        </div></body></html>"""

        self._envoyer_async(
            f"[DOURBIA] 🚗 Rappel — votre location débute demain ! ({rid})",
            html,
            email,
        )
        print(f"  [RAPPEL] Email J-1 → {email} ({rid})")
        return True

    # ──────────────────────────────────────────────────────────
    # 5. EMAIL CLIENT — DEMANDE DE FEEDBACK
    # ──────────────────────────────────────────────────────────

    def feedback_client(self, reservation: dict) -> bool:
        """Email de demande d'avis envoyé après la fin de location."""
        email = reservation.get("client_email", "")
        if not email or not self._valider_email(email):
            return False

        rid      = reservation.get("id", "")
        nom      = reservation.get("client_nom", "")
        vehicule = reservation.get("voiture_details", "")
        ville    = reservation.get("voiture_ville", "")
        d_debut  = reservation.get("date_debut", "")
        d_fin    = reservation.get("date_fin", "")
        base     = f"{self.serveur_base_url}/feedback/{rid}"

        html = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto">
        {self._header("DOURBIA — Votre avis nous tient à cœur 💬")}
        <div style="padding:24px">
          <p>Bonjour <b>{nom}</b>,</p>
          <p>Votre location <b>#{rid}</b> ({vehicule} — {ville})<br>du <b>{d_debut}</b> au <b>{d_fin}</b> est terminée.</p>
          <p>Pourriez-vous prendre <b>30 secondes</b> pour noter votre expérience ?</p>
          <div style="text-align:center;margin:28px 0">
            <p style="font-size:16px;font-weight:bold;margin-bottom:16px">Comment s'est passée votre location ?</p>
            <table style="margin:0 auto;border-collapse:separate;border-spacing:8px"><tr>
              <td><a href="{base}?note=5" style="display:block;background:#27ae60;color:white;padding:12px 16px;border-radius:8px;text-decoration:none;text-align:center">⭐⭐⭐⭐⭐<br><span style="font-size:11px">Excellent</span></a></td>
              <td><a href="{base}?note=4" style="display:block;background:#2ecc71;color:white;padding:12px 16px;border-radius:8px;text-decoration:none;text-align:center">⭐⭐⭐⭐<br><span style="font-size:11px">Bien</span></a></td>
              <td><a href="{base}?note=3" style="display:block;background:#f39c12;color:white;padding:12px 16px;border-radius:8px;text-decoration:none;text-align:center">⭐⭐⭐<br><span style="font-size:11px">Moyen</span></a></td>
              <td><a href="{base}?note=2" style="display:block;background:#e67e22;color:white;padding:12px 16px;border-radius:8px;text-decoration:none;text-align:center">⭐⭐<br><span style="font-size:11px">Décevant</span></a></td>
              <td><a href="{base}?note=1" style="display:block;background:#e74c3c;color:white;padding:12px 16px;border-radius:8px;text-decoration:none;text-align:center">⭐<br><span style="font-size:11px">Problème</span></a></td>
            </tr></table>
          </div>
          <p style="font-size:13px;color:#888;text-align:center">
            Chatbot : <a href="{self.chatbot_url}" style="color:#e8b86d">{self.chatbot_url}</a>
          </p>
          <p>Merci pour votre confiance, à bientôt sur Dourbia ! 🚗</p>
          <p>Cordialement,<br><b>L'équipe Dourbia</b></p>
        </div></body></html>"""

        self._envoyer_async(
            f"[DOURBIA] Comment s'est passée votre location ? ({rid})",
            html,
            email,
        )
        print(f"  [FEEDBACK] Email feedback → {email} ({rid})")
        return True

    # ──────────────────────────────────────────────────────────
    # 6. EMAIL CLIENT — REFUS DE DEMANDE
    # ──────────────────────────────────────────────────────────

    def refus_client(self, reservation: dict, raison: str = "") -> bool:
        """Email de refus avec lien vers le chatbot pour chercher une alternative."""
        email = reservation.get("client_email", "")
        if not email or not self._valider_email(email):
            return False

        rid      = reservation.get("id", "")
        nom      = reservation.get("client_nom", "")
        vehicule = reservation.get("voiture_details", "")
        ville    = reservation.get("voiture_ville", "")
        d_debut  = reservation.get("date_debut", "")
        d_fin    = reservation.get("date_fin", "")

        raison_html = (
            f"<tr style='background:#fff3cd'>"
            f"<td style='padding:10px;font-weight:bold;color:#856404'>🔎 Raison</td>"
            f"<td style='padding:10px;color:#856404'>{raison}</td></tr>"
        ) if raison else ""

        html = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto">
        {self._header("DOURBIA")}
        <div style="padding:24px">
          <p>Bonjour <b>{nom}</b>,</p>
          <p>Votre demande (réf. <b>{rid}</b>) n'a pas pu être confirmée.</p>
          <table style="width:100%;border-collapse:collapse;margin:16px 0;border:1px solid #ddd">
            {raison_html}
            <tr><td style="padding:8px;font-weight:bold">🚗 Véhicule</td><td style="padding:8px">{vehicule}</td></tr>
            <tr><td style="padding:8px;font-weight:bold">📅 Dates</td><td style="padding:8px">{d_debut} → {d_fin}</td></tr>
            <tr><td style="padding:8px;font-weight:bold">📍 Ville</td><td style="padding:8px">{ville}</td></tr>
          </table>
          <div style="background:#e8f5e9;border-left:4px solid #27ae60;padding:16px;margin:20px 0;border-radius:4px">
            <b style="font-size:15px">👉 Notre assistante Yasmine vous trouve une alternative !</b>
            <p style="margin:10px 0 14px 0;color:#555;font-size:14px">
              Cliquez ci-dessous — elle vous proposera d'autres véhicules disponibles.
            </p>
            <div style="text-align:center">
              <a href="{self.chatbot_url}"
                 style="display:inline-block;background:linear-gradient(135deg,#1a1a2e,#2d2d4e);
                        color:#e8b86d;padding:14px 32px;border-radius:8px;text-decoration:none;
                        font-weight:bold;font-size:15px;border:2px solid #e8b86d">
                🚗 Trouver une autre voiture →
              </a>
            </div>
          </div>
          <p>Cordialement,<br><b>L'équipe Dourbia</b></p>
        </div></body></html>"""

        self._envoyer_async(f"[DOURBIA] Demande non disponible - {rid}", html, email)
        return True

    # ──────────────────────────────────────────────────────────
    # 7. EMAIL ANNULATION — CLIENT + PROPRIÉTAIRE (double envoi)
    # ──────────────────────────────────────────────────────────

    def annulation_client(self, reservation: dict, source: str = "client"):
        """
        Envoie deux emails en parallèle :
          1. Au client : confirmation d'annulation + lien pour re-réserver
          2. Au propriétaire : alerte avec détails (véhicule remis à dispo)

        source : "client" (annulation volontaire) ou "admin" (annulation manuelle)
        """
        rid      = reservation.get("id", "")
        nom      = reservation.get("client_nom", "")
        tel      = reservation.get("client_tel", "")
        email    = reservation.get("client_email", "")
        vehicule = reservation.get("voiture_details", "")
        immat    = reservation.get("voiture_immat", "")
        agence   = reservation.get("voiture_agence", "")
        ville    = reservation.get("voiture_ville", "")
        d_debut  = reservation.get("date_debut", "")
        d_fin    = reservation.get("date_fin", "")
        nb_jours = reservation.get("nb_jours", "")
        prix     = reservation.get("prix_total", "")
        statut   = reservation.get("statut", "")

        # ── Email client ─────────────────────────────────────
        if email and self._valider_email(email):
            html_client = f"""
            <html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto">
            {self._header("DOURBIA — Annulation confirmée")}
            <div style="padding:24px">
              <p>Bonjour <b>{nom}</b>,</p>
              <p>Votre réservation <b>#{rid}</b> a bien été annulée à votre demande.</p>
              <table style="width:100%;border-collapse:collapse;margin:16px 0;border:1px solid #ddd">
                <tr><td style="padding:8px;font-weight:bold">🚗 Véhicule</td><td style="padding:8px">{vehicule}</td></tr>
                <tr><td style="padding:8px;font-weight:bold">📅 Dates</td><td style="padding:8px">{d_debut} → {d_fin}</td></tr>
              </table>
              <div style="background:#e8f5e9;border-left:4px solid #27ae60;padding:16px;margin:20px 0;border-radius:4px">
                <b>Vous souhaitez réserver un autre véhicule ?</b><br><br>
                <a href="{self.chatbot_url}"
                   style="display:inline-block;background:linear-gradient(135deg,#1a1a2e,#2d2d4e);
                          color:#e8b86d;padding:12px 28px;border-radius:8px;text-decoration:none;
                          font-weight:bold;border:2px solid #e8b86d">
                  🚗 Faire une nouvelle réservation →
                </a>
              </div>
              <p>Cordialement,<br><b>L'équipe Dourbia</b></p>
            </div></body></html>"""
            self._envoyer_async(
                f"[DOURBIA] Annulation de votre réservation - {rid}",
                html_client,
                email,
            )

        # ── Email propriétaire ───────────────────────────────
        source_label = "par le client" if source == "client" else "par l'administration"
        statut_color = "#e8b86d" if statut == "EN_ATTENTE" else "#27ae60"
        statut_label = "EN ATTENTE de confirmation" if statut == "EN_ATTENTE" else "CONFIRMÉE"

        html_proprio = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto">
        {self._header(f"🚫 DOURBIA — Réservation annulée {source_label}", couleur_bg="#7b1a1a", couleur_texte="#fff")}
        <div style="padding:24px">
          <div style="background:#fff3cd;border-left:4px solid #f9a825;padding:14px;border-radius:4px;margin-bottom:20px">
            <b>ℹ️ La réservation ci-dessous a été annulée {source_label}.</b><br>
            <span style="font-size:13px;color:#666">Le véhicule est automatiquement remis à disposition.</span>
          </div>
          <table style="width:100%;border-collapse:collapse;border:1px solid #e0e0e0">
            <tr style="background:#1a1a2e">
              <td colspan="2" style="padding:10px;color:#e8b86d;font-weight:bold">
                📋 Dossier #{rid}
                &nbsp;<span style="background:{statut_color};color:#000;padding:2px 8px;
                                   border-radius:10px;font-size:11px">{statut_label}</span>
              </td>
            </tr>
            <tr><td style="padding:10px;font-weight:bold;background:#f9f9f9;width:35%">👤 Client</td>
                <td style="padding:10px">{nom}</td></tr>
            <tr><td style="padding:10px;font-weight:bold;background:#f9f9f9">📞 Téléphone</td>
                <td style="padding:10px">{tel}</td></tr>
            <tr><td style="padding:10px;font-weight:bold;background:#f9f9f9">📧 Email</td>
                <td style="padding:10px">{email or 'Non fourni'}</td></tr>
            <tr><td style="padding:10px;font-weight:bold;background:#f9f9f9">🚗 Véhicule</td>
                <td style="padding:10px">{vehicule}</td></tr>
            <tr><td style="padding:10px;font-weight:bold;background:#f9f9f9">🔑 Immatriculation</td>
                <td style="padding:10px">{immat}</td></tr>
            <tr><td style="padding:10px;font-weight:bold;background:#f9f9f9">📍 Agence</td>
                <td style="padding:10px">{agence} — {ville}</td></tr>
            <tr><td style="padding:10px;font-weight:bold;background:#f9f9f9">📅 Dates annulées</td>
                <td style="padding:10px">{d_debut} → {d_fin} ({nb_jours} jours)</td></tr>
            <tr style="background:#fce4e4">
              <td style="padding:10px;font-weight:bold;color:#c0392b">💸 Montant perdu</td>
              <td style="padding:10px;font-weight:bold;color:#c0392b">{prix} TND</td>
            </tr>
          </table>
          <p style="margin-top:20px;font-size:13px;color:#888;text-align:center">
            Aucune action requise — le créneau est déjà libéré dans le système.
          </p>
        </div></body></html>"""
        self._envoyer_async(
            f"[DOURBIA] 🚫 Annulation {source_label} — {rid} ({vehicule})",
            html_proprio,
            self.proprietaire,
        )

        print(f"  [ANNUL] Emails → client ({email}) + propriétaire ({self.proprietaire}) | {rid}")
        return True

    # ──────────────────────────────────────────────────────────
    # 8. EMAIL PROPRIÉTAIRE — ALERTE FEEDBACK NÉGATIF
    # ──────────────────────────────────────────────────────────

    def alerte_feedback_negatif(self, reservation: dict, note: int):
        """
        Envoie une alerte au propriétaire si la note est ≤ 2.
        À appeler depuis la route /feedback après enregistrement.
        """
        rid      = reservation.get("id", "")
        nom      = reservation.get("client_nom", "")
        email    = reservation.get("client_email", "")
        vehicule = reservation.get("voiture_details", "")
        etoiles  = "⭐" * note

        html = f"""
        <html><body style="font-family:Arial">
        <h2 style="color:#e74c3c">⚠️ DOURBIA — Feedback négatif</h2>
        <p><b>Dossier :</b> {rid}<br>
        <b>Client :</b> {nom} ({email})<br>
        <b>Véhicule :</b> {vehicule}<br>
        <b>Note :</b> {etoiles} ({note}/5)</p>
        <p>Veuillez contacter ce client rapidement.</p>
        </body></html>"""

        self._envoyer_async(
            f"[DOURBIA] ⚠️ Feedback {note}/5 — {rid}",
            html,
            self.proprietaire,
        )

    # ──────────────────────────────────────────────────────────
    # 9. EMAIL CLIENT — SUGGESTION DE REBOOKING
    # ──────────────────────────────────────────────────────────

    def rebooking_suggestion(
        self,
        reservation: dict,
        voiture_alternative: dict,
        economie_totale: float,
    ) -> bool:
        """
        Notifie le client qu'une meilleure offre est disponible pour
        sa réservation déjà confirmée.

        Le client peut :
          - Accepter → lien vers le chatbot pour rebooker
          - Ignorer → ne rien faire (sa réservation reste valide)

        Retourne True si l'email a été envoyé avec succès.
        """
        email = reservation.get("client_email", "")
        if not email or not self._valider_email(email):
            return False

        rid      = reservation.get("id", "")
        nom      = reservation.get("client_nom", "")
        vehicule = reservation.get("voiture_details", "")
        d_debut  = reservation.get("date_debut", "")
        d_fin    = reservation.get("date_fin", "")
        nb_jours = reservation.get("nb_jours", "")

        alt_nom   = f"{voiture_alternative.get('marque','')} {voiture_alternative.get('modele','')}".strip()
        alt_prix  = voiture_alternative.get("prix_jour", "")
        alt_ville = voiture_alternative.get("ville", "")
        alt_note  = voiture_alternative.get("note_client", "")
        alt_id    = voiture_alternative.get("id", "")
        prix_actuel = reservation.get("prix_jour", "")

        html = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto">
        {self._header("DOURBIA — Bonne nouvelle pour votre location 💰")}
        <div style="padding:24px">
          <p>Bonjour <b>{nom}</b>,</p>
          <p>Vous avez une réservation confirmée <b>#{rid}</b> ({vehicule})
             du <b>{d_debut}</b> au <b>{d_fin}</b>.</p>
          <div style="background:#e8f5e9;border-left:4px solid #27ae60;padding:16px;
                      border-radius:6px;margin:20px 0">
            <b style="font-size:16px;color:#2e7d32">
              💡 Une meilleure offre vient de se libérer pour ces mêmes dates !
            </b>
            <p style="margin:12px 0 0 0;font-size:14px;color:#555">
              Vous pourriez économiser <b style="color:#27ae60;font-size:18px">{economie_totale} TND</b>
              sur votre location de {nb_jours} jours.
            </p>
          </div>
          <table style="width:100%;border-collapse:collapse;margin:16px 0;border:1px solid #e0e0e0">
            <tr style="background:#1a1a2e">
              <td style="padding:10px;color:#e8b86d;font-weight:bold">Comparaison</td>
              <td style="padding:10px;color:#e8b86d;font-weight:bold">Votre réservation</td>
              <td style="padding:10px;color:#e8b86d;font-weight:bold">Meilleure offre</td>
            </tr>
            <tr>
              <td style="padding:10px;font-weight:bold;background:#f9f9f9">Véhicule</td>
              <td style="padding:10px">{vehicule}</td>
              <td style="padding:10px"><b>{alt_nom}</b></td>
            </tr>
            <tr>
              <td style="padding:10px;font-weight:bold;background:#f9f9f9">Prix/jour</td>
              <td style="padding:10px">{prix_actuel} TND</td>
              <td style="padding:10px"><b style="color:#27ae60">{alt_prix} TND</b></td>
            </tr>
            <tr>
              <td style="padding:10px;font-weight:bold;background:#f9f9f9">Note</td>
              <td style="padding:10px">{reservation.get('note_client','—')}/5</td>
              <td style="padding:10px"><b>{alt_note}/5</b></td>
            </tr>
            <tr style="background:#e8f5e9">
              <td style="padding:10px;font-weight:bold;color:#2e7d32">Économie totale</td>
              <td style="padding:10px;color:#888">—</td>
              <td style="padding:10px;font-weight:bold;color:#27ae60;font-size:16px">
                {economie_totale} TND 🎉
              </td>
            </tr>
          </table>
          <p style="font-size:13px;color:#888;margin-bottom:20px">
            ⚠️ Cette offre est limitée et peut disparaître rapidement.
            Votre réservation actuelle <b>reste confirmée</b> si vous ne faites rien.
          </p>
          <div style="text-align:center">
            <a href="{self.chatbot_url}?rebooking={alt_id}&from={rid}"
               style="display:inline-block;background:linear-gradient(135deg,#1a1a2e,#2d2d4e);
                      color:#e8b86d;padding:14px 32px;border-radius:8px;text-decoration:none;
                      font-weight:bold;font-size:15px;border:2px solid #e8b86d">
              💰 Passer à la meilleure offre →
            </a>
          </div>
          <p style="margin-top:20px;font-size:12px;color:#aaa;text-align:center">
            Si vous ne souhaitez pas changer, ignorez simplement cet email.
            Votre réservation #{rid} reste valide.
          </p>
          <p>Cordialement,<br><b>L'équipe Dourbia</b></p>
        </div></body></html>"""

        self._envoyer_async(
            f"[DOURBIA] 💰 Économisez {economie_totale} TND sur votre location — {rid}",
            html,
            email,
        )
        return True

    # ──────────────────────────────────────────────────────────
    # 10. EMAIL CLIENT — ALERTE MÉTÉO PROACTIVE
    # ──────────────────────────────────────────────────────────

    def alerte_meteo_client(self, reservation: dict, alerte: dict) -> bool:
        """
        Notifie proactivement le client d'un événement météo impactant
        sa location (tempête, canicule, route coupée...).

        Déclenché par la coordination weather_agent → agent_réservation.
        Retourne True si l'email a été envoyé.
        """
        email = reservation.get("client_email", "")
        if not email or not self._valider_email(email):
            return False

        rid      = reservation.get("id", "")
        nom      = reservation.get("client_nom", "")
        vehicule = reservation.get("voiture_details", "")
        d_debut  = reservation.get("date_debut", "")
        d_fin    = reservation.get("date_fin", "")

        severite     = alerte.get("severite", "INFO")
        msg_meteo    = alerte.get("message", "")
        ville_alerte = alerte.get("ville", "")

        # Couleur et icône selon sévérité
        config = {
            "CRITICAL": ("#e74c3c", "🔴", "Alerte critique"),
            "WARNING":  ("#f39c12", "🟠", "Avertissement météo"),
            "INFO":     ("#3498db", "🔵", "Information météo"),
        }
        couleur, icone, label = config.get(severite, config["INFO"])

        html = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto">
        {self._header(f"DOURBIA — {label} pour votre location {icone}",
                      couleur_bg="#1a1a2e", couleur_texte="#e8b86d")}
        <div style="padding:24px">
          <p>Bonjour <b>{nom}</b>,</p>
          <p>Nous vous contactons au sujet de votre location <b>#{rid}</b>
             ({vehicule}) du <b>{d_debut}</b> au <b>{d_fin}</b>.</p>

          <div style="background:#fff8e1;border-left:5px solid {couleur};
                      padding:16px;border-radius:6px;margin:20px 0">
            <b style="font-size:15px;color:{couleur}">{icone} {label} — {ville_alerte}</b>
            <p style="margin:10px 0 0 0;color:#555;line-height:1.6">{msg_meteo}</p>
          </div>

          <p style="font-size:14px">
            <b>Ce que nous vous conseillons :</b>
          </p>
          <ul style="font-size:14px;line-height:2;color:#555">
            <li>Vérifiez les conditions routières avant de partir.</li>
            <li>Contactez l'agence <b>{reservation.get('voiture_agence','')}</b>
                pour confirmer la disponibilité du véhicule.</li>
            <li>Si vous souhaitez modifier ou annuler votre location,
                notre assistante Yasmine peut vous aider.</li>
          </ul>

          <div style="text-align:center;margin-top:24px">
            <a href="{self.chatbot_url}"
               style="display:inline-block;background:linear-gradient(135deg,#1a1a2e,#2d2d4e);
                      color:#e8b86d;padding:12px 28px;border-radius:8px;text-decoration:none;
                      font-weight:bold;border:2px solid #e8b86d">
              💬 Parler à Yasmine →
            </a>
          </div>

          <p style="margin-top:24px;font-size:13px;color:#aaa;text-align:center">
            Votre réservation #{rid} reste confirmée jusqu'à votre demande de modification.
          </p>
          <p>Cordialement,<br><b>L'équipe Dourbia</b></p>
        </div></body></html>"""

        self._envoyer_async(
            f"[DOURBIA] {icone} {label} pour votre location à {ville_alerte} — {rid}",
            html,
            email,
        )
        return True


# ══════════════════════════════════════════════════════════════
# INSTANCE GLOBALE PAR DÉFAUT (chargée depuis .env)
# ══════════════════════════════════════════════════════════════

#: Instance prête à l'emploi — importe-la directement si tu n'as pas
#: besoin de personnaliser la configuration au runtime.
#:
#: Exemple :
#:   from email_service import email_svc
#:   email_svc.proprietaire_attente(reservation, token)
email_svc = EmailService()


# ══════════════════════════════════════════════════════════════
# FONCTIONS COMPATIBLES AVEC L'ANCIEN API (agent.py v5.x)
# ══════════════════════════════════════════════════════════════
# Ces wrappers permettent de remplacer les appels directs de
# l'ancien agent.py sans changer une seule ligne dans le reste
# du code.

def envoyer_email_proprietaire_attente(reservation: dict, token: str):
    email_svc.proprietaire_attente(reservation, token)

def envoyer_email_relance_proprietaire(reservation: dict, token: str):
    email_svc.relance_proprietaire(reservation, token)

def envoyer_email_confirmation_client(
    reservation: dict,
    token_annulation: Optional[str] = None,
) -> bool:
    """
    Wrapper compatible v5.x + v7.0.
    token_annulation : si fourni, un lien d'annulation est inclus dans l'email.
    """
    return email_svc.confirmation_client(reservation, token_annulation=token_annulation)

def envoyer_email_rappel_client(reservation: dict) -> bool:
    return email_svc.rappel_client(reservation)

def envoyer_email_feedback_client(reservation: dict) -> bool:
    return email_svc.feedback_client(reservation)

def envoyer_email_refus_client(reservation: dict, raison: str = "") -> bool:
    return email_svc.refus_client(reservation, raison)

def envoyer_email_annulation_client(reservation: dict, source: str = "client") -> bool:
    return email_svc.annulation_client(reservation, source)
