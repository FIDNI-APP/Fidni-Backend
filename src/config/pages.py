"""Pages « À propos » et « Contact » : une seule source pour leurs textes.

Servies au front par GET /api/pages/<slug>/ (pages APropos.tsx et Contact.tsx) et pré-remplies pour les
moteurs de recherche par config/seo.py (listing_page), comme l'accueil : le même texte des deux côtés.
Ces pages comptent pour l'examen AdSense (qui fait le site, comment les contenus sont faits, comment
nous joindre). Rester exact : ne rien promettre que le site ne fait pas.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

CONTACT_EMAIL = 'contact@fidni.fr'

PAGES = {
    'a-propos': {
        'title': 'À propos de Fidni – maths corrigées pour le lycée au Maroc',
        'h1': 'À propos de Fidni',
        'description': ('Fidni : cours, exercices et devoirs de maths corrigés pour les lycéens marocains, du Tronc '
                        'commun au 2ème Bac. Qui fait le site, comment les contenus sont rédigés et corrigés.'),
        'intro': ('Fidni aide les lycéens marocains à réussir en mathématiques, du Tronc commun au 2ème Bac, '
                  'avec des cours clairs et des exercices dont la correction explique vraiment le raisonnement.'),
        'sections': [
            {'title': 'Ce que tu trouves sur Fidni', 'paragraphs': [
                'Des cours, des exercices corrigés pas à pas, des devoirs surveillés et des sujets du Bac national '
                'avec leur barème, pour le Tronc commun Sciences, la 1ère Bac Sciences mathématiques et le 2ème Bac '
                'Sciences mathématiques, Sciences physiques et SVT (option française).',
                'Tout est rangé niveau par niveau et chapitre par chapitre, dans l’ordre du programme officiel '
                'marocain. Pour chaque chapitre, la page rappelle ce que dit le programme : contenus, ce qu’il faut '
                'savoir faire, théorèmes.',
                'Avec un compte gratuit, tu t’auto-évalues question par question, tu suis ta progression chapitre '
                'par chapitre, tu prépares tes devoirs avec des listes de révision et tu imprimes tes feuilles '
                'd’exercices en PDF.',
            ], 'links': [
                {'label': 'Exercices corrigés', 'href': '/exercises'},
                {'label': 'Cours', 'href': '/lessons'},
                {'label': 'Devoirs et examens', 'href': '/exams'},
            ]},
            {'title': 'Qui fait Fidni', 'paragraphs': [
                'Fidni est fait par une petite équipe passionnée de mathématiques, fondée par Oussama Hadder. '
                'L’équipe écrit les contenus, les relit et développe le site.',
            ]},
            {'title': 'Comment les contenus sont rédigés', 'paragraphs': [
                'Les cours, les énoncés et les corrigés sont rédigés par l’équipe. Chaque contenu est rattaché à '
                'son niveau et à son chapitre du programme officiel.',
                'Les sujets du Bac national sont les sujets officiels des sessions passées ; leurs corrigés sont '
                'rédigés par l’équipe.',
                'Un corrigé détaille chaque étape : la méthode, les calculs et la conclusion. Les devoirs et les '
                'examens gardent leur barème, pour s’entraîner dans les conditions de l’épreuve.',
            ]},
            {'title': 'Une erreur ? On corrige', 'paragraphs': [
                'Une erreur peut nous échapper. Sous chaque contenu, le bouton « Une erreur ? Signale-la » prévient '
                'l’équipe : chaque signalement est vérifié, le contenu est corrigé si besoin et l’élève reçoit la '
                'réponse dans ses notifications.',
            ]},
            {'title': 'Gratuit, financé par la publicité', 'paragraphs': [
                'Fidni est gratuit, sans abonnement. Pour financer l’hébergement et le temps passé à écrire les '
                'contenus, le site peut afficher des annonces (Google AdSense), seulement si tu les acceptes dans '
                'le bandeau des cookies. Tu peux changer d’avis à tout moment (« Gérer les cookies », en bas de page).',
            ], 'links': [{'label': 'Politique de confidentialité', 'href': '/privacy-policy'}]},
            {'title': 'Nous écrire', 'paragraphs': [
                'Une question, une suggestion, une idée de contenu : écris-nous.',
            ], 'links': [{'label': CONTACT_EMAIL, 'href': f'mailto:{CONTACT_EMAIL}'},
                         {'label': 'Page Contact', 'href': '/contact'}]},
        ],
    },
    'contact': {
        'title': 'Contact – Fidni',
        'h1': 'Contacter l’équipe Fidni',
        'description': ('Contacter l’équipe Fidni : une question, une erreur dans un exercice ou un cours, une '
                        'suggestion, ou une demande sur tes données personnelles.'),
        'intro': 'Une question, une suggestion, une erreur dans un contenu : l’équipe lit tous les messages.',
        'sections': [
            {'title': 'Par e-mail', 'paragraphs': [
                f'Écris-nous à {CONTACT_EMAIL}. Nous lisons tous les messages et répondons dès que possible.',
            ], 'links': [{'label': CONTACT_EMAIL, 'href': f'mailto:{CONTACT_EMAIL}'}]},
            {'title': 'Une erreur dans un exercice ou un cours ?', 'paragraphs': [
                'Le plus rapide : le bouton « Une erreur ? Signale-la », sous le contenu ou à côté d’une question '
                '(avec un compte). Le signalement arrive à l’équipe avec le contenu concerné, et la réponse arrive '
                'dans tes notifications.',
            ]},
            {'title': 'Tes données personnelles', 'paragraphs': [
                f'Pour consulter, corriger ou supprimer tes données, écris à {CONTACT_EMAIL}, ou supprime ton '
                'compte depuis tes réglages.',
            ], 'links': [{'label': 'Politique de confidentialité', 'href': '/privacy-policy'}]},
            {'title': 'Éditeur du site', 'paragraphs': [
                'Fidni est édité par Oussama Hadder.',
            ], 'links': [{'label': 'Mentions légales', 'href': '/mentions-legales'},
                         {'label': 'À propos de Fidni', 'href': '/a-propos'}]},
        ],
    },
}


@api_view(['GET'])
@permission_classes([AllowAny])
def page_view(request, slug):
    """GET /api/pages/<slug>/ : texte d'une page (« a-propos », « contact »)."""
    page = PAGES.get(slug)
    if page is None:
        return Response({'detail': 'Page introuvable.'}, status=404)
    return Response({'slug': slug, **page})
