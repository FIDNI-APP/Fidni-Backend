from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views


router = DefaultRouter()
router.register(r'', views.ClassroomViewSet, basename='classroom')

# TDList nested under /classrooms/<classroom_pk>/td-lists/
td_list_collection = views.TDListViewSet.as_view({'get': 'list', 'post': 'create'})
td_list_detail = views.TDListViewSet.as_view({
    'get': 'retrieve', 'patch': 'partial_update', 'put': 'update', 'delete': 'destroy',
})
td_list_add_item = views.TDListViewSet.as_view({'post': 'add_item'})
td_list_remove_item = views.TDListViewSet.as_view({'delete': 'remove_item'})

urlpatterns = [
    path('join/', views.join_classroom, name='classroom-join'),
    path('progress/weekly/', views.weekly_progress, name='classroom-weekly-progress'),

    # TD lists nested
    path('<int:classroom_pk>/td-lists/', td_list_collection, name='tdlist-list'),
    path('<int:classroom_pk>/td-lists/<int:pk>/', td_list_detail, name='tdlist-detail'),
    path('<int:classroom_pk>/td-lists/<int:pk>/items/', td_list_add_item, name='tdlist-add-item'),
    path('<int:classroom_pk>/td-lists/<int:pk>/items/<int:item_id>/', td_list_remove_item, name='tdlist-remove-item'),

    # Skill stats
    path('<int:pk>/student-stats/', views.classroom_student_stats, name='classroom-student-stats'),
    path('<int:pk>/roster-stats/', views.classroom_roster_stats, name='classroom-roster-stats'),
] + router.urls
