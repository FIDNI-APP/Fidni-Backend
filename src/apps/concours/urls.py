from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views


router = DefaultRouter()
router.register(r'exams', views.ConcoursExamViewSet, basename='concours-exam')
router.register(r'tips', views.ConcoursTipViewSet, basename='concours-tip')

urlpatterns = [
    # Exam stats + activity
    path('exams/<int:exam_id>/stats/', views.exam_stats, name='concours-exam-stats'),
    path('exams/<int:exam_id>/activity/', views.exam_activity, name='concours-exam-activity'),

    # Comments
    path('exams/<int:exam_id>/comments/', views.exam_comments, name='concours-exam-comments'),
    path('tips/<int:tip_id>/comments/', views.tip_comments, name='concours-tip-comments'),
    path('comments/<int:comment_id>/', views.comment_detail, name='concours-comment-detail'),

    # Simulation
    path('sessions/start/', views.start_simulation, name='concours-session-start'),
    path('sessions/', views.my_sessions, name='concours-my-sessions'),
    path('sessions/<uuid:session_id>/', views.get_session, name='concours-session-detail'),
    path('sessions/<uuid:session_id>/answer/', views.answer_question, name='concours-session-answer'),
    path('sessions/<uuid:session_id>/submit/', views.submit_session, name='concours-session-submit'),
    path('sessions/<uuid:session_id>/recap/', views.session_recap, name='concours-session-recap'),
] + router.urls
