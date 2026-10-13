# apps/skilliq/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('my/', views.get_my_assessments, name='my-assessments'),
    path('available/', views.get_available, name='skill-available'),
    path('nouveaux/', views.get_new, name='skill-new'),
    path('quiz/<int:chapter_id>/', views.get_quiz, name='get-quiz'),
    path('submit/<int:chapter_id>/', views.submit_quiz, name='submit-quiz'),
    path('verifier/<int:question_id>/', views.check_answer, name='check-answer'),
    path('chapter/<int:chapter_id>/', views.get_chapter_assessment, name='chapter-assessment'),
]
