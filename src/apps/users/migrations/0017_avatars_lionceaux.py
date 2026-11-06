"""Les comptes qui ont encore un avatar DiceBear, attribué au hasard, reçoivent un lionceau au hasard.

Les photos envoyées et les autres adresses (compte Google…) ne changent pas. Pas de retour arrière :
les avatars DiceBear n'étaient pas des choix des élèves.
"""
import random

from django.conf import settings
from django.db import migrations

DICEBEAR = 'https://api.dicebear.com/'
NB_LIONCEAUX = 36  # valeur figée : la liste du modèle peut évoluer après cette migration


def vers_lionceaux(apps, schema_editor):
    UserProfile = apps.get_model('users', 'UserProfile')
    base = settings.FRONTEND_URL.rstrip('/')
    profils = []
    for profil in UserProfile.objects.filter(avatar_url__startswith=DICEBEAR).only('id', 'avatar_url').iterator():
        profil.avatar_url = f'{base}/avatars/lion-{random.randint(1, NB_LIONCEAUX):02d}.webp'
        profils.append(profil)
    UserProfile.objects.bulk_update(profils, ['avatar_url'], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0016_nouveautes_vues'),
    ]

    operations = [
        migrations.RunPython(vers_lionceaux, migrations.RunPython.noop),
    ]
