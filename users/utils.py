"""
Utility functions for users app
"""
import random

# Default avatar URLs (using DiceBear API for consistent, free avatars)
# These are SVG-based avatars that are always available
DEFAULT_AVATARS = [
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Felix",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Aneka",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Luna",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Max",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Sophie",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Oliver",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Emma",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Leo",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Mia",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Jack",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Zoe",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Noah",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Lily",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Lucas",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Ava",
]


def get_random_avatar():
    """
    Returns a random default avatar URL
    """
    return random.choice(DEFAULT_AVATARS)


def get_user_avatar_or_default(user_profile):
    """
    Returns the user's avatar if they have one, otherwise returns a random default avatar
    """
    if user_profile.avatar:
        return user_profile.avatar
    return get_random_avatar()
