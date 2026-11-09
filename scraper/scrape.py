#!/usr/bin/env python3
"""每天用 Playwright 读取各博物馆官网，规则解析开放时间/票价/优惠/展览，输出 data/museums.json。

不依赖任何付费 API。解析是启发式的：
- 某字段解析不出来时，保留上次的值；整个馆失败时标记 stale。
- 与上次相比票价/开放时间/优惠有变化，记入 changes（前端高亮 7 天）。
- 遵守 robots.txt，使用诚实的爬虫 User-Agent。

用法: python scraper/scrape.py [--only id1,id2] [--dump DIR]
"""
import argparse, datetime as dt, json, re, sys, urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse
import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "museums.json"
UA = "MuseumUpdatesBot/1.0 (personal project; daily fetch)"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAYNAMES = {"mon": "mon|monday|mandag", "tue": "tue|tues|tuesday|tirsdag", "wed": "wed|wednesday|onsdag",
            "thu": "thu|thur|thurs|thursday|torsdag", "fri": "fri|friday|fredag",
            "sat": "sat|saturday|lørdag", "sun": "sun|sunday|søndag"}
DAY_LOOKUP = {n: d for d, names in DAYNAMES.items() for n in names.split("|")}
DAY_RE = "|".join(sorted(DAY_LOOKUP, key=len, reverse=True))

# ---------------------------------------------------------------- 开放时间
T = r"(\d{1,2})(?:[.:](\d{2}))?\s*(am|pm)?"
TIME_RANGE = re.compile(rf"{T}\s*(?:-|–|—|to)\s*{T}", re.I)
LINE_RE = re.compile(
    rf"^\s*({DAY_RE})\b\.?(?:\s*(?:-|–|—|to)\s*({DAY_RE})\b\.?)?\s*[:\t ]\s*(.*)$", re.I)
DAY_ONLY = re.compile(rf"^\s*({DAY_RE})\b\.?\s*(\d{{1,2}}[./]\d{{1,2}})?\s*$", re.I)


def _hm(h, m, ap):
    h = int(h); m = int(m or 0)
    if ap:
        ap = ap.lower()
        h = h % 12 + (12 if ap == "pm" else 0)
    return f"{h:02d}:{m:02d}"


def parse_value(v):
    """'Closed' / '10.00 - 18.00' / '10:00 AM-05:00 PM' / '10 – 18' → 'closed' 或 'HH:MM-HH:MM'"""
    v = v.strip()
    if re.match(r"(closed|lukket)", v, re.I):
        return "closed"
    m = TIME_RANGE.match(v)
    if not m:
        return None
    h1, m1, a1, h2, m2, a2 = m.groups()
    if a1 is None and a2:
        a1 = a2 if int(h1) <= int(h2) or a2.lower() == "am" else "am"
    s, e = _hm(h1, m1, a1), _hm(h2, m2, a2)
    if not (0 <= int(s[:2]) < 24 and 0 <= int(e[:2]) < 24) or s >= e:
        return None
    return f"{s}-{e}"


def parse_hours(text):
    """逐行扫描；单日行覆盖前面的区间行。遇到第二次从周一开始的列表则停止（避免读到特别日期）。"""
    lines = [l for l in text.splitlines() if l.strip()]
    hours, started = {}, False
    i = 0
    while i < len(lines):
        line = lines[i]
        val = d1 = d2 = None
        m = LINE_RE.match(line)
        if m and (parsed := parse_value(m.group(3))):
            d1, d2, val = m.group(1), m.group(2), parsed
        else:
            m = DAY_ONLY.match(line)  # 星期和值分两行
            if m and i + 1 < len(lines) and (parsed := parse_value(lines[i + 1])):
                d1, val = m.group(1), parsed
                i += 1
        i += 1
        if val is None:
            if started and len(hours) >= 5:
                break
            continue
        a = DAYS.index(DAY_LOOKUP[d1.lower()])
        b = DAYS.index(DAY_LOOKUP[d2.lower()]) if d2 else a
        if a == 0 and b >= 4 or (a == 0 and not d2 and started and "mon" in hours and len(hours) >= 5):
            if "mon" in hours and len(hours) >= 5:
                break  # 第二轮周列表
        started = True
        for k in range(a, b + 1) if b >= a else list(range(a, 7)) + list(range(0, b + 1)):
            hours[DAYS[k]] = val
    return hours if len(hours) >= 5 else {}


# ---------------------------------------------------------------- 票价
AMOUNT = r"(?:DKK\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:DKK|kr\.?))|kr\.?\s*(\d+(?:[.,]\d+)?)"
AMOUNT_RE = re.compile(AMOUNT, re.I)
FREE_RE = re.compile(r"\b(free(?: entry| admission)?|gratis)\b", re.I)
SKIP_LABEL = re.compile(r"\b(annual|season|member|members|member.s|pass|from|total|guest|tour|workshop|k7|club)\b|per person|per year|copenhagen card", re.I)
AUDIENCE = re.compile(r"\b(child|children|kids?|under|youth|young|student|students|senior|adult|adults|visitors?)\b", re.I)
STOP = re.compile(r"^(annual pass|season ticket|annual passes?|membership)\b", re.I)


def _num(g):
    return float(next(x for x in g if x).replace(",", "."))


def parse_prices(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out, seen, seen_l = [], set(), []
    for i, line in enumerate(lines):
        if STOP.match(line) and out:
            break
        amts = [_num(m.groups()) for m in AMOUNT_RE.finditer(line)]
        label = AMOUNT_RE.sub("", line).strip(" :\t-–|").strip()
        note = ""
        if not amts and FREE_RE.search(line) and len(line) < 70:
            amts = [0.0]
            label = FREE_RE.sub("", label).strip(" :\t-–|")
            if not AUDIENCE.search(label):
                continue
        elif not label and amts and i > 0:  # 金额单独一行，标签在上一行
            label = lines[i - 1]
        label = re.sub(r"\([^)]*\)", "", label)
        label = re.sub(r"^ticket\s+|\s*[–-]\s*entry ticket$", "", label.strip(" :"), flags=re.I)
        label = re.sub(r"\s+", " ", label).strip(" :")
        if not amts or not label or len(label) > 60 or SKIP_LABEL.search(label):
            continue
        if re.search(r"[.!?]\s+\w", label) or "buy" in label.lower() and len(amts) == 1 and amts[0] == 0:
            continue
        if len(amts) == 2:
            note = f"线上价 {int(min(amts)) if min(amts).is_integer() else min(amts)} DKK"
        amt = max(amts)
        if label.lower() in seen or amt > 2000 or any(label.lower().startswith(o_l) and o['amount_dkk'] == amt for o_l, o in zip(seen_l, out)):
            continue
        if label.lower().startswith("buy your ticket online"):
            continue
        seen.add(label.lower()); seen_l.append(label.lower())
        out.append({"category": label[:1].upper() + label[1:], "amount_dkk": int(amt) if float(amt).is_integer() else amt,
                    **({"note": note} if note else {})})
        if len(out) >= 8:
            break
    return out


OFFER_RE = re.compile(r"(free (?:admission|entry)|gratis adgang|discount|% (?:off|discount)|rabat)", re.I)
OFFER_CTX = re.compile(r"(every|last|first|wednesday|tuesday|friday|evening|copenhagen card|children|under \d+|students?)", re.I)


def parse_offers(text):
    out, seen = [], set()
    for sent in re.split(r"(?<=[.!?])\s+|\n", text):
        s = sent.strip()
        if 20 <= len(s) <= 180 and OFFER_RE.search(s) and OFFER_CTX.search(s) and not re.search(r"annual|season pass|\bcafé\b|cafe|^note:", s, re.I):
            key = s.lower()[:60]
            if key not in seen:
                seen.add(key); out.append({"title": s})
        if len(out) >= 4:
            break
    return out


# ---------------------------------------------------------------- 展览
MONTHS = {m: i + 1 for i, names in enumerate([
    ["jan", "january", "januar"], ["feb", "february", "februar"], ["mar", "march", "marts"], ["apr", "april"],
    ["may", "maj"], ["jun", "june", "juni"], ["jul", "july", "juli"], ["aug", "august"], ["sep", "sept", "september"],
    ["oct", "okt", "october", "oktober"], ["nov", "november"], ["dec", "december"]]) for m in names}
MON = "|".join(sorted(MONTHS, key=len, reverse=True))
SEP = r"(?:–|—|-|to|til)"
RANGE_RE = re.compile(rf"(\d{{1,2}})\.?\s*({MON})?\.?\s*(\d{{4}})?\s*{SEP}\s*(\d{{1,2}})\.?\s*({MON})\.?\s*(\d{{4}})", re.I)
RANGE_US = re.compile(rf"({MON})\.?\s*(\d{{1,2}})(?:,?\s*(\d{{4}}))?\s*{SEP}\s*(?:({MON})\.?\s*)?(\d{{1,2}}),?\s*(\d{{4}})", re.I)
NUM_RANGE = re.compile(rf"(\d{{1,2}})[./](\d{{1,2}})[./](\d{{4}})\s*{SEP}\s*(\d{{1,2}})[./](\d{{1,2}})[./](\d{{4}})")


def parse_range(text):
    text = re.sub(r"\s+", " ", text)
    try:
        if m := NUM_RANGE.search(text):
            d1, m1, y1, d2, m2, y2 = map(int, m.groups())
            return dt.date(y1, m1, d1).isoformat(), dt.date(y2, m2, d2).isoformat()
        if m := RANGE_RE.search(text):
            d1, mo1, y1, d2, mo2, y2 = m.groups()
            mo2n = MONTHS[mo2.lower()]; mo1n = MONTHS[mo1.lower()] if mo1 else mo2n
            y2 = int(y2); y1 = int(y1) if y1 else y2
            s, e = dt.date(y1, mo1n, int(d1)), dt.date(y2, mo2n, int(d2))
            if s > e:
                s = s.replace(year=y1 - 1)
            return s.isoformat(), e.isoformat()
        if m := RANGE_US.search(text):
            mo1, d1, y1, mo2, d2, y2 = m.groups()
            mo1n = MONTHS[mo1.lower()]; mo2n = MONTHS[mo2.lower()] if mo2 else mo1n
            y2 = int(y2); y1 = int(y1) if y1 else y2
            s, e = dt.date(y1, mo1n, int(d1)), dt.date(y2, mo2n, int(d2))
            if s > e:
                s = s.replace(year=y1 - 1)
            return s.isoformat(), e.isoformat()
    except (ValueError, KeyError):
        pass
    return None, None


JS_LINKS = """(re) => { const rx = new RegExp(re); const out = [];
  for (const a of document.querySelectorAll('a[href]')) { if (!rx.test(a.href.split('#')[0])) continue;
    let box = a; for (let i = 0; i < 2 && box.parentElement && !['BODY','MAIN'].includes(box.parentElement.tagName); i++) box = box.parentElement;
    const h = a.querySelector('h1,h2,h3,h4') || box.querySelector('h1,h2,h3,h4');
    out.push({title: (a.textContent || '').trim(), heading: h ? h.textContent.trim() : '', href: a.href, ctx: box.innerText.slice(0, 600)}); }
  return out; }"""
JS_SELECT = """([sel, levels]) => [...document.querySelectorAll(sel)].map(el => { let box = el;
  for (let i = 0; i < levels && box.parentElement; i++) box = box.parentElement;
  const a = el.querySelector('a[href]') || el.closest('a[href]') || box.querySelector('a[href]');
  return {title: el.textContent.trim(), heading: '', href: a ? a.href : '', ctx: box.innerText.slice(0, 600)}; })"""
GENERIC = re.compile(r"^(read more|see the exhibition|learn more|se mere|læs mere|more|exhibitions?|current exhibitions?|upcoming exhibitions?|previous exhibitions?|permanent exhibitions?|visit)$", re.I)
PREFIX = re.compile(r"^(read more|læs mere|see more)( about)?\s*", re.I)


def tidy(t, strip=()):
    for s in strip:
        t = t.replace(s, " ")
    return re.sub(r"\s+", " ", PREFIX.sub("", re.sub(r"<br\s*/?>", ": ", t))).strip()


def scrape_exhibitions(page, cfg, today):
    load(page, cfg["url"])
    if cfg["mode"] == "links":
        raw = page.evaluate(JS_LINKS, cfg["link_re"])
    else:
        raw = page.evaluate(JS_SELECT, [cfg["item"], cfg.get("levels", 2)])
    items, seen = [], set()
    excl = {e.lower() for e in cfg.get("exclude", [])}
    for r in raw:
        title = tidy(r["title"].split("\n")[0], cfg.get("strip", ()))
        if not title or GENERIC.match(title):
            title = tidy(r["heading"].split("\n")[0], cfg.get("strip", ()))
        if not title or GENERIC.match(title) or not 3 <= len(title) <= 140 or title.lower() in excl:
            continue
        href = r["href"]; slug = href.rstrip("/").rsplit("/", 1)[-1]
        key = slug or title
        if key in seen:
            continue
        seen.add(key)
        s, e = parse_range(r["ctx"])
        if e and e < today.isoformat():
            continue
        items.append({"title": title, "url": href or cfg["url"], "start": s, "end": e})
    return items[: cfg.get("limit", 40)]


# ---------------------------------------------------------------- 抓取与对比
def load(page, url):
    resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
    if resp and resp.status >= 400:
        raise RuntimeError(f"HTTP {resp.status}")
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:  # 有些站点持续有网络活动，内容已渲染即可
        pass
    page.wait_for_timeout(500)



def robots_ok(url):
    p = urlparse(url)
    rp = urllib.robotparser.RobotFileParser(f"{p.scheme}://{p.netloc}/robots.txt")
    try:
        rp.read()
    except Exception:
        return True
    return rp.can_fetch(UA, url)


def get_text(ctx, url):
    if not robots_ok(url):
        print(f"  robots.txt disallows {url}", file=sys.stderr)
        return ""
    page = ctx.new_page()
    try:
        load(page, url)
        return page.inner_text("body")
    except Exception as e:
        print(f"  fetch failed {url}: {e}", file=sys.stderr)
        return ""
    finally:
        page.close()


def diff(old, new):
    ch = []
    op = {p["category"]: p.get("amount_dkk") for p in old.get("prices", [])}
    for p in new.get("prices", []):
        if p["category"] in op and op[p["category"]] != p.get("amount_dkk"):
            ch.append(f"票价变化：{p['category']} {op[p['category']]} → {p.get('amount_dkk')} DKK")
    if old.get("hours") and new.get("hours") and old["hours"] != new["hours"]:
        ch.append("开放时间有变化")
    ot = {o["title"] for o in old.get("offers", [])}
    if old.get("checked_at"):
        for o in new.get("offers", []):
            if o["title"] not in ot:
                ch.append(f"新优惠：{o['title'][:60]}")
    return ch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--dump", help="把各页面文本保存到该目录，便于调试规则")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright
    now = dt.datetime.now(dt.timezone.utc); today = dt.date.today()
    cfg = yaml.safe_load((ROOT / "scraper" / "museums.yaml").read_text(encoding="utf-8"))
    old = {}
    if OUT.exists():
        old = {m["id"]: m for m in json.loads(OUT.read_text(encoding="utf-8")).get("museums", [])}
    only = set(args.only.split(",")) if args.only else None
    museums, fails = [], 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(user_agent=UA, locale="en-GB")
        for m in cfg["museums"]:
            prev = old.get(m["id"], {})
            entry = {**prev, **{k: v for k, v in m.items() if k not in ("exhibitions", "pages")}, "exhibitions_url": m["exhibitions"]["url"]}
            if only and m["id"] not in only:
                museums.append(entry); continue
            print(f"[{m['id']}]")
            try:
                texts = {u: get_text(ctx, u) for u in m["pages"]}
                if args.dump:
                    Path(args.dump).mkdir(parents=True, exist_ok=True)
                    for i, (u, t) in enumerate(texts.items()):
                        (Path(args.dump) / f"{m['id']}_{i}.txt").write_text(t)
                if not any(texts.values()):
                    raise RuntimeError("no page could be fetched")
                hours_t = texts.get(m["hours_url"], "")
                tick_t = texts.get(m["tickets_url"], "")
                hours = parse_hours(hours_t) or next((h for t in texts.values() if (h := parse_hours(t))), {})
                for d in m.get("default_closed", []):
                    if hours:
                        hours.setdefault(d, "closed")
                prices = parse_prices(tick_t) or parse_prices(hours_t)
                offers = parse_offers(tick_t + "\n" + hours_t)
                page = ctx.new_page()
                try:
                    exhibitions = scrape_exhibitions(page, m["exhibitions"], today)
                finally:
                    page.close()
                new = {"hours": hours or prev.get("hours", {}), "prices": prices or prev.get("prices", []),
                       "offers": offers, "exhibitions": exhibitions or prev.get("exhibitions", [])}
                missing = [k for k, v in (("开放时间", hours), ("票价", prices), ("展览", exhibitions)) if not v]
                changes = [{"date": today.isoformat(), "text": t} for t in diff(prev, new)]
                kept = [c for c in prev.get("changes", []) if (today - dt.date.fromisoformat(c["date"])).days < 30]
                entry.update(new, scrape_status="ok" if not missing else "partial", checked_at=now.isoformat(timespec="seconds"),
                             changes=kept + changes, parse_missing=missing)
                entry.pop("scrape_error", None)
                print(f"  hours={len(hours)} days, prices={len(prices)}, offers={len(offers)}, exhibitions={len(exhibitions)}, changes={len(changes)}"
                      + (f"  (未解析: {','.join(missing)})" if missing else ""))
            except Exception as e:  # noqa: BLE001
                fails += 1
                entry.update(scrape_status="stale", scrape_error=str(e)[:200])
                print(f"  FAIL: {e}", file=sys.stderr)
            museums.append(entry)
        browser.close()
    OUT.write_text(json.dumps({"generated_at": now.isoformat(timespec="seconds"), "museums": museums},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"done: {len(museums) - fails}/{len(museums)} fetched")


if __name__ == "__main__":
    main()
