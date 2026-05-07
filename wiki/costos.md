# Costos del proyecto — Agente Toesca

## Resumen

| Ítem | Tipo | Costo | Período | Total acumulado |
|---|---|---|---|---|
| API Gemini (Google) | Uso | ~$10.000 CLP | Acumulado | $10.000 CLP |
| Dominio Cloudflare | Anual | ~$10 USD (~$9.500 CLP) | Año 1 | pendiente |

**Total invertido a 2026-05-07: ~$10.000 CLP**

---

## Detalle por ítem

### API Gemini (Google AI Studio)
- Modelo: Gemini 2.5 Flash
- Uso: procesamiento de instrucciones del agente, lectura de archivos, automatizaciones
- Costo acumulado: ~$10.000 CLP
- Monitorear en: [Google AI Studio → Usage](https://aistudio.google.com)

### Dominio Cloudflare (pendiente)
- Propósito: URL fija para tunnel cloudflared → Power Automate pueda llamar al agente
- Costo estimado: ~$10 USD/año (~$9.500 CLP al tipo de cambio actual)
- Registrar en: cloudflare.com

### cloudflared (Cloudflare Tunnel)
- Costo: $0 — gratuito con dominio propio
- Instalado: 2026-05-07

---

## Infraestructura sin costo adicional

- Microsoft 365 / SharePoint / Outlook / Teams — licencia corporativa existente
- Python, openpyxl, Flask, MarkItDown — open source
- GitHub — repositorio privado gratuito
- OneDrive — sincronización SharePoint incluida en M365
