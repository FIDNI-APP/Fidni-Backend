"""Custom exceptions for the application"""

class ServiceException(Exception):
    """Base exception for service layer"""
    pass

class ValidationException(ServiceException):
    """Raised when validation fails"""
    pass

class NotFoundException(ServiceException):
    """Raised when a resource is not found"""
    pass

class PermissionDeniedException(ServiceException):
    """Raised when permission is denied"""
    pass
