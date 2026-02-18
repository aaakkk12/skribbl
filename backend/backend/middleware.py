import uuid


class RequestIDMiddleware:
    """
    Attach a request id for tracing and return it in response headers.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.request_id = request_id
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        return response


class NoStoreAuthMiddleware:
    """
    Prevent auth/admin responses from being cached by browsers/proxies.
    """

    AUTH_PREFIXES = ("/api/auth/", "/api/admin/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(self.AUTH_PREFIXES):
            response["Cache-Control"] = "no-store"
            response["Pragma"] = "no-cache"
        return response
