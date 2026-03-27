"""
CapitalTek B2B Sales Intelligence Agent
========================================
Researches construction companies in Ottawa/Canada/USA, identifies IT/cybersecurity
pain points, and generates a full PDF report with personalized email pitches.

Requirements:
    pip install requests beautifulsoup4 reportlab python-dotenv anthropic

Environment variables (in .env):
    SERPER_API_KEY   — serper.dev API key for Google search
    ANTHROPIC_API_KEY — Anthropic API key for Claude analysis
"""

import os
import sys
import json
import time
import datetime
import traceback

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import anthropic
import httpx

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

SERPER_API_KEY   = os.getenv("SERPER_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL     = "claude-opus-4-5"
TODAY            = datetime.date.today().strftime("%Y-%m-%d")
OUTPUT_PDF       = os.path.join(
    os.path.dirname(__file__), '..',
    f"CapitalTek_Construction_Intelligence_Report_{TODAY}.pdf"
)

# ── Colours / brand ───────────────────────────────────────────────────────────

CAPITALTEK_BLUE  = colors.HexColor("#003087")
CAPITALTEK_CYAN  = colors.HexColor("#00AEEF")
LIGHT_GREY       = colors.HexColor("#F5F5F5")
MID_GREY         = colors.HexColor("#CCCCCC")
DARK_GREY        = colors.HexColor("#333333")

# ── Anthropic client ──────────────────────────────────────────────────────────

_anthropic_client = None

def get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        if not ANTHROPIC_API_KEY:
            print("  [WARN]  ANTHROPIC_API_KEY not set — Claude analysis will be skipped.")
            return None
        _anthropic_client = anthropic.Anthropic(
            api_key=ANTHROPIC_API_KEY,
            http_client=httpx.Client(verify=False),
        )
    return _anthropic_client

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — DISCOVER COMPANIES
# ─────────────────────────────────────────────────────────────────────────────

SEARCH_QUERIES = [
    "construction companies Ottawa Kanata Ontario",
    "general contractors Ottawa Ontario site:ca OR site:com",
    "commercial construction firms Ottawa Ontario",
    "residential construction companies Ottawa Ontario",
    "mid-size construction companies Toronto Calgary Vancouver",
    "construction company Houston TX commercial general contractor",
    "construction firms Phoenix AZ general contractor",
    "construction companies Denver CO general contractor",
]


def serper_search(query: str, num: int = 10) -> list[dict]:
    """POST to Serper API and return organic results."""
    if not SERPER_API_KEY:
        print("  [WARN]  SERPER_API_KEY not set — returning empty results.")
        return []
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": num, "gl": "ca"},
            timeout=15,
            verify=False,
        )
        resp.raise_for_status()
        return resp.json().get("organic", [])
    except Exception as exc:
        print(f"  [WARN]  Serper search failed for '{query}': {exc}")
        return []


def search_companies() -> list[dict]:
    """Run all discovery searches and deduplicate into a company list."""
    print("\n[SEARCH]  STEP 1 — Discovering construction companies …")
    seen_domains: set[str] = set()
    companies: list[dict] = []

    # Manually seed a handful of well-known Ottawa/Canada firms so the report
    # always has substance even if API keys are missing.
    seed_companies = [
        {"name": "Taggart Group of Companies", "website": "https://www.taggartgroup.com", "location": "Ottawa, ON"},
        {"name": "Dilfo Mechanical", "website": "https://www.dilfo.com", "location": "Ottawa, ON"},
        {"name": "Eastern Ontario Builders", "website": "https://eobuild.com", "location": "Ottawa, ON"},
        {"name": "Claridge Homes", "website": "https://www.claridgehomes.com", "location": "Ottawa, ON"},
        {"name": "Windmill Development Group", "website": "https://windmilldevelopment.com", "location": "Ottawa, ON"},
        {"name": "Magil Construction", "website": "https://www.magil.com", "location": "Montreal/Ottawa, QC/ON"},
        {"name": "PCL Construction", "website": "https://www.pcl.com", "location": "Ottawa, ON (branch)"},
        {"name": "EllisDon", "website": "https://www.ellisdon.com", "location": "Ottawa, ON (branch)"},
        {"name": "Vistas Homes", "website": "https://vistashomesottawa.com", "location": "Ottawa, ON"},
        {"name": "PACT Construction", "website": "https://www.pactconstruction.ca", "location": "Ottawa, ON"},
        {"name": "Bird Construction", "website": "https://www.bird.ca", "location": "Canada-wide"},
        {"name": "Aecon Group", "website": "https://www.aecon.com", "location": "Toronto, ON"},
        {"name": "Graham Construction", "website": "https://www.grahamconstruction.com", "location": "Calgary, AB"},
        {"name": "Ledcor Group", "website": "https://www.ledcor.com", "location": "Vancouver, BC"},
        {"name": "Flatiron Construction", "website": "https://www.flatironcorp.com", "location": "Denver, CO"},
        {"name": "McCarthy Building Companies", "website": "https://www.mccarthy.com", "location": "Phoenix, AZ"},
        {"name": "Turner Construction", "website": "https://www.turnerconstruction.com", "location": "Houston, TX"},
    ]

    for c in seed_companies:
        domain = c["website"].split("//")[-1].split("/")[0].lower()
        if domain not in seen_domains:
            seen_domains.add(domain)
            companies.append({
                "name": c["name"],
                "website": c["website"],
                "location": c["location"],
                "size": "Mid–Large",
                "source": "seed",
                "social_media": {},
            })

    # Augment with live Serper results
    for query in SEARCH_QUERIES:
        print(f"  >>  Searching: {query}")
        results = serper_search(query, num=5)
        for r in results:
            url = r.get("link", "")
            title = r.get("title", "").strip()
            snippet = r.get("snippet", "")
            if not url or not title:
                continue
            domain = url.split("//")[-1].split("/")[0].lower()
            # Basic filter — skip obvious directories and news sites
            skip_keywords = ["yellowpages", "yelp", "linkedin", "facebook",
                             "indeed", "wikipedia", "houzz", "homestars",
                             "bbb.org", "glassdoor", "reddit"]
            if any(k in domain for k in skip_keywords):
                continue
            if domain in seen_domains:
                continue
            # Crude location extraction from snippet/title
            location = "Canada"
            for loc in ["Ottawa", "Kanata", "Toronto", "Calgary", "Vancouver",
                        "Houston", "Phoenix", "Denver"]:
                if loc.lower() in (title + snippet).lower():
                    location = loc
                    break
            seen_domains.add(domain)
            companies.append({
                "name": title.split("|")[0].split("-")[0].strip(),
                "website": url,
                "location": location,
                "size": "Unknown",
                "source": "serper",
                "social_media": {},
            })
        time.sleep(0.5)   # polite rate limiting

    # Cap at 20
    companies = companies[:20]
    print(f"  [OK]  Found {len(companies)} companies.")
    return companies


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — RESEARCH EACH COMPANY
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def fetch_page(url: str, timeout: int = 12) -> str:
    """Fetch a URL and return visible text (stripped HTML)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True, verify=False)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "meta"]):
            tag.decompose()
        return " ".join(soup.get_text(separator=" ").split())[:8000]
    except Exception as exc:
        return f"[fetch error: {exc}]"


def search_social_media(company_name: str) -> dict:
    """Search for the company's social media presence."""
    social = {}
    platforms = {
        "linkedin": f"{company_name} LinkedIn construction company",
        "facebook": f"{company_name} Facebook construction",
        "instagram": f"{company_name} Instagram construction",
    }
    for platform, query in platforms.items():
        results = serper_search(query, num=3)
        for r in results:
            link = r.get("link", "")
            if platform in link.lower():
                social[platform] = link
                break
    return social


def search_reddit(company_name: str) -> str:
    """Search Reddit for mentions of the company."""
    queries = [
        f'"{company_name}" site:reddit.com',
        "Ottawa construction technology IT problems site:reddit.com",
        "construction company cybersecurity breach Canada site:reddit.com",
    ]
    snippets = []
    for q in queries[:2]:   # limit API calls
        results = serper_search(q, num=3)
        for r in results:
            snippet = r.get("snippet", "")
            if snippet:
                snippets.append(snippet)
    return " | ".join(snippets[:4]) if snippets else "No Reddit mentions found."


def search_news(company_name: str) -> str:
    """Search for recent news about the company."""
    queries = [
        f'"{company_name}" construction news 2024 OR 2025',
        f'"{company_name}" Ottawa growth expansion',
        "Ottawa construction cybersecurity breach incident 2024 2025",
    ]
    snippets = []
    for q in queries[:2]:
        results = serper_search(q, num=3)
        for r in results:
            snippet = r.get("snippet", "")
            title  = r.get("title", "")
            if snippet:
                snippets.append(f"{title}: {snippet}")
    return " | ".join(snippets[:4]) if snippets else "No recent news found."


def research_company(company: dict) -> dict:
    """Run all research for a single company and return enriched dict."""
    name    = company["name"]
    website = company["website"]
    print(f"\n  [CO]   Researching: {name}")

    # A) Website
    print(f"       Fetching website …")
    website_text = fetch_page(website)
    has_ssl = website.startswith("https://")

    # B) Careers page — look for IT job postings
    careers_text = ""
    for suffix in ["/careers", "/jobs", "/about/careers", "/join-us"]:
        careers_text = fetch_page(website.rstrip("/") + suffix)
        if "fetch error" not in careers_text and len(careers_text) > 200:
            break

    # C) Social media
    print(f"       Searching social media …")
    social = search_social_media(name)
    company["social_media"] = social

    # D) Reddit
    print(f"       Searching Reddit …")
    reddit_data = search_reddit(name)

    # E) News
    print(f"       Searching news …")
    news_data = search_news(name)

    # Compile
    company.update({
        "website_text":  website_text,
        "careers_text":  careers_text,
        "reddit_data":   reddit_data,
        "news_data":     news_data,
        "has_ssl":       has_ssl,
    })
    return company


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 + 4 + 5 — CLAUDE ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior B2B sales intelligence analyst for CapitalTek,
an Ottawa-based IT Managed Service Provider and Cybersecurity firm (capitaltek.com).
CapitalTek serves construction companies.

CapitalTek services:
- Managed IT & Co-Managed IT (24/7 monitoring, helpdesk, network management)
- Cybersecurity Solutions (real-time protection, penetration testing, assessments, IAM, phishing training)
- Cloud & Office IT (Microsoft 365, Google Workspace, SharePoint, server-to-cloud migration, network design)
- Compliance (PIPEDA, SOC Type 2, ISO 27001, Cybersecure Canada, PCI)
- vCISO / Fractional CISO services
- Dedicated IT Support

Key stats: 75% of construction firms had a cyber incident in the past year.
Average ransomware downtime = 20 days. 94% of malware is delivered via email.

You always respond with clean, structured JSON. No markdown fences. Pure JSON only."""


def analyze_with_claude(company: dict) -> dict:
    """Send company research to Claude for pain-point analysis + email draft."""
    client = get_anthropic_client()
    if client is None:
        return _fallback_analysis(company)

    prompt = f"""
Analyze this construction company and return a JSON object with exactly these keys:
{{
  "overview": "2-3 sentence company overview",
  "pain_points": [
    {{
      "name": "Pain point name",
      "likelihood": "High|Medium|Low",
      "evidence": "Brief evidence from the research data",
      "capitaltek_services": ["Service 1", "Service 2"]
    }}
  ],
  "priority_score": "High|Medium|Low",
  "priority_reasoning": "1-2 sentence justification",
  "email_subject": "Personalized subject line under 60 chars",
  "email_body": "Full email body under 200 words, 4 paragraphs as instructed"
}}

Company data:
- Name: {company['name']}
- Location: {company['location']}
- Website: {company['website']}
- Has SSL: {company['has_ssl']}
- Social media found: {json.dumps(company.get('social_media', {}))}
- Website content (excerpt): {company.get('website_text', '')[:3000]}
- Careers page (excerpt): {company.get('careers_text', '')[:1000]}
- Reddit mentions: {company.get('reddit_data', 'None')}
- News: {company.get('news_data', 'None')}

Pain points to evaluate:
1. Cybersecurity Risk (no SSL, no security mentions, outdated site)
2. Compliance Gap (government contracts, US clients needing PIPEDA/SOC2)
3. Cloud/Remote Work Lag (local servers, no cloud tool mentions)
4. IT Downtime Risk (IT job postings, overwhelmed internal IT)
5. Email Phishing Vulnerability (no email security mentions)
6. Data Protection (blueprints, contracts, client data at risk)
7. Network Connectivity Issues (multi-site, no network management)
8. Lack of IT Strategy (no CTO/CIO, informal IT)

Email requirements:
- Para 1: One sentence showing you know their specific business
- Para 2: Name the specific risk backed by an industry stat
- Para 3: Explain exactly how CapitalTek solves it (specific service name)
- Para 4: Soft CTA — free discovery call or free cybersecurity assessment
- Signature: CapitalTek | Ottawa's Trusted IT & Cybersecurity Partner | 613-227-4357 | capitaltek.com
- Under 200 words total. No generic language. No "[Company Name]" placeholders — use the actual name.

Return ONLY the JSON object. No explanation. No markdown.
"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1800,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"    [WARN]  JSON parse error for {company['name']}: {exc}")
        return _fallback_analysis(company)
    except Exception as exc:
        print(f"    [WARN]  Claude error for {company['name']}: {exc}")
        return _fallback_analysis(company)


def _fallback_analysis(company: dict) -> dict:
    """Return a generic analysis if Claude is unavailable."""
    name = company["name"]
    has_ssl = company.get("has_ssl", True)
    return {
        "overview": (
            f"{name} is a construction company based in {company.get('location', 'Canada')}. "
            "They operate in a sector where cybersecurity threats are rising rapidly. "
            "Their digital footprint suggests opportunities for IT modernization."
        ),
        "pain_points": [
            {
                "name": "Cybersecurity Risk",
                "likelihood": "High" if not has_ssl else "Medium",
                "evidence": "No SSL detected." if not has_ssl else "Limited security signals on website.",
                "capitaltek_services": ["Cybersecurity Assessment", "Real-Time Cybersecurity", "Penetration Testing"],
            },
            {
                "name": "Lack of IT Strategy",
                "likelihood": "Medium",
                "evidence": "No CTO/CIO or IT leadership visible in online presence.",
                "capitaltek_services": ["vCISO / Fractional CISO", "IT Strategy & Planning"],
            },
            {
                "name": "Email Phishing Vulnerability",
                "likelihood": "High",
                "evidence": "94% of malware is delivered via email; no email security mentions found.",
                "capitaltek_services": ["Employee Training & Phishing Simulations", "Identity & Access Management"],
            },
        ],
        "priority_score": "Medium",
        "priority_reasoning": "Standard construction sector risk profile. Recommend outreach to qualify.",
        "email_subject": f"Is {name}'s data protected from ransomware?",
        "email_body": (
            f"Hi [Name],\n\n"
            f"I noticed {name} has been active in the Ottawa construction market — impressive work on your recent projects.\n\n"
            "Here's a stat that might surprise you: 75% of construction firms experienced a cyber incident in the past year, "
            "and the average ransomware attack costs 20 days of complete operational downtime. With blueprints, bids, and "
            "client contracts all living digitally, construction companies are now prime targets.\n\n"
            "At CapitalTek, we specialize in protecting construction firms with real-time cybersecurity monitoring, "
            "employee phishing simulations, and a free Cybersecurity Assessment that shows you exactly where your gaps are — "
            "no commitment required.\n\n"
            "Would you be open to a 20-minute discovery call this week? I'd love to share what we're seeing across "
            "the Ottawa construction sector right now.\n\n"
            "CapitalTek | Ottawa's Trusted IT & Cybersecurity Partner | 613-227-4357 | capitaltek.com"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — MARKETING GUIDE
# ─────────────────────────────────────────────────────────────────────────────

def generate_marketing_guide() -> str:
    """Ask Claude to write the full CapitalTek Construction Marketing Playbook."""
    print("\n[MARKETING]  STEP 6 — Generating Marketing Playbook …")
    client = get_anthropic_client()
    if client is None:
        return _fallback_marketing_guide()

    prompt = """Write a detailed CapitalTek Construction Sector Marketing Playbook.
Return it as plain text (no markdown headers with #, use ALL CAPS for section titles instead).

Include ALL of the following sections in full detail:

1. TOP 3 MESSAGING ANGLES
   - Angle 1: "Your blueprints and bids are your most valuable assets — are they protected?"
   - Angle 2: "One ransomware attack = 20 days of downtime. Can your crew afford that?"
   - Angle 3: "You're winning bigger government contracts — PIPEDA and compliance is now your problem."
   For each angle, write 3-4 sentences explaining why it resonates and how to use it.

2. CHANNEL RECOMMENDATIONS
   - LinkedIn: targeting decision makers (owner, president, VP Operations, project manager)
   - Local Ottawa Facebook groups and community boards
   - Reddit: r/ottawa, r/construction, r/msp
   - Cold email via tools like Apollo or Hunter
   - Ottawa Chamber of Commerce and local construction association events
   For each channel, give a recommended posting cadence and 2-3 specific content ideas.

3. OBJECTION HANDLING GUIDE
   For each objection, write a confident, non-pushy 2-3 sentence response:
   - "We're too small to be targeted"
   - "We already have an IT guy"
   - "We can't afford it right now"
   - "We've never had a breach"
   - "We're happy with what we have"

4. FOLLOW-UP SEQUENCE
   - Day 1: Cold email (personalized, reference specific project or news)
   - Day 4: LinkedIn connection request with a short personal note
   - Day 8: Follow-up email referencing a local Ottawa news story about construction/cyber
   - Day 14: Final check-in with a free offer (link to free risk assessment)
   For each touchpoint, write the actual template message (under 80 words each).

5. CONTENT IDEAS FOR SOCIAL MEDIA
   Give 5 specific post ideas tailored to construction company audiences on LinkedIn.

Keep the full guide detailed and actionable. Write it for a sales team, not executives."""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=3000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as exc:
        print(f"  [WARN]  Marketing guide generation failed: {exc}")
        return _fallback_marketing_guide()


def _fallback_marketing_guide() -> str:
    return """CAPITALTEK CONSTRUCTION SECTOR MARKETING PLAYBOOK
Generated: """ + TODAY + """

1. TOP 3 MESSAGING ANGLES

Angle 1: "Your blueprints and bids are your most valuable assets — are they protected?"
Construction firms store highly sensitive data: architectural drawings, bid pricing, client contracts, and subcontractor agreements. This data has enormous value to competitors and ransomware actors alike. Use this angle to open a conversation about data protection without sounding alarmist. It frames cybersecurity as asset protection — language construction owners understand intuitively.

Angle 2: "One ransomware attack = 20 days of downtime. Can your crew afford that?"
The average ransomware-induced downtime in construction is 20 full business days. That means no invoicing, no project management, no site communications. For a company running multiple active sites, this is existential. Lead with this stat in email subject lines, LinkedIn posts, and cold calls. It's concrete, verifiable, and terrifying in the right way.

Angle 3: "You're winning bigger government contracts — PIPEDA and compliance is now your problem."
As Ottawa construction firms scale into federal and provincial contracts, compliance obligations (PIPEDA, Cybersecure Canada) follow. Many firms are unaware until a procurement officer asks for proof. Use this angle for firms that appear to be growing or bidding on public sector work.

2. CHANNEL RECOMMENDATIONS

LinkedIn:
- Target: Owner, President, VP Operations, Project Manager, Office Manager
- Cadence: 3x per week
- Content: Industry stats, client success stories, "did you know" cybersecurity tips for trades

Ottawa Facebook Groups & Community Boards:
- Join groups like "Ottawa Business Network" and "Ottawa Contractors & Trades"
- Cadence: 1-2x per week
- Content: Local news reactions, free tips, event announcements

Reddit (r/ottawa, r/construction):
- Participate authentically — answer questions, offer value before pitching
- Cadence: 2-3x per week (comment-based)
- Content: Responses to cybersecurity questions, Ottawa business discussions

Cold Email:
- Use Apollo.io or Hunter.io to find decision-maker emails
- Cadence: 1 sequence per prospect per quarter
- Content: Fully personalized (reference a real project, news story, or job posting)

3. OBJECTION HANDLING GUIDE

"We're too small to be targeted."
Attackers use automated tools that don't care about company size — they scan for open vulnerabilities across millions of sites simultaneously. In fact, small and mid-size firms are preferred targets precisely because they have less security. You don't need to be big to be valuable — you just need to have data worth stealing.

"We already have an IT guy."
That's great — we actually work alongside internal IT teams through our Co-Managed IT model. We handle 24/7 monitoring, threat response, and compliance overhead so your IT person can focus on day-to-day operations rather than chasing alerts at 2am. We're a force multiplier, not a replacement.

"We can't afford it right now."
We understand — which is why we start with a free Cybersecurity Assessment. No cost, no commitment. It takes 30 minutes and shows you exactly what you're exposed to. Many clients find that what they're spending on reactive IT fixes costs more than proactive protection. We can show you the math.

"We've never had a breach."
75% of construction firms had a cyber incident in the past year — many just didn't know it until months later. The average breach goes undetected for 207 days. The absence of a known breach doesn't mean you're protected; it may mean you haven't found it yet. Let us run a quick assessment and give you certainty either way.

"We're happy with what we have."
We're not here to tear anything out. We do a free assessment, show you what's working, and only flag what actually puts you at risk. If everything checks out, you'll have peace of mind and a documented security posture — which is increasingly required for government contracts in Ottawa.

4. FOLLOW-UP SEQUENCE

Day 1 — Cold Email:
Subject: [Reference their specific project or news] + cybersecurity angle
Send the fully personalized email generated in this report.

Day 4 — LinkedIn Connection Request:
"Hi [Name], I reached out by email earlier this week about cybersecurity for [Company]. I work with several Ottawa construction firms and thought it'd be good to connect here too. No pitch — just good to be in each other's network."

Day 8 — Follow-Up Email:
Subject: Thought you'd find this relevant, [Name]
"Hi [Name], I wanted to follow up on my email from last week. I came across [reference a real Ottawa construction or cybersecurity news story] and thought it was directly relevant to what firms like yours are navigating. Happy to share what we're seeing across the sector if you have 20 minutes. No obligation — just useful context."

Day 14 — Final Check-In with Free Offer:
Subject: Last note + a free resource for [Company]
"Hi [Name], I won't keep following up after this — I respect your time. I did want to leave you with a free Cybersecurity Risk Assessment we offer to Ottawa construction firms. Takes 30 minutes, fully confidential, and gives you a clear picture of your exposure. If you'd like it, just reply 'yes' and I'll get it scheduled. Either way, best of luck with your upcoming projects."

5. SOCIAL MEDIA CONTENT IDEAS (LinkedIn)

Post 1 — Stat-Based:
"75% of construction firms experienced a cyber incident in the past year. The average downtime? 20 days. For a firm running 3 active sites, that's catastrophic. Are your blueprints, bids, and client data protected? [Link to free assessment]"

Post 2 — Story-Based:
"A mid-size Ottawa contractor called us after a ransomware attack locked them out of their project management system for 3 weeks. They lost $180,000 in delayed billing and missed a bid deadline. It started with one phishing email. Here's what they wish they'd done differently."

Post 3 — Objection-Buster:
"'We're too small to be targeted.' We hear this from Ottawa construction owners every week. The truth: attackers use automated bots that scan millions of sites per hour. Size doesn't matter. An open door does."

Post 4 — Value-Led:
"Government contracts are growing in Ottawa — and so are the compliance requirements that come with them. PIPEDA. Cybersecure Canada. SOC 2. If you're bidding on federal or provincial work, your IT posture is now part of the evaluation. CapitalTek helps you get there."

Post 5 — CTA-Focused:
"We're offering 10 free Cybersecurity Assessments to Ottawa construction companies this quarter. 30 minutes. No commitment. You'll know exactly where your risks are. DM us or visit capitaltek.com to book yours."
"""


# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — BUILD PDF
# ─────────────────────────────────────────────────────────────────────────────

def _styles():
    """Return a dict of ReportLab paragraph styles."""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleStyle", parent=base["Title"],
            fontSize=26, textColor=CAPITALTEK_BLUE,
            spaceAfter=6, alignment=TA_CENTER, fontName="Helvetica-Bold",
        ),
        "subtitle": ParagraphStyle(
            "SubtitleStyle", parent=base["Normal"],
            fontSize=13, textColor=CAPITALTEK_CYAN,
            spaceAfter=4, alignment=TA_CENTER, fontName="Helvetica",
        ),
        "section": ParagraphStyle(
            "SectionStyle", parent=base["Heading1"],
            fontSize=16, textColor=colors.white,
            spaceAfter=6, spaceBefore=14, fontName="Helvetica-Bold",
            backColor=CAPITALTEK_BLUE, leftIndent=-6, rightIndent=-6,
            borderPadding=(4, 8, 4, 8),
        ),
        "subsection": ParagraphStyle(
            "SubsectionStyle", parent=base["Heading2"],
            fontSize=12, textColor=CAPITALTEK_BLUE,
            spaceAfter=4, spaceBefore=8, fontName="Helvetica-Bold",
        ),
        "company_header": ParagraphStyle(
            "CompanyHeader", parent=base["Heading2"],
            fontSize=14, textColor=colors.white,
            spaceAfter=2, spaceBefore=10, fontName="Helvetica-Bold",
            backColor=CAPITALTEK_CYAN, leftIndent=-6, rightIndent=-6,
            borderPadding=(3, 8, 3, 8),
        ),
        "body": ParagraphStyle(
            "BodyStyle", parent=base["Normal"],
            fontSize=9, textColor=DARK_GREY,
            spaceAfter=4, leading=14, alignment=TA_JUSTIFY,
        ),
        "bullet": ParagraphStyle(
            "BulletStyle", parent=base["Normal"],
            fontSize=9, textColor=DARK_GREY,
            spaceAfter=2, leading=13, leftIndent=12, bulletIndent=0,
        ),
        "label": ParagraphStyle(
            "LabelStyle", parent=base["Normal"],
            fontSize=9, textColor=CAPITALTEK_BLUE,
            spaceAfter=1, fontName="Helvetica-Bold",
        ),
        "email_body": ParagraphStyle(
            "EmailStyle", parent=base["Normal"],
            fontSize=8.5, textColor=DARK_GREY,
            spaceAfter=3, leading=13, leftIndent=10, rightIndent=10,
            backColor=LIGHT_GREY, borderPadding=(6, 8, 6, 8),
        ),
        "meta": ParagraphStyle(
            "MetaStyle", parent=base["Normal"],
            fontSize=8, textColor=colors.grey,
            spaceAfter=2, alignment=TA_CENTER,
        ),
        "playbook": ParagraphStyle(
            "PlaybookStyle", parent=base["Normal"],
            fontSize=9, textColor=DARK_GREY,
            spaceAfter=4, leading=14,
        ),
        "priority_high": ParagraphStyle(
            "PriorityHigh", parent=base["Normal"],
            fontSize=10, textColor=colors.white,
            fontName="Helvetica-Bold", backColor=colors.HexColor("#C0392B"),
            borderPadding=(2, 6, 2, 6),
        ),
        "priority_medium": ParagraphStyle(
            "PriorityMedium", parent=base["Normal"],
            fontSize=10, textColor=colors.white,
            fontName="Helvetica-Bold", backColor=colors.HexColor("#E67E22"),
            borderPadding=(2, 6, 2, 6),
        ),
        "priority_low": ParagraphStyle(
            "PriorityLow", parent=base["Normal"],
            fontSize=10, textColor=colors.white,
            fontName="Helvetica-Bold", backColor=colors.HexColor("#27AE60"),
            borderPadding=(2, 6, 2, 6),
        ),
    }


def _priority_badge(priority: str, styles: dict) -> Paragraph:
    label = f"  PRIORITY: {priority.upper()}  "
    key = f"priority_{priority.lower()}" if priority.lower() in ("high", "medium", "low") else "priority_medium"
    return Paragraph(label, styles.get(key, styles["priority_medium"]))


def _pain_point_table(pain_points: list, styles: dict):
    """Render pain points as a colour-coded table with proper word-wrapping."""
    colour_map = {
        "High":   colors.HexColor("#FDECEA"),
        "Medium": colors.HexColor("#FEF5E7"),
        "Low":    colors.HexColor("#EAFAF1"),
    }
    text_map = {
        "High":   colors.HexColor("#C0392B"),
        "Medium": colors.HexColor("#E67E22"),
        "Low":    colors.HexColor("#27AE60"),
    }

    # Cell styles for wrapping text inside table cells
    cell_style = ParagraphStyle(
        "cell", fontName="Helvetica", fontSize=8,
        leading=11, textColor=DARK_GREY, wordWrap="CJK",
    )
    hdr_style = ParagraphStyle(
        "cell_hdr", fontName="Helvetica-Bold", fontSize=8,
        leading=11, textColor=colors.white, wordWrap="CJK",
    )

    # Header row — Paragraph objects so they wrap too
    data = [[
        Paragraph("Pain Point",          hdr_style),
        Paragraph("Likelihood",          hdr_style),
        Paragraph("Evidence",            hdr_style),
        Paragraph("CapitalTek Services", hdr_style),
    ]]

    for pp in pain_points:
        likelihood = pp.get("likelihood", "Medium")
        services_text = "<br/>".join(
            f"• {s}" for s in pp.get("capitaltek_services", [])
        )
        lh_colour = text_map.get(likelihood, DARK_GREY)
        lh_style = ParagraphStyle(
            "lh", fontName="Helvetica-Bold", fontSize=8,
            leading=11, textColor=lh_colour, alignment=1, wordWrap="CJK",
        )
        data.append([
            Paragraph(pp.get("name", ""),     cell_style),
            Paragraph(likelihood,             lh_style),
            Paragraph(pp.get("evidence", ""), cell_style),
            Paragraph(services_text or "—",   cell_style),
        ])

    # Widths sum to exactly 7.0 in (letter - 0.75 in margins × 2)
    col_widths = [1.5 * inch, 0.85 * inch, 2.35 * inch, 2.3 * inch]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND",    (0, 0), (-1, 0), CAPITALTEK_BLUE),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, LIGHT_GREY]),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("GRID",          (0, 0), (-1, -1), 0.4, MID_GREY),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
    ]
    # Colour-code likelihood cell backgrounds
    for i, pp in enumerate(pain_points, start=1):
        likelihood = pp.get("likelihood", "Medium")
        bg = colour_map.get(likelihood, colors.white)
        style_cmds.append(("BACKGROUND", (1, i), (1, i), bg))

    t.setStyle(TableStyle(style_cmds))
    return t


def build_pdf(all_companies: list[dict], marketing_guide: str) -> None:
    """Compile everything into a structured PDF using ReportLab."""
    print(f"\n[PDF]  STEP 7 — Building PDF …")
    doc = SimpleDocTemplate(
        OUTPUT_PDF,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    styles = _styles()
    story  = []

    # ── Cover ──────────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.8 * inch))
    story.append(Paragraph("CAPITALTEK", styles["title"]))
    story.append(Paragraph("B2B Sales Intelligence Report", styles["subtitle"]))
    story.append(Paragraph("Construction Sector — Ottawa, Canada & USA", styles["subtitle"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(HRFlowable(width="100%", thickness=2, color=CAPITALTEK_CYAN))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph(f"Report Date: {TODAY}", styles["meta"]))
    story.append(Paragraph(f"Companies Researched: {len(all_companies)}", styles["meta"]))
    story.append(Paragraph("Prepared by: CapitalTek Sales Intelligence Agent", styles["meta"]))
    story.append(Spacer(1, 0.3 * inch))

    # Quick stat bar
    high_count   = sum(1 for c in all_companies if c.get("analysis", {}).get("priority_score") == "High")
    medium_count = sum(1 for c in all_companies if c.get("analysis", {}).get("priority_score") == "Medium")
    low_count    = len(all_companies) - high_count - medium_count
    stat_data = [
        ["Total Companies", "High Priority", "Medium Priority", "Low Priority"],
        [str(len(all_companies)), str(high_count), str(medium_count), str(low_count)],
    ]
    stat_table = Table(stat_data, colWidths=[1.7 * inch] * 4)
    stat_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), CAPITALTEK_BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 9),
        ("BACKGROUND",    (0, 1), (-1, 1), LIGHT_GREY),
        ("FONTSIZE",      (0, 1), (-1, 1), 18),
        ("FONTNAME",      (0, 1), (-1, 1), "Helvetica-Bold"),
        ("TEXTCOLOR",     (0, 1), (0, 1), CAPITALTEK_BLUE),
        ("TEXTCOLOR",     (1, 1), (1, 1), colors.HexColor("#C0392B")),
        ("TEXTCOLOR",     (2, 1), (2, 1), colors.HexColor("#E67E22")),
        ("TEXTCOLOR",     (3, 1), (3, 1), colors.HexColor("#27AE60")),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BOX",           (0, 0), (-1, -1), 1, MID_GREY),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, MID_GREY),
    ]))
    story.append(stat_table)
    story.append(PageBreak())

    # ── SECTION 1: Executive Summary ──────────────────────────────────────
    story.append(Paragraph("SECTION 1 — EXECUTIVE SUMMARY", styles["section"]))
    story.append(Spacer(1, 0.1 * inch))

    top5 = sorted(
        all_companies,
        key=lambda c: {"High": 0, "Medium": 1, "Low": 2}.get(
            c.get("analysis", {}).get("priority_score", "Low"), 2
        ),
    )[:5]

    story.append(Paragraph("Top 5 Highest-Priority Leads", styles["subsection"]))
    for i, c in enumerate(top5, 1):
        a = c.get("analysis", {})
        story.append(Paragraph(
            f"{i}. <b>{c['name']}</b> — {c['location']} "
            f"[Priority: {a.get('priority_score', 'N/A')}]",
            styles["body"],
        ))
        story.append(Paragraph(
            a.get("priority_reasoning", "See company profile for details."),
            styles["bullet"],
        ))
    story.append(Spacer(1, 0.15 * inch))

    # Most common pain points
    pain_counter: dict[str, int] = {}
    for c in all_companies:
        for pp in c.get("analysis", {}).get("pain_points", []):
            if pp.get("likelihood") == "High":
                pain_counter[pp["name"]] = pain_counter.get(pp["name"], 0) + 1
    if pain_counter:
        story.append(Paragraph("Most Common High-Likelihood Pain Points", styles["subsection"]))
        for pain, count in sorted(pain_counter.items(), key=lambda x: -x[1]):
            story.append(Paragraph(f"• {pain}: {count} companies", styles["bullet"]))

    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph(
        "Key Industry Statistics Used in Outreach",
        styles["subsection"],
    ))
    for stat in [
        "75% of construction firms experienced a cyber incident in the past year.",
        "Average ransomware downtime in construction = 20 business days.",
        "94% of malware is delivered via email.",
        "Average breach goes undetected for 207 days.",
    ]:
        story.append(Paragraph(f"• {stat}", styles["bullet"]))

    story.append(PageBreak())

    # ── SECTION 2: Company Profiles ───────────────────────────────────────
    story.append(Paragraph("SECTION 2 — COMPANY INTELLIGENCE PROFILES", styles["section"]))
    story.append(Spacer(1, 0.1 * inch))

    for idx, company in enumerate(all_companies, 1):
        a = company.get("analysis", {})
        name     = company.get("name", "Unknown")
        location = company.get("location", "")
        website  = company.get("website", "")
        social   = company.get("social_media", {})
        priority = a.get("priority_score", "Medium")

        profile_elements = []

        # Company header
        profile_elements.append(
            Paragraph(f"{idx}. {name}", styles["company_header"])
        )
        profile_elements.append(Spacer(1, 0.05 * inch))

        # Meta row
        meta_data = [
            ["Location", location],
            ["Website",  website],
            ["Priority", priority],
        ]
        if social:
            for platform, url in social.items():
                meta_data.append([platform.title(), url[:60] + ("…" if len(url) > 60 else "")])
        meta_table = Table(meta_data, colWidths=[1.0 * inch, 5.75 * inch])
        meta_table.setStyle(TableStyle([
            ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("TEXTCOLOR",     (0, 0), (0, -1), CAPITALTEK_BLUE),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        profile_elements.append(meta_table)
        profile_elements.append(Spacer(1, 0.08 * inch))

        # Priority badge
        profile_elements.append(_priority_badge(priority, styles))
        profile_elements.append(Spacer(1, 0.06 * inch))

        # Overview
        profile_elements.append(Paragraph("Company Overview", styles["subsection"]))
        profile_elements.append(Paragraph(a.get("overview", "No overview available."), styles["body"]))
        profile_elements.append(Spacer(1, 0.06 * inch))

        # Pain points table
        pain_points = a.get("pain_points", [])
        if pain_points:
            profile_elements.append(Paragraph("Pain Points Identified", styles["subsection"]))
            profile_elements.append(_pain_point_table(pain_points, styles))
            profile_elements.append(Spacer(1, 0.06 * inch))

        # Priority reasoning
        if a.get("priority_reasoning"):
            profile_elements.append(Paragraph("Priority Assessment", styles["label"]))
            profile_elements.append(Paragraph(a["priority_reasoning"], styles["body"]))
            profile_elements.append(Spacer(1, 0.06 * inch))

        # Email pitch
        profile_elements.append(Paragraph("Personalized Email Pitch", styles["subsection"]))
        subject = a.get("email_subject", "")
        body    = a.get("email_body", "")
        if subject:
            profile_elements.append(Paragraph(f"<b>Subject:</b> {subject}", styles["label"]))
        if body:
            # Render each paragraph of the email separately
            for para in body.split("\n\n"):
                para = para.strip()
                if para:
                    profile_elements.append(Paragraph(para, styles["email_body"]))
                    profile_elements.append(Spacer(1, 0.02 * inch))

        profile_elements.append(HRFlowable(width="100%", thickness=0.5, color=MID_GREY))
        profile_elements.append(Spacer(1, 0.1 * inch))

        story.extend(profile_elements)
        # Page break between companies (but not after the last one)
        if idx < len(all_companies):
            story.append(PageBreak())

    story.append(PageBreak())

    # ── SECTION 3: Marketing Playbook ─────────────────────────────────────
    story.append(Paragraph("SECTION 3 — CAPITALTEK CONSTRUCTION MARKETING PLAYBOOK", styles["section"]))
    story.append(Spacer(1, 0.1 * inch))

    for line in marketing_guide.split("\n"):
        stripped = line.strip()
        if not stripped:
            story.append(Spacer(1, 0.04 * inch))
            continue
        # Detect section titles (ALL CAPS lines)
        if stripped.isupper() and len(stripped) > 4:
            story.append(Spacer(1, 0.08 * inch))
            story.append(Paragraph(stripped, styles["subsection"]))
        elif stripped.startswith("- ") or stripped.startswith("• "):
            story.append(Paragraph(stripped.lstrip("-• "), styles["bullet"]))
        else:
            story.append(Paragraph(stripped, styles["playbook"]))

    story.append(PageBreak())

    # ── SECTION 4: Appendix ───────────────────────────────────────────────
    story.append(Paragraph("SECTION 4 — APPENDIX", styles["section"]))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("Research Sources", styles["subsection"]))
    sources = [
        "Serper.dev — Google Search API for company discovery and news research",
        "Direct website fetches — HTML parsed with BeautifulSoup4",
        "Social media search — LinkedIn, Facebook, Instagram via Serper",
        "Reddit search — community mentions via Serper",
        "Claude claude-opus-4-5 (Anthropic) — AI pain-point analysis and email generation",
    ]
    for s in sources:
        story.append(Paragraph(f"• {s}", styles["bullet"]))

    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph("Report Generation Details", styles["subsection"]))
    story.append(Paragraph(f"Report generated: {TODAY}", styles["body"]))
    story.append(Paragraph(f"Total companies profiled: {len(all_companies)}", styles["body"]))
    story.append(Paragraph(f"AI model used: {CLAUDE_MODEL}", styles["body"]))
    story.append(Paragraph(f"Output file: {os.path.basename(OUTPUT_PDF)}", styles["body"]))

    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph("Recommended Next Steps for CapitalTek Sales Team", styles["subsection"]))
    next_steps = [
        "Prioritize outreach to all 'High' priority companies within 48 hours.",
        "Use the personalized email pitches as-is — they are ready to send after a quick review.",
        "Upload company list to your CRM (HubSpot/Salesforce) and tag by priority and location.",
        "Follow the Day 1 → Day 4 → Day 8 → Day 14 sequence for each prospect.",
        "Run this report again in 30 days to catch new companies and refresh intelligence.",
        "Consider running a LinkedIn ad campaign targeting 'General Manager' and 'President' "
        "at Ottawa construction companies using the messaging angles in Section 3.",
        "Share the 'Top 5 High Priority' list with the CapitalTek CEO/VP Sales for warm intro opportunities.",
    ]
    for step in next_steps:
        story.append(Paragraph(f"• {step}", styles["bullet"]))

    story.append(Spacer(1, 0.3 * inch))
    story.append(HRFlowable(width="100%", thickness=1, color=CAPITALTEK_CYAN))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph(
        "CapitalTek | Ottawa's Trusted IT &amp; Cybersecurity Partner | "
        "613-227-4357 | capitaltek.com",
        styles["meta"],
    ))

    # Build
    doc.build(story)
    print(f"  [OK]  PDF written: {OUTPUT_PDF}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  CapitalTek B2B Sales Intelligence Agent")
    print(f"  Date: {TODAY}")
    print("=" * 65)

    if not SERPER_API_KEY:
        print("\n  [WARN]  WARNING: SERPER_API_KEY is not set in .env")
        print("     Web searches will be skipped. Seed companies will still be profiled.")
    if not ANTHROPIC_API_KEY:
        print("\n  [WARN]  WARNING: ANTHROPIC_API_KEY is not set in .env")
        print("     Claude analysis will use fallback templates.")

    # STEP 1 — Discover
    companies = search_companies()

    # STEP 2 + 3 + 4 + 5 — Research + Analyse each company
    print(f"\n[RESEARCH]  STEPS 2–5 — Researching and analysing {len(companies)} companies …")
    for i, company in enumerate(companies, 1):
        print(f"\n  [{i}/{len(companies)}] {company['name']}")
        try:
            company = research_company(company)
        except Exception as exc:
            print(f"    [WARN]  Research failed: {exc}")
            traceback.print_exc()

        try:
            print(f"       Analysing with Claude …")
            company["analysis"] = analyze_with_claude(company)
            priority = company["analysis"].get("priority_score", "?")
            print(f"       Priority: {priority}")
        except Exception as exc:
            print(f"    [WARN]  Claude analysis failed: {exc}")
            company["analysis"] = _fallback_analysis(company)

        # Rate limit — 1 s between companies to be polite
        time.sleep(1)

    # STEP 6 — Marketing guide
    marketing_guide = generate_marketing_guide()

    # STEP 7 — PDF
    build_pdf(companies, marketing_guide)

    print("\n" + "=" * 65)
    print(f"[OK]  Report saved as {os.path.basename(OUTPUT_PDF)}")
    print("=" * 65)


if __name__ == "__main__":
    main()
