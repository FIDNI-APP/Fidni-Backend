# Fiches des documents « Groupe scolaire Sanaa » (M. Haddar) publiées sans établissement : ce nom n'est pas celui de la
# liste officielle (plusieurs « Sanaa »). Natsu a choisi Sanaa 5, Hay-Hassani (16/10/2026) ; l'import le traduit
# désormais (importing.ALIAS_ECOLES). Ici, les contenus déjà publiés, reconnus par leur clé d'import, reçoivent cet
# établissement s'ils n'en ont pas (un choix fait à la main sur le site est gardé). Retour arrière : rien.
from django.db import migrations

CLES = [
    "applications-1sm-ex1", "applications-1sm-ex10", "applications-1sm-ex11", "applications-1sm-ex12",
    "applications-1sm-ex2", "applications-1sm-ex3", "applications-1sm-ex4", "applications-1sm-ex5",
    "applications-1sm-ex6", "applications-1sm-ex7", "applications-1sm-ex8", "applications-1sm-ex9",
    "derivabilite-2sm-s2-ex1", "derivabilite-2sm-s2-ex10", "derivabilite-2sm-s2-ex11", "derivabilite-2sm-s2-ex12",
    "derivabilite-2sm-s2-ex13", "derivabilite-2sm-s2-ex2", "derivabilite-2sm-s2-ex3", "derivabilite-2sm-s2-ex4",
    "derivabilite-2sm-s2-ex5", "derivabilite-2sm-s2-ex6", "derivabilite-2sm-s2-ex7", "derivabilite-2sm-s2-ex8",
    "derivabilite-2sm-s2-ex9", "ds1-1sm-2026", "ds1-tcs-2014", "ds2-1sm-2014", "ds2-1sm-2016", "ds2-1sm-2020",
    "ds2-1sm-2020-rattrapage", "ds2-1sm-2021", "ds2-1sm-2022", "ds2-1sm-2023", "ds2-1sm-2024",
    "ds2-1sm-2024-benyounes", "ds2-1sm-2025", "ds2-2pc-2016", "ds2-2sm-2016", "ds2-2sm-2018", "ds2-2sm-2019",
    "ds2-2sm-2020", "ds2-2sm-2021", "ds2-2sm-2022", "ds2-2sm-2023", "ds2-2sm-2024", "ds2-2sm-2025",
    "ds2-2sm-rattrapage", "ds2-tcs-2016", "ds2-tcs-2017", "ds2-tcs-2020", "ds2-tcs-2021", "ds2-tcs-2022",
    "ds2-tcs-2023", "ds2-tcs-2024", "ds2-tcs-2025", "ensembles-1sm-s1-ex1", "ensembles-1sm-s1-ex10",
    "ensembles-1sm-s1-ex3", "ensembles-1sm-s1-ex4", "ensembles-1sm-s1-ex5", "ensembles-1sm-s1-ex6",
    "ensembles-1sm-s1-ex7", "ensembles-1sm-s1-ex9", "etude-fonctions-2pc-auxiliaire-sanaa",
    "etude-fonctions-2pc-serie-ex1", "etude-fonctions-2pc-serie-ex2", "etude-fonctions-2pc-serie-ex3",
    "etude-fonctions-2pc-serie-ex4", "etude-fonctions-2pc-serie-ex5", "etude-fonctions-2sm-sanaa-ex1",
    "etude-fonctions-2sm-sanaa-ex2", "etude-fonctions-2sm-sanaa-ex3", "etude-fonctions-2sm-sanaa-serie2-ex1",
    "etude-fonctions-2sm-sanaa-serie2-ex2", "etude-fonctions-prepa-ds2-2sm-ex1", "etude-fonctions-prepa-ds2-2sm-ex2",
    "etude-fonctions-prepa-ds2-2sm-ex3", "etude-fonctions-prepa-ds2-2sm-ex4", "etude-fonctions-prepa-ds2-2sm-ex5",
    "etude-fonctions-prepa-ds2-2sm-ex6", "methodes-etude-des-fonctions-2bac",
    *[f"ordre-tcs-ex{i}" for i in range(1, 42)], *[f"ordre-tcs-niv1-ex{i}" for i in range(1, 9)],
    *[f"representation-fonctions-2pc-ex{i}" for i in range(1, 8)], *[f"vecteurs-tcs-ex{i}" for i in range(1, 9)],
]


def forwards(apps, schema_editor):
    School = apps.get_model('caracteristics', 'School')
    Content = apps.get_model('things', 'Content')
    ecole = School.objects.filter(name='Sanaa 5', city='Hay-Hassani').first()
    if ecole is None:  # liste des établissements pas encore chargée (base de test vide)
        return
    Content.objects.filter(school__isnull=True, json_content__import__cle__in=CLES).update(school=ecole)


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0015_methode_retiree_des_solutions'),
        ('caracteristics', '0004_pc_svt'),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
