"""
OpenAI GPT-4 Vision integration for solution correction
"""
import base64
import json
import time
import re
from typing import Dict, List, Any
from openai import OpenAI
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def strip_html(html_text: str) -> str:
    """Remove HTML tags from text"""
    if not html_text:
        return ""
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', '', html_text)
    # Decode HTML entities
    clean = clean.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    return clean.strip()

SYSTEM_PROMPT_CONVERSATIONAL = """Professeur expert maths/physique. Niveau académique élevé.

Rôle: Guide avec rigueur sans donner réponses complètes. Pose questions techniques. Indices progressifs théoriques. Vocabulaire scientifique précis.

Modes:
- hints: Indice 3 niveaux (théorème→méthodo→étapes)
- concepts: Définitions formelles rigoureuses
- socratic: Questions techniques guidées
- general: Discussion scientifique

**CRITIQUE - LaTeX OBLIGATOIRE pour TOUTES expressions maths:**
- Inline: $f(x)=x^2$, $\Delta x$, $\frac{dy}{dx}$
- Display: $$\int_0^1 x^2dx=\frac{1}{3}$$
- JAMAIS texte brut. Ex: $\vec{v}$, $\mathbf{A}$, $\lim_{x\to 0}$
- Français. Ne donne JAMAIS solution complète."""

SYSTEM_PROMPT_CORRECTION = """Tu es un professeur expert en mathématiques et physique qui évalue des copies avec rigueur académique.

Compare la solution manuscrite de l'étudiant (dans l'image) avec la solution type fournie.

Critères d'évaluation:
1. Rigueur méthodologique et raisonnement formel
2. Exactitude des calculs et manipulations algébriques
3. Complétude de la démonstration
4. Notation mathématique et présentation

Identifie EXPLICITEMENT:
- **Forces**: Aspects corrects avec justification technique
- **Faiblesses**: Erreurs, imprécisions, lacunes théoriques
- **Suggestions**: Améliorations précises avec références théoriques

FORMATAGE MATHÉMATIQUE - OBLIGATOIRE:
- **TOUTES** les expressions mathématiques DOIVENT être en LaTeX
- Inline: $f(x) = x^2$, $\Delta x$, $\nabla \cdot \vec{E}$
- Display: $$\int_0^1 x^2 dx = \frac{1}{3}$$
- N'écris JAMAIS de maths en texte brut

Retourne UNIQUEMENT du JSON valide dans ce format EXACT:
{
  "score_awarded": 18.5,
  "score_total": 20,
  "feedback": {
    "q1": {
      "status": "correct",
      "points": 5,
      "comment": "Démonstration rigoureuse. Application correcte du théorème. La dérivée $f'(x) = 2x - 4$ est obtenue par $\\frac{d}{dx}(x^2) = 2x$ et $\\frac{d}{dx}(-4x) = -4$.",
      "strengths": ["Application correcte des règles de dérivation", "Notation mathématique appropriée"],
      "weaknesses": []
    },
    "q2": {
      "status": "partial",
      "points": 3,
      "comment": "Identification correcte de la formule $F = ma$ mais conversion d'unités manquante.",
      "strengths": ["Identification correcte de la loi de Newton $\\vec{F} = m\\vec{a}$"],
      "weaknesses": ["Absence de conversion SI: $1\\text{ km/h} = \\frac{1}{3.6}\\text{ m/s}$", "Étape de vérification dimensionnelle omise"],
      "suggestions": "Toujours vérifier l'homogénéité: $[F] = [m][a] = \\text{kg} \\cdot \\text{m/s}^2 = \\text{N}$"
    }
  },
  "overall_comment": "Maîtrise des concepts fondamentaux. Attention à la rigueur dans les conversions et vérifications dimensionnelles."
}

Le statut doit être: "correct", "partial", ou "incorrect"
Utilise terminologie technique française."""


class AIVisionService:
    """OpenAI GPT-4 Vision integration for solution correction"""

    def __init__(self, api_key: str = None):
        """
        Initialize OpenAI client

        Args:
            api_key: OpenAI API key (defaults to settings.OPENAI_API_KEY)
        """
        self.api_key = api_key or settings.OPENAI_API_KEY
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")

        self.client = OpenAI(api_key=self.api_key)
        self.model = settings.OPENAI_MODEL
        self.max_tokens = settings.OPENAI_MAX_TOKENS
        self.temperature = settings.OPENAI_TEMPERATURE

    def _encode_image(self, image_path: str) -> str:
        """
        Encode image to base64 string

        Args:
            image_path: Path to image file

        Returns:
            Base64 encoded image string
        """
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def analyze_solution(
        self,
        image_path: str,
        marked_solution: str,
        structure: Dict[str, Any],
        total_points: int
    ) -> Dict[str, Any]:
        """
        Send image + context to GPT-4 Vision for correction

        Args:
            image_path: Path to uploaded solution image
            marked_solution: HTML content of marked solution
            structure: Exercise structure dict
            total_points: Total points for the exercise

        Returns:
            dict: {
                score_awarded: float,
                score_total: float,
                feedback: dict,
                raw_response: str,
                processing_time_ms: int
            }
        """
        start_time = time.time()

        try:
            # Encode image
            base64_image = self._encode_image(image_path)

            # Build context about the exercise
            context = self._build_exercise_context(structure, marked_solution, total_points)

            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT_CORRECTION
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": context
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                max_completion_tokens=self.max_tokens
            )

            processing_time_ms = int((time.time() - start_time) * 1000)

            # Extract response
            raw_response = response.choices[0].message.content
            logger.info(f"AI Vision response received in {processing_time_ms}ms")

            # Parse JSON response
            try:
                # Try to extract JSON from response (in case model adds extra text)
                json_start = raw_response.find('{')
                json_end = raw_response.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = raw_response[json_start:json_end]
                    result = json.loads(json_str)
                else:
                    raise ValueError("No JSON found in response")

                return {
                    'score_awarded': float(result.get('score_awarded', 0)),
                    'score_total': float(result.get('score_total', total_points)),
                    'feedback': result.get('feedback', {}),
                    'raw_response': raw_response,
                    'processing_time_ms': processing_time_ms
                }

            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Failed to parse AI response as JSON: {e}")
                logger.error(f"Raw response: {raw_response}")

                # Return error structure
                return {
                    'score_awarded': 0,
                    'score_total': total_points,
                    'feedback': {'error': {'status': 'incorrect', 'comment': 'Failed to analyze solution. Please try again.'}},
                    'raw_response': raw_response,
                    'processing_time_ms': processing_time_ms
                }

        except Exception as e:
            logger.error(f"AI Vision analysis failed: {e}", exc_info=True)
            processing_time_ms = int((time.time() - start_time) * 1000)

            return {
                'score_awarded': 0,
                'score_total': total_points,
                'feedback': {'error': {'status': 'incorrect', 'comment': f'Error analyzing solution: {str(e)}'}},
                'raw_response': str(e),
                'processing_time_ms': processing_time_ms
            }

    def start_conversation(
        self,
        exercise_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Start conversation before solution submission

        Args:
            exercise_context: Exercise info (title, structure, points)

        Returns:
            dict: {greeting_message: str}
        """
        try:
            context_text = self._build_exercise_context(
                exercise_context.get('structure', {}),
                exercise_context.get('solution', ''),
                exercise_context.get('total_points', 20)
            )

            messages = [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT_CONVERSATIONAL + "\n\nREMINDER CRITIQUE: Utilise TOUJOURS $...$ pour les expressions mathématiques. Exemple: $f(x) = x^2$ et NON pas f(x) = x^2"
                },
                {
                    "role": "user",
                    "content": f"Voici l'exercice sur lequel je vais travailler:\n\n{context_text}\n\nPrésente-toi brièvement et propose ton aide de manière technique."
                }
            ]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=512
            )

            greeting = response.choices[0].message.content

            return {
                'greeting_message': greeting
            }

        except Exception as e:
            logger.error(f"Failed to start conversation: {e}", exc_info=True)
            return {
                'greeting_message': "Bonjour ! Je suis là pour t'aider avec cet exercice. N'hésite pas à me poser des questions !"
            }

    def chat_pedagogical(
        self,
        user_message: str,
        chat_history: List[Dict[str, str]],
        exercise_context: Dict[str, Any],
        pedagogical_mode: str = 'general',
        pedagogical_context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Pedagogical chat with different modes

        Args:
            user_message: User's message
            chat_history: Previous chat messages
            exercise_context: Exercise info for context
            pedagogical_mode: 'hints', 'concepts', 'socratic', 'general'
            pedagogical_context: Track hints given, concepts explained

        Returns:
            dict: {response: str, updated_history: list, updated_context: dict}
        """
        try:
            pedagogical_context = pedagogical_context or {'hints_given': {}, 'concepts_explained': []}

            # Build mode-specific system instruction (concise to save tokens)
            mode_instructions = {
                'hints': "\nINDICES: Niveau 1→théorème. 2→méthodo. 3→étapes. LaTeX: $f'(x)$",
                'concepts': "\nCONCEPTS: Définitions formelles. Théorèmes. LaTeX: $\\forall x\\in\\mathbb{R}$",
                'socratic': "\nSOCRATIQUE: Questions guidées. Ex: \"Dérivée de $x^n$?\"",
                'general': "\nGÉNÉRAL: Discussion technique rigoureuse. LaTeX obligatoire."
            }

            system_content = SYSTEM_PROMPT_CONVERSATIONAL + mode_instructions.get(pedagogical_mode, '')

            # Build messages
            messages = [
                {
                    "role": "system",
                    "content": system_content
                }
            ]

            # Add exercise context ONLY if chat history is empty (first message)
            # Otherwise context is already in greeting message
            if exercise_context and len(chat_history) == 0:
                context_text = self._build_exercise_context(
                    exercise_context.get('structure', {}),
                    exercise_context.get('solution', ''),
                    exercise_context.get('total_points', 20)
                )
                messages.append({
                    "role": "system",
                    "content": f"Exercice:\n{context_text}"
                })

            # Add pedagogical context
            if pedagogical_context.get('hints_given'):
                hints_summary = ", ".join([f"{q}: niveau {lvl}" for q, lvl in pedagogical_context['hints_given'].items()])
                messages.append({
                    "role": "system",
                    "content": f"Indices déjà donnés: {hints_summary}"
                })

            # Add chat history
            for msg in chat_history:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

            # Add new user message
            messages.append({
                "role": "user",
                "content": user_message
            })

            # Call OpenAI
            logger.info(f"Calling OpenAI with {len(messages)} messages in {pedagogical_mode} mode")
            logger.info(f"Last user message: {user_message[:100]}...")

            # Calculate approximate token count for debugging
            total_chars = sum(len(str(m.get('content', ''))) for m in messages)
            logger.info(f"Approximate total context characters: {total_chars}")

            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_completion_tokens=2048  # Increased from 1024
                )
            except Exception as api_error:
                logger.error(f"OpenAI API call failed: {api_error}", exc_info=True)
                raise

            logger.info(f"OpenAI response finish_reason: {response.choices[0].finish_reason if response.choices else 'NO_CHOICES'}")

            # Check for refusal
            if hasattr(response.choices[0].message, 'refusal') and response.choices[0].message.refusal:
                logger.error(f"OpenAI refused to respond: {response.choices[0].message.refusal}")
                ai_response = f"L'IA a refusé de répondre: {response.choices[0].message.refusal}"
            else:
                ai_response = response.choices[0].message.content

            logger.info(f"OpenAI response content length: {len(ai_response) if ai_response else 0}")

            if ai_response and len(ai_response) > 0:
                logger.info(f"Response preview: {ai_response[:200]}...")
            else:
                logger.error("OpenAI returned empty/null/None response")
                logger.error(f"finish_reason: {response.choices[0].finish_reason}")
                logger.error(f"message object: {response.choices[0].message}")
                ai_response = "Désolé, je n'ai pas pu générer de réponse. Peux-tu reformuler ta question ?"

            # Update pedagogical context based on mode
            if pedagogical_mode == 'hints':
                # Track hint level (simple increment for now)
                question_id = 'general'
                current_level = pedagogical_context['hints_given'].get(question_id, 0)
                pedagogical_context['hints_given'][question_id] = min(current_level + 1, 3)

            # Update history (timestamp in milliseconds for frontend)
            current_time_ms = int(time.time() * 1000)
            updated_history = chat_history + [
                {"role": "user", "content": user_message, "timestamp": current_time_ms},
                {"role": "assistant", "content": ai_response, "timestamp": current_time_ms}
            ]

            return {
                'response': ai_response,
                'updated_history': updated_history,
                'updated_context': pedagogical_context
            }

        except Exception as e:
            logger.error(f"Pedagogical chat failed: {e}", exc_info=True)
            return {
                'response': f"Désolé, j'ai rencontré une erreur : {str(e)}",
                'updated_history': chat_history,
                'updated_context': pedagogical_context
            }

    def chat_followup(
        self,
        user_message: str,
        chat_history: List[Dict[str, str]],
        original_feedback: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Continue conversation about correction

        Args:
            user_message: User's follow-up question
            chat_history: Previous chat messages
            original_feedback: Original correction feedback for context

        Returns:
            dict: {response: str, updated_history: list}
        """
        try:
            # Build messages from history
            messages = [
                {
                    "role": "system",
                    "content": "Tu es un professeur bienveillant de mathématiques et physique qui répond aux questions sur une correction que tu viens de faire. Sois encourageant et fournis des explications claires en français."
                },
                {
                    "role": "assistant",
                    "content": f"Je viens de corriger ta solution. Voici mon évaluation : {json.dumps(original_feedback, ensure_ascii=False)}"
                }
            ]

            # Add chat history
            for msg in chat_history:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

            # Add new user message
            messages.append({
                "role": "user",
                "content": user_message
            })

            # Call OpenAI
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=1024
            )

            ai_response = response.choices[0].message.content

            # Update history (timestamp in milliseconds for frontend)
            current_time_ms = int(time.time() * 1000)
            updated_history = chat_history + [
                {"role": "user", "content": user_message, "timestamp": current_time_ms},
                {"role": "assistant", "content": ai_response, "timestamp": current_time_ms}
            ]

            return {
                'response': ai_response,
                'updated_history': updated_history
            }

        except Exception as e:
            logger.error(f"AI chat follow-up failed: {e}", exc_info=True)
            return {
                'response': f"Désolé, j'ai rencontré une erreur : {str(e)}",
                'updated_history': chat_history
            }

    def _build_exercise_context(
        self,
        structure: Dict[str, Any],
        marked_solution: str,
        total_points: int
    ) -> str:
        """
        Build context string about the exercise

        Args:
            structure: Exercise structure dict (contains exercise content in blocks)
            marked_solution: HTML of marked solution
            total_points: Total points

        Returns:
            Formatted context string
        """
        context_parts = [
            f"Points totaux: {total_points}",
            "\n=== ÉNONCÉ DE L'EXERCICE ==="
        ]

        # Extract full exercise content from structure blocks
        if structure and 'blocks' in structure:
            for block in structure['blocks']:
                block_type = block.get('type', '')

                # Extract text content from different block types
                if block_type == 'context':
                    # Context block contains general information
                    content_obj = block.get('content', {})
                    if isinstance(content_obj, dict) and 'html' in content_obj:
                        html_content = content_obj['html']
                        clean_text = strip_html(html_content)
                        if clean_text:
                            context_parts.append(f"\n{clean_text}")
                    elif isinstance(content_obj, str):
                        context_parts.append(content_obj)

                elif block_type == 'text':
                    # Text block contains exercise statement
                    content_obj = block.get('content', {})
                    if isinstance(content_obj, dict) and 'html' in content_obj:
                        html_content = content_obj['html']
                        clean_text = strip_html(html_content)
                        if clean_text:
                            context_parts.append(f"\n{clean_text}")
                    elif isinstance(content_obj, str):
                        context_parts.append(content_obj)

                elif block_type == 'question':
                    # Question block
                    q_label = block.get('label', '')
                    q_points = block.get('points', 0)

                    # Extract question content from questionContent.html
                    question_content_obj = block.get('questionContent', {})
                    q_content = ""
                    if isinstance(question_content_obj, dict) and 'html' in question_content_obj:
                        q_content = strip_html(question_content_obj['html'])
                    elif isinstance(question_content_obj, str):
                        q_content = strip_html(question_content_obj)

                    context_parts.append(f"\n**Question {q_label}** ({q_points} points)")
                    if q_content:
                        context_parts.append(q_content)

                    # Add sub-questions with their content
                    if 'subQuestions' in block:
                        for sub_q in block['subQuestions']:
                            sub_label = sub_q.get('label', '')
                            sub_points = sub_q.get('points', 0)

                            sub_content_obj = sub_q.get('questionContent', {})
                            sub_content = ""
                            if isinstance(sub_content_obj, dict) and 'html' in sub_content_obj:
                                sub_content = strip_html(sub_content_obj['html'])
                            elif isinstance(sub_content_obj, str):
                                sub_content = strip_html(sub_content_obj)

                            context_parts.append(f"\n  **Sous-question {q_label}{sub_label}** ({sub_points} points)")
                            if sub_content:
                                context_parts.append(f"  {sub_content}")

        # Add marked solution if available
        if marked_solution:
            context_parts.append("\n=== SOLUTION TYPE (pour référence) ===")
            context_parts.append(marked_solution)

        return "\n".join(context_parts)
