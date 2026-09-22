# Python Scrape Pipeline + Dashboard

## Local setup
```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scraper.py
python -m http.server 8000     # http://localhost:8000
```

## Kaise kaam karta hai
1. `config.json` me sources define karo
2. `scraper.py` har source ko fetch + parse karta hai
3. Output → `data/latest.json` + `data/history/YYYY-MM-DD.json`
4. `index.html` us JSON ko fetch karke dashboard render karta hai
5. GitHub Actions har 6 ghante auto-run karke data commit karta hai

## Naya source add karna
`config.json` me `targets` array me push karo:
```json
{
  "name": "my_site",
  "url": "https://example.com/items",
  "container": ".item-card",
  "fields": { "title": "h2", "price": ".price" },
  "list_field": { "tags": ".tag" }
}
```
Bas. Koi code change nahi chahiye.

## GitHub Pages enable karna
Settings → Pages → Source: `main` branch, `/ (root)` → Save
URL: `https://<user>.github.io/<repo>/`
