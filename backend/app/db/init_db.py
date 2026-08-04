from app.db.database import Base, engine
from app.db import models


def init_db():
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
    print("Database initialized: energy_platform.db")
