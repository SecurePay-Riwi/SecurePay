from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from seeds.config import DATABASE_URL

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)

def get_session():
    return SessionLocal()