"""
Correction IA d'une copie manuscrite (photo) — pipeline minimal.

Une seule responsabilité : photo + structure de l'exercice (json_content)
→ verdict PAR QUESTION, aligné sur les question_path ('q1', 'q1.a', …),
comparé aux solutions officielles contenues dans la structure.

Accès réservé au superuser (voir things/views.ai_correct).
"""
import base64
import json
import re
import time
import logging

from openai import OpenAI
from django.conf import settings

logger = logging.getLogger(__name__)


def strip_html(html_text: str) -> str:
    if not html_text:
        return ""
    clean = re.sub(r'<[^>]+>', '', html_text)
    return re.sub(r'\s+', ' ', clean).strip()


def _walk_questions(structure: dict):
    """Yield (path, label, enonce, solution, points) pour chaque question.

    `path` = id du bloc (et `<block_id>.<sub_id>`), aligné sur le renderer front
    et sur QuestionProgress.question_path. `label` est lisible (Q1, Q2a…).
    """
    def sol_text(node):
        sol = node.get('solution')
        if isinstance(sol, dict):
            return strip_html((sol.get('content') or {}).get('html', '') if isinstance(sol.get('content'), dict) else str(sol))
        return strip_html(str(sol or ''))

    qnum = 0
    for block in structure.get('blocks', []):
        if block.get('type') != 'question':
            continue
        qnum += 1
        bid = block.get('id')
        subs = block.get('subQuestions') or []
        if subs:
            for i, sub in enumerate(subs):
                yield (
                    f"{bid}.{sub.get('id')}",
                    f"Q{qnum}{chr(ord('a') + i)}",
                    strip_html((sub.get('content') or {}).get('html', '')),
                    sol_text(sub),
                    sub.get('points') or 0,
                )
        else:
            yield (
                str(bid),
                f"Q{qnum}",
                strip_html((block.get('content') or {}).get('html', '')),
                sol_text(block),
                block.get('points') or 0,
            )


PROMPT = """Tu es un correcteur de mathématiques rigoureux et bienveillant.
Voici un exercice et ses solutions officielles, question par question, puis la PHOTO de la copie manuscrite d'un étudiant.

{questions}

Analyse la copie et rends ton verdict pour CHAQUE question listée ci-dessus.
Réponds UNIQUEMENT avec un JSON valide, exactement ce schéma :
{{
  "per_question": [
    {{"path": "<le path exact, ex. q1 ou q2.a>",
      "verdict": "success" | "partial" | "failed" | "not_attempted",
      "comment": "<1-2 phrases en français : ce qui est juste, l'erreur précise s'il y en a une>"}}
  ],
  "score_awarded": <total des points obtenus, nombre>,
  "global_feedback": "<3-4 phrases en français : bilan et conseil principal>"
}}
Si une question n'apparaît pas sur la copie, verdict "not_attempted". N'invente jamais de contenu absent de la copie."""


class AICorrector:
    """Photo d'une copie → verdicts par question. C'est tout."""

    def __init__(self):
        api_key = getattr(settings, 'OPENAI_API_KEY', None)
        if not api_key:
            raise RuntimeError('OPENAI_API_KEY manquant')
        self.client = OpenAI(api_key=api_key)
        self.model = settings.OPENAI_MODEL

    def correct(self, image_path: str, structure: dict) -> dict:
        questions = list(_walk_questions(structure))
        if not questions:
            raise ValueError('Structure sans questions')
        total_points = sum(q[4] for q in questions) or 20

        qtext = '\n'.join(
            f'--- path="{path}" ({label}, {points} pts)\nÉNONCÉ : {enonce}\nSOLUTION OFFICIELLE : {solution or "(non fournie)"}'
            for path, label, enonce, solution, points in questions
        )

        with open(image_path, 'rb') as f:
            image_b64 = base64.b64encode(f.read()).decode()

        start = time.time()
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': PROMPT.format(questions=qtext)},
                    {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{image_b64}'}},
                ],
            }],
            max_tokens=settings.OPENAI_MAX_TOKENS,
        )
        elapsed_ms = int((time.time() - start) * 1000)
        raw = response.choices[0].message.content or ''

        # Le modèle peut entourer le JSON de texte/backticks — on extrait le premier objet.
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            raise ValueError(f'Réponse IA sans JSON: {raw[:200]}')
        result = json.loads(match.group(0))

        return {
            'per_question': result.get('per_question', []),
            'score_awarded': result.get('score_awarded', 0),
            'score_total': total_points,
            'global_feedback': result.get('global_feedback', ''),
            'raw_response': raw,
            'processing_time_ms': elapsed_ms,
        }
