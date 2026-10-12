"""Documents ↔ Word (.docx), par pandoc (déjà là pour l'IA : `pypandoc_binary`).

- Importer : formules Word (éditeur d'équations, OMML) → LaTeX exact `$…$` / `$$…$$`, images envoyées sur S3
  (URL stable `/api/files/<uuid>/download/`), titres, listes, tableaux, gras/italique/souligné.
  Les formules MathType (objets OLE) n'ont qu'un aperçu WMF/EMF illisible : elles sont signalées.
- Exporter : `$…$` → vraies équations Word modifiables (OMML), encadrés numérotés, sauts de page, en-tête FIDNI,
  orientation et marges du document, paragraphes centrés ou à droite.
"""
import html as htmlmod
import io
import os
import re
import tempfile
import zipfile

MAX_DOCX = 15 * 1024 * 1024
MAX_IMAGE = 5 * 1024 * 1024
MAX_IMAGES = 60
IMAGES_WEB = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif', 'webp': 'image/webp'}
SAUT = 'FIDNI-SAUT-DE-PAGE-7c1e'
FILE_RE = re.compile(r'/api/files/([0-9a-fA-F-]{32,36})/download/?')


class WordErreur(Exception):
    pass


def _pandoc():
    try:
        import pypandoc
    except ImportError:
        raise WordErreur('Conversion Word indisponible sur le serveur.')
    return pypandoc


# ── Importer ───────────────────────────────────────────────────────────────────────────────────────

def _math(tex, display):
    tex = htmlmod.unescape(tex).strip()
    tex = re.sub(r'\\rbrack\s?', ']', tex)
    tex = re.sub(r'\\lbrack\s?', '[', tex)
    tex = re.sub(r'\s*\n\s*', ' ', tex)
    tex = htmlmod.escape(tex, quote=False)
    return f'$${tex}$$' if display else f'${tex}$'


def _nettoyer_import(h):
    h = re.sub(r'<span class="math inline">\\\((.*?)\\\)</span>', lambda m: _math(m.group(1), False), h, flags=re.S)
    h = re.sub(r'<span class="math display">\\\[(.*?)\\\]</span>', lambda m: _math(m.group(1), True), h, flags=re.S)
    # Une formule centrée seule entre deux blocs : dans son paragraphe.
    h = re.sub(r'(^|\n)(\$\$.*?\$\$)(?=\n|$)', r'\1<p>\2</p>', h, flags=re.S)
    h = re.sub(r'<span class="underline">(.*?)</span>', r'<u>\1</u>', h, flags=re.S)
    h = re.sub(r'<span class="smallcaps">(.*?)</span>', r'\1', h, flags=re.S)
    h = re.sub(r'<colgroup>.*?</colgroup>', '', h, flags=re.S)
    h = re.sub(r'</?(figure|figcaption|section|header|nav|article|aside)\b[^>]*>', '', h)
    h = re.sub(r'<(/?)(div|span)\b[^>]*>', '', h)
    # Attributs : seuls ceux que l'éditeur comprend.
    def attrs(m):
        tag, rest = m.group(1), m.group(2)
        keep = []
        for name, val in re.findall(r'([\w:-]+)="([^"]*)"', rest):
            if (tag == 'img' and name in ('src', 'alt')) or (tag == 'a' and name == 'href') \
                    or (tag == 'ol' and name in ('start', 'type')) or (tag in ('td', 'th') and name in ('colspan', 'rowspan')):
                keep.append(f'{name}="{val}"')
        return f'<{tag}{"".join(" " + k for k in keep)}{" /" if tag == "img" else ""}>'
    h = re.sub(r'<(\w+)(\s[^>]*?)\s*/?>', attrs, h)
    h = re.sub(r'<p>\s*</p>', '', h)
    return h.strip()


def importer_docx(data, nom, user, request=None):
    """→ (titre, html, avertissements). Les images du document sont enregistrées pour `user`."""
    if len(data) > MAX_DOCX:
        raise WordErreur(f'Fichier trop lourd ({len(data) // (1024 * 1024)} Mo, {MAX_DOCX // (1024 * 1024)} Mo au plus).')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read('word/document.xml').decode('utf-8', 'ignore')
    except (zipfile.BadZipFile, KeyError):
        raise WordErreur('Ce fichier n’est pas un document Word (.docx). Un .doc doit d’abord être enregistré en .docx.')
    avertissements = []
    mathtype = len(re.findall(r'ProgID="Equation\.(?:DSMT|3)', xml))
    pypandoc = _pandoc()
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, 'doc.docx')
        with open(src, 'wb') as fh:
            fh.write(data)
        try:
            h = pypandoc.convert_file(src, 'html', extra_args=['--mathjax', '--wrap=none', f'--extract-media={d}/m'])
        except (RuntimeError, OSError) as e:
            raise WordErreur(f'Le document n’a pas pu être lu ({str(e)[:200]}).')
        h = _nettoyer_import(h)
        illisibles = 0
        envoyees = 0

        def image(m):
            nonlocal illisibles, envoyees
            chemin = htmlmod.unescape(m.group(1))
            ext = chemin.rsplit('.', 1)[-1].lower()
            plein = os.path.realpath(chemin if os.path.isabs(chemin) else os.path.join(os.getcwd(), chemin))
            if not plein.startswith(os.path.realpath(d) + os.sep) or not os.path.isfile(plein):
                plein = os.path.realpath(os.path.join(d, chemin))
            if ext not in IMAGES_WEB or not plein.startswith(os.path.realpath(d) + os.sep) or not os.path.isfile(plein):
                illisibles += 1
                return '<em>[image ou formule non convertie]</em>'
            if envoyees >= MAX_IMAGES or os.path.getsize(plein) > MAX_IMAGE:
                illisibles += 1
                return '<em>[image trop lourde, non importée]</em>'
            with open(plein, 'rb') as fh:
                octets = fh.read()
            envoyees += 1
            return f'<img src="{_enregistrer_image(octets, ext, user, request)}" alt="" />'

        h = re.sub(r'<img src="([^"]*)"[^>]*/>', image, h)
    if mathtype:
        avertissements.append(
            f'{mathtype} formule(s) MathType n’ont pas pu être converties (marquées « [image ou formule non convertie] »). '
            'Dans Word : MathType › Convertir les équations › « Équation Office (OMML) », puis importe à nouveau.')
    elif illisibles:
        avertissements.append(f'{illisibles} image(s) dans un format ancien (WMF/EMF) ou trop lourdes n’ont pas été importées.')
    titre = (re.sub(r'\.docx?$', '', os.path.basename(nom or ''), flags=re.I).strip() or 'Document importé')[:200]
    return titre, h, avertissements


def _enregistrer_image(octets, ext, user, request):
    from django.core.files.base import ContentFile
    from apps.uploads.models import FileAttachment
    nom = f'word.{ext}'
    att = FileAttachment.objects.create(file=ContentFile(octets, name=nom), file_name=nom, file_size=len(octets),
                                        file_type='image', mime_type=IMAGES_WEB[ext], uploaded_by=user)
    path = f'/api/files/{att.id}/download/'
    return request.build_absolute_uri(path) if request else path


# ── Exporter ───────────────────────────────────────────────────────────────────────────────────────

LABELS = {'theorem': 'Théorème', 'property': 'Propriété', 'definition': 'Définition', 'lemma': 'Lemme',
          'corollary': 'Corollaire', 'example': 'Exemple', 'remark': 'Remarque', 'proof': 'Preuve',
          'method': 'Méthode', 'warning': 'Attention'}
NUMEROTES = {'theorem', 'property', 'definition', 'lemma', 'corollary', 'example'}
ENTETE_LIGNE = [('etablissement', ''), ('classe', ''), ('annee', ''), ('professeur', 'Professeur : '), ('duree', 'Durée : ')]


def _tex_export(tex):
    """LaTeX de l'éditeur → LaTeX que pandoc sait mettre en équation Word."""
    tex = re.sub(r'(?<!\\)%[^\n]*(\n|$)', '', tex)                # commentaires (marque %TV des tableaux de variations)
    tex = re.sub(r'\\tag\*?\{([^{}]*)\}', r'\\qquad (\1)', tex)   # numéro d'équation en fin de ligne
    tex = tex.replace('\\placeholder{}', '\\square')
    return tex


def _tableau(tex):
    """`\\begin{array}{c|cc} … \\hline …` (tableau de variations, tableau de signes) → vrai tableau Word,
    une formule par case : une équation Word n'a pas de traits."""
    tex = _tex_export(htmlmod.unescape(tex)).strip()
    m = re.fullmatch(r'\\begin\{array\}\{([^{}]*)\}(.*)\\end\{array\}', tex, flags=re.S)
    if not m or '\\begin{array}' in m.group(2) or ('|' not in m.group(1) and '\\hline' not in m.group(2)):
        return None
    lignes = [ligne.replace('\\hline', '').strip() for ligne in re.split(r'\\\\', m.group(2))]
    lignes = [ligne for ligne in lignes if ligne]
    cases = lambda ligne: ''.join(  # noqa: E731
        f'<td>{"$" + htmlmod.escape(c.strip(), quote=False) + "$" if c.strip() else ""}</td>' for c in ligne.split('&'))
    return '<table><tbody>' + ''.join(f'<tr>{cases(ligne)}</tr>' for ligne in lignes) + '</tbody></table>'


def _attr(attrs, nom):
    m = re.search(rf'\b{nom}="([^"]*)"', attrs)
    return htmlmod.unescape(m.group(1)) if m else None


def _html_export(doc):
    h = doc.html or ''
    h = re.sub(r'<p>\s*\$\$((?:(?!</p>).)+?)\$\$\s*</p>', lambda m: _tableau(m.group(1)) or m.group(0), h, flags=re.S)
    # Formules : pandoc lit `$…$` (extension tex_math_dollars) ; on retouche leur LaTeX.
    h = re.sub(r'(?<!\\)\$\$(.+?)(?<!\\)\$\$', lambda m: '$$' + _tex_export(m.group(1)) + '$$', h, flags=re.S)
    h = re.sub(r'(?<![\\$])\$(?!\$)(.+?)(?<!\\)\$', lambda m: '$' + _tex_export(m.group(1)) + '$', h, flags=re.S)
    # Paragraphes centrés ou à droite : styles « Centré » / « Droite » (réglés dans styles.xml).
    def align(m):
        style = re.search(r'text-align:\s*(center|right)', m.group(1))
        if not style:
            return m.group(0)
        return f'<div custom-style="{"Centré" if style.group(1) == "center" else "Droite"}"><p>{m.group(2)}</p></div>'
    h = re.sub(r'<p(\s[^>]*)>(.*?)</p>', align, h, flags=re.S)
    # Encadrés (numérotés comme dans l'éditeur) et sauts de page : les <div> sont suivis avec une pile.
    out, pile, compte, pos = [], [], {}, 0
    for m in re.finditer(r'<(/?)div\b([^>]*)>', h):
        out.append(h[pos:m.start()])
        pos = m.end()
        if m.group(1):
            sorte = pile.pop() if pile else 'div'
            out.append({'encadre': '</blockquote>', 'saut': '', 'div': '</div>'}[sorte])
            continue
        attrs = m.group(2)
        if 'data-page-break' in attrs:
            pile.append('saut')
            out.append(f'<p>{SAUT}</p>')
        elif 'data-callout-type' in attrs:
            t = _attr(attrs, 'data-callout-type') or 'remark'
            label = LABELS.get(t, 'Remarque')
            if t in NUMEROTES:
                compte[t] = compte.get(t, 0) + 1
                label += f' {compte[t]}'
            titre = (_attr(attrs, 'data-callout-title') or '').strip()
            if titre:
                label += f' ({htmlmod.escape(titre)})'
            pile.append('encadre')
            out.append(f'<blockquote><p><strong>{label}.</strong></p>')
        else:
            pile.append('div')
            out.append(m.group(0))
    out.append(h[pos:])
    return _entete_html(doc.entete or {}) + ''.join(out)


def _entete_html(e):
    if not isinstance(e, dict) or not e.get('actif'):
        return ''
    esc = lambda k: htmlmod.escape(str(e.get(k) or '').strip())  # noqa: E731
    parties = []
    if esc('type'):
        parties.append(f'<div custom-style="Centré"><p><strong>{esc("type")}</strong></p></div>')
    ligne = ' · '.join(f'{p}{esc(k)}' for k, p in ENTETE_LIGNE if esc(k))
    if ligne:
        parties.append(f'<div custom-style="Centré"><p>{ligne}</p></div>')
    if e.get('nom_prenom'):
        parties.append('<p>Nom et prénom : ……………………………………………………</p>')
    if esc('consignes'):
        parties.append(f'<p><em>{esc("consignes")}</em></p>')
    return ''.join(parties) + '<hr />'


def _images_locales(h, d):
    """Images du document : copiées depuis S3 dans le dossier de travail ; les autres sont retirées."""
    from apps.uploads.models import FileAttachment
    n = 0

    def image(m):
        nonlocal n
        src = htmlmod.unescape(m.group(1) or '')
        fm = FILE_RE.search(src)
        att = FileAttachment.objects.filter(pk=fm.group(1)).first() if fm and n < MAX_IMAGES else None
        if not att or not att.file:
            return ''
        ext = (att.file_name.rsplit('.', 1)[-1].lower() if '.' in att.file_name else 'png')
        if ext not in IMAGES_WEB:
            return ''
        try:
            with att.file.open('rb') as fh:
                octets = fh.read(MAX_IMAGE + 1)
        except Exception:
            return ''
        if len(octets) > MAX_IMAGE:
            return ''
        n += 1
        nom = f'img{n}.{ext}'
        with open(os.path.join(d, nom), 'wb') as fh:
            fh.write(octets)
        return f'<img src="{nom}" />'

    return re.sub(r'<img\b[^>]*?src="([^"]*)"[^>]*>', image, h)


BORDURES = '<w:tblBorders>' + ''.join(
    f'<w:{c} w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
    for c in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV')) + '</w:tblBorders>'


def _bordures(m):
    """Tableaux tracés comme dans l'éditeur (l'ordre des éléments de tblPr compte pour Word)."""
    pr = m.group(1)
    if '<w:tblBorders' in pr:
        return m.group(0)
    for suivant in ('<w:shd', '<w:tblLayout', '<w:tblCellMar', '<w:tblLook', '<w:tblCaption', '<w:tblDescription'):
        i = pr.find(suivant)
        if i >= 0:
            return '<w:tblPr>' + pr[:i] + BORDURES + pr[i:] + '</w:tblPr>'
    return '<w:tblPr>' + pr + BORDURES + '</w:tblPr>'


def _retoucher_docx(chemin, doc):
    """Sauts de page, format de page et styles d'alignement dans le .docx produit par pandoc."""
    paysage = doc.orientation == 'paysage'
    w, hgt = (16838, 11906) if paysage else (11906, 16838)
    marges = {'normale': (2.5, 2.5), 'etroite': (1.27, 1.27), 'large': (3.5, 2.5)}.get(doc.marges, (2.5, 2.5))
    tw = lambda cm: int(round(cm / 2.54 * 1440))  # noqa: E731
    sect = (f'<w:pgSz w:w="{w}" w:h="{hgt}"{" w:orient=\"landscape\"" if paysage else ""}/>'
            f'<w:pgMar w:top="{tw(marges[1])}" w:right="{tw(marges[0])}" w:bottom="{tw(marges[1])}" '
            f'w:left="{tw(marges[0])}" w:header="709" w:footer="709" w:gutter="0"/>')
    buf = io.BytesIO()
    with zipfile.ZipFile(chemin) as zin, zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == 'word/document.xml':
                x = data.decode('utf-8')
                x = re.sub(r'<w:p>(?:(?!</w:p>).)*?' + SAUT + r'.*?</w:p>',
                           '<w:p><w:r><w:br w:type="page"/></w:r></w:p>', x, flags=re.S)
                x = re.sub(r'<w:sectPr>(.*?)</w:sectPr>', lambda m: '<w:sectPr>' + m.group(1) + sect + '</w:sectPr>', x,
                           count=1, flags=re.S)
                x = re.sub(r'<w:tblPr>(.*?)</w:tblPr>', _bordures, x, flags=re.S)
                data = x.encode('utf-8')
            elif item.filename == 'word/styles.xml':
                x = data.decode('utf-8')
                for nom, jc in (('Centré', 'center'), ('Droite', 'right')):
                    x = re.sub(rf'(<w:style [^>]*w:styleId="{nom}"[^>]*>.*?)(</w:style>)',
                               lambda m: m.group(1) + f'<w:pPr><w:jc w:val="{jc}"/></w:pPr>' + m.group(2), x, count=1, flags=re.S)
                data = x.encode('utf-8')
            zout.writestr(item, data)
    return buf.getvalue()


def exporter_docx(doc):
    """Document → octets .docx."""
    pypandoc = _pandoc()
    with tempfile.TemporaryDirectory() as d:
        h = _images_locales(_html_export(doc), d)
        src, dst = os.path.join(d, 'doc.html'), os.path.join(d, 'doc.docx')
        with open(src, 'w', encoding='utf-8') as fh:
            fh.write(f'<html><head><meta charset="utf-8"></head><body>{h}</body></html>')
        try:
            pypandoc.convert_file(src, 'docx', format='html+tex_math_dollars', outputfile=dst,
                                  extra_args=[f'--resource-path={d}'], cworkdir=d)
        except (RuntimeError, OSError) as e:
            raise WordErreur(f'La conversion en Word a échoué ({str(e)[:200]}).')
        return _retoucher_docx(dst, doc)
