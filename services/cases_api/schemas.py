"""Request and response bodies of the cases API.

Join point: each owner adds the models of their endpoints here. The
tables and states are shared/cases.py; never redefine them.
Money is Decimal (a decimal string in JSON), dates are UTC.
"""

from pydantic import BaseModel


class Health(BaseModel):
    status: str
