"""Request identity, also copied into background AI/grading jobs."""
from contextvars import ContextVar

current_user = ContextVar('mathmaster_user', default='zzy')
