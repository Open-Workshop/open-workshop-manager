from sqlalchemy import create_engine, Column, Integer, String, DateTime, insert
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from fastapi import Request
from ow_config import user_sql, password_sql
import bcrypt


# engine = create_engine(f'mysql+mysqldb://{user_sql}:{password_sql}@localhost/access')
engine = create_engine('sqlite:///./access.db', echo=True)
base = declarative_base()

class AccessError(base): # Таблица "игры"
    __tablename__ = 'access_errors'
    id = Column(Integer, primary_key=True)

    func_name = Column(String)
    type = Column(String)
    when_error = Column(DateTime)

    user_ip = Column(String)
    user_port = Column(Integer)
    target_url = Column(String)
    user_agent = Column(String)

    token = Column(String)


base.metadata.create_all(engine)