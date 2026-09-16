import os

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

#إنشاء قاعدة بيانات SQLLite محلية
# DATABASE_URL lets a deployment point this at a persistent-volume path
# (e.g. sqlite:////data/accounting.db on Fly.io) instead of the relative
# file next to the code, which would reset on every redeploy.
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./accounting.db")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

sessionLocal = sessionmaker(autocommit = False, autoflush = False, bind = engine)

Base = declarative_base()