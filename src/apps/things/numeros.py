"""Numéro d'un contenu dans son chapitre (15/11/2026, demande de Natsu).

Chaque type (exercice, devoir, leçon) a sa propre numérotation par niveau ET par chapitre : les exercices des
« Limites et continuité » de 2ème Bac SM vont de 1 à N, ceux des « Suites numériques » repartent à 1, et un chapitre
partagé par deux niveaux (2ème Bac SM et 2ème Bac PC/SVT) a une numérotation par niveau. Un contenu sans chapitre est
numéroté dans son niveau (chapitre vide). Les sujets du Bac national ne sont pas numérotés : ils ont leur rubrique (par
année) et ne doivent pas faire de trous dans la numérotation des devoirs de classe.

Une ligne `NumeroContenu` par couple (niveau, chapitre) du contenu : un exercice ou un devoir en a une (un seul niveau,
le dernier chapitre) ; une leçon peut en avoir plusieurs. Numéro donné à l'ordre d'arrivée (le suivant du plus grand
déjà donné) ; il ne change plus tant que le contenu reste dans ce niveau et ce chapitre. Changer de chapitre donne un
nouveau numéro à la fin du nouveau chapitre.

À ne pas confondre avec `Content.display_id` (un seul compteur par type pour tout le site, recherche « #12 » des
discussions, concours) ni avec l'identifiant des adresses (/exercises/<id>), qui ne changent pas.

Tenu à jour par les signaux (things/signals.py) quand les niveaux ou les chapitres d'un contenu changent ; un ajout en
masse qui contourne les signaux se rattrape avec `python manage.py numeroter_contenus`.
"""
import re

from django.db import IntegrityError, models, transaction


def paires(content):
    """Couples (niveau, chapitre) numérotés pour ce contenu : chaque chapitre avec chacun de ses niveaux qui est aussi
    un niveau du contenu ; sans chapitre, (niveau, None)."""
    niveaux = [lv.id for lv in content.class_levels.all()]
    chapitres = list(content.chapters.all())
    if not niveaux or content.is_national_exam:
        return set()
    if not chapitres:
        return {(lv, None) for lv in niveaux}
    out = set()
    for ch in chapitres:
        siens = {lv.id for lv in ch.class_levels.all()}
        for lv in niveaux:
            if not siens or lv in siens:
                out.add((lv, ch.id))
    # Chapitre d'aucun des niveaux du contenu (donnée incohérente) : on numérote quand même plutôt que rien.
    return out or {(lv, ch.id) for lv in niveaux for ch in chapitres}


def numeroter(content):
    """Met les numéros de ce contenu à jour (garde ceux qui restent valables). Renvoie {(niveau, chapitre): numéro}."""
    from .models import Content, NumeroContenu
    content = (Content.objects.filter(pk=content.pk if isinstance(content, Content) else content)
               .prefetch_related('class_levels', 'chapters__class_levels').first())
    if content is None:
        return {}
    voulues = paires(content)
    for essai in range(5):
        try:
            with transaction.atomic():
                lignes = list(NumeroContenu.objects.filter(content=content))
                gardees = {}
                for ligne in lignes:
                    cle = (ligne.class_level_id, ligne.chapter_id)
                    if cle in voulues and ligne.type == content.type and cle not in gardees:
                        gardees[cle] = ligne.numero
                    else:
                        ligne.delete()
                for lv, ch in sorted(voulues - set(gardees), key=lambda p: (p[0], p[1] or 0)):
                    dernier = (NumeroContenu.objects.filter(type=content.type, class_level_id=lv, chapter_id=ch)
                               .aggregate(m=models.Max('numero'))['m'])
                    NumeroContenu.objects.create(content=content, type=content.type, class_level_id=lv,
                                                 chapter_id=ch, numero=(dernier or 0) + 1)
                    gardees[(lv, ch)] = (dernier or 0) + 1
                return gardees
        except IntegrityError:
            # Deux contenus du même chapitre enregistrés au même instant : on reprend avec le numéro suivant.
            if essai == 4:
                raise
    return {}


def serialiser(content):
    """[{niveau, chapitre, numero}] (préchargé par things/listing.py : `numeros`)."""
    return [{'niveau': n.class_level_id, 'chapitre': n.chapter_id, 'numero': n.numero}
            for n in content.numeros.all()]


# Recherche par numéro (17/11/2026, Natsu : « je suis dans le chapitre de la dérivation, j'écris exercice 48, et
# l'exercice 48 apparaît »). Requête déjà normalisée (search_text.normalize : minuscules, sans accents) :
# « 48 », « #48 », « n° 48 », « no 48 », « numero 48 », « exercice 48 », « ex 48 », « devoir n° 3 », « DS 3 »…
_NUMERO_CHERCHE = re.compile(
    r'^(?:(?:exercices?|exos?|ex|devoirs?|ds|lecons?|cours|sujets?)\s*)?'
    r'(?:n\s*[°o]\.?|num(?:ero)?\.?|#)?\s*(\d{1,4})$')


def numero_cherche(requete):
    """Numéro demandé par une recherche (« exercice 48 » → 48), sinon None."""
    from .search_text import normalize
    m = _NUMERO_CHERCHE.match(normalize(requete))
    return int(m.group(1)) if m else None


def contenus_numero(numero, type_contenu=None, niveaux=(), chapitres=()):
    """Identifiants des contenus qui portent ce numéro, dans les niveaux et chapitres de la page (s'ils sont donnés)."""
    from .models import NumeroContenu
    qs = NumeroContenu.objects.filter(numero=numero)
    if type_contenu:
        qs = qs.filter(type=type_contenu)
    if niveaux:
        qs = qs.filter(class_level_id__in=niveaux)
    if chapitres:
        qs = qs.filter(chapter_id__in=chapitres)
    return qs.values('content_id')
