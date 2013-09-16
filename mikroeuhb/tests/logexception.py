import logging
class LogException(Exception):
    def __init__(self, record):
        self.record = record
    def __str__(self):
        return repr(self.record.getMessage())
class LogExceptionHandler(logging.Handler):
    """Raise a LogException if a logging message occurs"""
    def emit(self, record):
        raise LogException(record)
