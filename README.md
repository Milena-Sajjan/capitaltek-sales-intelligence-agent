# CapitalTek B2B Sales Intelligence Agent

An AI-powered sales research agent that automatically discovers construction companies, analyzes their IT/cybersecurity vulnerabilities, and generates a branded PDF report with personalized cold email pitches — ready for your sales team in minutes.

Built for **CapitalTek** (Ottawa's IT & Cybersecurity MSP), but fully adaptable to any industry or target market.

---

## What It Does

1. **Discovers** 15–20 construction companies across Ottawa, Canada, and the USA using live Google search
2. **Researches** each company — visits their website, finds their social media, searches Reddit and news
3. **Analyzes** pain points using Claude AI (cybersecurity gaps, compliance risks, cloud lag, IT downtime, phishing exposure, and more)
4. **Writes** a personalized cold email for every company — ready to send
5. **Generates** a full branded PDF report with:
   - Executive summary & priority scoring
   - Company intelligence profiles (one per page)
   - Pain point tables colour-coded by severity
   - Full Marketing Playbook with messaging angles, objection handling, and a 14-day follow-up sequence

---

## Sample Output

The PDF report includes sections like:

- **Section 1:** Executive Summary — top 5 leads, most common pain points, key industry stats
- **Section 2:** Company Profiles — overview, pain points scored High/Medium/Low, CapitalTek services mapped, personalized email pitch
- **Section 3:** Marketing Playbook — messaging angles, channel strategy, objection handling, follow-up sequence
- **Section 4:** Appendix — sources, generation date, next steps for the sales team

---

## Tech Stack

| Tool | Purpose |
|------|---------|
| `anthropic` | Claude AI for pain-point analysis and email writing |
| `requests` + `beautifulsoup4` | Website fetching and HTML parsing |
| `reportlab` | PDF generation |
| `python-dotenv` | Secure API key loading |
| Serper API | Live Google search for company discovery |

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/capitaltek-sales-intelligence-agent.git
cd capitaltek-sales-intelligence-agent
```

### 2. Install dependencies

```bash
pip install requests beautifulsoup4 reportlab python-dotenv anthropic
```

### 3. Get your API keys

| Key | Where to get it | Cost |
|-----|----------------|------|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → API Keys | ~$0.50–2.00 per full run |
| `SERPER_API_KEY` | [serper.dev](https://serper.dev) | Free tier: 2,500 searches/month |

### 4. Create your `.env` file

Create a file named `.env` in the project root:

```
ANTHROPIC_API_KEY=your_anthropic_key_here
SERPER_API_KEY=your_serper_key_here
```

> ⚠️ Never commit your `.env` file. It is already blocked by `.gitignore`.

### 5. Run the agent

```bash
python tools/capitaltek_sales_intelligence.py
```

The PDF will be saved in the project root as:
```
CapitalTek_Construction_Intelligence_Report_YYYY-MM-DD.pdf
```

---

## Customizing for Your Business

This agent is built for CapitalTek targeting construction companies, but you can adapt it for any MSP, agency, or B2B business:

**Change the target industry:**
Edit the `SEARCH_QUERIES` list and `seed_companies` list in the script to target a different sector (e.g. law firms, healthcare, real estate).

**Change the company selling:**
Update the `SYSTEM_PROMPT` and email signature with your company name, services, and phone number.

**Change the pain points:**
Edit the pain point list in the `analyze_with_claude()` prompt to match your service offering.

**Change the PDF branding:**
Update `CAPITALTEK_BLUE`, `CAPITALTEK_CYAN`, and the cover page text in `build_pdf()`.

---

## How It Works (Architecture)

```
main()
  │
  ├── search_companies()        ← Serper API: 8 Google searches, deduped
  │
  ├── research_company()        ← For each company:
  │     ├── fetch_page()        │  Website text extraction
  │     ├── search_social_media()│  LinkedIn / Facebook / Instagram
  │     ├── search_reddit()     │  Reddit mentions
  │     └── search_news()       │  Recent news
  │
  ├── analyze_with_claude()     ← Claude AI: pain points + email pitch
  │
  ├── generate_marketing_guide()← Claude AI: full marketing playbook
  │
  └── build_pdf()               ← ReportLab: branded PDF report
```

All steps are wrapped in `try/except` — if one company fails, the agent logs the error and continues. The report always completes.

---

## Error Handling

- **No API keys:** Agent runs in fallback mode using seed companies and template analysis
- **Website fetch fails:** Logged and skipped, rest of research continues
- **Claude API error:** Falls back to template pain-point analysis
- **Serper API error:** Logged and skipped, seed companies still profiled

---

## Requirements

- Python 3.10+
- Internet connection
- Anthropic API key
- Serper API key

---

## License

MIT License — free to use, modify, and distribute.

---

## About CapitalTek

[CapitalTek](https://capitaltek.com) is Ottawa's trusted IT Managed Service Provider and Cybersecurity firm, serving construction companies and other industries across Canada.

📞 613-227-4357 | 🌐 capitaltek.com
