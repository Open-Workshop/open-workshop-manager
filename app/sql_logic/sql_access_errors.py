from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from .envs import DB_HOST, DB_PASSWORD, DB_PORT, DB_USER

engine = create_engine(
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/access",
    pool_pre_ping=True,
)
base = declarative_base()

class AccessError(base):
    __tablename__ = 'access_errors'
    id = Column(Integer, primary_key=True)

    func_name = Column(String(64))
    type = Column(String(64))
    when_error = Column(DateTime)

    user_ip = Column(String(128))
    user_port = Column(Integer(16))
    target_url = Column(String(256))
    user_agent = Column(String(512))

    token = Column(String(256))


base.metadata.create_all(engine)