"""Programme officiel (apps/caracteristics/programme.py) : base après seeder = programme (chapitres de chaque niveau,
dans leur ordre ; théorèmes, domaines, rattachements), alias cohérents, traduction des anciens noms, annexe D de l'IA
(taille, aucun mot interne), données figées de la migration 0003 d'accord avec le programme."""
import importlib
import os
import re
import runpy
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-programme.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
from apps.caracteristics import programme as P  # noqa: E402
from apps.caracteristics.hubs import slug  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel, Subject, Subfield, Theorem  # noqa: E402
from apps.caracteristics.notions import NOTIONS, TRANSVERSAL  # noqa: E402

results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


TC, SM1, SM2, PC = P.TC, P.SM1, P.SM2, P.PC
DOMAINES = {'Algèbre', 'Analyse', 'Géométrie', 'Probabilités', 'Statistiques'}
maths = Subject.objects.get(name=P.MATIERE)

# ── Base après seeder = programme
ecarts = P.ecarts_base()
check('base = programme : chapitres', ecarts['chapitres'] == [], ecarts['chapitres'])
check('base = programme : théorèmes (domaine, chapitres, niveaux)', ecarts['theoremes'] == [], ecarts['theoremes'])
check('niveaux dans l\'ordre des menus', list(ClassLevel.objects.order_by('order').values_list('name', 'order')) == P.NIVEAUX)
for niveau, chapitres in P.PROGRAMME.items():
    level = ClassLevel.objects.get(name=niveau)
    got = [c.name for c in P.chapitres_du_niveau(level)]
    check(f'{niveau} : {len(chapitres)} chapitres dans l\'ordre du programme', got == [c['nom'] for c in chapitres], got)
    check(f'{niveau} : ordre 1…n', [c['ordre'] for c in chapitres] == list(range(1, len(chapitres) + 1)))
check('comptes : 14 / 17 / 13 / 13 chapitres, 42 lignes', [len(P.PROGRAMME[n]) for n in (TC, SM1, SM2, PC)] == [14, 17, 13, 13]
      and len(P.DOMAINE_CHAPITRE) == 42 and Chapter.objects.filter(subject=maths).count() == 42)
sm2 = [c['nom'] for c in P.PROGRAMME[SM2]]
check('décisions : Espaces vectoriels gardé juste après Structures algébriques ; Dénombrement hors 2ème SM ; scissions',
      sm2.index('Espaces vectoriels') == sm2.index('Structures algébriques') + 1 and 'Dénombrement' not in sm2
      and P.DECISIONS == {'fusion_espaces_vectoriels': False, 'detacher_denombrement_2sm': True, 'scinder_homonymes_1ere': True}
      and all(v in [c['nom'] for c in P.PROGRAMME[SM1]] and k not in [c['nom'] for c in P.PROGRAMME[SM1]]
              for k, v in P.SCISSIONS_1ERE.items()))
ev = P.chapitre(SM2, 'Espaces vectoriels')
sa = P.chapitre(SM2, 'Structures algébriques')
check('Espaces vectoriels : capacités 2.4.6 (sous-espace), 2.4.7, 2.4.8 et ses trois théorèmes',
      [re.search(r'\((2\.4\.\d)\)', x).group(1) for x in ev['capacites']] == ['2.4.6', '2.4.7', '2.4.8']
      and 'sous-espace' in ev['capacites'][0] and ev['theoremes'] == ['Sous-espaces vectoriels', 'Familles libres et génératrices',
                                                                     "Base et dimension d'un espace vectoriel"]
      and ev['domaine'] == 'Algèbre' and ev['hors_programme'])
check('Structures algébriques : 2.4.1 à 2.4.5 et le sous-groupe de 2.4.6, sans « aussi »',
      [re.search(r'\((2\.4\.\d)\)', x).group(1) for x in sa['capacites']] == ['2.4.1', '2.4.2', '2.4.3', '2.4.4', '2.4.5', '2.4.6']
      and 'sous-groupe' in sa['capacites'][-1] and 'sous-espace' not in sa['capacites'][-1] and sa['aussi'] == []
      and 'Produit scalaire et propriétés' not in P.DOMAINE_THEOREME)
check('1ère Bac SM : repères et « vu plus tard » (indicatifs), aucun champ « à valider »',
      sum(len(c['reperes']) for c in P.PROGRAMME[SM1]) > 50 and sum(len(c['vu_plus_tard']) for c in P.PROGRAMME[SM1]) >= 5
      and 'reperes' in P.CHAMPS_IA and 'vu_plus_tard' in P.CHAMPS_IA
      and not any('a_valider' in k for c in P.PROGRAMME[SM1] for k in c)
      and 'valider' not in (P.__doc__ or ''))

# ── Domaines
check('DOMAINE_THEOREME : 152 théorèmes, domaines connus', len(P.DOMAINE_THEOREME) == 152
      and set(P.DOMAINE_THEOREME.values()) <= DOMAINES and set(P.DOMAINE_CHAPITRE.values()) <= DOMAINES)
check('théorèmes : une ligne par nom, dans leur domaine « maison »', all(
    Theorem.objects.filter(name=n, subject=maths).count() == 1
    and Theorem.objects.get(name=n, subject=maths).subfield.name == d for n, d in P.DOMAINE_THEOREME.items()))
check('domaine maison même sous un chapitre d\'un autre domaine', Theorem.objects.get(name='Formule du binôme de Newton').subfield.name
      == 'Probabilités' and Theorem.objects.get(name='Formule du binôme de Newton').chapters.filter(name='Nombres complexes').exists()
      and Theorem.objects.get(name='Raisonnement par récurrence').subfield.name == 'Algèbre')
check('cinq domaines, une ligne chacun', sorted(Subfield.objects.filter(subject=maths).values_list('name', flat=True)) == sorted(DOMAINES))

# ── Ordre, rang, copies
r = P.rang(SM2)
check('rang : ordre du niveau, RANG_ABSENT sinon', r['Limites et continuité'] == 1 and r['Espaces vectoriels'] == 12
      and r['Dénombrement'] == P.RANG_ABSENT == 10 ** 6 and P.rang(ClassLevel.objects.get(name=PC))['Probabilités'] == 13)
c = P.chapitre(TC, 'Statistiques')
c['capacites'].append('x')
check('chapitre() renvoie une copie', P.chapitre(TC, 'Statistiques')['capacites'][-1] != 'x' and P.chapitre(TC, 'Inconnu') is None)
extra = Chapter.objects.create(name='Chapitre maison', subject=maths, subfield=Subfield.objects.get(name='Analyse', subject=maths))
extra.class_levels.add(ClassLevel.objects.get(name=TC))
got = [x.name for x in P.chapitres_du_niveau('Tronc commun Sciences')]
check('chapitres_du_niveau : chapitre hors programme en dernier ; par nom ou par id', got[-1] == 'Chapitre maison'
      and got[:-1] == [x['nom'] for x in P.PROGRAMME[TC]]
      and [x.name for x in P.chapitres_du_niveau(ClassLevel.objects.get(name=TC).id)] == got)
check('écarts : chapitre rattaché hors programme signalé', any('Chapitre maison' in e for e in P.ecarts_base()['chapitres']))
extra.delete()

# ── Alias
tous = set(P.DOMAINE_CHAPITRE)
ok = True
for ancien, regles in P.ALIAS_CHAPITRES.items():
    for niveau, nouveaux in regles.items():
        ok &= all(n in tous for n in nouveaux)
        ok &= (ancien not in tous) if niveau is None else (ancien not in [c['nom'] for c in P.PROGRAMME[niveau]]
                                                            and all(n in [c['nom'] for c in P.PROGRAMME[niveau]] for n in nouveaux))
check('alias de chapitres : cibles au programme, anciens noms absents du niveau', ok)
check('pas d\'alias pour Espaces vectoriels (gardé)', 'Espaces vectoriels' not in P.ALIAS_CHAPITRES
      and all('espaces-vectoriels' not in v for v in P.ALIAS_SLUGS.values()))
check('alias de théorèmes : cibles au programme, anciens noms retirés', all(
    a not in P.DOMAINE_THEOREME and all(n in P.DOMAINE_THEOREME for n in v) for a, v in P.ALIAS_THEOREMES.items()))
niveau_slug = {slug(n): n for n, _o in P.NIVEAUX}
ok = set(P.ALIAS_SLUGS) <= set(niveau_slug)
for ns, table in P.ALIAS_SLUGS.items():
    slugs = {slug(c['nom']) for c in P.PROGRAMME[niveau_slug[ns]]}
    ok &= all(nouveau in slugs and ancien not in slugs for ancien, nouveau in table.items())
check('alias d\'adresses : nouvelle page existante au niveau, ancienne absente (15 adresses + ln/exp + filet)', ok
      and sum(len(t) for t in P.ALIAS_SLUGS.values()) == 9)

# ── Traduction des anciens noms (import, fiches IA)
t = P.traduire_noms
check('1ère seule : Calcul trigonométrique → Trigonométrie (formules de transformation)',
      t(['Calcul trigonométrique'], [], [SM1])[0] == ['Trigonométrie (formules de transformation)'])
check('TC + 1ère : ancien gardé, nouveau ajouté', t(['calcul trigonométrique'], [], [TC, SM1])[0]
      == ['calcul trigonométrique', 'Trigonométrie (formules de transformation)'])
check('TC seul : inchangé', t(['Calcul trigonométrique'], [], [TC]) == (['Calcul trigonométrique'], [], []))
check('Dénombrement : 2ème SM → Probabilités ; 2ème SM + PC → les deux ; 1ère → inchangé',
      t(['Dénombrement'], [], [SM2])[0] == ['Probabilités'] and t(['Dénombrement'], [], [SM2, PC])[0] == ['Dénombrement', 'Probabilités']
      and t(['Dénombrement'], [], [ClassLevel.objects.get(name=SM1)])[0] == ['Dénombrement'])
ch_, th_, av = t(['Théorème des Accroissements Finis (TAF)', 'Fonctions logarithmiques et exponentielles', 'Dérivation et étude des fonctions'],
                 ['Théorème de Moivre', 'Loi des grands nombres', "Dérivée et propriétés du logarithme et de l'exponentielle"], [SM2])
check('alias sans niveau, sans doublon ; théorèmes traduits ou retirés avec avertissement',
      ch_ == ['Dérivation et étude des fonctions', 'Fonctions logarithmiques', 'Fonctions exponentielles']
      and th_ == ['Formule de Moivre', 'Dérivée et propriétés du logarithme', "Dérivée et propriétés de l'exponentielle"]
      and len(av) == 5 and any('retiré' in a for a in av), (ch_, th_, av))
check('Espaces vectoriels et Structures algébriques non traduits', t(['Espaces vectoriels', 'Structures algébriques'], [], [SM2])
      == (['Espaces vectoriels', 'Structures algébriques'], [], []))

# ── Annexe D (consigne de l'IA)
INTERDITS = ['taxonomie', r'\bpartition\b', 'seeder', 'contenus vont', 'Cadres', 'base_tables', r'\bretirée?\b',
             'à vérifier', 'à valider', 'propriétaire', 'spécification']
d = P.annexe_d()
trouves = [m for m in INTERDITS if re.search(m, d, re.IGNORECASE if m != 'Cadres' else 0)]
check('annexe D : aucun mot interne', not trouves, trouves)
check('annexe D : tous les chapitres, noms exacts', all(f"**{c['nom']}**" in d for n in P.PROGRAMME for c in P.PROGRAMME[n]))
check('annexe D : ni périodes, ni heures, ni remarques, ni théorèmes', all(
    (c['remarque'] or '§§') not in d and (c['periode'] or '§§') not in d for n in P.PROGRAMME for c in P.PROGRAMME[n])
    and 'Théorème des valeurs intermédiaires (TVI)' not in d)
check('annexe D : titres officiels de la 1ère seulement', "titre officiel : « La logique »" in d
      and d.count('titre officiel :') == len(P.PROGRAMME[SM1]))
check('annexe D : repères de 1ère en indications (titres prévus)',
      d.count('Repères habituels du programme (indicatifs, non exhaustifs) :') == sum(1 for c in P.PROGRAMME[SM1] if c['reperes'])
      and 'Habituellement vu plus tard (indicatif, pas une interdiction) :' in d
      and 'Hors programme : Fonction de répartition' in d and 'Périmètre habituel (pas une interdiction)' in d)
seul = P.annexe_d([SM2])
check('annexe D filtrée par niveau', f'### {SM2}' in seul and f'### {PC}' not in seul and f'### {SM1}' not in seul
      and P.annexe_d([ClassLevel.objects.get(name=PC)]).count('### ') == 1 and P.annexe_d([]) == d)
tailles = {n: len(P.annexe_d([n] + ([P.NIVEAU_PRECEDENT[n]] if n in P.NIVEAU_PRECEDENT else []))) for n, _o in P.NIVEAUX}
print(f'     tailles de l\'annexe D (niveau + niveau précédent) : {tailles} ; 4 niveaux : {len(d)}')
check('annexe D : au plus 30 000 caractères pour un niveau et son niveau précédent', max(tailles.values()) <= 30000, tailles)
check('annexe D : au plus 45 000 caractères pour les 4 niveaux (repères de 1ère compris)', len(d) <= 45000, len(d))

# ── Notions rangées sous des chapitres du programme
check('notions : chaque rubrique est un chapitre du programme', set(NOTIONS) - {TRANSVERSAL} <= set(P.DOMAINE_CHAPITRE),
      set(NOTIONS) - {TRANSVERSAL} - set(P.DOMAINE_CHAPITRE))

# ── Migration 0003 : données figées d'accord avec le programme au moment de l'écrire
m = importlib.import_module('apps.caracteristics.migrations.0003_programme_officiel')
D = m.DONNEES
check('0003 : mêmes réponses aux questions ouvertes', m.DECISIONS == P.DECISIONS)
check('0003 : cibles des opérations au programme, au bon niveau', all(
    op['vers'] in [c['nom'] for c in P.PROGRAMME[op['niveau']]] and op['de'] not in [c['nom'] for c in P.PROGRAMME[op['niveau']]]
    for op in D['scissions'])
    and all(op['vers'] in [c['nom'] for c in P.PROGRAMME[op['niveau']]] for op in D['detachements'])
    and all(op['chapitre'] in [c['nom'] for c in P.PROGRAMME[op['niveau']]] for op in D['rattachements'])
    and all(op['vers'] in P.DOMAINE_CHAPITRE and op['de'] not in P.DOMAINE_CHAPITRE for op in D['fusions'])
    and 'Espaces vectoriels' not in [op['de'] for op in D['fusions']])
# Vrai au moment d'écrire 0003. Si programme.py change APRÈS le déploiement de 0003, adapter ce test, jamais 0003.
check('0003 : programme, domaines et alias figés = programme.py',
      D['programme'] == {n: [(c['nom'], c['domaine']) for c in ch] for n, ch in P.PROGRAMME.items()}
      and D['domaine_theoreme'] == P.DOMAINE_THEOREME
      and sorted(map(tuple, ((a, n, tuple(v)) for a, n, v in D['alias_chapitres'])))
      == sorted((a, n, tuple(v)) for a, r_ in P.ALIAS_CHAPITRES.items() for n, v in r_.items())
      and dict((a, tuple(v)) for a, v in D['alias_theoremes']) == P.ALIAS_THEOREMES)
src = open(m.__file__, encoding='utf-8').read() + open(importlib.import_module('apps.caracteristics.programme_migration').__file__,
                                                       encoding='utf-8').read()
check('0003 et programme_migration n\'importent ni programme.py ni les modèles des apps',
      not re.search(r'caracteristics\.programme import|import programme\b|apps\.\w+\.models|from \.models', src))

print(f'\n{sum(results)}/{len(results)} vérifications OK')
sys.exit(0 if all(results) else 1)
