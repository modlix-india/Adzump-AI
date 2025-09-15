from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

async def scrape_website(url: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)  # wait for JS to load if needed
        html = await page.content()
        await browser.close()

    soup = BeautifulSoup(html, "html.parser")

    data = {
        "title": soup.title.string.strip() if soup.title else "",
        "meta": {
            "description": (
                soup.find("meta", attrs={"name": "description"}).get("content", "").strip()
                if soup.find("meta", attrs={"name": "description"}) else ""
            ),
            "keywords": (
                soup.find("meta", attrs={"name": "keywords"}).get("content", "").strip()
                if soup.find("meta", attrs={"name": "keywords"}) else ""
            )
        },
        "headings": {
            tag: [h.get_text(strip=True) for h in soup.find_all(tag)]
            for tag in ["h1", "h2", "h3", "h4", "h5", "h6"]
        },
        "paragraphs": [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)],
        "spans": [span.get_text(strip=True) for span in soup.find_all("span") if span.get_text(strip=True)],
        "divs": [div.get_text(strip=True) for div in soup.find_all("div") if div.get_text(strip=True)],
        "lists": {
            "unordered": [
                [li.get_text(strip=True) for li in ul.find_all("li")]
                for ul in soup.find_all("ul")
            ],
            "ordered": [
                [li.get_text(strip=True) for li in ol.find_all("li")]
                for ol in soup.find_all("ol")
            ]
        },
        "tables": [
            {
                "headers": [th.get_text(strip=True) for th in table.find_all("th")],
                "rows": [
                    [td.get_text(strip=True) for td in row.find_all("td")]
                    for row in table.find_all("tr") if row.find_all("td")
                ]
            }
            for table in soup.find_all("table")
        ],
        "links": [
            {"text": a.get_text(strip=True), "href": a["href"]}
            for a in soup.find_all("a", href=True)
        ],
        "images": [
            {"alt": img.get("alt", ""), "src": img["src"]}
            for img in soup.find_all("img", src=True)
        ]
    }

    return data
