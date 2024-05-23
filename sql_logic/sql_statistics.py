from datetime import datetime, date
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Date, insert
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from ow_config import user_sql, password_sql



# engine = create_engine(f'mysql+mysqldb://{user_sql}:{password_sql}@localhost/statistic')
engine = create_engine('sqlite:///./statistic.db', echo=True) # echo=True для видео
base = declarative_base()


# Определяем модель
class StatisticsHour(base):
    __tablename__ = 'statistics_hour'
    id = Column(Integer, primary_key=True)
    date_time = Column(DateTime)

    # user, mod, etc...
    type = Column(String)
    type_id = Column(Integer, default=None)

    # views, downloads, etc
    name = Column(String)

    count = Column(Integer, default=0)


class StatisticsDay(base):
    __tablename__ = 'statistics_day'
    id = Column(Integer, primary_key=True)
    date = Column(Date)

    #user, mod, etc...
    type = Column(String)
    type_id = Column(Integer, default=None)

    #views, downloads, etc
    name = Column(String)

    count = Column(Integer, default=0)


class ProcessingTime(base):
    __tablename__ = 'processing_time'
    time = Column(DateTime, primary_key=True)
    type = Column(String)
    delay = Column(Integer)


def create_processing(type, time_start):
    milliseconds = int((datetime.now()-time_start).total_seconds() * 1000)

    req = insert(ProcessingTime).values(
        time=time_start,
        type=type,
        delay=milliseconds
    )

    session = sessionmaker(bind=engine)()

    session.execute(req)

    session.commit()
    session.close()


# Производит обновление в статистике (почасовая, ежедневная)
def update(type:str):
    session = sessionmaker(bind=engine)()

    update_hour(session=session, type=type)
    update_day(session=session, type=type)

    session.commit()
    session.close()

def update_hour(session, type:str):
    # Получение текущего часа
    current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)

    # Запрос к базе данных для получения колонки
    query = session.query(StatisticsHour).filter_by(date_time=current_hour, type=str(type))
    column = query.first()

    if column:
        query.update({'count': column.count+1})
    else:
        session.execute(insert(StatisticsHour).values(
            date_time=current_hour,
            type=type,
            count=1
        ))
def update_day(session, type:str):
    # Получение текущего часа
    current_day = date.today()

    # Запрос к базе данных для получения колонки
    query = session.query(StatisticsDay).filter_by(date=current_day, type=str(type))
    column = query.first()

    if column:
        query.update({'count': column.count+1})
    else:
        session.execute(insert(StatisticsDay).values(
            date=current_day,
            type=type,
            count=1
        ))


# Создаем таблицу в базе данных
base.metadata.create_all(engine)