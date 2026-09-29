"""Identité obligatoire d'un compte : prénom, nom, civilité, date de naissance et établissement.

Utilisé par l'onboarding (tout est exigé) et par la mise à jour du compte (on ne peut
pas vider un champ déjà rempli).
"""
import re
from datetime import date

from apps.caracteristics.models import School

MIN_AGE, MAX_AGE = 8, 100  # bornes de vraisemblance (élèves de collège/lycée, enseignants)

# Lettres de toutes les écritures (latin accentué, arabe…), espaces, apostrophes, traits d'union.
_NAME_RE = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ '’.\-])*$")


def _squash(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def clean_person_name(value, label):
    name = _squash(value)
    if not name:
        return None, f'{label} obligatoire.'
    if len(name) > 60:
        return None, f'{label} trop long (60 caractères au plus).'
    if not _NAME_RE.match(name):
        return None, f'{label} : lettres uniquement.'
    return name, None


def clean_birth_date(value):
    """« AAAA-MM-JJ » → (date, erreur). Refuse les dates futures ou invraisemblables."""
    try:
        born = date.fromisoformat(str(value or '').strip())
    except ValueError:
        return None, 'Date de naissance obligatoire (jour, mois, année).'
    today = date.today()
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    if born > today or not MIN_AGE <= age <= MAX_AGE:
        return None, 'Date de naissance invalide : vérifie l’année.'
    return born, None


def resolve_school(data):
    """Renvoie (school, school_name, erreur). Un établissement de la liste l'emporte sur le texte libre."""
    school_id = data.get('school_id')
    if school_id not in (None, ''):
        try:
            school = School.objects.get(pk=int(school_id))
        except (School.DoesNotExist, TypeError, ValueError):
            return None, None, 'Établissement introuvable.'
        return school, school.name, None
    name = _squash(data.get('school_name'))
    if not name:
        return None, None, 'Établissement obligatoire.'
    if not 3 <= len(name) <= 150:
        return None, None, 'Nom d’établissement invalide (3 à 150 caractères).'
    return None, name, None


def apply_identity(user, data, *, required):
    """Valide et applique prénom, nom et établissement, sans enregistrer.

    required=True : les trois sont exigés (onboarding). Sinon, seuls les champs présents
    dans `data` sont modifiés, et ils ne peuvent pas être vidés.
    Renvoie un message d'erreur, ou None.
    """
    for field, label in (('first_name', 'Prénom'), ('last_name', 'Nom')):
        if required or field in data:
            value, error = clean_person_name(data.get(field), label)
            if error:
                return error
            setattr(user, field, value)

    if required or 'gender' in data:
        gender = str(data.get('gender') or '').strip().upper()
        if gender not in ('M', 'F', 'N'):
            return 'Indique ta civilité (ou « Je préfère ne pas le dire »).'
        user.profile.gender = gender

    if required or 'birth_date' in data:
        born, error = clean_birth_date(data.get('birth_date'))
        if error:
            return error
        user.profile.birth_date = born

    if required or 'school_id' in data or 'school_name' in data:
        school, school_name, error = resolve_school(data)
        if error:
            return error
        user.profile.school = school
        user.profile.school_name = school_name
    return None

