"""The inbox, a case with its events, assigning and resolving (HU-26, HU-27, HU-30).

Empty until those stories add their endpoints.
"""

from fastapi import APIRouter

router = APIRouter(tags=["Cases"])
