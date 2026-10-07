"""Documents envoyés par l'administrateur → blocs lisibles par Claude, et découpe des figures.

PDF : envoyé tel quel (Claude lit le texte et l'image de chaque page). Images : envoyées telles quelles.
Word (.docx) : converti en texte par pandoc (formules Word → LaTeX exact) + images intégrées.
"""
import base64
import io
import os
import tempfile

from .client import IAErreur

MIMES = {
    'application/pdf': 'pdf',
    'image/png': 'image', 'image/jpeg': 'image', 'image/webp': 'image', 'image/gif': 'image',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
}
EXTENSIONS = {'pdf': 'application/pdf', 'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
              'webp': 'image/webp', 'gif': 'image/gif',
              'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
MAX_PDF = 25 * 1024 * 1024
MAX_IMAGE = 5 * 1024 * 1024
MAX_IMAGES = 10


def type_mime(nom, mime):
    ext = nom.rsplit('.', 1)[-1].lower() if '.' in nom else ''
    return EXTENSIONS.get(ext) or mime


def controler(fichiers):
    """fichiers : [(nom, mime, octets)]. Un PDF, ou un .docx, ou jusqu'à 10 images."""
    if not fichiers:
        raise IAErreur('Aucun fichier envoyé.')
    sortes = [MIMES.get(m) for _, m, _ in fichiers]
    if None in sortes:
        raise IAErreur('Format non pris en charge : PDF, Word (.docx) ou images (PNG, JPEG, WebP). '
                       'Un .doc doit d’abord être enregistré en .docx ou en PDF.')
    if ('pdf' in sortes or 'docx' in sortes) and len(fichiers) > 1:
        raise IAErreur('Un seul PDF ou un seul document Word à la fois (ou plusieurs images).')
    if len(fichiers) > MAX_IMAGES:
        raise IAErreur(f'{MAX_IMAGES} images au maximum.')
    for nom, mime, data in fichiers:
        limite = MAX_PDF if MIMES[mime] == 'pdf' else MAX_IMAGE if MIMES[mime] == 'image' else MAX_PDF
        if len(data) > limite:
            raise IAErreur(f'« {nom} » est trop lourd ({len(data) // (1024 * 1024)} Mo).')
    return sortes[0]


def _b64(data):
    return base64.b64encode(data).decode()


def _docx(data):
    """Texte Markdown (formules en LaTeX) et images extraites : (texte, {nom: (mime, octets)})."""
    try:
        import pypandoc
    except ImportError:
        raise IAErreur('Conversion Word indisponible sur le serveur : envoyer le document en PDF.')
    images = {}
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, 'doc.docx')
        with open(src, 'wb') as fh:
            fh.write(data)
        texte = pypandoc.convert_file(src, 'markdown', extra_args=['--wrap=none', f'--extract-media={d}/m'])
        for racine, _, noms in os.walk(os.path.join(d, 'm')):
            for n in noms:
                ext = n.rsplit('.', 1)[-1].lower()
                with open(os.path.join(racine, n), 'rb') as fh:
                    images[n] = (EXTENSIONS.get(ext, ''), fh.read())
        texte = texte.replace(f'{d}/m/media/', '').replace(f'{d}/m/', '')
    return texte, images


def blocs(fichiers):
    """Blocs de contenu du message utilisateur, et description pour la consigne."""
    sorte = controler(fichiers)
    contenu = []
    if sorte == 'pdf':
        nom, _, data = fichiers[0]
        contenu.append({'type': 'document', 'source': {'type': 'base64', 'media_type': 'application/pdf', 'data': _b64(data)}})
        return contenu, f'Le document est le PDF « {nom} » ({nb_pages(data)} page(s)).'
    if sorte == 'image':
        for i, (nom, mime, data) in enumerate(fichiers, 1):
            contenu.append({'type': 'text', 'text': f'Image {i} (« {nom} ») :'})
            contenu.append({'type': 'image', 'source': {'type': 'base64', 'media_type': mime, 'data': _b64(data)}})
        return contenu, f'Le document est composé de {len(fichiers)} image(s), dans l’ordre des pages.'
    nom, _, data = fichiers[0]
    texte, images = _docx(data)
    contenu.append({'type': 'text', 'text': f'Contenu du document Word « {nom} », converti en Markdown '
                    f'(les formules Word sont déjà en LaTeX exact : reprends-les telles quelles) :\n\n{texte}'})
    illisibles = []
    for n, (mime, octets) in images.items():
        if mime in ('image/png', 'image/jpeg', 'image/webp', 'image/gif') and len(octets) <= MAX_IMAGE:
            contenu.append({'type': 'text', 'text': f'Image intégrée « {n} » :'})
            contenu.append({'type': 'image', 'source': {'type': 'base64', 'media_type': mime, 'data': _b64(octets)}})
        else:
            illisibles.append(n)
    desc = f'Le document est le fichier Word « {nom} ».'
    if illisibles:
        desc += (' Images au format non lisible (WMF/EMF, souvent des formules d’anciens Word) : '
                 + ', '.join(illisibles) + ' — signale dans « doutes » tout passage qui en dépend.')
    return contenu, desc


def nb_pages(pdf):
    try:
        import pymupdf as fitz
        with fitz.open(stream=pdf, filetype='pdf') as doc:
            return doc.page_count
    except Exception:
        return '?'


def _png(img):
    out = io.BytesIO()
    img.save(out, format='PNG', optimize=True)
    return out.getvalue()


def figure(fichiers, spec):
    """Recadre une figure déclarée par l'IA → octets PNG. spec : {page|image|fichier, cadre}."""
    from PIL import Image
    sorte = controler(fichiers)
    cadre = spec.get('cadre')
    if sorte == 'docx':
        _, images = _docx(fichiers[0][2])
        n = spec.get('fichier')
        if n not in images:
            raise IAErreur(f'figure « {spec.get("nom")} » : image « {n} » introuvable dans le document Word')
        img = Image.open(io.BytesIO(images[n][1]))
        return _png(img.convert('RGBA') if img.mode in ('P', 'LA') else img)
    if not (isinstance(cadre, list) and len(cadre) == 4 and all(isinstance(v, (int, float)) for v in cadre)
            and 0 <= cadre[0] < cadre[2] <= 1 and 0 <= cadre[1] < cadre[3] <= 1):
        raise IAErreur(f'figure « {spec.get("nom")} » : cadre invalide {cadre}')
    if sorte == 'pdf':
        import pymupdf as fitz
        with fitz.open(stream=fichiers[0][2], filetype='pdf') as doc:
            p = int(spec.get('page') or 1)
            if not 1 <= p <= doc.page_count:
                raise IAErreur(f'figure « {spec.get("nom")} » : page {p} inexistante')
            page = doc[p - 1]
            r = page.rect
            clip = fitz.Rect(r.x0 + cadre[0] * r.width, r.y0 + cadre[1] * r.height,
                             r.x0 + cadre[2] * r.width, r.y0 + cadre[3] * r.height)
            pix = page.get_pixmap(dpi=200, clip=clip)
            return pix.tobytes('png')
    i = int(spec.get('image') or 1)
    if not 1 <= i <= len(fichiers):
        raise IAErreur(f'figure « {spec.get("nom")} » : image {i} inexistante')
    img = Image.open(io.BytesIO(fichiers[i - 1][2]))
    w, h = img.size
    return _png(img.crop((int(cadre[0] * w), int(cadre[1] * h), int(cadre[2] * w), int(cadre[3] * h))))
