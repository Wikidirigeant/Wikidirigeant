#!/usr/bin/env python3
"""
Génère search-index.json à partir des pages HTML du guide.

À relancer manuellement après toute modification de contenu :
    python tools/build-search-index.py

Stratégie : chaque page est découpée en "chunks" (un par section/article/
onglet/accordéon). Chaque chunk a un titre, un texte brut (pour la recherche)
et une URL (avec ancre #id quand c'est pertinent). Les ids nécessaires à
l'ancrage sont injectés directement dans le HTML source s'ils n'existent pas
déjà (idempotent : relancer le script ne duplique rien).
"""
import html
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NAV_LABELS = {
    "index.html": "Accueil",
    "generalites.html": "Généralités",
    "rh.html": "RH",
    "finances.html": "Finances & Sponsoring",
    "adoc.html": "ADOC",
    "autres-pratiques.html": "Autres pratiques",
    "pensez-y.html": "Pensez-y !",
    "calendrier-gouvernance.html": "Calendrier de gouvernance",
    "charte-photos.html": "Charte photos",
    "fiches-postes.html": "Fiches de postes",
    "equipementier.html": "Équipementier",
    "partenariat.html": "Partenariat",
    "arbitrage.html": "Arbitrage",
    "tournois-officiels.html": "Tournois officiels",
    "trophee-club.html": "Trophée club",
    "aides-au-club.html": "Aides au club",
}

TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
WS_RE = re.compile(r"\s+")


def slugify(text):
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "section"


def strip_tags(fragment):
    fragment = SCRIPT_STYLE_RE.sub(" ", fragment)
    text = TAG_RE.sub(" ", fragment)
    text = html.unescape(text)
    return WS_RE.sub(" ", text).strip()


def unique_slug(base, used):
    slug = base
    i = 2
    while slug in used:
        slug = f"{base}-{i}"
        i += 1
    used.add(slug)
    return slug


def inject_ids_h2(content, used_ids):
    """Ajoute id="slug" sur chaque <h2> qui n'en a pas déjà un (idempotent)."""
    def repl(m):
        attrs, raw_title = m.group(1), m.group(2)
        if 'id="' in attrs:
            return m.group(0)
        title = strip_tags(raw_title)
        if not title:
            return m.group(0)
        slug = unique_slug(slugify(title), used_ids)
        return f"<h2{attrs} id=\"{slug}\">{raw_title}</h2>"

    return re.sub(r"<h2([^>]*)>(.*?)</h2>", repl, content, flags=re.S)


def build_page_h2(path, filename):
    content = path.read_text(encoding="utf-8")
    used_ids = set(re.findall(r'<h2[^>]*\bid="([^"]+)"', content))
    content = inject_ids_h2(content, used_ids)
    path.write_text(content, encoding="utf-8")

    results = []
    headings = list(re.finditer(r'<h2[^>]*\bid="([^"]+)"[^>]*>(.*?)</h2>', content, re.S))
    for idx, m in enumerate(headings):
        slug = m.group(1)
        title = strip_tags(m.group(2))
        body_start = m.end()
        body_end = headings[idx + 1].start() if idx + 1 < len(headings) else len(content)
        body_text = strip_tags(content[body_start:body_end])
        if not title or not body_text:
            continue
        results.append(
            {
                "page": filename,
                "pageTitle": NAV_LABELS.get(filename, filename),
                "heading": title,
                "url": f"{filename}#{slug}",
                "text": body_text,
            }
        )
    return results


def build_finances(path):
    filename = "finances.html"
    content = path.read_text(encoding="utf-8")

    # Sections principales (h2)
    used_ids = set(re.findall(r'<h2[^>]*\bid="([^"]+)"', content))
    content = inject_ids_h2(content, used_ids)

    # Items d'accordéon (acc-item / acc-label / acc-body)
    used_acc_ids = set(re.findall(r'<div class="acc-item"[^>]*\bid="([^"]+)"', content))

    def acc_repl(m):
        full = m.group(0)
        if m.group(1):
            return full
        label_m = re.search(r'<span class="acc-label">(.*?)</span>', full, re.S)
        label = strip_tags(label_m.group(1)) if label_m else "accordeon"
        slug = unique_slug("acc-" + slugify(label), used_acc_ids)
        return full.replace('<div class="acc-item"', f'<div class="acc-item" id="{slug}"', 1)

    content = re.sub(
        r'<div class="acc-item"( id="[^"]*")?>.*?(?=<div class="acc-item"|</div>\s*</div>\s*</section>|\Z)',
        acc_repl,
        content,
        flags=re.S,
    )
    path.write_text(content, encoding="utf-8")

    results = build_page_h2(path, filename)

    for m in re.finditer(
        r'<div class="acc-item" id="([^"]+)">\s*<button class="acc-trigger"[^>]*>.*?'
        r'<span class="acc-label">(.*?)</span>.*?<div class="acc-body">(.*?)</div>\s*</div>',
        content,
        re.S,
    ):
        slug, raw_label, raw_body = m.group(1), m.group(2), m.group(3)
        label = strip_tags(raw_label)
        body = strip_tags(raw_body)
        if not label:
            continue
        results.append(
            {
                "page": filename,
                "pageTitle": NAV_LABELS[filename],
                "heading": label,
                "url": f"{filename}#{slug}",
                "text": body,
            }
        )
    return results


def build_fiches_postes(path):
    filename = "fiches-postes.html"
    content = path.read_text(encoding="utf-8")

    # Ajoute le script de gestion du hash s'il n'existe pas déjà
    if "fichesHashOpened" not in content:
        content = content.replace(
            "</script>\n\n</body>",
            "  window.fichesHashOpened = true;\n"
            "  if (location.hash.indexOf('#fiche-') === 0) {\n"
            "    var id = location.hash.replace('#fiche-', '');\n"
            "    var btn = document.querySelector('.tab-btn[onclick*=\"\\'' + id + '\\'\"]');\n"
            "    if (btn) showTab(id, btn);\n"
            "  }\n"
            "</script>\n\n</body>",
        )
        path.write_text(content, encoding="utf-8")

    results = []
    openings = list(re.finditer(r'<div id="fiche-([a-z]+)" class="fiche-page[^"]*">', content))
    for idx, m in enumerate(openings):
        fiche_id = m.group(1)
        body_start = m.end()
        body_end = openings[idx + 1].start() if idx + 1 < len(openings) else len(content)
        body = content[body_start:body_end]
        title_m = re.search(r'<div class="fbh-title">(.*?)</div>', body, re.S)
        title = strip_tags(title_m.group(1)) if title_m else fiche_id.title()
        text = strip_tags(body)
        if not text:
            continue
        results.append(
            {
                "page": filename,
                "pageTitle": NAV_LABELS[filename],
                "heading": title,
                "url": f"{filename}#fiche-{fiche_id}",
                "text": text,
            }
        )
    return results


def build_charte_photos(path):
    filename = "charte-photos.html"
    content = path.read_text(encoding="utf-8")

    used_ids = set(re.findall(r'<div class="article"[^>]*\bid="([^"]+)"', content))

    def art_repl(m):
        full = m.group(0)
        if m.group(1):
            return full
        title_m = re.search(r'<div class="article-title">(.*?)</div>', full, re.S)
        title = strip_tags(title_m.group(1)) if title_m else "article"
        slug = unique_slug("art-" + slugify(title), used_ids)
        return full.replace('<div class="article"', f'<div class="article" id="{slug}"', 1)

    content = re.sub(
        r'<div class="article"( id="[^"]*")?>.*?(?=<hr class="art-divider">|</div>\s*</div>\s*<div class="doc-foot)',
        art_repl,
        content,
        flags=re.S,
    )
    path.write_text(content, encoding="utf-8")

    results = []
    for m in re.finditer(
        r'<div class="article" id="([^"]+)">(.*?)(?=<hr class="art-divider">|<div class="doc-foot)',
        content,
        re.S,
    ):
        slug, body = m.group(1), m.group(2)
        title_m = re.search(r'<div class="article-title">(.*?)</div>', body, re.S)
        title = strip_tags(title_m.group(1)) if title_m else slug
        text = strip_tags(body)
        if not text:
            continue
        results.append(
            {
                "page": filename,
                "pageTitle": NAV_LABELS[filename],
                "heading": title,
                "url": f"{filename}#{slug}",
                "text": text,
            }
        )
    return results


def main():
    all_chunks = []

    special = {
        "finances.html": build_finances,
        "fiches-postes.html": build_fiches_postes,
        "charte-photos.html": build_charte_photos,
    }

    for filename in NAV_LABELS:
        path = ROOT / filename
        if not path.exists():
            continue
        if filename in special:
            all_chunks.extend(special[filename](path))
        else:
            all_chunks.extend(build_page_h2(path, filename))

    out_path = ROOT / "search-index.json"
    out_path.write_text(
        json.dumps(all_chunks, ensure_ascii=False, indent=0, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"{len(all_chunks)} chunks écrits dans {out_path}")


if __name__ == "__main__":
    main()
