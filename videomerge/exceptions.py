"""Custom exception types for the videomerge application."""


class NonRetryableError(RuntimeError):
    """Raised when an operation fails due to invalid input or a permanent upstream error.

    Temporal activities that raise this exception signal that retrying the same
    request will never succeed (e.g. bad ``image_style``, constraint violations,
    or a RunPod job that returned FAILED with a validation message).

    Wire this into ``RetryPolicy.non_retryable_error_types`` so Temporal
    immediately fails the activity instead of burning through retry attempts.
    """
