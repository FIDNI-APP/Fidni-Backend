"""Pages des copies : un fichier envoyé (photo ou PDF scanné) → pages JPEG normalisées.

Chaque page est remise droite (orientation EXIF des photos de téléphone) et réduite à COPIES_IMAGE_COTE pixels sur
son plus grand côté : assez pour lire une écriture manuscrite, et une page coûte alors environ 2 000 jetons à l'IA.
"""
import io

from django.conf import settings

TAILLE_MAX = 25 * 1024 * 1024  # même limite que nginx (client_max_body_size)
IMAGES = {'image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'}
PDF = 'application/pdf'


class FichierRefuse(ValueError):
    """Message lisible par le professeur."""


def _jpeg(img, cote=None):
    from PIL import Image
    cote = cote or settings.COPIES_IMAGE_COTE
    if img.mode not in ('RGB', 'L'):
        fond = Image.new('RGB', img.size, 'white')
        img = img.convert('RGBA')
        fond.paste(img, mask=img.split()[-1])
        img = fond
    img.thumbnail((cote, cote))
    out = io.BytesIO()
    img.save(out, format='JPEG', quality=85, optimize=True)
    return out.getvalue(), img.width, img.height


def sorte(nom, mime, debut):
    """'pdf' | 'image' d'après le contenu (pas seulement l'extension annoncée)."""
    if debut[:5] == b'%PDF-':
        return 'pdf'
    if (mime or '').lower() in IMAGES or str(nom).lower().rsplit('.', 1)[-1] in ('jpg', 'jpeg', 'png', 'webp'):
        return 'image'
    raise FichierRefuse('Format non pris en charge : envoie une photo (JPEG, PNG) ou un PDF.')


def pages(donnees, nom='', mime='', limite=None):
    """Octets d'un fichier → [(jpeg, largeur, hauteur)], une entrée par page."""
    limite = limite or settings.COPIES_PAGES_MAX
    if len(donnees) > TAILLE_MAX:
        raise FichierRefuse('Fichier trop lourd (25 Mo au plus).')
    s = sorte(nom, mime, donnees)
    if s == 'image':
        from PIL import Image, ImageOps, UnidentifiedImageError
        try:
            img = Image.open(io.BytesIO(donnees))
            img = ImageOps.exif_transpose(img)
        except (UnidentifiedImageError, OSError):
            raise FichierRefuse('Image illisible.')
        return [_jpeg(img)]
    import pymupdf as fitz
    from PIL import Image
    try:
        doc = fitz.open(stream=donnees, filetype='pdf')
    except Exception:
        raise FichierRefuse('PDF illisible.')
    with doc:
        if doc.page_count > limite:
            raise FichierRefuse(f'Trop de pages ({doc.page_count}) : {limite} au plus.')
        out = []
        for page in doc:
            r = page.rect
            zoom = min(150 / 72, settings.COPIES_IMAGE_COTE / max(r.width, r.height, 1))
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
            out.append(_jpeg(img))
        return out


def nb_pages_pdf(donnees):
    import pymupdf as fitz
    try:
        with fitz.open(stream=donnees, filetype='pdf') as doc:
            return doc.page_count
    except Exception:
        raise FichierRefuse('PDF illisible.')


def page_pdf(donnees, numero, cote=None):
    """Une page (1…n) du PDF d'une classe → (jpeg, largeur, hauteur)."""
    import pymupdf as fitz
    from PIL import Image
    cote = cote or settings.COPIES_IMAGE_COTE
    with fitz.open(stream=donnees, filetype='pdf') as doc:
        page = doc[numero - 1]
        r = page.rect
        zoom = min(150 / 72, cote / max(r.width, r.height, 1))
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return _jpeg(Image.frombytes('RGB', (pix.width, pix.height), pix.samples), cote)


def entete(jpeg, part=0.28, cote=900):
    """Haut d'une page (là où l'élève écrit son nom), en niveaux de gris : peu de jetons pour lire les noms."""
    from PIL import Image
    img = Image.open(io.BytesIO(jpeg)).convert('L')
    img = img.crop((0, 0, img.width, max(1, int(img.height * part))))
    return _jpeg(img, cote)[0]
