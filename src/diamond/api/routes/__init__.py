"""Route modules. Each exports a `router: APIRouter`.

Adding a new route module:
1. Create ``diamond/api/routes/<resource>.py`` with ``router = APIRouter()``.
2. Register handlers on ``router``.
3. Add ``app.include_router(<resource>.router, prefix="/api", tags=[<tag>])``
   in ``diamond/api/app.py``.
4. Define request/response Pydantic schemas in
   ``diamond/api/schemas/<resource>.py`` and re-export from the
   schemas package ``__init__``.
5. Run ``make types`` to regenerate the TS interfaces.
"""
