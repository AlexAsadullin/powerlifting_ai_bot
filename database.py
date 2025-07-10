import os
from sqlalchemy import create_engine, false
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DB_PATH")

engine = create_engine(DB_PATH, echo=False)
Session = sessionmaker(bind=engine)
Base = declarative_base()

def init_db():
    Base.metadata.create_all(engine, checkfirst=True)