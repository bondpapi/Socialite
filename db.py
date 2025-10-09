from sqlmodel import SQLModel, create_engine, Session
from pathlib import Path

db_path = Path("./social_agent.db").resolve()
engine = create_engine(f"sqlite:///{db_path}", echo=False)


def init_db():
    from . import models  # ensure models are imported
    SQLModel.metadata.create_all(engine)


def get_session():
    return Session(engine)
