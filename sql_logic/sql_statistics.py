from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from typing import Iterator

from sqlalchemy import Column, Date, DateTime, Integer, String, create_engine, insert
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from .envs import DB_HOST, DB_PASSWORD, DB_PORT, DB_USER

engine = create_engine(
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/access",
    pool_pre_ping=True,
)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class StatisticsHour(Base):
    __tablename__ = "statistics_hour"
    id = Column(Integer, primary_key=True)
    date_time = Column(DateTime)

    # user, mod, etc...
    type = Column(String(32))
    type_id = Column(Integer, default=None)

    # views, downloads, etc
    name = Column(String(64))

    count = Column(Integer, default=0)


class StatisticsDay(Base):
    __tablename__ = "statistics_day"
    id = Column(Integer, primary_key=True)
    date = Column(Date)

    # user, mod, etc...
    type = Column(String(32))
    type_id = Column(Integer, default=None)

    # views, downloads, etc
    name = Column(String(64))

    count = Column(Integer, default=0)


class ProcessingTime(Base):
    __tablename__ = "processing_time"
    time = Column(DateTime, primary_key=True)

    # user, mod, etc...
    type = Column(String(32))
    type_id = Column(Integer, default=None)

    # views, downloads, etc
    name = Column(String(64))

    delay = Column(Integer)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _increment_stat(
    session: Session,
    model,
    time_field,
    time_value: datetime | date,
    entity_type: str,
    entity_id: int | None,
    name: str,
) -> None:
    updated = (
        session.query(model)
        .filter(
            time_field == time_value,
            model.type == str(entity_type),
            model.type_id == entity_id,
            model.name == name,
        )
        .update({model.count: model.count + 1}, synchronize_session=False)
    )

    if not updated:
        session.execute(
            insert(model).values(
                **{
                    time_field.name: time_value,
                    "type": entity_type,
                    "type_id": entity_id,
                    "name": name,
                    "count": 1,
                }
            )
        )


def create_processing(type: str, type_id: int, name: str, time_start: datetime) -> None:
    """Backward-compatible wrapper for recording processing time."""
    record_processing_time(entity_type=type, entity_id=type_id, name=name, time_start=time_start)


def record_processing_time(entity_type: str, entity_id: int, name: str, time_start: datetime) -> None:
    milliseconds = int((datetime.now() - time_start).total_seconds() * 1000)

    with session_scope() as session:
        session.execute(
            insert(ProcessingTime).values(
                time=time_start,
                type=entity_type,
                type_id=entity_id,
                name=name,
                delay=milliseconds,
            )
        )


# Производит обновление в статистике (почасовая, ежедневная)
def update(type: str, type_id: int, name: str) -> None:
    now = datetime.now()
    with session_scope() as session:
        _update_hour(session=session, entity_type=type, entity_id=type_id, name=name, now=now)
        _update_day(session=session, entity_type=type, entity_id=type_id, name=name, today=now.date())


def update_hour(session: Session, type: str, type_id: int, name: str) -> None:
    _update_hour(session=session, entity_type=type, entity_id=type_id, name=name, now=datetime.now())


def update_day(session: Session, type: str, type_id: int, name: str) -> None:
    _update_day(session=session, entity_type=type, entity_id=type_id, name=name, today=date.today())


def _update_hour(session: Session, entity_type: str, entity_id: int, name: str, now: datetime) -> None:
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    entity_id_value = int(entity_id) if entity_id is not None else None
    _increment_stat(
        session=session,
        model=StatisticsHour,
        time_field=StatisticsHour.date_time,
        time_value=current_hour,
        entity_type=entity_type,
        entity_id=entity_id_value,
        name=name,
    )


def _update_day(session: Session, entity_type: str, entity_id: int, name: str, today: date) -> None:
    entity_id_value = int(entity_id) if entity_id is not None else None
    _increment_stat(
        session=session,
        model=StatisticsDay,
        time_field=StatisticsDay.date,
        time_value=today,
        entity_type=entity_type,
        entity_id=entity_id_value,
        name=name,
    )


# Создаем таблицу в базе данных
Base.metadata.create_all(engine)
