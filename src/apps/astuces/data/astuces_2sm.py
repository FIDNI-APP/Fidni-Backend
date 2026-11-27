"""Astuces de 2ème Bac SM — chapitres des DS n° 1 et n° 2 (Limites et continuité, Dérivation et étude des fonctions,
Suites numériques). Rédigées le 27/11/2026 à partir des solutions du site (1 851 questions de 228 contenus relues
par mots-clés : techniques les plus utilisées, puis celles qu'un élève ne devine pas seul, comme l'absurde).

Chaque astuce : `signaux` = ce qu'on lit dans l'énoncé ; `pourquoi` = pourquoi cette technique et pas une autre ;
`methode` = étapes ; exemple ORIGINAL (pas recopié d'un contenu) ; `sur_le_site` = questions du site qui l'utilisent.
Charger : python manage.py charger_astuces
"""
NIVEAU = '2ème Bac SM'

LC = 'Limites et continuité'
DE = 'Dérivation et étude des fonctions'
SU = 'Suites numériques'


def ref(cle, bloc=None, note=''):
    r = {'cle': cle}
    if bloc:
        r['bloc'] = f'{cle}-{bloc}'
    if note:
        r['note'] = note
    return r


ASTUCES = [
    # ───────────────────────────── Limites et continuité
    {
        'slug': 'unique-solution-tvi-monotonie', 'chapitre': LC,
        'type_question': 'Équation f(x) = 0 : existence et unicité', 'technique': 'TVI et stricte monotonie',
        'titre': 'Montrer qu’une équation a une unique solution',
        'resume': 'Le TVI donne « au moins une » ; la stricte monotonie donne « une seule ».',
        'signaux': [
            'L’énoncé dit « admet une unique solution $\\alpha$ » ou « $\\exists!\\, \\alpha$ ».',
            'La fonction est continue et tu connais (ou peux trouver) son sens de variation.',
        ],
        'pourquoi': 'Le TVI ne dit rien sur le nombre de solutions : une courbe peut couper l’axe plusieurs fois. '
                    'Si $f$ est strictement monotone, elle ne peut pas prendre deux fois la même valeur : la solution '
                    'est donc unique. C’est exactement ce que dit le théorème de la bijection.',
        'methode': [
            'Justifier que $f$ est continue sur l’intervalle $I$.',
            'Montrer que $f$ est strictement monotone sur $I$ (signe de $f\'$, ou somme de fonctions de même sens).',
            'Calculer $f(I)$ avec les valeurs ou les limites aux bornes.',
            'Vérifier que $0 \\in f(I)$, puis conclure : $f$ est une bijection de $I$ sur $f(I)$.',
        ],
        'exemple_enonce': 'Montrer que l’équation $x^3 + x - 1 = 0$ a une unique solution $\\alpha$ dans $\\mathbb{R}$.',
        'exemple_solution': 'Soit $f(x) = x^3 + x - 1$. $f$ est continue sur $\\mathbb{R}$ et '
                            '$f\'(x) = 3x^2 + 1 > 0$, donc $f$ est strictement croissante.</p><p>'
                            '$\\lim\\limits_{x \\to -\\infty} f(x) = -\\infty$ et $\\lim\\limits_{x \\to +\\infty} f(x) = +\\infty$, '
                            'donc $f(\\mathbb{R}) = \\mathbb{R}$, qui contient $0$.</p><p>'
                            'Donc l’équation a une unique solution $\\alpha$ dans $\\mathbb{R}$.',
        'piege': 'Écrire seulement « $f(0) \\times f(1) < 0$ » : cela prouve l’existence, pas l’unicité.',
        'sur_le_site': [ref('etude-fonctions-limite-suite-2sm-ex2', 'b4-1'), ref('cc2-s1-2sm-2026', 'b5'),
                        ref('ds2-2sm-fidni-2026', 'b16')],
    },
    {
        'slug': 'encadrer-alpha', 'chapitre': LC,
        'type_question': 'Équation f(x) = 0 : encadrer la solution', 'technique': 'TVI et stricte monotonie',
        'titre': 'Encadrer une solution $\\alpha$ qu’on ne sait pas calculer',
        'resume': 'Pour montrer $a < \\alpha < b$, compare $f(a)$ et $f(b)$ à $f(\\alpha) = 0$.',
        'signaux': ['« Vérifier que $1 < \\alpha < 2$ », « justifier que $\\alpha < 1$ ».',
                    '$\\alpha$ est définie par $f(\\alpha) = 0$ dans une question précédente.'],
        'pourquoi': 'On ne connaît pas $\\alpha$, mais on connaît $f(\\alpha) = 0$. Comme $f$ est strictement monotone, '
                    'comparer des images revient à comparer les nombres eux-mêmes.',
        'methode': ['Calculer $f(a)$ et $f(b)$ (valeurs simples).',
                    'Si $f$ est strictement croissante : $f(a) < 0 = f(\\alpha) < f(b)$ donne $a < \\alpha < b$.',
                    'Si $f$ est strictement décroissante, les inégalités changent de sens.'],
        'exemple_enonce': 'Avec $f(x) = x^3 + x - 1$ (strictement croissante, $f(\\alpha) = 0$), montrer que '
                          '$\\frac{1}{2} < \\alpha < 1$.',
        'exemple_solution': '$f\\left(\\frac{1}{2}\\right) = \\frac{1}{8} + \\frac{1}{2} - 1 = -\\frac{3}{8} < 0$ et '
                            '$f(1) = 1 > 0$.</p><p>Donc $f\\left(\\frac{1}{2}\\right) < f(\\alpha) < f(1)$, et comme '
                            '$f$ est strictement croissante : $\\frac{1}{2} < \\alpha < 1$.',
        'piege': 'Oublier de citer la stricte monotonie : sans elle, $f(a) < f(\\alpha)$ ne donne pas $a < \\alpha$.',
        'sur_le_site': [ref('cc3-2sm-2026-palmiers', 'b13-2'), ref('cc2-s1-2sm-2026', 'b5')],
    },
    {
        'slug': 'signe-constant-absurde', 'chapitre': LC,
        'type_question': 'Signe d’une fonction', 'technique': 'Raisonnement par l’absurde',
        'titre': 'Une fonction continue qui ne s’annule pas garde un signe constant',
        'resume': 'Si elle changeait de signe, le TVI la ferait s’annuler : contradiction.',
        'signaux': ['« Montrer que $f$ garde un signe constant », « $f$ ne s’annule pas sur $I$ ».',
                    'On veut prouver qu’une situation est IMPOSSIBLE (« ne … pas », « jamais »).'],
        'pourquoi': 'Prouver directement « $f$ est toujours positive » est difficile sans formule. '
                    'Par l’absurde, on part du contraire, qui donne deux points concrets $a$ et $b$ où $f$ change de '
                    'signe : le TVI s’applique alors et produit un zéro interdit. '
                    'Pense à l’absurde quand le contraire de ce qu’on veut est plus facile à utiliser.',
        'methode': ['Écrire « Supposons que … » avec le contraire exact de la conclusion.',
                    'Utiliser cette hypothèse pour obtenir un objet concret (deux points, une limite, un réel).',
                    'Appliquer un théorème du cours à cet objet.',
                    'Arriver à une phrase fausse (« $f(c) = 0$ alors que $f$ ne s’annule pas ») et conclure.'],
        'exemple_enonce': '$f$ est continue sur $[0 ; 1]$, $f(x) \\neq 0$ pour tout $x$ et $f(0) = 2$. '
                          'Montrer que $f(x) > 0$ pour tout $x \\in [0 ; 1]$.',
        'exemple_solution': 'Supposons qu’il existe $b \\in [0 ; 1]$ tel que $f(b) < 0$. Alors $f(0) \\times f(b) < 0$.'
                            '</p><p>$f$ est continue sur $[0 ; b]$, donc d’après le TVI il existe $c \\in ]0 ; b[$ tel '
                            'que $f(c) = 0$. C’est impossible, car $f$ ne s’annule pas.</p><p>'
                            'Donc $f(x) > 0$ pour tout $x \\in [0 ; 1]$.',
        'piege': 'Mal écrire le contraire : le contraire de « $f(x) > 0$ pour tout $x$ » est « il existe $x$ tel que '
                 '$f(x) \\leq 0$ », pas « $f(x) < 0$ pour tout $x$ ».',
        'sur_le_site': [ref('serie-continuite-reciproque-ex10', 'b2')],
    },
    {
        'slug': 'limite-conjugue', 'chapitre': LC,
        'type_question': 'Calculer une limite', 'technique': 'Expression conjuguée',
        'titre': 'Forme indéterminée avec des racines carrées',
        'resume': 'Multiplie par l’expression conjuguée pour faire disparaître la différence de racines.',
        'signaux': ['Une différence $\\sqrt{A} - \\sqrt{B}$ ou $\\sqrt{A} - B$ qui donne « $\\infty - \\infty$ » ou « $0/0$ ».'],
        'pourquoi': 'La différence de deux racines proches est petite, mais on ne voit pas à quel point. '
                    'Avec $(\\sqrt{A} - \\sqrt{B})(\\sqrt{A} + \\sqrt{B}) = A - B$, les racines partent du numérateur '
                    'et la somme $\\sqrt{A} + \\sqrt{B}$ n’est plus indéterminée.',
        'methode': ['Multiplier et diviser par le conjugué $\\sqrt{A} + \\sqrt{B}$.',
                    'Simplifier le numérateur : $A - B$.',
                    'Mettre en facteur le terme dominant, puis calculer la limite.'],
        'exemple_enonce': 'Calculer $\\lim\\limits_{x \\to +\\infty} \\left(\\sqrt{x + 1} - \\sqrt{x}\\right)$.',
        'exemple_solution': '$$\\begin{aligned} \\sqrt{x + 1} - \\sqrt{x} &= \\frac{(x + 1) - x}{\\sqrt{x + 1} + \\sqrt{x}} \\\\ '
                            '&= \\frac{1}{\\sqrt{x + 1} + \\sqrt{x}} \\end{aligned}$$</p><p>'
                            'Le dénominateur tend vers $+\\infty$, donc la limite vaut $0$.',
        'piege': 'Avec des racines cubiques ou $n$-ièmes, le conjugué ne suffit pas : utilise '
                 '$a^n - b^n = (a - b)(a^{n-1} + \\cdots + b^{n-1})$ ou le changement de variable $t = \\sqrt[n]{x}$.',
        'sur_le_site': [ref('continuite-soir-ex1', 'b2'), ref('dc2-2sm-belkhatir-4h', 'b41')],
    },
    {
        'slug': 'limite-nombre-derive', 'chapitre': LC,
        'type_question': 'Calculer une limite', 'technique': 'Reconnaître un nombre dérivé',
        'titre': 'Une limite de la forme $\\dfrac{f(x) - f(a)}{x - a}$',
        'resume': 'Si tu reconnais un taux d’accroissement, la limite est $f\'(a)$, sans aucun calcul.',
        'signaux': ['Forme « $0/0$ » en un point $a$ avec $x - a$ au dénominateur.',
                    'Le numérateur s’écrit $f(x) - f(a)$ pour une fonction dérivable connue ($\\arctan$, $\\sqrt[n]{\\;}$…).'],
        'pourquoi': 'Par définition, $f\'(a) = \\lim\\limits_{x \\to a} \\frac{f(x) - f(a)}{x - a}$. '
                    'Transformer l’expression serait long ; reconnaître la définition règle tout d’un coup.',
        'methode': ['Repérer $a$ et la fonction $f$ telle que le numérateur soit $f(x) - f(a)$.',
                    'Vérifier que $f$ est dérivable en $a$.',
                    'Conclure : la limite vaut $f\'(a)$.'],
        'exemple_enonce': 'Calculer $\\lim\\limits_{x \\to 1} \\dfrac{\\arctan x - \\frac{\\pi}{4}}{x - 1}$.',
        'exemple_solution': 'Avec $f = \\arctan$ et $a = 1$ : $f(1) = \\frac{\\pi}{4}$. $f$ est dérivable sur '
                            '$\\mathbb{R}$ et $f\'(x) = \\frac{1}{1 + x^2}$.</p><p>Donc la limite vaut '
                            '$f\'(1) = \\frac{1}{2}$.',
        'piege': 'Si le dénominateur est $x^2 - 1$, il faut d’abord écrire $x^2 - 1 = (x - 1)(x + 1)$.',
        'sur_le_site': [ref('derivabilite-2sm-s2-ex4', 'b2')],
    },
    {
        'slug': 'arctan-inverse', 'chapitre': LC,
        'type_question': 'Calculer une limite', 'technique': 'Identité de arc tangente',
        'titre': 'Limites avec $\\arctan$ en l’infini',
        'resume': 'Pour $x > 0$ : $\\arctan x = \\frac{\\pi}{2} - \\arctan\\frac{1}{x}$. On revient en $0$.',
        'signaux': ['« $\\arctan x - \\frac{\\pi}{2}$ » multiplié par $x$ (forme $\\infty \\times 0$).',
                    '$\\arctan\\frac{1}{x}$ dans l’énoncé.'],
        'pourquoi': 'En $+\\infty$, $\\arctan x$ s’approche de $\\frac{\\pi}{2}$ sans qu’on voie la vitesse. '
                    'L’identité remplace cet écart par $\\arctan\\frac{1}{x}$, qui se traite en $0$ avec '
                    '$\\lim\\limits_{t \\to 0} \\frac{\\arctan t}{t} = 1$.',
        'methode': ['Écrire $\\arctan x - \\frac{\\pi}{2} = -\\arctan\\frac{1}{x}$ (pour $x > 0$ ; '
                    'pour $x < 0$ : $\\arctan x + \\frac{\\pi}{2} = -\\arctan\\frac{1}{x}$).',
                    'Poser $t = \\frac{1}{x}$, qui tend vers $0$.',
                    'Utiliser $\\lim\\limits_{t \\to 0} \\frac{\\arctan t}{t} = 1$.'],
        'exemple_enonce': 'Calculer $\\lim\\limits_{x \\to +\\infty} x\\left(\\arctan x - \\frac{\\pi}{2}\\right)$.',
        'exemple_solution': 'Pour $x > 0$ : $x\\left(\\arctan x - \\frac{\\pi}{2}\\right) = -\\dfrac{\\arctan\\frac{1}{x}}{\\frac{1}{x}}$.'
                            '</p><p>Avec $t = \\frac{1}{x} \\to 0^+$ : la limite vaut $-1$.',
        'piege': 'L’identité change de signe pour $x < 0$ : $\\arctan x + \\arctan\\frac{1}{x} = -\\frac{\\pi}{2}$.',
        'sur_le_site': [ref('haddar-lc-ex18', 'b7'), ref('ds3-rattrapage-2sm-2022', 'b10-1')],
    },
    {
        'slug': 'racine-n-changement-variable', 'chapitre': LC,
        'type_question': 'Calculer une limite', 'technique': 'Changement de variable',
        'titre': 'Limites avec des racines $n$-ièmes',
        'resume': 'Pose $t = \\sqrt[n]{x}$ : les racines deviennent des puissances, plus faciles à factoriser.',
        'signaux': ['$\\sqrt[3]{x}$, $\\sqrt[n]{x}$ ou plusieurs racines d’ordres différents dans la même expression.'],
        'pourquoi': 'Les règles de calcul des racines $n$-ièmes sont lourdes. Avec $t = \\sqrt[n]{x}$, on a $x = t^n$ : '
                    'l’expression devient un quotient de polynômes en $t$, qu’on factorise par $t - 1$ ou par le terme dominant.',
        'methode': ['Poser $t = \\sqrt[n]{x}$ (ou $t = \\sqrt[6]{x}$ si l’on a $\\sqrt{x}$ et $\\sqrt[3]{x}$).',
                    'Trouver la limite de $t$.', 'Réécrire tout en $t$, factoriser, conclure.'],
        'exemple_enonce': 'Calculer $\\lim\\limits_{x \\to 1} \\dfrac{\\sqrt[3]{x} - 1}{x - 1}$.',
        'exemple_solution': 'Posons $t = \\sqrt[3]{x}$ : $t \\to 1$ et $x = t^3$.</p><p>'
                            '$$\\begin{aligned} \\frac{t - 1}{t^3 - 1} &= \\frac{t - 1}{(t - 1)(t^2 + t + 1)} \\\\ '
                            '&= \\frac{1}{t^2 + t + 1} \\end{aligned}$$</p><p>Donc la limite vaut $\\frac{1}{3}$.',
        'piege': 'Oublier que $\\sqrt[n]{x}$ n’est défini que pour $x \\geq 0$.',
        'sur_le_site': [ref('ds2-2sm-addam-2026', 'b20'), ref('dc2-2sm-belkhatir-4h', 'b43')],
    },
    {
        'slug': 'prolongement-continuite', 'chapitre': LC,
        'type_question': 'Prolongement par continuité', 'technique': 'Calcul de limite',
        'titre': 'Montrer qu’une fonction se prolonge par continuité en $a$',
        'resume': '$f$ n’est pas définie en $a$, mais a une limite FINIE en $a$ : on pose $\\tilde{f}(a) =$ cette limite.',
        'signaux': ['« admet un prolongement par continuité en $a$ », « est-elle prolongeable » ; $a \\notin D_f$.'],
        'pourquoi': 'Prolonger, c’est boucher le trou de la courbe en $a$. Ce n’est possible que si les deux côtés '
                    'arrivent au même point : une limite finie (à gauche ET à droite si $f$ est définie des deux côtés).',
        'methode': ['Vérifier que $a \\notin D_f$ et que $f$ est définie au voisinage de $a$.',
                    'Calculer $\\lim\\limits_{x \\to a} f(x) = \\ell$ et vérifier que $\\ell$ est un réel.',
                    'Définir $\\tilde{f}(x) = f(x)$ pour $x \\neq a$ et $\\tilde{f}(a) = \\ell$.'],
        'exemple_enonce': 'Montrer que $f(x) = \\dfrac{\\arctan x}{x}$ se prolonge par continuité en $0$.',
        'exemple_solution': '$\\lim\\limits_{x \\to 0} \\frac{\\arctan x}{x} = 1$ (limite de référence), qui est finie.'
                            '</p><p>Donc $f$ se prolonge par continuité en $0$ par $\\tilde{f}(0) = 1$.',
        'piege': 'Une limite infinie, ou des limites différentes à gauche et à droite : pas de prolongement.',
        'sur_le_site': [ref('revision-fct-suites-2sm-haddar-ex1', 'b3'), ref('ds2-2sm-2021', 'b3')],
    },
    {
        'slug': 'continuite-encadrement', 'chapitre': LC,
        'type_question': 'Continuité en un point', 'technique': 'Encadrement (gendarmes)',
        'titre': 'Continuité en $a$ quand la limite ne se calcule pas directement',
        'resume': 'Encadre $f(x) - f(a)$ par deux quantités qui tendent vers $0$.',
        'signaux': ['Un $\\sin$, un $\\cos$, une partie entière $E(x)$ ou une inégalité donnée juste avant.',
                    'La question précédente demande d’établir une inégalité.'],
        'pourquoi': 'Quand l’expression oscille ou saute ($\\sin\\frac{1}{x}$, $E(x)$), aucune règle de calcul ne '
                    'donne la limite. Un encadrement la « coince » : c’est souvent pour cela que l’énoncé a demandé '
                    'une inégalité juste avant.',
        'methode': ['Écrire $|f(x) - f(a)| \\leq g(x)$ (ou $g_1(x) \\leq f(x) \\leq g_2(x)$).',
                    'Montrer que $g(x) \\to 0$ quand $x \\to a$.',
                    'Conclure : $\\lim\\limits_{x \\to a} f(x) = f(a)$, donc $f$ est continue en $a$.'],
        'exemple_enonce': '$f(x) = x^2 \\sin\\frac{1}{x}$ pour $x \\neq 0$ et $f(0) = 0$. Montrer que $f$ est continue en $0$.',
        'exemple_solution': 'Pour $x \\neq 0$ : $|f(x) - f(0)| = x^2 \\left|\\sin\\frac{1}{x}\\right| \\leq x^2$, '
                            'car $|\\sin| \\leq 1$.</p><p>Or $\\lim\\limits_{x \\to 0} x^2 = 0$, donc '
                            '$\\lim\\limits_{x \\to 0} f(x) = 0 = f(0)$ : $f$ est continue en $0$.',
        'piege': 'Encadrer par deux fonctions qui n’ont pas la même limite : cela ne prouve rien.',
        'sur_le_site': [ref('ds2-2sm-fidni-2026', 'b7')],
    },
    {
        'slug': 'reciproque-expression', 'chapitre': LC,
        'type_question': 'Fonction réciproque', 'technique': 'Résoudre y = f(x)',
        'titre': 'Déterminer $J$ et l’expression de $f^{-1}$',
        'resume': 'Bijection par continuité et stricte monotonie, puis on résout $y = f(x)$ en $x$.',
        'signaux': ['« admet une fonction réciproque définie sur un intervalle $J$ », « déterminer $f^{-1}(x)$ ».'],
        'pourquoi': '$f^{-1}(y)$ est par définition l’unique $x$ de $I$ tel que $f(x) = y$ : résoudre cette équation '
                    'en gardant $x \\in I$ donne directement l’expression.',
        'methode': ['Continuité et stricte monotonie de $f$ sur $I$, puis $J = f(I)$.',
                    'Pour $y \\in J$ et $x \\in I$ : écrire $f(x) = y$ et isoler $x$.',
                    'Choisir la solution qui est dans $I$ (signe, racine positive…).'],
        'exemple_enonce': '$f(x) = \\dfrac{x}{1 + x}$ sur $I = [0 ; +\\infty[$. Déterminer $J$ et $f^{-1}$.',
        'exemple_solution': '$f$ est continue et $f\'(x) = \\frac{1}{(1 + x)^2} > 0$ ; $f(0) = 0$ et '
                            '$\\lim\\limits_{x \\to +\\infty} f(x) = 1$, donc $J = [0 ; 1[$.</p><p>'
                            'Pour $y \\in J$ : $\\frac{x}{1 + x} = y$ signifie $x = y + xy$, soit $x = \\frac{y}{1 - y}$.'
                            '</p><p>Donc $f^{-1}(x) = \\dfrac{x}{1 - x}$ pour $x \\in [0 ; 1[$.',
        'piege': 'Oublier de garder la solution dans $I$ quand on prend une racine carrée.',
        'sur_le_site': [ref('ds1-2sm-2022', 'b15')],
    },
    {
        'slug': 'equation-arctan', 'chapitre': LC,
        'type_question': 'Équation avec arc tangente', 'technique': 'Appliquer tan avec des intervalles',
        'titre': 'Résoudre une équation avec des $\\arctan$',
        'resume': 'Applique $\\tan$ aux deux membres, mais vérifie d’abord que la somme reste dans $]-\\frac{\\pi}{2} ; \\frac{\\pi}{2}[$.',
        'signaux': ['« $\\arctan a + \\arctan b = \\dots$ » ou une équation en $\\arctan$.'],
        'pourquoi': '$\\tan$ « défait » $\\arctan$, et la formule $\\tan(a + b)$ transforme l’équation en équation '
                    'algébrique. Mais $\\tan$ n’est injective que sur $]-\\frac{\\pi}{2} ; \\frac{\\pi}{2}[$ : '
                    'sans contrôle de l’intervalle, on récupère de fausses solutions.',
        'methode': ['Encadrer chaque $\\arctan$ pour savoir où se trouve la somme.',
                    'Appliquer $\\tan$ et la formule $\\tan(a + b) = \\frac{\\tan a + \\tan b}{1 - \\tan a \\tan b}$.',
                    'Résoudre, puis garder seulement les solutions compatibles avec l’encadrement.'],
        'exemple_enonce': 'Résoudre dans $\\mathbb{R}$ : $\\arctan x + \\arctan(2x) = \\frac{\\pi}{4}$.',
        'exemple_solution': 'Le membre de gauche est strictement croissant et positif seulement si $x > 0$ : on cherche '
                            '$x > 0$, et alors $0 < \\arctan x + \\arctan 2x < \\pi$.</p><p>En appliquant $\\tan$ : '
                            '$\\frac{x + 2x}{1 - 2x^2} = 1$, soit $2x^2 + 3x - 1 = 0$, donc '
                            '$x = \\frac{-3 + \\sqrt{17}}{4}$ (l’autre racine est négative).',
        'piege': 'Garder les deux racines de l’équation du second degré sans vérifier le signe.',
        'sur_le_site': [ref('continuite-soir-ex22', 'b3')],
    },

    # ───────────────────────────── Dérivation et étude des fonctions
    {
        'slug': 'derivabilite-point', 'chapitre': DE,
        'type_question': 'Dérivabilité en un point', 'technique': 'Taux d’accroissement',
        'titre': 'Étudier la dérivabilité en un point « à problème »',
        'resume': 'Aux points de raccord ou là où une racine s’annule, on revient à la définition.',
        'signaux': ['Fonction définie par morceaux, valeur absolue, $\\sqrt{\\;}$ ou $\\sqrt[n]{\\;}$ qui s’annule en $a$.',
                    '« Étudier la dérivabilité à droite en $0$ et interpréter graphiquement ».'],
        'pourquoi': 'Les formules de dérivation ne s’appliquent que là où la fonction est « lisse ». '
                    'Au point à problème, seule la définition (limite du taux d’accroissement) dit ce qui se passe.',
        'methode': ['Écrire $\\dfrac{f(x) - f(a)}{x - a}$ à droite (et à gauche si besoin).',
                    'Calculer la limite : réelle = dérivable ; infinie = pas dérivable.',
                    'Interpréter : demi-tangente de pente $\\ell$, ou demi-tangente verticale si la limite est infinie.'],
        'exemple_enonce': 'Étudier la dérivabilité à droite en $0$ de $f(x) = x\\sqrt{x}$ et de $g(x) = \\sqrt{x}$.',
        'exemple_solution': '$\\frac{f(x) - f(0)}{x} = \\sqrt{x} \\to 0$ : $f$ est dérivable à droite en $0$, '
                            'tangente horizontale.</p><p>$\\frac{g(x) - g(0)}{x} = \\frac{1}{\\sqrt{x}} \\to +\\infty$ : '
                            '$g$ n’est pas dérivable à droite en $0$, demi-tangente verticale.',
        'piege': 'Dériver avec les formules puis remplacer $x$ par $a$ : la formule n’est pas valable en $a$.',
        'sur_le_site': [ref('ds2-2sm-fidni-2026', 'b9'), ref('cc2-2sm-2026-palmiers', 'b14-2')],
    },
    {
        'slug': 'rolle-fonction-auxiliaire', 'chapitre': DE,
        'type_question': 'Existence d’un réel c', 'technique': 'Théorème de Rolle',
        'titre': 'Montrer qu’il existe $c$ tel que « une relation avec $f\'(c)$ »',
        'resume': 'Trouve une fonction $\\varphi$ dont la dérivée qui s’annule donne la relation, puis Rolle.',
        'signaux': ['« Montrer qu’il existe $c \\in ]a ; b[$ tel que … $f\'(c)$ … ».',
                    'La relation ne ressemble pas à $f\'(c) = \\frac{f(b) - f(a)}{b - a}$ (sinon : TAF).'],
        'pourquoi': 'Rolle dit seulement « une dérivée s’annule ». Pour obtenir une relation plus compliquée, on '
                    'fabrique une fonction $\\varphi$ dont la dérivée, quand elle est nulle, donne exactement la relation. '
                    'Astuce pour la trouver : la relation ressemble souvent à la dérivée d’un produit ou d’un quotient.',
        'methode': ['Transformer la relation en « quelque chose $= 0$ ».',
                    'Reconnaître la dérivée d’un produit : $f\'g + fg\'$, ou d’un quotient.',
                    'Poser $\\varphi$, vérifier continuité, dérivabilité et $\\varphi(a) = \\varphi(b)$.',
                    'Rolle donne $c$ avec $\\varphi\'(c) = 0$, puis revenir à la relation.'],
        'exemple_enonce': '$f$ dérivable sur $[0 ; 1]$, $f(1) = 0$. Montrer qu’il existe $c \\in ]0 ; 1[$ tel que '
                          '$c f\'(c) + f(c) = 0$.',
        'exemple_solution': '$c f\'(c) + f(c)$ est la dérivée de $\\varphi(x) = x f(x)$ en $c$. $\\varphi$ est continue '
                            'sur $[0 ; 1]$, dérivable sur $]0 ; 1[$ et $\\varphi(0) = 0 = \\varphi(1)$.</p><p>'
                            'D’après Rolle, il existe $c \\in ]0 ; 1[$ tel que $\\varphi\'(c) = c f\'(c) + f(c) = 0$.',
        'piege': 'Oublier de vérifier $\\varphi(a) = \\varphi(b)$ : c’est l’hypothèse qui rend Rolle utilisable.',
        'sur_le_site': [ref('dc2-2sm-2022-belkhatir-ibn-alyassamine', 'b6'), ref('ds2-2sm-fidni-2026', 'b26')],
    },
    {
        'slug': 'rolle-repete', 'chapitre': DE,
        'type_question': 'Existence d’un réel c', 'technique': 'Théorème de Rolle',
        'titre': 'Compter les zéros de $f\'$, $f\'\'$… à partir de ceux de $f$',
        'resume': 'Entre deux zéros de $f$, Rolle place un zéro de $f\'$ ; on recommence avec $f\'$.',
        'signaux': ['« $f$ s’annule en $n + 1$ points », « montrer que $f^{(k)}$ s’annule au moins … fois ».'],
        'pourquoi': 'Chaque application de Rolle « perd » un zéro : $n + 1$ zéros de $f$ donnent $n$ zéros de $f\'$, '
                    'puis $n - 1$ de $f\'\'$… Une récurrence rend cela rigoureux.',
        'methode': ['Ranger les zéros : $x_0 < x_1 < \\cdots < x_n$.',
                    'Appliquer Rolle sur chaque $[x_i ; x_{i+1}]$ : un zéro de $f\'$ dans chaque intervalle ouvert.',
                    'Ces zéros sont distincts (intervalles disjoints). Recommencer ou faire une récurrence.'],
        'exemple_enonce': '$f$ deux fois dérivable s’annule en $0$, $1$ et $2$. Montrer que $f\'\'$ s’annule.',
        'exemple_solution': 'Rolle sur $[0 ; 1]$ et $[1 ; 2]$ : $f\'(a) = 0$ et $f\'(b) = 0$ avec $0 < a < 1 < b < 2$.'
                            '</p><p>Rolle appliqué à $f\'$ sur $[a ; b]$ : il existe $c$ tel que $f\'\'(c) = 0$.',
        'piege': 'Ne pas justifier que les zéros obtenus sont distincts.',
        'sur_le_site': [ref('rolle-taf-2sm-ex2', 'b2')],
    },
    {
        'slug': 'taf-inegalite', 'chapitre': DE,
        'type_question': 'Inégalité entre fonctions', 'technique': 'Accroissements finis',
        'titre': 'Démontrer une inégalité comme $\\frac{t}{1 + t^2} < \\arctan t < t$',
        'resume': 'Le TAF écrit $\\arctan t - \\arctan 0 = t \\times f\'(c)$, puis on encadre $f\'(c)$.',
        'signaux': ['Une inégalité avec un écart $f(b) - f(a)$ (ici $\\arctan t - \\arctan 0$).',
                    '« En utilisant le théorème des accroissements finis ».'],
        'pourquoi': 'L’écart $f(b) - f(a)$ est difficile à encadrer directement. Le TAF le remplace par '
                    '$(b - a) f\'(c)$ ; or encadrer $f\'(c)$ revient à encadrer $c$, qu’on connaît : $a < c < b$.',
        'methode': ['Choisir $f$ et l’intervalle $[a ; b]$ (souvent $[0 ; t]$).',
                    'TAF : il existe $c \\in ]a ; b[$ avec $f(b) - f(a) = (b - a) f\'(c)$.',
                    'Encadrer $f\'(c)$ à partir de $a < c < b$ (sens de variation de $f\'$).',
                    'Multiplier par $b - a > 0$.'],
        'exemple_enonce': 'Montrer que pour tout $t > 0$ : $\\dfrac{t}{1 + t^2} < \\arctan t < t$.',
        'exemple_solution': 'TAF pour $\\arctan$ sur $[0 ; t]$ : il existe $c \\in ]0 ; t[$ tel que '
                            '$\\arctan t = \\frac{t}{1 + c^2}$.</p><p>Comme $0 < c < t$ : $1 < 1 + c^2 < 1 + t^2$, '
                            'donc $\\frac{1}{1 + t^2} < \\frac{1}{1 + c^2} < 1$.</p><p>En multipliant par $t > 0$ : '
                            '$\\frac{t}{1 + t^2} < \\arctan t < t$.',
        'piege': 'Inverser sans changer le sens : $1 + c^2 < 1 + t^2$ donne $\\frac{1}{1 + c^2} > \\frac{1}{1 + t^2}$.',
        'sur_le_site': [ref('ds2-2sm-fidni-2026', 'b2'), ref('ds3-rattrapage-2sm-2022', 'b9-1')],
    },
    {
        'slug': 'derivee-nulle-constante', 'chapitre': DE,
        'type_question': 'Montrer une identité', 'technique': 'Dérivée nulle ⇒ constante',
        'titre': 'Prouver une égalité vraie pour tout $x$ (souvent avec $\\arctan$)',
        'resume': 'Mets tout d’un côté, dérive : si la dérivée est nulle sur un INTERVALLE, la fonction est constante.',
        'signaux': ['« Montrer que pour tout $x > 0$ : $\\arctan x + \\arctan\\frac{1}{x} = \\frac{\\pi}{2}$ ».',
                    '« En utilisant la notion de dérivée ».'],
        'pourquoi': 'On ne peut pas calculer $\\arctan x$, mais on sait dériver. Une fonction de dérivée nulle '
                    'sur un intervalle est constante ; il suffit alors de calculer sa valeur en un point simple.',
        'methode': ['Poser $h(x) =$ membre de gauche $-$ membre de droite (ou seulement le membre de gauche).',
                    'Calculer $h\'(x)$ et montrer que $h\'(x) = 0$ sur l’intervalle.',
                    'Calculer $h$ en un point facile ($x = 1$, $x = 0$).'],
        'exemple_enonce': 'Montrer que pour tout $x > 0$ : $\\arctan x + \\arctan\\frac{1}{x} = \\frac{\\pi}{2}$.',
        'exemple_solution': '$h(x) = \\arctan x + \\arctan\\frac{1}{x}$ est dérivable sur $]0 ; +\\infty[$ et '
                            '$h\'(x) = \\frac{1}{1 + x^2} - \\frac{1}{x^2} \\times \\frac{1}{1 + \\frac{1}{x^2}} = 0$.'
                            '</p><p>$]0 ; +\\infty[$ est un intervalle, donc $h$ est constante : '
                            '$h(x) = h(1) = \\frac{\\pi}{4} + \\frac{\\pi}{4} = \\frac{\\pi}{2}$.',
        'piege': 'Sur $\\mathbb{R}^*$ (deux intervalles), la constante peut changer : ici elle vaut $-\\frac{\\pi}{2}$ pour $x < 0$.',
        'sur_le_site': [ref('ds2-2sm-2025', 'b12-1'), ref('ds3-rattrapage-2sm-2022', 'b10-1')],
    },
    {
        'slug': 'branches-infinies', 'chapitre': DE,
        'type_question': 'Branches infinies', 'technique': 'Limite de f(x)/x',
        'titre': 'Étudier la branche infinie d’une courbe',
        'resume': 'Si $f(x) \\to \\infty$, regarde $\\frac{f(x)}{x}$, puis $f(x) - ax$.',
        'signaux': ['« Étudier la branche infinie de $(C_f)$ au voisinage de $+\\infty$ ».'],
        'pourquoi': 'Savoir que $f(x) \\to +\\infty$ ne dit pas la FORME de la courbe. $\\frac{f(x)}{x}$ mesure la '
                    'pente lointaine ; $f(x) - ax$ dit si la courbe se rapproche d’une droite.',
        'methode': ['$\\lim f(x)$ finie : asymptote horizontale.',
                    'Sinon $\\lim \\frac{f(x)}{x}$ : $\\pm\\infty$ = branche parabolique de direction l’axe des ordonnées ; '
                    '$0$ = direction l’axe des abscisses ; $a \\neq 0$ : continuer.',
                    '$\\lim (f(x) - ax)$ : $b$ réel = asymptote $y = ax + b$ ; infinie = branche parabolique de direction $y = ax$.'],
        'exemple_enonce': 'Étudier la branche infinie de $f(x) = x + \\sqrt{x}$ en $+\\infty$.',
        'exemple_solution': '$\\frac{f(x)}{x} = 1 + \\frac{1}{\\sqrt{x}} \\to 1$ et $f(x) - x = \\sqrt{x} \\to +\\infty$.'
                            '</p><p>Donc $(C_f)$ a une branche parabolique de direction la droite $y = x$.',
        'piege': 'Conclure « asymptote $y = x$ » dès que $\\frac{f(x)}{x} \\to 1$ : il faut encore $f(x) - x$.',
        'sur_le_site': [ref('cc2-s1-2sm-2026', 'b11'), ref('etude-fonctions-resume-2sm-ex1', 'b6')],
    },

    # ───────────────────────────── Suites numériques
    {
        'slug': 'encadrer-suite-recurrence', 'chapitre': SU,
        'type_question': 'Encadrer une suite', 'technique': 'Récurrence',
        'titre': 'Montrer que $a \\leq u_n \\leq b$ pour une suite $u_{n+1} = f(u_n)$',
        'resume': 'Récurrence, et pour l’hérédité : $f$ envoie $[a ; b]$ dans $[a ; b]$.',
        'signaux': ['« Montrer que pour tout $n$ : $0 \\leq u_n \\leq 1$ », la suite est définie par $u_{n+1} = f(u_n)$.'],
        'pourquoi': 'Chaque terme est construit à partir du précédent : une propriété qui passe d’un terme au suivant '
                    'se démontre naturellement par récurrence. Le sens de variation de $f$ permet de faire passer '
                    'l’encadrement à travers $f$.',
        'methode': ['Initialisation : vérifier pour $u_0$.',
                    'Hérédité : supposer $a \\leq u_n \\leq b$ ; si $f$ est croissante sur $[a ; b]$, alors '
                    '$f(a) \\leq u_{n+1} \\leq f(b)$.',
                    'Vérifier que $[f(a) ; f(b)] \\subset [a ; b]$.'],
        'exemple_enonce': '$u_0 = 0$ et $u_{n+1} = \\sqrt{2 + u_n}$. Montrer que $0 \\leq u_n \\leq 2$.',
        'exemple_solution': '$u_0 = 0 \\in [0 ; 2]$. Si $0 \\leq u_n \\leq 2$, alors $2 \\leq 2 + u_n \\leq 4$, '
                            'donc $\\sqrt{2} \\leq u_{n+1} \\leq 2$, et a fortiori $0 \\leq u_{n+1} \\leq 2$.</p><p>'
                            'Donc pour tout $n$ : $0 \\leq u_n \\leq 2$.',
        'piege': 'Si $f$ est décroissante, l’encadrement s’inverse : $f(b) \\leq u_{n+1} \\leq f(a)$.',
        'sur_le_site': [ref('ds3-rattrapage-2sm-2022', 'b5'), ref('cc3-2sm-2026-palmiers', 'b7-2'),
                        ref('dc2-2sm-belkhatir-4h', 'b33')],
    },
    {
        'slug': 'monotonie-suite-recurrente', 'chapitre': SU,
        'type_question': 'Monotonie d’une suite', 'technique': 'Signe de f(x) − x',
        'titre': 'Sens de variation d’une suite $u_{n+1} = f(u_n)$',
        'resume': '$u_{n+1} - u_n = f(u_n) - u_n$ : étudie le signe de $f(x) - x$ là où vivent les $u_n$.',
        'signaux': ['« Montrer que $(u_n)$ est décroissante », après un encadrement $u_n \\in I$.'],
        'pourquoi': 'On ne connaît pas $u_n$, mais on sait qu’il est dans $I$. Si $f(x) - x$ a un signe constant sur $I$, '
                    'ce signe est celui de $u_{n+1} - u_n$ pour tout $n$.',
        'methode': ['Écrire $u_{n+1} - u_n = f(u_n) - u_n$.',
                    'Étudier le signe de $g(x) = f(x) - x$ sur $I$ (souvent donné par une question sur $f$).',
                    'Comme $u_n \\in I$ : conclure. Autre voie : si $f$ est croissante, comparer $u_1$ et $u_0$ puis récurrence.'],
        'exemple_enonce': 'Avec $u_{n+1} = \\sqrt{2 + u_n}$, $u_0 = 0$ et $0 \\leq u_n \\leq 2$ : sens de variation ?',
        'exemple_solution': 'Pour $x \\in [0 ; 2]$ : $\\sqrt{2 + x} - x = \\frac{2 + x - x^2}{\\sqrt{2 + x} + x} = '
                            '\\frac{(2 - x)(1 + x)}{\\sqrt{2 + x} + x} \\geq 0$.</p><p>Donc $u_{n+1} - u_n \\geq 0$ : '
                            '$(u_n)$ est croissante.',
        'piege': 'Si $f$ est décroissante, la suite n’est en général PAS monotone : voir l’astuce des sous-suites.',
        'sur_le_site': [ref('etude-fonctions-limite-suite-2sm-ex3', 'b10-3')],
    },
    {
        'slug': 'limite-point-fixe', 'chapitre': SU,
        'type_question': 'Limite d’une suite', 'technique': 'Point fixe',
        'titre': 'Trouver la limite d’une suite $u_{n+1} = f(u_n)$',
        'resume': 'Si $(u_n)$ converge vers $\\ell$ et $f$ est continue, alors $f(\\ell) = \\ell$.',
        'signaux': ['« Montrer que $(u_n)$ converge et déterminer sa limite », avec $u_{n+1} = f(u_n)$.'],
        'pourquoi': 'Quand $n$ devient grand, $u_n$ et $u_{n+1}$ sont tous les deux proches de $\\ell$. '
                    'En passant à la limite dans $u_{n+1} = f(u_n)$, la continuité de $f$ donne $\\ell = f(\\ell)$ : '
                    'la limite fait partie des solutions de cette équation.',
        'methode': ['Prouver la convergence d’abord (monotone et bornée).',
                    'Vérifier : $f$ continue sur $I$, $f(I) \\subset I$, $u_0 \\in I$, $I$ fermé (donc $\\ell \\in I$).',
                    'Résoudre $f(x) = x$ dans $I$ et choisir la bonne solution.'],
        'exemple_enonce': 'Avec $u_{n+1} = \\sqrt{2 + u_n}$ (croissante, $0 \\leq u_n \\leq 2$), trouver $\\lim u_n$.',
        'exemple_solution': '$(u_n)$ est croissante et majorée, donc converge vers $\\ell \\in [0 ; 2]$. '
                            '$f(x) = \\sqrt{2 + x}$ est continue sur $[0 ; 2]$ et $f([0 ; 2]) \\subset [0 ; 2]$, donc '
                            '$\\ell = \\sqrt{2 + \\ell}$.</p><p>$\\ell^2 - \\ell - 2 = 0$ donne $\\ell = 2$ ou $\\ell = -1$ ; '
                            'or $\\ell \\geq 0$, donc $\\lim u_n = 2$.',
        'piege': 'Écrire $\\ell = f(\\ell)$ avant d’avoir prouvé que la suite converge.',
        'sur_le_site': [ref('etude-fonctions-limite-suite-2sm-ex3', 'b11-2'), ref('ds3-rattrapage-2sm-2022', 'b7')],
    },
    {
        'slug': 'contraction-taf', 'chapitre': SU,
        'type_question': 'Limite d’une suite', 'technique': 'Accroissements finis',
        'titre': 'Montrer que $|u_{n+1} - \\alpha| \\leq k\\,|u_n - \\alpha|$',
        'resume': 'Inégalité des accroissements finis entre $u_n$ et $\\alpha$, avec $|f\'| \\leq k$ et $f(\\alpha) = \\alpha$.',
        'signaux': ['Le nombre $\\alpha$ vérifie $f(\\alpha) = \\alpha$ (question précédente).',
                    'Une question demande $|f\'(x)| \\leq k$ sur un intervalle.'],
        'pourquoi': '$u_{n+1} - \\alpha = f(u_n) - f(\\alpha)$ : c’est un écart de valeurs de $f$, exactement ce que '
                    'contrôle l’IAF. Avec $k < 1$, l’écart est divisé au moins par $\\frac{1}{k}$ à chaque étape.',
        'methode': ['Écrire $u_{n+1} - \\alpha = f(u_n) - f(\\alpha)$.',
                    'IAF sur l’intervalle entre $u_n$ et $\\alpha$ (tous deux dans $I$ où $|f\'| \\leq k$).',
                    'Par récurrence : $|u_n - \\alpha| \\leq k^n |u_0 - \\alpha|$.',
                    'Comme $0 < k < 1$, $k^n \\to 0$ : par encadrement, $u_n \\to \\alpha$.'],
        'exemple_enonce': '$f(\\alpha) = \\alpha$, $|f\'(x)| \\leq \\frac{1}{2}$ sur $I$, $u_n \\in I$ et $\\alpha \\in I$. '
                          'Montrer que $u_n \\to \\alpha$.',
        'exemple_solution': 'IAF : $|u_{n+1} - \\alpha| = |f(u_n) - f(\\alpha)| \\leq \\frac{1}{2}|u_n - \\alpha|$.'
                            '</p><p>Par récurrence : $|u_n - \\alpha| \\leq \\left(\\frac{1}{2}\\right)^n |u_0 - \\alpha|$, '
                            'qui tend vers $0$. Donc $\\lim u_n = \\alpha$.',
        'piege': 'Appliquer l’IAF sans dire que $u_n$ et $\\alpha$ sont dans l’intervalle où $|f\'| \\leq k$.',
        'sur_le_site': [ref('ds3-rattrapage-2sm-2022', 'b6'), ref('cc3-2sm-2026-palmiers', 'b8-1'),
                        ref('ds2-2sm-fidni-2026', 'b18-2')],
    },
    {
        'slug': 'suites-adjacentes', 'chapitre': SU,
        'type_question': 'Convergence de deux suites', 'technique': 'Suites adjacentes',
        'titre': 'Montrer que deux suites ont la même limite',
        'resume': 'Une croissante, une décroissante, leur différence tend vers $0$ : elles sont adjacentes.',
        'signaux': ['Deux suites qui s’encadrent ($u_n \\leq v_n$), ou les sommes partielles paires et impaires.',
                    '« Montrer qu’elles convergent vers la même limite ».'],
        'pourquoi': 'On ne sait souvent calculer la limite d’aucune des deux. Le théorème des suites adjacentes donne '
                    'la convergence ET l’égalité des limites, sans calcul : il suffit de trois vérifications.',
        'methode': ['$(u_n)$ croissante : signe de $u_{n+1} - u_n$.',
                    '$(v_n)$ décroissante : signe de $v_{n+1} - v_n$.',
                    '$\\lim (v_n - u_n) = 0$ (souvent par encadrement).'],
        'exemple_enonce': '$u_n = \\sum_{k=1}^{n} \\frac{1}{k^2}$ et $v_n = u_n + \\frac{1}{n}$. Montrer qu’elles sont adjacentes.',
        'exemple_solution': '$u_{n+1} - u_n = \\frac{1}{(n + 1)^2} > 0$.</p><p>'
                            '$v_{n+1} - v_n = \\frac{1}{(n + 1)^2} + \\frac{1}{n + 1} - \\frac{1}{n} = -\\frac{1}{n(n + 1)^2} < 0$.'
                            '</p><p>$v_n - u_n = \\frac{1}{n} \\to 0$. Donc $(u_n)$ et $(v_n)$ sont adjacentes.',
        'piege': 'Oublier une des trois conditions, souvent la limite de la différence.',
        'sur_le_site': [ref('suites-limites-sanaa-2sm-ex13', 'b2-4'), ref('revision-fct-suites-2sm-haddar-ex4', 'b2')],
    },
    {
        'slug': 'sous-suites-paires-impaires', 'chapitre': SU,
        'type_question': 'Monotonie d’une suite', 'technique': 'Sous-suites paires et impaires',
        'titre': 'Suite $u_{n+1} = f(u_n)$ avec $f$ DÉCROISSANTE',
        'resume': 'La suite oscille : étudie $(u_{2n})$ et $(u_{2n+1})$, qui vérifient $x_{n+1} = (f \\circ f)(x_n)$.',
        'signaux': ['$f$ est décroissante sur l’intervalle où vivent les $u_n$.',
                    '« On pose $x_n = u_{2n}$ et $y_n = u_{2n+1}$ ».'],
        'pourquoi': 'Avec $f$ décroissante, les termes sautent d’un côté à l’autre de la limite : $(u_n)$ n’est pas '
                    'monotone. Mais $f \\circ f$ est croissante, donc chaque sous-suite (un terme sur deux) est monotone.',
        'methode': ['Montrer que $g = f \\circ f$ est croissante sur $I$.',
                    'Comparer $u_2$ et $u_0$, puis $u_3$ et $u_1$ ; récurrence avec $g$ croissante.',
                    'Montrer que les deux sous-suites ont la même limite (adjacentes, ou point fixe commun).',
                    'Conclure : si $u_{2n} \\to \\ell$ et $u_{2n+1} \\to \\ell$, alors $u_n \\to \\ell$.'],
        'exemple_enonce': '$u_0 = 1$ et $u_{n+1} = \\frac{1}{1 + u_n}$. Pourquoi étudier $(u_{2n})$ et $(u_{2n+1})$ ?',
        'exemple_solution': '$f(x) = \\frac{1}{1 + x}$ est décroissante : $u_0 = 1$, $u_1 = \\frac{1}{2}$, '
                            '$u_2 = \\frac{2}{3}$, $u_3 = \\frac{3}{5}$… les termes montent et descendent.</p><p>'
                            '$f \\circ f(x) = \\frac{1 + x}{2 + x}$ est croissante : $(u_{2n})$ et $(u_{2n+1})$ sont monotones.',
        'piege': 'Chercher le signe de $u_{n+1} - u_n$ : il change à chaque terme.',
        'sur_le_site': [ref('suites-limites-sanaa-2sm-ex14', 'b3'), ref('dst-suites-2sm-avicenna', 'b18-2')],
    },
    {
        'slug': 'absurde-limite-precise', 'chapitre': SU,
        'type_question': 'Limite d’une suite', 'technique': 'Raisonnement par l’absurde',
        'titre': 'Montrer qu’une suite tend vers une valeur précise sans pouvoir la calculer',
        'resume': 'Tu sais que $\\ell$ existe et que $\\ell \\geq a$. Suppose $\\ell > a$ : une question précédente '
                  'donne alors une contradiction.',
        'signaux': [
            'La suite est définie de façon IMPLICITE (« $u_n$ est la solution de … ») : aucune formule pour $u_n$.',
            'Tu as déjà : la convergence, un encadrement $\\ell \\geq a$, et une question sur un paramètre $\\rho > a$ '
            '(« soit $\\rho \\in ]a ; 1[$, montrer que … $> 0$ »).',
            'La dernière question dit « converge vers $a$ » : il reste seulement à exclure $\\ell > a$.',
        ],
        'pourquoi': 'Sans formule pour $u_n$, on ne peut pas calculer la limite. En revanche, on sait raisonner sur '
                    'une inégalité. Supposer $\\ell > a$ donne un nombre CONCRET ($\\rho = \\ell$) auquel on peut '
                    'appliquer la question précédente. L’énoncé t’y prépare : quand une question introduit un $\\rho$ '
                    'quelconque juste avant « montrer que la limite vaut $a$ », c’est presque toujours pour remplacer '
                    '$\\rho$ par $\\ell$ dans un raisonnement par l’absurde.',
        'methode': [
            'Rassembler ce qu’on sait : $(u_n)$ converge vers $\\ell$ et $\\ell \\geq a$ (passage à la limite).',
            'Écrire « Supposons $\\ell \\neq a$, donc $\\ell > a$ ».',
            'Trouver une inégalité vraie pour tout $n$ qui fait intervenir $\\ell$ (souvent avec la monotonie : '
            '$u_n \\geq \\ell$ si $(u_n)$ décroît).',
            'Passer à la limite et la comparer au résultat de la question sur $\\rho$, avec $\\rho = \\ell$ : contradiction.',
        ],
        'exemple_enonce': '$P_n(x) = x^n + \\cdots + x - 1$ a une unique racine $u_n > 0$ ; $(u_n)$ est décroissante, '
                          '$u_n > \\frac{1}{2}$, et pour $\\rho \\in ]\\frac{1}{2} ; 1[$ : '
                          '$\\lim\\limits_{n \\to +\\infty} P_n(\\rho) = \\frac{2\\rho - 1}{1 - \\rho} > 0$. '
                          'Montrer que $u_n \\to \\frac{1}{2}$.',
        'exemple_solution': '$(u_n)$ décroît et est minorée : elle converge vers $\\ell$, avec $\\frac{1}{2} \\leq \\ell < 1$.'
                            '</p><p>Supposons $\\ell > \\frac{1}{2}$. Comme $(u_n)$ décroît vers $\\ell$ : $u_n \\geq \\ell$, '
                            'donc $P_n(\\ell) \\leq P_n(u_n) = 0$ ($P_n$ croissante). En passant à la limite : '
                            '$\\lim P_n(\\ell) \\leq 0$.</p><p>Mais avec $\\rho = \\ell$ : $\\lim P_n(\\ell) > 0$. '
                            'Contradiction, donc $\\ell = \\frac{1}{2}$.',
        'piege': 'Écrire « $P_n(u_n) = 0$ donc $P(\\ell) = 0$ » : $P_n$ change avec $n$, on ne peut pas passer à la limite '
                 'ainsi. C’est justement pour cela qu’on passe par l’absurde.',
        'sur_le_site': [ref('suites-limites-sanaa-2sm-ex08', 'b4', 'même idée pour prouver une divergence')],
    },
    {
        'slug': 'absurde-divergence', 'chapitre': SU,
        'type_question': 'Divergence d’une suite', 'technique': 'Raisonnement par l’absurde',
        'titre': 'Montrer qu’une suite diverge',
        'resume': 'Suppose qu’elle converge vers $\\ell$ : une inégalité de l’énoncé devient impossible à la limite.',
        'signaux': ['« Montrer que $(u_n)$ est divergente » ou « $\\lim u_n = +\\infty$ ».',
                    'Une question précédente donne une inégalité comme $u_{2n} - u_n \\geq \\frac{1}{2}$.'],
        'pourquoi': '« Diverger » veut dire « ne converger vers aucun réel » : on ne peut pas le vérifier réel par réel. '
                    'En supposant la convergence vers un $\\ell$, on obtient un nombre précis avec lequel calculer, '
                    'et l’inégalité donnée fournit la contradiction.',
        'methode': ['Supposer $\\lim u_n = \\ell$ (réel).',
                    'En déduire la limite d’une expression ($u_{2n} \\to \\ell$, donc $u_{2n} - u_n \\to 0$).',
                    'Passer à la limite dans l’inégalité connue : $0 \\geq \\frac{1}{2}$, absurde.',
                    'Pour $+\\infty$ : une suite croissante non majorée tend vers $+\\infty$.'],
        'exemple_enonce': '$u_n = 1 + \\frac{1}{2} + \\cdots + \\frac{1}{n}$ et $u_{2n} - u_n \\geq \\frac{1}{2}$. '
                          'Montrer que $(u_n)$ diverge.',
        'exemple_solution': 'Si $u_n \\to \\ell$, alors $u_{2n} \\to \\ell$ et $u_{2n} - u_n \\to 0$. '
                            'Avec $u_{2n} - u_n \\geq \\frac{1}{2}$ : $0 \\geq \\frac{1}{2}$, absurde.</p><p>'
                            'Donc $(u_n)$ diverge ; croissante et non majorée, elle tend vers $+\\infty$.',
        'piege': 'Conclure « diverge » à partir de « croissante » : une suite croissante et majorée converge.',
        'sur_le_site': [ref('suites-limites-sanaa-2sm-ex08', 'b4'), ref('suites-limites-sanaa-2sm-ex08', 'b2')],
    },
    {
        'slug': 'suite-implicite-monotonie', 'chapitre': SU,
        'type_question': 'Monotonie d’une suite', 'technique': 'Comparer avec la fonction suivante',
        'titre': 'Suite définie par « $u_n$ est la solution de $f_n(x) = 0$ »',
        'resume': 'Pour comparer $u_{n+1}$ et $u_n$, calcule le signe de $f_{n+1}(u_n)$.',
        'signaux': ['« L’équation $f_n(x) = 0$ admet une unique solution $u_n$ ».',
                    '« Étudier la monotonie de $(u_n)$ ».'],
        'pourquoi': '$u_n$ n’a pas de formule. Mais $f_{n+1}(u_{n+1}) = 0$ : si l’on connaît le signe de $f_{n+1}(u_n)$, '
                    'la stricte monotonie de $f_{n+1}$ dit de quel côté de $u_{n+1}$ se trouve $u_n$.',
        'methode': ['Exprimer $f_{n+1}(x)$ avec $f_n(x)$ (souvent $f_{n+1}(x) = f_n(x) + $ un terme).',
                    'En déduire le signe de $f_{n+1}(u_n)$, car $f_n(u_n) = 0$.',
                    'Comparer à $f_{n+1}(u_{n+1}) = 0$ avec la monotonie de $f_{n+1}$.'],
        'exemple_enonce': '$f_n(x) = x^n + x - 1$ sur $[0 ; 1]$, de racine unique $u_n$. Monotonie de $(u_n)$ ?',
        'exemple_solution': '$f_{n+1}(u_n) = u_n^{n+1} + u_n - 1 = u_n^{n+1} - u_n^n = u_n^n(u_n - 1) < 0$, '
                            'car $0 < u_n < 1$.</p><p>Donc $f_{n+1}(u_n) < 0 = f_{n+1}(u_{n+1})$ et, $f_{n+1}$ étant '
                            'strictement croissante : $u_n < u_{n+1}$. La suite est croissante.',
        'piege': 'Comparer $f_n(u_n)$ et $f_{n+1}(u_{n+1})$ : ils valent tous deux $0$, cela ne dit rien.',
        'sur_le_site': [ref('ds2-2sm-2021', 'b16-1'), ref('dc2-2sm-belkhatir-4h', 'b4')],
    },
    {
        'slug': 'somme-encadrement', 'chapitre': SU,
        'type_question': 'Somme de termes', 'technique': 'Encadrement (gendarmes)',
        'titre': 'Encadrer une somme $\\sum_{k=n+1}^{2n} \\dots$',
        'resume': 'Chaque terme est entre le plus petit et le plus grand : multiplie par le nombre de termes.',
        'signaux': ['Une somme dont le nombre de termes dépend de $n$, sans formule fermée.'],
        'pourquoi': 'On ne sait pas calculer la somme, mais chaque terme est facile à encadrer. Une somme de $N$ termes '
                    'tous compris entre $m$ et $M$ est entre $Nm$ et $NM$.',
        'methode': ['Compter les termes : de $k = n + 1$ à $2n$, il y en a $n$.',
                    'Encadrer le terme général pour $k$ dans cet intervalle.',
                    'Sommer les inégalités, puis appliquer les gendarmes si on cherche une limite.'],
        'exemple_enonce': 'Montrer que $\\frac{1}{2} \\leq \\sum_{k=n+1}^{2n} \\frac{1}{k} \\leq 1$.',
        'exemple_solution': 'Pour $n + 1 \\leq k \\leq 2n$ : $\\frac{1}{2n} \\leq \\frac{1}{k} \\leq \\frac{1}{n + 1}$.'
                            '</p><p>Il y a $n$ termes : $\\frac{n}{2n} \\leq \\sum \\leq \\frac{n}{n + 1}$, soit '
                            '$\\frac{1}{2} \\leq \\sum \\leq 1$.',
        'piege': 'Se tromper dans le nombre de termes : de $p$ à $q$, il y en a $q - p + 1$.',
        'sur_le_site': [ref('suites-limites-sanaa-2sm-ex08', 'b2')],
    },
    {
        'slug': 'somme-telescopique', 'chapitre': SU,
        'type_question': 'Somme de termes', 'technique': 'Télescopage',
        'titre': 'Calculer ou majorer une somme par télescopage',
        'resume': 'Écris chaque terme comme $a_k - a_{k+1}$ : presque tout s’annule.',
        'signaux': ['$\\frac{1}{k(k + 1)}$, $\\sqrt{k + 1} - \\sqrt{k}$, ou une inégalité « $\\leq 2(\\sqrt{k} - \\sqrt{k - 1})$ » à prouver d’abord.'],
        'pourquoi': 'Une somme de différences successives se simplifie : il ne reste que le premier et le dernier terme. '
                    'Quand l’énoncé fait prouver une inégalité avec une différence, c’est pour sommer ensuite.',
        'methode': ['Écrire (ou majorer) le terme $k$ sous la forme $a_k - a_{k+1}$.',
                    'Écrire la somme en ligne pour voir les termes qui s’annulent.',
                    'Garder $a_1 - a_{n+1}$.'],
        'exemple_enonce': 'Calculer $S_n = \\sum_{k=1}^{n} \\frac{1}{k(k + 1)}$.',
        'exemple_solution': '$\\frac{1}{k(k + 1)} = \\frac{1}{k} - \\frac{1}{k + 1}$, donc '
                            '$S_n = \\left(1 - \\frac{1}{2}\\right) + \\left(\\frac{1}{2} - \\frac{1}{3}\\right) + \\cdots + '
                            '\\left(\\frac{1}{n} - \\frac{1}{n + 1}\\right) = 1 - \\frac{1}{n + 1}$.',
        'piege': 'Mal placer les indices du dernier terme restant.',
        'sur_le_site': [ref('dst-suites-2sm-avicenna', 'b6-2')],
    },
]
