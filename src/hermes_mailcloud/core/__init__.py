"""Stable JSON-contract and safety primitives for hermes-mailcloud."""

from .errors import ErrorKind, ErrorPayload, MailCloudError
from .policy import (
    OperationRequest,
    PolicyDecision,
    PolicyViolation,
    execute_with_policy,
    validate_operation,
)
from .result import ResultEnvelope

__all__ = [
    "ErrorKind",
    "ErrorPayload",
    "MailCloudError",
    "OperationRequest",
    "PolicyDecision",
    "PolicyViolation",
    "ResultEnvelope",
    "execute_with_policy",
    "validate_operation",
]
