from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from shared.config import DATABASE_URL


def url_con_psycopg3(url: str) -> str:
    """Pide explícitamente el controlador Psycopg 3 (`psycopg[binary]`).

    Con `postgresql://` a secas, SQLAlchemy elige el controlador según su
    versión (psycopg2 en las 2.0.x y anteriores, psycopg 3 en las nuevas),
    y el proyecto solo instala psycopg 3. Si la URL ya trae un controlador
    (`postgresql+algo://`), se respeta tal cual. Las credenciales no cambian.
    """
    for prefijo in ("postgresql://", "postgres://"):
        if url.startswith(prefijo):
            return "postgresql+psycopg://" + url[len(prefijo):]
    return url


engine = create_engine(url_con_psycopg3(DATABASE_URL), echo=False)
SessionLocal = sessionmaker(bind=engine)

def get_session():
    return SessionLocal()
